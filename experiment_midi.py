#!/usr/bin/env python
"""Experimento: efeito da ORDEM da cadeia num corpus MIDI seu (ex.: Undertale). Equivale ao experiment_orders.py.

Para cada textura (melody / outer / piano) e cada ordem n gera 60 peças de forma ABCD (4 seções distintas
de 4 compassos) e mede: contextos, cobertura em PEÇAS inéditas (validação cruzada em 5 partes, por peça),
trechos copiados (k eventos), seções inteiras copiadas e a viabilidade do --max-copy 0.3.

    python experiment_midi.py --midi-dir "data/undertale/Undertale MIDI"

Saídas: docs/undertale_orders.csv e docs/undertale_order_tradeoff.png
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from experiment_orders import COPY_COLOR, COVERAGE_COLOR, ORDER_COLORS, spread
from markov_music.corpus import TICKS_PER_QUARTER
from markov_music.markov import START, MarkovChain
from markov_music.midi_corpus import TEXTURES_MIDI, build_sections, load_midi_folder
from markov_music.plots import INK, INK_2, SURFACE, style_axes, use_agg
from markov_music.sections import END_SECTION, SectionModel

ORDERS = [1, 2, 3, 4]
K_VALUES = list(range(2, 13))
TEXTURE_TITLES = {"melody": "Só a melodia (nota mais aguda)", "outer": "Melodia + baixo", "piano": "Piano completo"}
TAU, TAU_SEEDS = 0.3, 20
BAR = 4 * TICKS_PER_QUARTER


def heldout_coverage(pieces, texture, bars, order, folds=5) -> float:
    """Validação cruzada POR PEÇA: % dos contextos de peças de teste que já existiam no treino."""
    usable = [p for p in pieces if p.bar_ticks == BAR]
    seen = total = 0
    for f in range(folds):
        train = [p for i, p in enumerate(usable) if i % folds != f]
        test = [p for i, p in enumerate(usable) if i % folds == f]
        chain = MarkovChain(order).fit(
            list(s.events) + [END_SECTION] for s in build_sections(train, texture, BAR, bars))
        for s in build_sections(test, texture, BAR, bars):
            padded = [START] * order + list(s.events) + [END_SECTION]
            for i in range(order, len(padded)):
                total += 1
                seen += tuple(padded[i - order:i]) in chain.counts
    return seen / total


def run(texture, pieces, bars, n_pieces):
    sections = build_sections(pieces, texture, BAR, bars)
    whole = {s.events for s in sections}
    rows = []
    for order in ORDERS:
        model = SectionModel(order, sections, texture, BAR, bars)
        generated, failed = [], 0
        for seed in range(n_pieces):
            try:
                generated.append(model.compose("ABCD", seed=seed))
            except RuntimeError:
                failed += 1
        curve = {}
        for k in K_VALUES:
            counts = [model.copy_counts(p, k) for p in generated]
            curve[k] = sum(c for c, _ in counts) / max(1, sum(t for _, t in counts))
        gen_sections = [tuple(s) for p in generated for s in p.distinct_phrases]
        ok = copied = total = 0
        for seed in range(TAU_SEEDS):
            try:
                piece = model.compose("AB", seed=seed, max_copy=TAU, max_tries=4000)
            except RuntimeError:
                continue
            ok += 1
            c, t = model.copy_counts(piece)
            copied, total = copied + c, total + t
        row = {
            "texture": texture, "order": order, "contexts": model.chain.n_contexts,
            "mean_branching": round(model.chain.mean_branching(), 3),
            "no_choice_contexts": round(model.chain.deterministic_fraction(), 3),
            "heldout_coverage": round(heldout_coverage(pieces, texture, bars, order), 3),
            "copy_k": model.copy_k, "copied_kgram": round(curve[model.copy_k], 3),
            "whole_sections_copied": round(sum(s in whole for s in gen_sections) / max(1, len(gen_sections)), 3),
            "failed_pieces": failed,
            "tau": TAU, "tau_feasible_seeds": ok, "tau_seeds": TAU_SEEDS,
            "tau_copied_kgram": round(copied / total, 3) if total else None,
            "curve": curve,
        }
        rows.append(row)
        print(f"  {texture:6s} n={order}: contextos={row['contexts']:6d}  ramificação={row['mean_branching']:.2f}  "
              f"sem escolha={row['no_choice_contexts']:.0%}  cobertura={row['heldout_coverage']:.0%}  "
              f"trechos de {model.copy_k} copiados={row['copied_kgram']:.0%}  "
              f"seções inteiras copiadas={row['whole_sections_copied']:.0%}  "
              f"max-copy {TAU}: viável em {ok}/{TAU_SEEDS}, cópia restante={row['tau_copied_kgram']}", flush=True)
    return rows


def plot(all_rows, path: Path) -> None:
    plt = use_agg()
    fig, axes = plt.subplots(len(TEXTURES_MIDI), 2, figsize=(11.5, 12.2), facecolor=SURFACE,
                             gridspec_kw={"width_ratios": [1.25, 1]})
    colors = ORDER_COLORS["satb"]
    for r, texture in enumerate(TEXTURES_MIDI):
        rows = [x for x in all_rows if x["texture"] == texture]

        ax = axes[r][0]                                       # curva de novidade
        style_axes(ax)
        ends = []
        for row, color in zip(rows, colors):
            ys = [100 * row["curve"][k] for k in K_VALUES]
            ax.plot(K_VALUES, ys, color=color, linewidth=2, solid_capstyle="round", label=f"ordem {row['order']}")
            ends.append(ys[-1])
        for row, y_text in zip(rows, spread(ends, 6.5)):
            ax.text(K_VALUES[-1] + 0.25, y_text, f"n={row['order']}", fontsize=8, color=INK_2, va="center")
        ax.grid(axis="x", visible=False)
        ax.set_xticks(K_VALUES[::2])
        ax.set_xlim(2, K_VALUES[-1] + 1.4)
        ax.set_ylim(-3, 103)
        ax.set_xlabel("tamanho k do trecho (em eventos consecutivos)", fontsize=9)
        ax.set_ylabel("% dos trechos que existem no corpus", fontsize=9)
        ax.set_title(f"{TEXTURE_TITLES[texture]} — novidade x tamanho do trecho", fontsize=10, color=INK, loc="left")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, frameon=False, labelcolor=INK_2, ncol=4)

        ax = axes[r][1]                                       # resumo por ordem
        style_axes(ax)
        orders = [row["order"] for row in rows]
        for label, key, color in ((f"trechos de {rows[0]['copy_k']} eventos copiados (geração)", "copied_kgram", COPY_COLOR),
                                  ("contextos já vistos em peça inédita (dados)", "heldout_coverage", COVERAGE_COLOR)):
            ys = [100 * row[key] for row in rows]
            ax.plot(orders, ys, color=color, linewidth=2, marker="o", markersize=7, markeredgecolor=SURFACE,
                    markeredgewidth=1.5, label=label, solid_capstyle="round")
            ax.text(orders[-1] + 0.12, ys[-1], f"{ys[-1]:.0f}%", fontsize=8, color=INK_2, va="center")
        ax.grid(axis="x", visible=False)
        ax.set_xticks(orders)
        ax.set_xlim(orders[0] - 0.2, orders[-1] + 0.7)
        ax.set_ylim(-3, 103)
        ax.set_xlabel("ordem n da cadeia", fontsize=9)
        ax.set_ylabel("%", fontsize=9)
        ax.set_title(f"{TEXTURE_TITLES[texture]} — resumo por ordem", fontsize=10, color=INK, loc="left")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, frameon=False, labelcolor=INK_2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--midi-dir", type=Path, required=True)
    p.add_argument("--pieces", type=int, default=60, help="peças geradas por ordem (padrão: 60)")
    p.add_argument("--bars", type=int, default=4)
    p.add_argument("--out", type=Path, default=Path("docs"))
    p.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    args = p.parse_args(argv)

    pieces = load_midi_folder(str(args.midi_dir), args.cache_dir)
    all_rows = []
    for texture in TEXTURES_MIDI:
        print(f"Textura: {texture}")
        all_rows += run(texture, pieces, args.bars, args.pieces)

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "undertale_orders.csv"
    fields = [k for k in all_rows[0] if k != "curve"] + [f"copied_k{k}" for k in K_VALUES]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        for row in all_rows:
            w.writerow({**{k: v for k, v in row.items() if k != "curve"},
                        **{f"copied_k{k}": round(v, 3) for k, v in row["curve"].items()}})
    plot(all_rows, args.out / "undertale_order_tradeoff.png")
    print(f"Gravado: {csv_path} e {args.out / 'undertale_order_tradeoff.png'}")


if __name__ == "__main__":
    main()
