"""Corpus MIDI arbitrário (transcrições de piano, trilhas de jogos...) -> seções de eventos.

Diferenças em relação ao corpus de Bach (`corpus.py`):

    * não há partitura: só notas MIDI (sem fermatas, sem vozes separadas);
    * a "frase" passa a ser uma SEÇÃO de N compassos (padrão 4), cortada a partir do início da peça;
    * o estado (`Event`) é um conjunto de alturas soando: `pitches` é uma tupla ORDENADA e de tamanho
      variável (vazia = pausa); `attacks[i]` diz se `pitches[i]` foi tocada de novo nesta fatia.

As fatias são cortadas nos ATAQUES, e também quando o som realmente PARA (uma pausa de pelo menos
`MIN_REST` ticks). Folgas menores entre notas (staccato/legato das transcrições) são absorvidas pela
nota anterior: cortar em todo fim de nota criaria durações ruidosas sem importância musical.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .corpus import TICKS_PER_QUARTER, Event, Phrase

TEXTURES_MIDI = ("melody", "outer", "piano")
MAX_NOTES = 8                         # teto de polifonia por fatia (descarta notas internas além disso)
MELODY_FLOOR = 55                     # textura "melody": notas abaixo de Sol3 são acompanhamento, não melodia
MIN_REST = 4                          # ticks: pausas menores (folga de articulação/staccato) são absorvidas pela nota
CACHE_VERSION = 1

# Perfis de tonalidade de Krumhansl-Kessler (usados no algoritmo de Krumhansl-Schmuckler)
_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


@dataclass
class MidiPiece:
    """Uma peça lida de um .mid: notas em ticks (12 por semínima), já transpostas."""
    name: str
    bar_ticks: int                        # duração do compasso, em ticks
    notes: List[Tuple[int, int, int]]     # (início, fim, altura MIDI)
    transpose: int                        # semitons aplicados (normalização de tonalidade)
    key: str                              # tonalidade estimada ANTES de transpor, ex.: "A minor"
    bpm: float


class _Skip(Exception):
    """Arquivo descartado (o motivo vai na mensagem)."""


# ------------------------------------------------------------------------------- leitura
def _read_midi(path: str) -> Tuple[List[Tuple[int, int, int]], int, float]:
    """Lê o .mid com a API de baixo nível do music21. Devolve (notas, ticks do compasso, bpm)."""
    from music21 import midi

    mf = midi.MidiFile()
    mf.open(path, "rb")
    try:
        mf.read()
    finally:
        mf.close()
    tpq = mf.ticksPerQuarterNote
    if not isinstance(tpq, int) or tpq <= 0 or tpq >= 0x8000:
        raise _Skip("resolução de tempo não suportada (SMPTE)")

    signatures, tempos = [], []
    raw: List[Tuple[int, int, int]] = []
    for track in mf.tracks:
        tick, sounding = 0, {}
        for e in track.events:
            if isinstance(e, midi.DeltaTime):
                tick += e.time
            elif e.type == midi.MetaEvents.TIME_SIGNATURE and len(e.data) >= 2:
                signatures.append((e.data[0], 2 ** e.data[1]))
            elif e.type == midi.MetaEvents.SET_TEMPO and e.data:
                us = int.from_bytes(e.data, "big")
                if us > 0:
                    tempos.append(60e6 / us)
            elif e.isNoteOn():
                if e.channel == 10:                         # canal 10 = percussão: fora
                    continue
                key = (e.channel, e.pitch)
                if key in sounding:                         # mesma nota re-tocada: fecha a anterior
                    raw.append((sounding.pop(key), tick, e.pitch))
                sounding[key] = tick
            elif e.isNoteOff() and e.channel != 10:
                start = sounding.pop((e.channel, e.pitch), None)
                if start is not None:
                    raw.append((start, tick, e.pitch))
        for (_, pitch), start in sounding.items():           # notas que ficaram abertas no fim da trilha
            raw.append((start, max(tick, start + 1), pitch))

    if len(set(signatures)) > 1:
        raise _Skip("compasso variável")
    num, den = signatures[0] if signatures else (4, 4)
    bar_ticks = round(TICKS_PER_QUARTER * 4 * num / den)

    scale = TICKS_PER_QUARTER / tpq
    notes = set()
    for s, e, p in raw:                                      # quantiza para a grade de 12 ticks/semínima
        qs = round(s * scale)
        qe = max(qs + 1, round(e * scale))
        notes.add((qs, qe, p))
    ordered = sorted(notes)
    if len(ordered) < 16:
        raise _Skip("quase sem notas")
    if max(e for _, e, _ in ordered) < bar_ticks:
        raise _Skip("menos de um compasso")
    return ordered, bar_ticks, (statistics.median(tempos) if tempos else 120.0)


def estimate_key(notes: Sequence[Tuple[int, int, int]]) -> Tuple[int, str]:
    """Krumhansl-Schmuckler: (tônica 0-11, "major"/"minor") a partir do histograma de classes de altura."""
    import numpy as np

    hist = np.zeros(12)
    for s, e, p in notes:
        hist[p % 12] += e - s
    best, best_corr = (0, "major"), -2.0
    for mode, profile in (("major", _MAJOR), ("minor", _MINOR)):
        prof = np.array(profile)
        for root in range(12):
            corr = np.corrcoef(hist, np.roll(prof, root))[0, 1]
            if corr > best_corr:
                best, best_corr = (root, mode), corr
    return best


def _normalizing_shift(root: int, mode: str) -> int:
    """Semitons (de -6 a +5) que levam a tonalidade para a sua relativa em Dó maior / Lá menor.

    Maior e menor viram o MESMO conjunto de notas (teclas brancas): o corpus pequeno não é dividido por modo.
    """
    relative_major = root if mode == "major" else (root + 3) % 12
    return (-relative_major + 6) % 12 - 6


def load_midi_folder(folder: str, cache_dir: Optional[Path] = None, verbose: bool = True) -> List[MidiPiece]:
    """Lê todos os .mid de uma pasta (com cache em disco). Arquivos problemáticos são pulados e contados."""
    files = sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith((".mid", ".midi"))
    )
    if not files:
        raise FileNotFoundError(f"Nenhum arquivo .mid em {folder!r}")

    cache_file = None
    if cache_dir is not None:
        fingerprint = hashlib.sha1(
            "|".join(f"{os.path.basename(f)}:{os.path.getsize(f)}" for f in files).encode("utf-8")
        ).hexdigest()[:12]
        cache_file = Path(cache_dir) / f"midi_v{CACHE_VERSION}_{fingerprint}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass

    pieces: List[MidiPiece] = []
    skipped: Dict[str, int] = {}
    for path in files:
        try:
            notes, bar_ticks, bpm = _read_midi(path)
            root, mode = estimate_key(notes)
        except _Skip as why:
            skipped[str(why)] = skipped.get(str(why), 0) + 1
            continue
        except Exception as err:                              # arquivo malformado: nunca derruba o carregamento
            reason = f"erro de leitura ({type(err).__name__})"
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        shift = _normalizing_shift(root, mode)
        pieces.append(MidiPiece(
            name=os.path.splitext(os.path.basename(path))[0],
            bar_ticks=bar_ticks,
            notes=[(s, e, p + shift) for s, e, p in notes],
            transpose=shift,
            key=f"{_NOTE_NAMES[root]} {mode}",
            bpm=bpm,
        ))
    if verbose:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(skipped.items())) or "nenhum"
        print(f"  [midi] {len(pieces)} de {len(files)} arquivos aproveitados (descartados -> {detail}).")

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(pieces, f)
    return pieces


# ------------------------------------------------------------------- fatiamento em seções
def _slice_section(notes: Sequence[Tuple[int, int, int]], c0: int, c1: int, bar_ticks: int, texture: str) -> List[Event]:
    """Cria os eventos de UMA seção [c0, c1): uma fatia a cada ataque de nota."""
    sel = [(max(s, c0), min(e, c1), p, s >= c0) for s, e, p in notes
           if s < c1 and e > c0 and (texture != "melody" or p >= MELODY_FLOOR)]
    sel.sort()
    onsets = sorted({c0} | {cs for cs, _, _, new in sel if new})
    events: List[Event] = []
    active: List[Tuple[int, int, bool]] = []                   # (fim, altura, é nota nova?)
    nxt = 0
    for i, t in enumerate(onsets):
        while nxt < len(sel) and sel[nxt][0] <= t:
            cs, ce, p, new = sel[nxt]
            active.append((ce, p, new and cs == t))
            nxt += 1
        active = [(ce, p, att) if ce > t else None for ce, p, att in active]
        active = [a for a in active if a is not None]
        t_next = onsets[i + 1] if i + 1 < len(onsets) else c1
        sounding_end = max((ce for ce, _, _ in active), default=t)     # quando o som deste ataque realmente acaba
        by_pitch: Dict[int, bool] = {}
        for ce, p, att in active:                                # mesma altura duplicada: um ataque vale
            by_pitch[p] = by_pitch.get(p, False) or att
        # nota "nova" só conta como ataque na fatia em que começa; nas seguintes ela é sustentada
        active = [(ce, p, False) for ce, p, _ in active]
        pitches = sorted(by_pitch)
        if texture == "melody":
            pitches = pitches[-1:]
        elif texture == "outer":
            pitches = sorted({pitches[0], pitches[-1]}) if pitches else []
        elif len(pitches) > MAX_NOTES:
            pitches = pitches[:2] + pitches[-(MAX_NOTES - 2):]
        has_rest = bool(active) and t_next - sounding_end >= MIN_REST
        events.append(Event(
            pos=(t - c0) % bar_ticks,
            pitches=tuple(pitches),
            attacks=tuple(by_pitch[p] for p in pitches),
            dur=(sounding_end if has_rest else t_next) - t,
        ))
        if has_rest:                                                   # pausa real entre este som e o próximo ataque
            events.append(Event((sounding_end - c0) % bar_ticks, (), (), t_next - sounding_end))
    # junta fatias consecutivas iguais SEM novo ataque (ex.: nota do topo sustentada sob acordes que mudam)
    merged: List[Event] = []
    for ev in events:
        if merged and merged[-1].pitches == ev.pitches and not any(ev.attacks):
            prev = merged[-1]
            merged[-1] = Event(prev.pos, prev.pitches, prev.attacks, prev.dur + ev.dur)
        else:
            merged.append(ev)
    return merged


def build_sections(
    pieces: Sequence[MidiPiece],
    texture: str,
    bar_ticks: int = 4 * TICKS_PER_QUARTER,
    section_bars: int = 4,
    max_silence: float = 0.5,
) -> List[Phrase]:
    """Corta cada peça (com o compasso pedido) em seções de `section_bars` compassos cheios."""
    if texture not in TEXTURES_MIDI:
        raise ValueError(f"textura inválida: {texture!r} (use {list(TEXTURES_MIDI)})")
    section_ticks = section_bars * bar_ticks
    out: List[Phrase] = []
    for piece in pieces:
        if piece.bar_ticks != bar_ticks:
            continue
        total = max(e for _, e, _ in piece.notes)
        for k in range(total // section_ticks):
            events = _slice_section(piece.notes, k * section_ticks, (k + 1) * section_ticks, bar_ticks, texture)
            silent = sum(ev.dur for ev in events if not ev.pitches)
            if silent > max_silence * section_ticks or len(events) < 2:
                continue
            out.append(Phrase(tuple(events), final=False))
    return out
