"""Treina o modelo e compõe peças (frase por frase, respeitando a forma do coral).

Restrição estilística do projeto: **coral de J. S. Bach**
    * peça = sequência de N frases; cada frase termina numa fermata (cadência);
    * as frases se encaixam metricamente (a anacruse da frase seguinte cai onde a anterior termina);
    * a última frase termina em cadência final, com a TÔNICA no grave (Dó em modo maior, Lá em menor).

A cadeia de Markov sozinha não garante nada disso -- por isso há "amostragem por rejeição":
geramos uma frase, e se ela violar a restrição, sorteamos outra.

Restrição opcional anti-plágio (`max_copy`): rejeita frases cujos trechos de k eventos são
cópias demais do corpus. É um botão para ajustar o trade-off fidelidade x novidade.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .corpus import BAR_TICKS, REST, Event, Phrase, RawChorale, build_phrases, load_raw_chorales
from .markov import MarkovChain
from .novelty import NoveltyMixin

END_MID = "<FIM_DE_FRASE>"      # a frase terminou numa fermata, a peça continua
END_FINAL = "<FIM_DA_PECA>"     # última frase do coral
END_TOKENS = (END_MID, END_FINAL)

TEXTURES: Dict[str, Tuple[int, ...]] = {
    "melody": (0,),             # só a melodia (soprano): cada nota é um estado
    "satb": (0, 1, 2, 3),       # 4 vozes: cada "fatia vertical" (acorde) é um estado
}
TONIC_PITCH_CLASS = {"major": 0, "minor": 9}     # corpus transposto para Dó maior / Lá menor
MIN_PHRASE_EVENTS = 4
# tamanho k (em eventos) dos trechos usados para medir cópia: a melodia tem frases curtas (~8 notas)
COPY_K = {"melody": 6, "satb": 8}


@dataclass
class Piece:
    """Resultado da composição: frases (listas de Event) + os parâmetros usados."""
    phrases: List[List[Event]]
    params: Dict[str, object] = field(default_factory=dict)
    distinct: Optional[List[List[Event]]] = None     # seções distintas (se a forma repete seções, ex.: AABA)

    @property
    def distinct_phrases(self) -> List[List[Event]]:
        return self.distinct if self.distinct is not None else self.phrases

    @property
    def events(self) -> List[Event]:
        return [e for phrase in self.phrases for e in phrase]

    @property
    def n_voices(self) -> int:
        return len(self.phrases[0][0].pitches)


class ChoraleModel(NoveltyMixin):
    """Cadeia de Markov + regras do estilo (o "compositor")."""

    def __init__(self, order: int, phrases: Sequence[Phrase], mode: str, texture: str) -> None:
        self.order, self.mode, self.texture = order, mode, texture
        self.phrases = list(phrases)
        self.chain = MarkovChain(order).fit(training_sequences(self.phrases))
        # posições métricas em que frases reais começam (para encaixar as frases)
        self.start_positions: Set[int] = {p.events[0].pos for p in self.phrases}
        self.n_phrases_train = len(self.phrases)
        self.copy_k = COPY_K[texture]
        self._init_novelty()

    # --------------------------------------------------------------- composição
    def compose(
        self,
        n_phrases: int = 5,
        seed: int = 0,
        temperature: float = 1.0,
        max_copy: Optional[float] = None,
        max_phrase_events: int = 60,
        max_tries: int = 5000,
    ) -> Piece:
        """Compõe uma peça de `n_phrases` frases. Mesma `seed` => mesma música."""
        rng = random.Random(seed)
        phrases: List[List[Event]] = []
        required_pos: Optional[int] = None          # onde a próxima frase PRECISA começar no compasso
        for i in range(n_phrases):
            events = self._compose_phrase(
                rng, temperature, is_last=(i == n_phrases - 1), required_pos=required_pos,
                max_copy=max_copy, max_events=max_phrase_events, max_tries=max_tries,
            )
            phrases.append(events)
            last = events[-1]
            required_pos = (last.pos + last.dur) % BAR_TICKS
        params = dict(order=self.order, texture=self.texture, mode=self.mode, phrases=n_phrases,
                      seed=seed, temperature=temperature, max_copy=max_copy)
        return Piece(phrases, params)

    def _compose_phrase(self, rng, temperature, is_last, required_pos, max_copy, max_events, max_tries) -> List[Event]:
        accept_first = None if required_pos is None else (lambda ev, p=required_pos: ev.pos == p)
        for _ in range(max_tries):
            seq = self.chain.generate(rng, END_TOKENS, max_events, temperature, accept_first)
            if seq is None:
                continue
            *events, end = seq
            if len(events) < MIN_PHRASE_EVENTS:
                continue
            last = events[-1]
            if is_last:
                # cadência final: termina em END_FINAL e com a tônica no grave
                if end != END_FINAL or not self._ends_on_tonic(last):
                    continue
            else:
                # frase do meio: termina em fermata e deixa a próxima começar num ponto métrico válido
                if end != END_MID or (last.pos + last.dur) % BAR_TICKS not in self.start_positions:
                    continue
            if max_copy is not None and self._phrase_copy_rate(events) > max_copy:
                continue                                  # cópia demais do corpus: sorteia outra frase
            return events
        raise RuntimeError(
            f"Não consegui gerar uma frase válida em {max_tries} tentativas "
            f"(tente reduzir a ordem, aumentar a temperatura ou aumentar --max-copy)."
        )

    def _ends_on_tonic(self, event: Event) -> bool:
        sounding = [p for p in event.pitches if p != REST]
        return bool(sounding) and min(sounding) % 12 == TONIC_PITCH_CLASS[self.mode]


def training_sequences(phrases: Sequence[Phrase]) -> List[List[object]]:
    """Cada frase vira uma sequência de eventos terminada por um marcador de fim."""
    return [list(p.events) + [END_FINAL if p.final else END_MID] for p in phrases]


def train_model(
    order: int = 2,
    texture: str = "satb",
    mode: str = "major",
    raw_chorales: Optional[Sequence[RawChorale]] = None,
    cache_dir: Optional[Path] = Path(".cache"),
) -> ChoraleModel:
    """Atalho: lê o corpus (com cache), fatia na textura escolhida e treina a cadeia."""
    if texture not in TEXTURES:
        raise ValueError(f"textura inválida: {texture!r} (use {list(TEXTURES)})")
    if mode not in TONIC_PITCH_CLASS:
        raise ValueError(f"modo inválido: {mode!r} (use 'major' ou 'minor')")
    raws = raw_chorales if raw_chorales is not None else load_raw_chorales(cache_dir)
    phrases = build_phrases(raws, mode, TEXTURES[texture])
    return ChoraleModel(order, phrases, mode, texture)
