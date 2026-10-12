"""Do corpus de corais de Bach (music21) até os "eventos" que a cadeia de Markov lê.

Fluxo deste módulo:

    partitura (music21) --extract--> RawChorale  (notas em ticks, já transpostas)
    RawChorale --build_phrases--> Phrase = sequência de Event (um "estado" cada)

Um *Event* é o estado da cadeia de Markov. Ele resume "o que está soando agora":

    pos      posição dentro do compasso (em ticks)      -> a cadeia respeita a métrica
    pitches  altura MIDI de cada voz (-1 = pausa)       -> melodia e/ou harmonia
    attacks  a voz tocou uma nota nova nesta fatia?      -> distingue nota repetida de nota sustentada
    dur      duração da fatia (em ticks)                 -> ritmo
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

TICKS_PER_QUARTER = 12                 # 12 divide bem por 2, 3 e 4: semínima, colcheia, tercina, semicolcheia
BAR_TICKS = 4 * TICKS_PER_QUARTER      # só usamos corais em compasso 4/4
REST = -1                              # "altura" que representa pausa
CACHE_VERSION = 1


@dataclass(frozen=True)
class Event:
    """Um estado da cadeia (imutável e "hashable", logo pode ser chave de dicionário)."""
    pos: int
    pitches: Tuple[int, ...]
    attacks: Tuple[bool, ...]
    dur: int


@dataclass
class Phrase:
    events: Tuple[Event, ...]
    final: bool          # True se é a última frase do coral (termina em cadência final)


@dataclass
class RawChorale:
    """Um coral "cru": notas por voz em ticks, já transpostas para Dó maior / Lá menor."""
    name: str
    mode: str                                   # "major" ou "minor"
    transpose: int                              # semitons aplicados na transposição
    voices: List[List[Tuple[int, int, int]]]    # por voz: (início, fim, altura MIDI)
    fermata_ends: List[int]                     # tick onde termina cada nota com fermata (soprano)
    origin: int                                 # tick de um início de compasso (para calcular `pos`)


# --------------------------------------------------------------------------- extração
def _extract_voice(part) -> Tuple[List[List[int]], List[int]]:
    """Lê uma voz do music21. Une notas ligadas (ligaduras) e anota as fermatas."""
    from music21 import expressions

    notes: List[List[int]] = []          # [início, fim, altura]
    fermata_idx: List[int] = []
    for n in part.flatten().notes:
        start = round(float(n.offset) * TICKS_PER_QUARTER)
        end = start + max(1, round(float(n.quarterLength) * TICKS_PER_QUARTER))
        midi = n.pitch.midi
        tied = n.tie is not None and n.tie.type in ("stop", "continue")
        if notes and notes[-1][1] > start:               # sobreposição: corta a nota anterior
            notes[-1][1] = start
        if tied and notes and notes[-1][1] == start and notes[-1][2] == midi:
            notes[-1][1] = end                           # prolonga a nota anterior
        else:
            notes.append([start, end, midi])
        if any(isinstance(e, expressions.Fermata) for e in n.expressions):
            fermata_idx.append(len(notes) - 1)
    return notes, [notes[i][1] for i in fermata_idx]


class _Skip(Exception):
    """Coral descartado (com o motivo na mensagem)."""


def _read_chorale(path: str) -> RawChorale:
    from music21 import chord, corpus, meter

    score = corpus.parse(path)
    if len(score.parts) != 4:
        raise _Skip("não tem 4 vozes")
    signatures = {ts.ratioString for ts in score.recurse().getElementsByClass(meter.TimeSignature)}
    if signatures != {"4/4"}:
        raise _Skip(f"compasso {sorted(signatures)}")
    if any(isinstance(n, chord.Chord) for n in score.recurse().notes):
        raise _Skip("voz com acordes")

    # Tonalidade (algoritmo de Krumhansl-Schmuckler) -> transposição para Dó maior / Lá menor.
    key = score.analyze("key")
    target = 0 if key.mode == "major" else 9
    shift = (target - key.tonic.pitchClass + 6) % 12 - 6          # menor deslocamento, em [-6, +5]

    voices: List[List[Tuple[int, int, int]]] = []
    fermata_ends: List[int] = []
    for i, part in enumerate(score.parts):                         # 0=soprano 1=contralto 2=tenor 3=baixo
        notes, ferm = _extract_voice(part)
        if not notes:
            raise _Skip("voz vazia")
        voices.append([(s, e, m + shift) for s, e, m in notes])
        if i == 0:
            fermata_ends = ferm

    # Origem do compasso: lida a partir do `beat` da primeira nota do soprano (cobre anacruse).
    soprano = score.parts[0]
    first = next(iter(soprano.recurse().notes))
    pos_first = round((float(first.beat) - 1.0) * TICKS_PER_QUARTER)
    origin = voices[0][0][0] - pos_first

    # Todo compasso COMPLETO precisa cair na grade de 4/4. (Compassos incompletos são
    # normais: a anacruse e os compassos "partidos em dois" ao redor das fermatas.)
    for m in soprano.getElementsByClass("Measure"):
        full = float(m.duration.quarterLength) == 4.0 and not m.paddingLeft
        if full and (round(float(m.offset) * TICKS_PER_QUARTER) - origin) % BAR_TICKS != 0:
            raise _Skip("compassos irregulares")

    return RawChorale(path, key.mode, shift, voices, fermata_ends, origin)


def load_raw_chorales(
    cache_dir: Optional[Path] = None,
    limit: Optional[int] = None,
    verbose: bool = True,
) -> List[RawChorale]:
    """Lê os corais de Bach do music21 (ou do cache em disco, se existir).

    A primeira execução leva ~1 min (parse + análise de tonalidade de ~350 corais);
    as seguintes são instantâneas graças ao cache.
    """
    import music21
    from music21 import corpus

    cache_file = None
    if cache_dir is not None and limit is None:
        cache_file = Path(cache_dir) / f"bach_chorales_v{CACHE_VERSION}_m21-{music21.__version__}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return pickle.load(f)
            except Exception:
                pass  # cache corrompido: reconstrói

    paths = sorted(corpus.chorales.Iterator(returnType="filename"))
    if limit is not None:
        paths = paths[:limit]
    chorales: List[RawChorale] = []
    skipped: Dict[str, int] = {}
    for i, path in enumerate(paths, 1):
        try:
            chorales.append(_read_chorale(path))
        except _Skip as why:
            skipped[str(why)] = skipped.get(str(why), 0) + 1
        if verbose and (i % 50 == 0 or i == len(paths)):
            print(f"  [corpus] {i}/{len(paths)} corais lidos...", flush=True)
    if verbose:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(skipped.items())) or "nenhum"
        print(f"  [corpus] {len(chorales)} corais aproveitados (descartados -> {detail}).")

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "wb") as f:
            pickle.dump(chorales, f)
    return chorales


# ---------------------------------------------------------------- fatiamento -> estados
def slice_chorale(raw: RawChorale, voices: Sequence[int], min_events: int = 3) -> List[Phrase]:
    """Corta o coral em fatias verticais e agrupa as fatias em frases (separadas por fermatas).

    Fatia = trecho entre dois instantes consecutivos em que QUALQUER voz escolhida muda.
    Com `voices=(0,)` obtemos só a melodia (cada nota do soprano é um estado); com
    `voices=(0,1,2,3)` obtemos acordes a 4 vozes (cada fatia é um estado).
    """
    tracks = [raw.voices[v] for v in voices]
    bounds = sorted({t for track in tracks for s, e, _ in track for t in (s, e)})
    end_of_piece = bounds[-1]
    phrase_ends = set(raw.fermata_ends)
    cursor = [0] * len(tracks)                       # ponteiro por voz (varredura linear)

    phrases: List[Phrase] = []
    current: List[Event] = []
    for b0, b1 in zip(bounds, bounds[1:]):
        pitches, attacks = [], []
        for k, track in enumerate(tracks):
            while cursor[k] < len(track) and track[cursor[k]][1] <= b0:
                cursor[k] += 1
            if cursor[k] < len(track) and track[cursor[k]][0] <= b0:
                s, _, midi = track[cursor[k]]
                pitches.append(midi)
                attacks.append(s == b0)
            else:
                pitches.append(REST)
                attacks.append(False)
        current.append(Event((b0 - raw.origin) % BAR_TICKS, tuple(pitches), tuple(attacks), b1 - b0))
        if b1 in phrase_ends or b1 == end_of_piece:
            if len(current) >= min_events:
                phrases.append(Phrase(tuple(current), final=(b1 == end_of_piece)))
            current = []
    return phrases


def build_phrases(raws: Sequence[RawChorale], mode: str, voices: Sequence[int]) -> List[Phrase]:
    """Todas as frases de todos os corais de um modo (major/minor) numa textura (voices)."""
    out: List[Phrase] = []
    for raw in raws:
        if raw.mode == mode:
            out.extend(slice_chorale(raw, voices))
    return out
