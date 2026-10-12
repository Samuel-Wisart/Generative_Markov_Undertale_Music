#!/usr/bin/env python
"""Gera corais no estilo de Bach com uma cadeia de Markov.

Exemplos:
    python generate.py                                  # 1 coral a 4 vozes (modo maior, ordem 1)
    python generate.py --count 3 --seed 10              # 3 corais diferentes (sementes 10, 11, 12)
    python generate.py --texture melody --order 4       # só a melodia, cadeia de ordem 4
    python generate.py --mode minor --temperature 1.5   # modo menor, escolhas mais "arriscadas"
    python generate.py --order 2 --max-copy 0.5         # ordem 2, mas recusando frases muito copiadas

Para cada peça são gravados, em --out: um .mid (resultado oficial), um .wav (audição),
um .png (piano-roll) e um .json (parâmetros e métricas, para reprodutibilidade).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from markov_music.audio import render_wav
from markov_music.generator import COPY_K, TEXTURES, train_model
from markov_music.midi_io import CHURCH_ORGAN, piece_to_notes, read_midi_seconds, write_midi
from markov_music.plots import save_piano_roll

DEFAULT_ORDER = {"satb": 1, "melody": 2}      # justificativa: experiment_orders.py (docs/order_experiment.csv)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_argument_group("modelo (hiperparâmetros da cadeia de Markov)")
    g.add_argument("--texture", choices=list(TEXTURES), default="satb",
                   help="satb = coral a 4 vozes; melody = só a melodia do soprano (padrão: satb)")
    g.add_argument("--mode", choices=["major", "minor"], default="major",
                   help="corpus de treino: corais em modo maior ou menor (padrão: major)")
    g.add_argument("--order", type=int, default=None,
                   help="ordem n da cadeia = quantos estados anteriores ela lembra "
                        "(padrão: 1 para satb, 2 para melody)")
    g.add_argument("--temperature", type=float, default=1.0,
                   help="<1 escolhe o mais provável; >1 achata as probabilidades (padrão: 1.0)")
    g.add_argument("--max-copy", type=float, default=None, metavar="FRAÇÃO",
                   help="restrição anti-plágio: recusa frases em que mais que esta fração (0-1) dos trechos "
                        "é cópia literal do corpus (padrão: desligada)")
    g = p.add_argument_group("composição")
    g.add_argument("--phrases", type=int, default=5, help="número de frases do coral (padrão: 5)")
    g.add_argument("--seed", type=int, default=1, help="semente aleatória (mesma semente = mesma música)")
    g.add_argument("--count", type=int, default=1,
                   help="quantas peças gerar; usa as sementes seed, seed+1, ... (padrão: 1)")
    g = p.add_argument_group("saída")
    g.add_argument("--out", type=Path, default=Path("output"), help="pasta de saída (padrão: output)")
    g.add_argument("--bpm", type=int, default=76, help="andamento em semínimas por minuto (padrão: 76)")
    g.add_argument("--fermata", type=float, default=1.5,
                   help="fator de alongamento da nota final de cada frase (padrão: 1.5)")
    g.add_argument("--program", type=int, default=CHURCH_ORGAN,
                   help="instrumento General MIDI, 0-127 (padrão: 19 = órgão de igreja)")
    g.add_argument("--no-audio", action="store_true", help="não gera o .wav")
    g.add_argument("--no-plot", action="store_true", help="não gera o piano-roll .png")
    g.add_argument("--sample-rate", type=int, default=22050, help="taxa de amostragem do .wav (padrão: 22050)")
    g.add_argument("--cache-dir", type=Path, default=Path(".cache"),
                   help="onde guardar o corpus já processado (padrão: .cache)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    order = args.order if args.order is not None else DEFAULT_ORDER[args.texture]

    print(f"Treinando: textura={args.texture}, modo={args.mode}, ordem={order} ...")
    model = train_model(order, args.texture, args.mode, cache_dir=args.cache_dir)
    chain = model.chain
    print(f"  {model.n_phrases_train} frases de treino | {chain.n_contexts} contextos | "
          f"média de {chain.mean_branching():.2f} continuações por contexto | "
          f"{chain.deterministic_fraction():.0%} dos contextos sem escolha")

    for k in range(args.count):
        seed = args.seed + k
        try:
            piece = model.compose(args.phrases, seed=seed, temperature=args.temperature, max_copy=args.max_copy)
        except RuntimeError as err:                    # restrições impossíveis (ex.: ordem alta + --max-copy baixo)
            print(f"ERRO (semente {seed}): {err}", file=sys.stderr)
            return 2
        notes = piece_to_notes(piece, args.fermata)
        stem = f"{args.texture}_{args.mode}_o{order}_T{args.temperature:g}"
        stem += f"_copy{args.max_copy:g}" if args.max_copy is not None else ""
        stem += f"_seed{seed}"
        mid_path = args.out / f"{stem}.mid"
        write_midi(notes, mid_path, args.bpm, args.program)

        seconds = max(n.start + n.dur for n in notes) * 60.0 / args.bpm
        copy = model.copy_rate(piece)
        info = {**piece.params, "bpm": args.bpm, "fermata": args.fermata, "program": args.program,
                "events": len(piece.events), "notes": len(notes), "seconds": round(seconds, 1),
                "copy_k": COPY_K[args.texture], "copied_from_corpus": round(copy, 3)}
        (args.out / f"{stem}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        if not args.no_plot:
            save_piano_roll(notes, args.out / f"{stem}.png", title=stem)
        if not args.no_audio:
            # o áudio é sintetizado a partir do ARQUIVO .mid (o resultado oficial), não da memória
            render_wav(read_midi_seconds(mid_path), args.out / f"{stem}.wav", args.sample_rate)

        print(f"[{k + 1}/{args.count}] {mid_path}  ({seconds:.0f}s, {len(notes)} notas, "
              f"{copy:.0%} dos trechos de {COPY_K[args.texture]} eventos copiados do corpus)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
