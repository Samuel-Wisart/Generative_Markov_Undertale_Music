"""Medidas de "cópia do corpus" (memorização), compartilhadas por todos os modelos compositores.

O modelo que usar este mixin precisa ter:
    self.phrases   lista de objetos com `.events` (as frases/seções de treino)
    self.copy_k    tamanho padrão (em eventos) dos trechos comparados
e chamar `self._init_novelty()` no construtor.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Set, Tuple

from .corpus import Event


class NoveltyMixin:
    phrases: Sequence
    copy_k: int

    def _init_novelty(self) -> None:
        self._ngram_cache: Dict[int, Set[Tuple[Event, ...]]] = {}

    def _corpus_ngrams(self, k: int) -> Set[Tuple[Event, ...]]:
        """Todos os trechos de k eventos consecutivos que existem no corpus de treino."""
        if k not in self._ngram_cache:
            grams: Set[Tuple[Event, ...]] = set()
            for phrase in self.phrases:
                ev = phrase.events
                grams.update(ev[i:i + k] for i in range(len(ev) - k + 1))
            self._ngram_cache[k] = grams
        return self._ngram_cache[k]

    def copy_counts(self, piece, k: Optional[int] = None) -> Tuple[int, int]:
        """(trechos copiados, total de trechos) de k eventos consecutivos dentro das frases da peça.

        Seções repetidas de propósito (forma AABA) são contadas uma vez só.
        """
        k = k or self.copy_k
        grams, total, copied = self._corpus_ngrams(k), 0, 0
        for phrase in piece.distinct_phrases:
            for i in range(len(phrase) - k + 1):
                total += 1
                copied += tuple(phrase[i:i + k]) in grams
        return copied, total

    def copy_rate(self, piece, k: Optional[int] = None) -> float:
        """Fração dos trechos de k eventos da peça que existem IGUAIS no corpus (memorização).

        k pequeno mede "plausibilidade local" (quanto maior, mais parecido com o estilo);
        k grande mede "plágio" (trechos longos copiados do corpus).
        """
        copied, total = self.copy_counts(piece, k)
        return copied / total if total else float("nan")

    def _phrase_copy_rate(self, events: Sequence[Event]) -> float:
        """Fração de trechos copiados em UMA frase (usada pela restrição `max_copy`).

        Frases mais curtas que k são medidas pelo trecho inteiro (senão uma frase de poucas
        notas nunca seria considerada cópia e o gerador fugiria para frases minúsculas).
        """
        k = min(self.copy_k, len(events))
        grams = self._corpus_ngrams(k)
        windows = [tuple(events[i:i + k]) for i in range(len(events) - k + 1)]
        return sum(w in grams for w in windows) / len(windows)
