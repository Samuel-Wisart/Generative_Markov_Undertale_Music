"""Testes do corpus MIDI genérico (Undertale etc.): leitura, tonalidade, fatiamento, seções e composição."""
import wave

import pytest

from markov_music.audio import TIMBRES, render_wav
from markov_music.corpus import Event
from markov_music.generator import Piece
from markov_music.midi_corpus import (MidiPiece, _normalizing_shift, _slice_section, build_sections, estimate_key,
                                      load_midi_folder)
from markov_music.midi_io import NoteSpec, piece_to_notes_sets, write_midi
from markov_music.sections import SectionModel

BAR = 48                                   # 4/4 em ticks (12 por semínima)
C_MAJOR = [0, 2, 4, 5, 7, 9, 11]


def scale_notes(root, scale, octave=5):
    """Escala subindo e descendo, em semínimas (ticks de 12), tônica mais longa."""
    base = 12 * octave + root
    pitches = [base + s for s in scale] + [base + 12]
    notes, t = [], 0
    for p in pitches + pitches[::-1][1:]:
        notes.append((t, t + 12, p))
        t += 12
    notes.append((t, t + 48, base))
    return notes


# ------------------------------------------------------------------------------- tonalidade
def test_estimate_key_finds_major_and_minor():
    assert estimate_key(scale_notes(0, C_MAJOR)) == (0, "major")
    assert estimate_key(scale_notes(2, C_MAJOR)) == (2, "major")                      # ré maior
    a_minor = [0, 2, 3, 5, 7, 8, 10]                                                   # escala menor natural
    root, mode = estimate_key(scale_notes(9, a_minor, octave=4))
    assert (root, mode) == (9, "minor")


def test_normalizing_shift_sends_the_relative_major_to_c():
    assert _normalizing_shift(0, "major") == 0
    assert _normalizing_shift(9, "minor") == 0                 # lá menor ~ dó maior
    assert _normalizing_shift(2, "major") == -2                # ré maior desce 2
    assert _normalizing_shift(11, "minor") == -2               # si menor ~ ré maior
    assert _normalizing_shift(6, "major") == -6                # menor deslocamento possível, em [-6, +5]
    assert all(-6 <= _normalizing_shift(r, m) <= 5 for r in range(12) for m in ("major", "minor"))


# ------------------------------------------------------------------------------ fatiamento
BAR_NOTES = [(0, 48, 60),                                                              # baixo: Dó longo
             (0, 12, 72), (12, 24, 74), (24, 36, 76), (36, 48, 77)]                    # melodia


def test_slice_piano_texture_marks_sustained_notes_without_attack():
    ev = _slice_section(BAR_NOTES, 0, 48, BAR, "piano")
    assert ev == [
        Event(0, (60, 72), (True, True), 12),
        Event(12, (60, 74), (False, True), 12),                 # o baixo SUSTENTA
        Event(24, (60, 76), (False, True), 12),
        Event(36, (60, 77), (False, True), 12),
    ]


def test_slice_melody_and_outer_textures():
    melody = _slice_section(BAR_NOTES, 0, 48, BAR, "melody")
    assert [e.pitches for e in melody] == [(72,), (74,), (76,), (77,)]
    assert all(e.attacks == (True,) and e.dur == 12 for e in melody)
    outer = _slice_section(BAR_NOTES, 0, 48, BAR, "outer")
    assert [e.pitches for e in outer] == [(60, 72), (60, 74), (60, 76), (60, 77)]


def test_melody_texture_ignores_accompaniment_register():
    """Quando a mão direita para, a nota mais aguda passaria a ser o baixo: isso NÃO é melodia (vira pausa)."""
    notes = [(0, 12, 72), (12, 24, 40), (24, 36, 74)]
    melody = _slice_section(notes, 0, 48, BAR, "melody")
    assert melody == [Event(0, (72,), (True,), 12), Event(12, (), (), 12), Event(24, (74,), (True,), 12), Event(36, (), (), 12)]
    outer = _slice_section(notes, 0, 48, BAR, "outer")                 # nas outras texturas o baixo é bem-vindo
    assert (40,) in [e.pitches for e in outer]


def test_slice_merges_a_sustained_top_note_under_changing_bass():
    notes = [(0, 48, 72), (0, 24, 48), (24, 48, 50)]            # topo sustentado 1 compasso; o baixo muda no meio
    melody = _slice_section(notes, 0, 48, BAR, "melody")
    assert melody == [Event(0, (72,), (True,), 48)]             # uma nota só, de 48 ticks
    piano = _slice_section(notes, 0, 48, BAR, "piano")
    assert [e.dur for e in piano] == [24, 24]
    assert piano[1].pitches == (50, 72) and piano[1].attacks == (True, False)       # ordenado por altura: baixo novo, topo sustentado


def test_slice_positions_rests_and_clipping():
    notes = [(0, 12, 60), (24, 96, 64)]                         # pausa de 12 a 24; a 2ª nota atravessa a seção
    ev = _slice_section(notes, 0, 48, BAR, "piano")
    assert ev == [Event(0, (60,), (True,), 12), Event(12, (), (), 12), Event(24, (64,), (True,), 24)]
    nxt = _slice_section(notes, 48, 96, BAR, "piano")           # a nota continua na seção seguinte, SEM ataque
    assert nxt == [Event(0, (64,), (False,), 48)]


def test_build_sections_respects_meter_length_and_silence():
    long_piece = MidiPiece("a", BAR, [(t, t + 12, 60 + (t // 12) % 7) for t in range(0, 8 * BAR, 12)], 0, "C major", 120)
    waltz = MidiPiece("b", 36, [(t, t + 12, 62) for t in range(0, 8 * 36, 12)], 0, "C major", 120)
    quiet = MidiPiece("c", BAR, [(0, 12, 60)] * 1 + [(7 * BAR, 7 * BAR + 12, 60)] * 16, 0, "C major", 120)
    sections = build_sections([long_piece, waltz, quiet], "piano", BAR, 4)
    # só as peças de 4/4 contam: a longa tem 8 compassos = 2 seções; a "quiet" é quase só silêncio
    assert len(sections) == 2
    assert build_sections([waltz], "piano", 36, 4)                                 # com o compasso certo, entra
    with pytest.raises(ValueError):
        build_sections([long_piece], "violino", BAR, 4)


# --------------------------------------------------------------------------- arquivos .mid reais
def write_test_midi(folder, name, root):
    """Escreve um .mid de 2 mãos: escala maior com tônica `root` (direita) e a tônica no baixo (esquerda)."""
    notes = [NoteSpec(s / 12, (e - s) / 12, p, 0, 88) for s, e, p in scale_notes(root, C_MAJOR)]
    notes += [NoteSpec(float(4 * bar), 4.0, 36 + root, 1, 72) for bar in range(5)]
    write_midi(notes, folder / name, bpm=120, program=0, voice_names=["D", "E"], time_signature="4/4")


def test_load_midi_folder_reads_normalizes_and_skips_bad_files(tmp_path):
    write_test_midi(tmp_path, "c_major.mid", root=0)
    write_test_midi(tmp_path, "d_major.mid", root=2)
    (tmp_path / "quebrado.mid").write_bytes(b"MThd\x00\x00\x00\x06" + b"\xff" * 20)         # malformado
    write_midi([NoteSpec(0.0, 1.0, 60, 0, 80)], tmp_path / "quase_vazio.mid")             # 1 nota só
    pieces = load_midi_folder(str(tmp_path), cache_dir=None, verbose=False)
    assert sorted(p.name for p in pieces) == ["c_major", "d_major"]                        # os 2 ruins foram pulados
    by_name = {p.name: p for p in pieces}
    assert by_name["c_major"].transpose == 0 and by_name["d_major"].transpose == -2        # ré maior -> dó maior
    assert all(p.bar_ticks == BAR for p in pieces)
    # depois de transpostas, as duas peças ficam IGUAIS
    assert by_name["c_major"].notes == by_name["d_major"].notes
    assert by_name["c_major"].notes[0][:2] == (0, 12)                                      # quantização exata de 1 semínima
    (tmp_path / "vazia").mkdir()
    with pytest.raises(FileNotFoundError):
        load_midi_folder(str(tmp_path / "vazia"), cache_dir=None)


def test_load_midi_folder_uses_cache(tmp_path):
    data, cache = tmp_path / "midis", tmp_path / "cache"
    data.mkdir()
    write_test_midi(data, "a.mid", root=0)
    first = load_midi_folder(str(data), cache_dir=cache, verbose=False)
    assert len(list(cache.glob("midi_v*.pkl"))) == 1
    assert [p.notes for p in load_midi_folder(str(data), cache_dir=cache, verbose=False)] == [p.notes for p in first]


# --------------------------------------------------------------------------- compositor de seções
@pytest.fixture(scope="module")
def tiny_model():
    pieces = []
    for k in range(6):                                          # 6 peças sintéticas de 16 compassos, padrões variados
        notes = [(t, t + 12 * (1 + (k + t // 12) % 2), 60 + C_MAJOR[(t // 12 * (1 + k % 3)) % 7]) for t in range(0, 16 * BAR, 12)]
        pieces.append(MidiPiece(f"p{k}", BAR, notes, 0, "C major", 120))
    return SectionModel(1, build_sections(pieces, "melody", BAR, 4), "melody", BAR, 4)


def test_compose_sections_have_exact_length_and_form_repeats(tiny_model):
    piece = tiny_model.compose("AABA", seed=3)
    assert len(piece.phrases) == 4 and len(piece.distinct_phrases) == 2
    for section in piece.phrases:
        assert sum(e.dur for e in section) == 4 * BAR
        assert section[0].pos == 0
    assert piece.phrases[0] == piece.phrases[1] == piece.phrases[3] and piece.phrases[2] != piece.phrases[0]
    assert piece.params["form"] == "AABA"


def test_compose_is_reproducible_and_validates_form(tiny_model):
    assert tiny_model.compose("AB", seed=5).phrases == tiny_model.compose("AB", seed=5).phrases
    assert any(tiny_model.compose("A", seed=s).phrases != tiny_model.compose("A", seed=5).phrases for s in range(6, 14))
    for bad in ("", "aab", "A1", "AB "):
        with pytest.raises(ValueError):
            tiny_model.compose(bad)


def test_copy_rate_counts_repeated_sections_once(tiny_model):
    once, repeated = tiny_model.compose("A", seed=2), tiny_model.compose("AAAA", seed=2)
    assert tiny_model.copy_counts(once) == tiny_model.copy_counts(repeated)


def test_empty_training_set_is_rejected():
    with pytest.raises(ValueError):
        SectionModel(1, [], "piano", BAR, 4)


# ------------------------------------------------------------------------------ notas e áudio
def test_piece_to_notes_sets_sustains_splits_hands_and_trims_silence():
    piece = Piece(phrases=[[
        Event(0, (), (), 12),                                   # silêncio inicial: cortado
        Event(12, (48, 72), (True, True), 12),
        Event(24, (48, 74), (False, True), 12),                 # o baixo (48) é sustentado
        Event(36, (50,), (True,), 12),
    ]])
    notes = piece_to_notes_sets(piece)
    bass = [n for n in notes if n.pitch == 48]
    assert len(bass) == 1 and bass[0].start == 0.0 and bass[0].dur == pytest.approx(2.0) and bass[0].voice == 1
    assert {n.voice for n in notes if n.pitch >= 60} == {0}
    assert {n.voice for n in piece_to_notes_sets(piece, split_hands=False)} == {0}


@pytest.mark.parametrize("timbre", list(TIMBRES))
def test_every_timbre_renders_a_finite_wav(tmp_path, timbre):
    path = tmp_path / f"{timbre}.wav"
    seconds = render_wav([(0.0, 0.4, 60, 90, 0), (0.2, 0.4, 67, 90, 1)], path, sample_rate=8000, timbre=timbre)
    with wave.open(str(path)) as f:
        assert f.getnframes() / 8000 == pytest.approx(seconds)
        data = f.readframes(f.getnframes())
    assert any(data)                                            # não é silêncio
    with pytest.raises(ValueError):
        render_wav([(0.0, 0.4, 60, 90, 0)], path, timbre="violino")
