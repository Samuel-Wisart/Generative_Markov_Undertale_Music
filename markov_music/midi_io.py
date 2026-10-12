"""Peça (lista de eventos) <-> arquivo MIDI, usando music21.

`piece_to_notes` converte os estados da cadeia em notas "de verdade" (início, duração, altura).
Essa lista é a fonte única para o MIDI, para o piano-roll e (via arquivo) para o áudio.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .corpus import REST, TICKS_PER_QUARTER
from .generator import Piece

VOICE_NAMES = ["Soprano", "Contralto", "Tenor", "Baixo"]
CHURCH_ORGAN = 19                    # programa General MIDI (0-indexado): Church Organ


@dataclass(frozen=True)
class NoteSpec:
    start: float      # em semínimas (beats), a partir do começo da peça
    dur: float        # em semínimas
    pitch: int        # número MIDI
    voice: int        # 0 = soprano ... 3 = baixo
    velocity: int


def piece_to_notes(piece: Piece, fermata_factor: float = 1.5) -> List[NoteSpec]:
    """Transforma a sequência de eventos em notas.

    * Uma voz que "não ataca" e repete a altura da fatia anterior apenas SUSTENTA a nota.
    * A última fatia de cada frase (a fermata) é alongada por `fermata_factor`.
    * Pausas entre frases (a "respiração" do coral) são mantidas; só o silêncio no INÍCIO da peça é cortado.
    """
    n_voices = piece.n_voices
    notes: List[NoteSpec] = []
    open_note: List[Optional[List[float]]] = [None] * n_voices     # por voz: [início, fim, altura]
    clock = 0.0
    for ev in piece.phrases[0]:                                   # corta o silêncio inicial
        if any(p != REST for p in ev.pitches):
            break
        clock -= ev.dur / TICKS_PER_QUARTER

    def close(v: int) -> None:
        if open_note[v] is not None:
            s, e, p = open_note[v]
            notes.append(NoteSpec(s, e - s, int(p), v, 88 if v == 0 else 72))
            open_note[v] = None

    for phrase in piece.phrases:
        for i, ev in enumerate(phrase):
            dur = ev.dur / TICKS_PER_QUARTER
            if i == len(phrase) - 1:
                dur *= fermata_factor
            for v in range(n_voices):
                p = ev.pitches[v]
                current = open_note[v]
                if not ev.attacks[v] and current is not None and current[2] == p:
                    current[1] = clock + dur                      # sustenta a nota que já soa
                else:
                    close(v)
                    if p != REST:
                        open_note[v] = [clock, clock + dur, p]
            clock += dur
        for v in range(n_voices):                                 # nada atravessa a fronteira entre frases
            close(v)
    return sorted(notes, key=lambda n: (n.start, n.voice))


HAND_SPLIT = 60                      # corpus MIDI: alturas >= Dó central vão para a "mão direita"
HAND_NAMES = ["Mão direita", "Mão esquerda"]


def piece_to_notes_sets(piece: Piece, split_hands: bool = True) -> List[NoteSpec]:
    """Como `piece_to_notes`, mas para eventos que são CONJUNTOS de alturas (corpus MIDI genérico).

    Uma altura com `attack=False` que já estava soando na fatia anterior apenas prolonga essa nota;
    nada atravessa a fronteira entre seções. Com `split_hands`, alturas >= HAND_SPLIT vão para a trilha 0
    e as demais para a 1; sem ele, tudo vai para a trilha 0.
    """
    notes: List[NoteSpec] = []
    open_note: Dict[int, List[float]] = {}                       # altura -> [início, fim]
    clock = 0.0
    for ev in piece.phrases[0]:                                  # corta o silêncio inicial
        if ev.pitches:
            break
        clock -= ev.dur / TICKS_PER_QUARTER

    def close(pitch: int) -> None:
        start, end = open_note.pop(pitch)
        right = pitch >= HAND_SPLIT or not split_hands
        notes.append(NoteSpec(start, end - start, pitch, 0 if right else 1, 88 if right else 72))

    for phrase in piece.phrases:
        for ev in phrase:
            dur = ev.dur / TICKS_PER_QUARTER
            now = set(ev.pitches)
            for p in [q for q in open_note if q not in now]:     # notas que pararam de soar
                close(p)
            for p, attack in zip(ev.pitches, ev.attacks):
                if not attack and p in open_note:
                    open_note[p][1] = clock + dur                # sustenta
                else:
                    if p in open_note:
                        close(p)                                 # mesma altura tocada de novo
                    open_note[p] = [clock, clock + dur]
            clock += dur
        for p in list(open_note):                                # nada atravessa a fronteira entre seções
            close(p)
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def write_midi(
    notes: Sequence[NoteSpec],
    path: Path,
    bpm: int = 76,
    program: int = CHURCH_ORGAN,
    voice_names: Optional[Sequence[str]] = None,
    time_signature: str = "4/4",
) -> None:
    """Grava um .mid com uma trilha (Part) por voz, cada uma no seu canal MIDI."""
    from music21 import instrument, meter, midi, note, stream, tempo

    n_voices = max(n.voice for n in notes) + 1
    score = stream.Score()
    for v in range(n_voices):
        part = stream.Part()
        inst = instrument.Instrument()
        inst.midiProgram = program
        if voice_names is not None:
            inst.partName = voice_names[v]
        else:
            inst.partName = VOICE_NAMES[v] if n_voices == 4 else "Melodia"
        part.insert(0, inst)
        if v == 0:
            part.insert(0, tempo.MetronomeMark(number=bpm))
            part.insert(0, meter.TimeSignature(time_signature))
        for n in (x for x in notes if x.voice == v):
            m21 = note.Note(n.pitch)
            m21.quarterLength = n.dur
            m21.volume.velocity = n.velocity
            part.insert(n.start, m21)
        score.insert(0, part)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    score.write("midi", fp=str(path))

    # O music21 põe todas as trilhas no mesmo canal quando o instrumento é igual.
    # Separamos (voz v -> canal v+1) para uma nota de uma voz nunca cortar a de outra.
    mf = midi.MidiFile()
    mf.open(str(path), "rb")
    mf.read()
    mf.close()
    for v in range(n_voices):
        for event in mf.tracks[v + 1].events:            # trilha 0 = "maestro" (andamento/compasso)
            if getattr(event, "channel", None) is not None:
                event.channel = v + 1
    mf.open(str(path), "wb")
    mf.write()
    mf.close()


def read_midi_seconds(path: Path) -> List[Tuple[float, float, int, int, int]]:
    """Lê um .mid e devolve [(início_s, duração_s, altura, velocity, trilha)].

    Lê os eventos MIDI "crus" (note-on/note-off) para obter as durações exatas, sem
    nenhuma quantização. Aceita mapa de andamentos (mudanças de tempo).
    """
    from music21 import midi

    mf = midi.MidiFile()
    mf.open(str(path), "rb")
    mf.read()
    mf.close()
    tpq = mf.ticksPerQuarterNote

    # mapa de andamento: [(tick, microssegundos por semínima)]
    tempo_map = [(0, 500000)]
    for track in mf.tracks:
        tick = 0
        for e in track.events:
            if isinstance(e, midi.DeltaTime):
                tick += e.time
            elif e.type == midi.MetaEvents.SET_TEMPO:
                tempo_map.append((tick, int.from_bytes(e.data, "big")))
    tempo_map.sort()

    def to_seconds(tick: int) -> float:
        seconds, prev_tick, prev_us = 0.0, 0, tempo_map[0][1]
        for t, us in tempo_map[1:]:
            if t >= tick:
                break
            seconds += (t - prev_tick) / tpq * prev_us / 1e6
            prev_tick, prev_us = t, us
        return seconds + (tick - prev_tick) / tpq * prev_us / 1e6

    out = []
    for index, track in enumerate(mf.tracks):
        tick, pending = 0, {}
        for e in track.events:
            if isinstance(e, midi.DeltaTime):
                tick += e.time
            elif e.isNoteOn():
                pending[(e.channel, e.pitch)] = (tick, e.velocity)
            elif e.isNoteOff() and (e.channel, e.pitch) in pending:
                start, velocity = pending.pop((e.channel, e.pitch))
                out.append((to_seconds(start), to_seconds(tick) - to_seconds(start), e.pitch, velocity, index - 1))
    return sorted(out)
