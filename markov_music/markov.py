"""Cadeia de Markov de ordem n -- a parte "matemática" do projeto.

Este módulo não sabe NADA sobre música. Ele trabalha com "tokens" quaisquer
(qualquer objeto que possa ser usado como chave de dicionário). Quem decide o
que é um token musical é o módulo `corpus.py`.

Ideia central (ordem n = 2, por exemplo):

    treino:   Dó Mi Sol Mi Dó      ->  (Dó, Mi) -> Sol
                                        (Mi, Sol) -> Mi
                                        (Sol, Mi) -> Dó

    geração:  olha as últimas n notas geradas, consulta a tabela e sorteia
              a próxima de acordo com as contagens observadas no treino.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Callable, Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

Token = Hashable
Context = Tuple[Token, ...]

# Marcador usado para "encher" o começo de cada sequência. Assim as primeiras
# notas de uma frase também têm um contexto de tamanho n:  (INICIO, INICIO, x)
START = "<INICIO>"


class MarkovChain:
    """Cadeia de Markov de ordem `order` treinada por contagem de transições."""

    def __init__(self, order: int) -> None:
        if order < 1:
            raise ValueError("A ordem da cadeia deve ser >= 1.")
        self.order = order
        # contexto -> contagem de cada próximo token observado
        self.counts: Dict[Context, Counter] = {}
        # cache de (tokens, pesos) para não recalcular a cada sorteio
        self._cache: Dict[Tuple[Context, float], Tuple[List[Token], List[float]]] = {}

    # ------------------------------------------------------------------ treino
    def fit(self, sequences: Iterable[Sequence[Token]]) -> "MarkovChain":
        """Aprende a tabela de transição a partir de uma lista de sequências.

        Cada sequência deve terminar com o seu próprio token de fim (é ele que
        ensina à cadeia QUANDO parar).
        """
        for seq in sequences:
            padded = [START] * self.order + list(seq)
            for i in range(self.order, len(padded)):
                context = tuple(padded[i - self.order:i])
                self.counts.setdefault(context, Counter())[padded[i]] += 1
        self._cache.clear()
        return self

    # --------------------------------------------------------------- consulta
    def probabilities(self, context: Sequence[Token], temperature: float = 1.0) -> Dict[Token, float]:
        """Distribuição de probabilidade do próximo token dado o contexto."""
        tokens, weights = self._weights(tuple(context), temperature)
        total = sum(weights)
        return {t: w / total for t, w in zip(tokens, weights)}

    def _weights(self, context: Context, temperature: float) -> Tuple[List[Token], List[float]]:
        key = (context, temperature)
        if key not in self._cache:
            counter = self.counts.get(context)
            if not counter:
                self._cache[key] = ([], [])
            else:
                # Temperatura: p ~ contagem^(1/T). T=1 -> probabilidades do corpus;
                # T<1 -> favorece o mais comum; T>1 -> achata (mais aleatório).
                expo = 1.0 / temperature
                tokens = list(counter)
                self._cache[key] = (tokens, [counter[t] ** expo for t in tokens])
        return self._cache[key]

    # ---------------------------------------------------------------- geração
    def sample_next(
        self,
        context: Sequence[Token],
        rng: random.Random,
        temperature: float = 1.0,
        accept: Optional[Callable[[Token], bool]] = None,
    ) -> Optional[Token]:
        """Sorteia o próximo token. `accept` (opcional) restringe os candidatos.

        Devolve None se o contexto é desconhecido ou se nenhum candidato passa
        no filtro `accept`.
        """
        if temperature <= 0:
            raise ValueError("A temperatura deve ser > 0.")
        tokens, weights = self._weights(tuple(context), temperature)
        if accept is not None:
            kept = [(t, w) for t, w in zip(tokens, weights) if accept(t)]
            if not kept:
                return None
            tokens, weights = [t for t, _ in kept], [w for _, w in kept]
        if not tokens:
            return None
        return rng.choices(tokens, weights=weights, k=1)[0]

    def generate(
        self,
        rng: random.Random,
        stop_tokens: Iterable[Token],
        max_len: int = 200,
        temperature: float = 1.0,
        accept_first: Optional[Callable[[Token], bool]] = None,
    ) -> Optional[List[Token]]:
        """Gera uma sequência a partir do INICIO até sortear um token de parada.

        A sequência devolvida inclui o token de parada no final. Devolve None
        se passar de `max_len` (cadeia "perdida") ou se não houver continuação.
        `accept_first` filtra apenas o primeiro token (usado p/ restrições).
        """
        stop = frozenset(stop_tokens)
        context: Context = (START,) * self.order
        out: List[Token] = []
        for step in range(max_len):
            token = self.sample_next(context, rng, temperature, accept_first if step == 0 else None)
            if token is None:
                return None
            out.append(token)
            if token in stop:
                return out
            context = context[1:] + (token,)  # janela deslizante de tamanho n
        return None

    # ------------------------------------------------------------ estatísticas
    @property
    def n_contexts(self) -> int:
        return len(self.counts)

    def mean_branching(self) -> float:
        """Média de continuações distintas por contexto (quanto menor, mais previsível)."""
        return sum(len(c) for c in self.counts.values()) / max(1, len(self.counts))

    def deterministic_fraction(self) -> float:
        """Fração dos contextos que têm UMA única continuação (zero escolha)."""
        return sum(1 for c in self.counts.values() if len(c) == 1) / max(1, len(self.counts))
