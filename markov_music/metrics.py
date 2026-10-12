"""Métricas de estilo (condução de vozes) para comparar peças geradas com o corpus de Bach."""
from __future__ import annotations

from typing import Iterable, Sequence, Tuple

from .corpus import REST, Event


def parallel_perfects(phrases: Iterable[Sequence[Event]]) -> Tuple[int, int]:
    """Conta quintas e oitavas (ou uníssonos) paralelas entre pares de vozes.

    Para cada par de eventos consecutivos DENTRO de uma frase e cada par de vozes, há paralelismo
    quando as duas vozes se movem na mesma direção e o intervalo (módulo oitava) é uma quinta justa
    ou uma oitava/uníssono tanto antes quanto depois. Devolve (paralelos, transições entre eventos).
    """
    parallels = transitions = 0
    for events in phrases:
        for a, b in zip(events, events[1:]):
            transitions += 1
            n = len(a.pitches)
            for i in range(n):
                for j in range(i + 1, n):
                    ai, aj, bi, bj = a.pitches[i], a.pitches[j], b.pitches[i], b.pitches[j]
                    if REST in (ai, aj, bi, bj) or ai == bi or aj == bj:
                        continue                                  # pausa ou voz parada: não é "movimento"
                    if (bi > ai) != (bj > aj):
                        continue                                  # movimento contrário/oblíquo
                    before, after = (ai - aj) % 12, (bi - bj) % 12
                    if before == after and before in (0, 7):
                        parallels += 1
    return parallels, transitions
