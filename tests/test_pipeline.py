"""Testes do pipeline musical: fatiamento, composição com restrições, MIDI e áudio."""
import wave

import pytest

from markov_music.audio import render_wav
from markov_music.corpus import BAR_TICKS, Event, RawChorale, load_raw_chorales, slice_chorale
from markov_music.generator import TEXTURES, TONIC_PITCH_CLASS, train_model
from markov_music.midi_io import NoteSpec, piece_to_notes, read_midi_seconds, write_midi


# ------------------------------------------------------------------ fatiamento (sem music21)
def synthetic_chorale():
    """Soprano: Dó-Ré-Mi (3 semínimas). Baixo: Dó (2 semínimas) e Ré (1). Fermata no fim (tick 36)."""
    return RawChorale(
        name="sintetico", mode="major", transpose=0,
        voices=[[(0, 12, 60), (12, 24, 62), (24, 36, 64)], [(0, 24, 48), (24, 36, 50)]],
        fermata_ends=[36], origin=0,
    )


def test_slice_chorale_splits_at_every_voice_change():
    phrases = slice_chorale(synthetic_chorale(), voices=(0, 1))
    assert len(phrases) == 1 and phrases[0].final
    assert phrases[0].events == (
        Event(0, (60, 48), (True, True), 12),
        Event(12, (62, 48), (True, False), 12),     # o baixo SUSTENTA o Dó (attack=False)
        Event(24, (64, 50), (True, True), 12),
    )


def test_melody_texture_uses_only_the_soprano():
    ev = slice_chorale(synthetic_chorale(), voices=(0,))[0].events
    assert ev == (Event(0, (60,), (True,), 12), Event(12, (62,), (True,), 12), Event(24, (64,), (True,), 12))


# --------------------------------------------------------- corpus real reduzido (usa music21)
@pytest.fixture(scope="module")
def raws():
    chorales = load_raw_chorales(limit=60, verbose=False)
    assert {c.mode for c in chorales} == {"major", "minor"}
    return chorales


def test_corpus_is_normalized_to_c_major_a_minor(raws):
    for c in raws:
        assert -6 <= c.transpose <= 5 and len(c.voices) == 4
    # corais maiores terminam, em geral, na tônica (Dó)
    major = [c for c in raws if c.mode == "major"]
    on_tonic = sum(c.voices[3][-1][2] % 12 == 0 for c in major)
    assert on_tonic / len(major) > 0.5


@pytest.mark.parametrize("texture", list(TEXTURES))
@pytest.mark.parametrize("mode", ["major", "minor"])
def test_composition_respects_the_style_constraints(raws, texture, mode):
    model = train_model(order=1, texture=texture, mode=mode, raw_chorales=raws)
    piece = model.compose(n_phrases=4, seed=5)
    assert len(piece.phrases) == 4
    for a, b in zip(piece.phrases, piece.phrases[1:]):                       # as frases se encaixam no compasso
        assert (a[-1].pos + a[-1].dur) % BAR_TICKS == b[0].pos
    last = piece.phrases[-1][-1]
    assert min(p for p in last.pitches if p >= 0) % 12 == TONIC_PITCH_CLASS[mode]     # termina na tônica


def test_reproducibility_and_variation(raws):
    model = train_model(order=2, texture="melody", mode="major", raw_chorales=raws)
    a, b = model.compose(4, seed=1), model.compose(4, seed=1)
    assert a.phrases == b.phrases                                               # mesma semente => mesma peça
    assert any(model.compose(4, seed=s).phrases != a.phrases for s in range(2, 8))   # outra semente => outra peça
    t_low = model.compose(4, seed=1, temperature=0.3)
    assert t_low.params["temperature"] == 0.3


def test_every_transition_in_the_piece_was_seen_in_training(raws):
    model = train_model(order=1, texture="satb", mode="major", raw_chorales=raws)
    piece = model.compose(3, seed=9)
    for phrase in piece.phrases:
        for x, y in zip(phrase, phrase[1:]):
            assert y in model.chain.counts[(x,)]


def test_copy_rate_is_a_fraction(raws):
    model = train_model(order=3, texture="satb", mode="major", raw_chorales=raws)
    rate = model.copy_rate(model.compose(3, seed=2))
    assert 0.0 <= rate <= 1.0


# ------------------------------------------------------------------------ MIDI e áudio
def test_midi_roundtrip_is_exact(tmp_path):
    notes = [NoteSpec(0.0, 1.0, 72, 0, 88), NoteSpec(0.0, 1.5, 55, 1, 72), NoteSpec(1.0, 0.5, 74, 0, 88),
             NoteSpec(1.5, 2.0, 59, 1, 72)]
    path = tmp_path / "t.mid"
    write_midi(notes, path, bpm=60)
    back = read_midi_seconds(path)                       # bpm=60 => 1 semínima = 1 segundo
    got = sorted((round(s, 3), round(d, 3), p, track) for s, d, p, _, track in back)
    want = sorted((n.start, n.dur, n.pitch, n.voice) for n in notes)
    assert got == want


def test_piece_to_notes_merges_sustained_voices_and_stretches_fermata():
    from markov_music.generator import Piece

    piece = Piece(phrases=[[
        Event(0, (60, 48), (True, True), 12),
        Event(12, (60, 50), (False, True), 12),      # soprano sustenta o Dó; baixo muda
    ]])
    notes = piece_to_notes(piece, fermata_factor=2.0)
    soprano = [n for n in notes if n.voice == 0]
    assert len(soprano) == 1 and soprano[0].start == 0 and soprano[0].dur == pytest.approx(1.0 + 2.0)
    assert len([n for n in notes if n.voice == 1]) == 2


def test_leading_silence_is_trimmed_but_breaths_between_phrases_are_kept():
    from markov_music.generator import Piece

    rest, sound = Event(0, (-1,), (False,), 12), Event(12, (60,), (True,), 12)
    piece = Piece(phrases=[[rest, rest, sound], [rest, sound]])
    notes = piece_to_notes(piece, fermata_factor=1.0)
    assert [n.start for n in notes] == [0.0, 2.0]              # 1ª nota em 0 (silêncio inicial cortado); pausa entre frases mantida


def test_render_wav_writes_a_valid_file(tmp_path):
    path = tmp_path / "t.wav"
    seconds = render_wav([(0.0, 0.5, 60, 80, 0), (0.5, 0.5, 64, 80, 1)], path, sample_rate=8000)
    with wave.open(str(path)) as f:
        assert f.getnchannels() == 2 and f.getframerate() == 8000
        assert f.getnframes() / 8000 == pytest.approx(seconds)
    assert seconds > 1.0


def _rates(model, **kwargs):
    """Taxas de cópia das peças que foram possíveis (num corpus minúsculo algumas sementes são inviáveis)."""
    out = []
    for seed in range(10):
        try:
            rate = model.copy_rate(model.compose(3, seed=seed, **kwargs))
        except RuntimeError:
            continue
        if rate == rate:                                      # descarta NaN (peça sem janelas)
            out.append(rate)
    return out


def test_max_copy_constraint_limits_memorization(raws):
    model = train_model(order=2, texture="satb", mode="major", raw_chorales=raws)
    free, capped = _rates(model), _rates(model, max_copy=0.4)
    assert len(free) >= 3 and len(capped) >= 3
    assert all(r <= 0.4 for r in capped)
    assert sum(capped) / len(capped) < sum(free) / len(free)


def test_max_copy_can_be_infeasible_and_says_so(raws):
    model = train_model(order=1, texture="melody", mode="major", raw_chorales=raws)
    with pytest.raises(RuntimeError, match="max-copy"):
        model.compose(3, seed=1, max_copy=-1.0, max_tries=50)       # nenhuma frase pode ter taxa < 0


def test_parallel_perfects_detects_only_similar_motion_between_perfect_intervals():
    from markov_music.metrics import parallel_perfects

    fifth_up = [Event(0, (67, 60), (True, True), 12), Event(12, (69, 62), (True, True), 12)]          # quintas paralelas
    octave_down = [Event(0, (72, 60), (True, True), 12), Event(12, (71, 59), (True, True), 12)]       # oitavas paralelas
    contrary = [Event(0, (67, 60), (True, True), 12), Event(12, (65, 62), (True, True), 12)]          # mov. contrário
    held_voice = [Event(0, (67, 60), (True, True), 12), Event(12, (67, 62), (False, True), 12)]       # soprano parado
    to_third = [Event(0, (67, 60), (True, True), 12), Event(12, (69, 65), (True, True), 12)]          # 5ª -> 3ª: ok
    assert parallel_perfects([fifth_up, octave_down]) == (2, 2)
    assert parallel_perfects([contrary, held_voice, to_third]) == (0, 3)
    assert parallel_perfects([[Event(0, (67, 60), (True, True), 12)]]) == (0, 0)          # sem transições
