"""Compositor baseado em SEÇÕES para corpora MIDI genéricos (ex.: Undertale).

Uma peça é uma `forma` (por exemplo "AABA"): cada letra é uma seção de N compassos sorteada da cadeia
de Markov, e letras repetidas REPETEM a mesma seção, como nas trilhas de jogos em loop.

Regras de estilo (amostragem por rejeição, como no modelo de corais):
    * a seção termina no marcador de fim E tem exatamente `section_bars` compassos;
    * não pode ser só silêncio;
    * (opcional) `max_copy`: recusa seções que copiam trechos demais do corpus.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .corpus import TICKS_PER_QUARTER, Event, Phrase
from .generator import Piece
from .markov import MarkovChain
from .midi_corpus import TEXTURES_MIDI, build_sections, load_midi_folder
from .novelty import NoveltyMixin

END_SECTION = "<FIM_DA_SECAO>"
COPY_K_MIDI = {"melody": 8, "outer": 8, "piano": 6}      # tamanho (em eventos) dos trechos que medem "cópia"


class SectionModel(NoveltyMixin):
    """Cadeia de Markov + regras de seção (o "compositor" do corpus MIDI)."""

    def __init__(self, order: int, sections: Sequence[Phrase], texture: str, bar_ticks: int, section_bars: int) -> None:
        if not sections:
            raise ValueError("Nenhuma seção de treino: confira a pasta de MIDI e o compasso (--beats-per-bar).")
        self.order, self.texture = order, texture
        self.bar_ticks, self.section_bars = bar_ticks, section_bars
        self.section_ticks = bar_ticks * section_bars
        self.phrases = list(sections)
        self.chain = MarkovChain(order).fit(list(p.events) + [END_SECTION] for p in self.phrases)
        self.n_phrases_train = len(self.phrases)
        self.copy_k = COPY_K_MIDI[texture]
        self._init_novelty()

    # --------------------------------------------------------------- composição
    def compose(
        self,
        form: str = "AABA",
        seed: int = 0,
        temperature: float = 1.0,
        max_copy: Optional[float] = None,
        max_tries: int = 20000,
    ) -> Piece:
        """Compõe uma peça com a `form` dada (letras A-Z). Mesma `seed` => mesma música."""
        if not form or not form.isalpha() or not form.isupper():
            raise ValueError("A forma deve ter só letras maiúsculas, por exemplo 'AABA'.")
        rng = random.Random(seed)
        made: Dict[str, List[Event]] = {}
        for letter in form:                                       # uma seção nova por letra distinta
            if letter not in made:
                made[letter] = self._compose_section(rng, temperature, max_copy, max_tries)
        params = dict(order=self.order, texture=self.texture, form=form, bars=self.section_bars, seed=seed,
                      temperature=temperature, max_copy=max_copy)
        return Piece([made[c] for c in form], params, distinct=[made[c] for c in dict.fromkeys(form)])

    def _compose_section(self, rng, temperature, max_copy, max_tries) -> List[Event]:
        max_events = self.section_ticks // 2                      # seção com eventos de >= 2 ticks em média
        for _ in range(max_tries):
            seq = self.chain.generate(rng, (END_SECTION,), max_events, temperature)
            if seq is None:
                continue
            events = seq[:-1]
            if sum(ev.dur for ev in events) != self.section_ticks:    # tem de ter exatamente N compassos
                continue
            if not any(ev.pitches for ev in events):                  # não vale seção muda
                continue
            if max_copy is not None and self._phrase_copy_rate(events) > max_copy:
                continue
            return events
        raise RuntimeError(
            f"Não consegui gerar uma seção válida em {max_tries} tentativas "
            f"(tente reduzir a ordem, aumentar a temperatura, usar menos compassos ou aumentar --max-copy)."
        )


def train_section_model(
    midi_dir: str,
    order: int = 2,
    texture: str = "piano",
    section_bars: int = 4,
    beats_per_bar: int = 4,
    cache_dir: Optional[Path] = Path(".cache"),
    verbose: bool = True,
) -> SectionModel:
    """Atalho: lê os MIDIs (com cache), corta em seções e treina a cadeia."""
    if texture not in TEXTURES_MIDI:
        raise ValueError(f"textura inválida: {texture!r} (use {list(TEXTURES_MIDI)})")
    pieces = load_midi_folder(midi_dir, cache_dir, verbose)
    bar_ticks = beats_per_bar * TICKS_PER_QUARTER
    sections = build_sections(pieces, texture, bar_ticks, section_bars)
    n_used = len({id(p) for p in pieces if p.bar_ticks == bar_ticks})
    if verbose:
        print(f"  [midi] {n_used} peças com compasso de {beats_per_bar} tempos -> {len(sections)} seções de {section_bars} compassos")
    return SectionModel(order, sections, texture, bar_ticks, section_bars)
