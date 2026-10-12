#!/usr/bin/env python
"""Reproduz TODOS os resultados do trabalho com um comando:

    python reproduce_all.py

Recria as peças de `examples/` (MIDI + WAV + piano-roll + JSON) e a figura/tabela do
experimento de ordem em `docs/`. Como todas as sementes são fixas, o resultado é o mesmo
em qualquer máquina com as mesmas versões de Python e music21 (veja o README).
"""
from pathlib import Path

import experiment_orders
import generate

EXAMPLES = Path("examples")

# (pasta, argumentos do generate.py) -- cada linha é um "experimento" descrito no README
RUNS = [
    # A) MESMA configuração, sementes diferentes -> peças diferentes
    ("A_sementes_diferentes", ["--texture", "satb", "--mode", "major", "--order", "1", "--seed", "1", "--count", "3"]),
    # B) outro corpus de treino (modo menor)
    ("B_modo_menor",          ["--texture", "satb", "--mode", "minor", "--order", "1", "--seed", "1", "--count", "2"]),
    # C) efeito da ORDEM na melodia (mesma semente): 1, 2 e 4
    ("C_ordem_melodia",       ["--texture", "melody", "--order", "1", "--seed", "7"]),
    ("C_ordem_melodia",       ["--texture", "melody", "--order", "2", "--seed", "7"]),
    ("C_ordem_melodia",       ["--texture", "melody", "--order", "4", "--seed", "7"]),
    # D) efeito da ORDEM no coral a 4 vozes (mesma semente): 1, 2 e 3
    ("D_ordem_coral",         ["--texture", "satb", "--order", "1", "--seed", "4"]),
    ("D_ordem_coral",         ["--texture", "satb", "--order", "2", "--seed", "4"]),
    ("D_ordem_coral",         ["--texture", "satb", "--order", "3", "--seed", "4"]),
    # E) efeito da TEMPERATURA na melodia (mesma semente e ordem)
    ("E_temperatura_melodia", ["--texture", "melody", "--order", "2", "--seed", "7", "--temperature", "0.5"]),
    ("E_temperatura_melodia", ["--texture", "melody", "--order", "2", "--seed", "7", "--temperature", "2.0"]),
    # F) restrição anti-plágio: coral de ordem 2 com e sem --max-copy (mesma semente)
    ("F_anti_plagio",         ["--texture", "satb", "--order", "2", "--seed", "4", "--max-copy", "0.3"]),
    ("F_anti_plagio",         ["--texture", "melody", "--order", "4", "--seed", "7", "--max-copy", "0.3"]),
]


def main() -> None:
    for folder, args in RUNS:
        print(f"\n=== {folder}: {' '.join(args)}")
        generate.main(args + ["--out", str(EXAMPLES / folder)])
    print("\n=== Experimento de ordem")
    experiment_orders.main([])


if __name__ == "__main__":
    main()
