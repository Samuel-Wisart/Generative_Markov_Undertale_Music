#!/usr/bin/env python
"""Experimento: o que muda quando aumentamos a ORDEM da cadeia de Markov?

Para cada ordem n gera várias peças e mede, entre outras coisas:

  * novidade em função do tamanho do trecho k: que fração dos trechos de k eventos
    consecutivos da peça gerada EXISTE igual no corpus?  (k pequeno ~ "soa como o estilo";
    k grande ~ "copiou do corpus");
  * cobertura em corais inéditos (validação cruzada em 5 partes): que fração dos contextos de
    n estados de um coral que a cadeia NUNCA viu já aparece no treino (esparsidade dos dados);
  * ramificação: média de continuações possíveis por contexto e fração de contextos sem escolha;
  * frases inteiras copiadas: fração de frases geradas idênticas a uma frase do corpus;
  * quintas/oitavas paralelas (só coral a 4 vozes): defeito clássico de condução de vozes, por
    100 transições entre acordes, comparado com o próprio corpus de Bach;
  * viabilidade da restrição anti-plágio (--max-copy 0.3): em quantas sementes foi possível gerar
    a peça e qual a taxa de cópia que sobrou.

Saídas: docs/order_experiment.csv e docs/order_tradeoff.png

    python experiment_orders.py                 # ~1 min
    python experiment_orders.py --pieces 100    # mais peças = médias mais estáveis
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from markov_music.corpus import build_phrases, load_raw_chorales
from markov_music.generator import COPY_K, TEXTURES, ChoraleModel, training_sequences
from markov_music.markov import START, MarkovChain
from markov_music.metrics import parallel_perfects
from markov_music.plots import INK, INK_2, SURFACE, style_axes, use_agg

ORDERS = {"melody": [1, 2, 3, 4, 5], "satb": [1, 2, 3, 4]}
TAU, TAU_SEEDS = 0.3, 40                       # restrição anti-plágio testada e nº de sementes da viabilidade
K_VALUES = {"melody": list(range(2, 9)), "satb": list(range(2, 13))}
TEXTURE_TITLES = {"melody": "Melodia (soprano)", "satb": "Coral a 4 vozes (SATB)"}
# rampa ordinal (um matiz, claro -> escuro) validada: uma cor por ordem
ORDER_COLORS = {
    "melody": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b"],
    "satb": ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
}
COPY_COLOR, COVERAGE_COLOR = "#eb6834", "#2a78d6"            # categórico: slots 2 e 1


def heldout_coverage(raws, mode, voices, order, folds=5) -> float:
    """Validação cruzada: % dos contextos de corais de TESTE que já existiam no treino."""
    chorales = [r for r in raws if r.mode == mode]
    seen = total = 0
    for f in range(folds):
        train = [r for i, r in enumerate(chorales) if i % folds != f]
        test = [r for i, r in enumerate(chorales) if i % folds == f]
        chain = MarkovChain(order).fit(training_sequences(build_phrases(train, mode, voices)))
        for seq in training_sequences(build_phrases(test, mode, voices)):
            padded = [START] * order + seq
            for i in range(order, len(padded)):
                total += 1
                seen += tuple(padded[i - order:i]) in chain.counts
    return seen / total


def maxcopy_feasibility(model, n_phrases):
    """Com --max-copy TAU: em quantas sementes deu para compor e qual a cópia que restou (pooled)."""
    ok = copied = total = 0
    for seed in range(TAU_SEEDS):
        try:
            piece = model.compose(n_phrases, seed=seed, max_copy=TAU)
        except RuntimeError:                              # restrição inviável para esta semente
            continue
        ok += 1
        c, t = model.copy_counts(piece)
        copied, total = copied + c, total + t
    return ok, (copied / total if total else None)


def run(texture, mode, raws, n_pieces, n_phrases):
    voices = TEXTURES[texture]
    phrases = build_phrases(raws, mode, voices)
    whole_phrases = {p.events for p in phrases}
    baseline = None
    if len(voices) > 1:                                   # quintas/oitavas paralelas do próprio Bach
        par, trans = parallel_perfects(p.events for p in phrases)
        baseline = {"texture": texture, "mode": mode, "order": "corpus", "parallels_per100": round(100 * par / trans, 2)}
        print(f"  {texture:6s} corpus: {baseline['parallels_per100']:.2f} quintas/oitavas paralelas por 100 transições")
    rows = []
    for order in ORDERS[texture]:
        model = ChoraleModel(order, phrases, mode, texture)
        pieces = [model.compose(n_phrases, seed=s) for s in range(n_pieces)]
        curve = {}
        for k in K_VALUES[texture]:                      # soma sobre TODAS as peças (frases curtas => poucas janelas)
            counts = [model.copy_counts(p, k) for p in pieces]
            curve[k] = sum(c for c, _ in counts) / max(1, sum(t for _, t in counts))
        k_sum = COPY_K[texture]
        gen_phrases = [tuple(ph) for p in pieces for ph in p.phrases]
        row = {
            "texture": texture, "mode": mode, "order": order,
            "contexts": model.chain.n_contexts,
            "mean_branching": round(model.chain.mean_branching(), 3),
            "no_choice_contexts": round(model.chain.deterministic_fraction(), 3),
            "heldout_coverage": round(heldout_coverage(raws, mode, voices, order), 3),
            "copy_k": k_sum, "copied_kgram": round(curve[k_sum], 3),
            "whole_phrases_copied": round(sum(p in whole_phrases for p in gen_phrases) / len(gen_phrases), 3),
            "curve": curve,
        }
        if len(voices) > 1:
            par, trans = parallel_perfects(gen_phrases)
            row["parallels_per100"] = round(100 * par / max(1, trans), 2)
        ok, rate = maxcopy_feasibility(model, n_phrases)
        row.update({"tau": TAU, "tau_feasible_seeds": ok, "tau_seeds": TAU_SEEDS,
                    "tau_copied_kgram": None if rate is None else round(rate, 3)})
        rows.append(row)
        print(f"  {texture:6s} n={order}: contextos={row['contexts']:6d}  ramificação={row['mean_branching']:.2f}  "
              f"sem escolha={row['no_choice_contexts']:.0%}  cobertura={row['heldout_coverage']:.0%}  "
              f"trechos de {k_sum} copiados={row['copied_kgram']:.0%}  frases inteiras copiadas={row['whole_phrases_copied']:.0%}  "
              f"paralelas/100={row.get('parallels_per100', '-')}  "
              f"max-copy {TAU}: viável em {ok}/{TAU_SEEDS} sementes, cópia restante={row['tau_copied_kgram']}")
    return rows, baseline


def spread(values, min_gap):
    """Afasta rótulos que colidiriam: devolve posições y (mesma ordem) com folga mínima entre vizinhos."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    for a, b in zip(order, order[1:]):
        if out[b] - out[a] < min_gap:
            out[b] = out[a] + min_gap
    return out


def plot(all_rows, path: Path) -> None:
    plt = use_agg()
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.4), facecolor=SURFACE, gridspec_kw={"width_ratios": [1.25, 1]})
    for r, texture in enumerate(("melody", "satb")):
        rows = [x for x in all_rows if x["texture"] == texture and x["order"] != "corpus"]
        colors = ORDER_COLORS[texture]
        ks = K_VALUES[texture]

        # (a) curva de novidade: % de trechos de k eventos que existem no corpus
        ax = axes[r][0]
        style_axes(ax)
        ends = []
        for row, color in zip(rows, colors):
            ys = [100 * row["curve"][k] for k in ks]
            ax.plot(ks, ys, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round",
                    label=f"ordem {row['order']}")
            ends.append(ys[-1])
        for row, y_text in zip(rows, spread(ends, 6.5)):
            ax.text(ks[-1] + 0.25, y_text, f"n={row['order']}", fontsize=8, color=INK_2, va="center")
        ax.grid(axis="x", visible=False)
        ax.set_xticks(ks if len(ks) <= 8 else ks[::2])
        ax.set_xlim(2, ks[-1] + 1.4)
        ax.set_ylim(-3, 103)
        ax.set_xlabel("tamanho k do trecho (em eventos consecutivos)", fontsize=9)
        ax.set_ylabel("% dos trechos que existem no corpus", fontsize=9)
        ax.set_title(f"{TEXTURE_TITLES[texture]} — novidade x tamanho do trecho", fontsize=10, color=INK, loc="left")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, frameon=False, labelcolor=INK_2,
                  ncol=len(rows))

        # (b) resumo por ordem: cópia de 8 eventos (geração) e cobertura em corais inéditos (dados)
        ax = axes[r][1]
        style_axes(ax)
        orders = [row["order"] for row in rows]
        series = ((f"trechos de {COPY_K[texture]} eventos copiados (geração)", "copied_kgram", COPY_COLOR),
                  ("contextos já vistos em coral inédito (dados)", "heldout_coverage", COVERAGE_COLOR))
        for label, key, color in series:
            ys = [100 * row[key] for row in rows]
            ax.plot(orders, ys, color=color, linewidth=2, marker="o", markersize=7,
                    markeredgecolor=SURFACE, markeredgewidth=1.5, label=label,
                    solid_capstyle="round", solid_joinstyle="round")
            ax.text(orders[-1] + 0.12, ys[-1], f"{ys[-1]:.0f}%", fontsize=8, color=INK_2, va="center")
        ax.set_xticks(orders)
        ax.set_xlim(orders[0] - 0.2, orders[-1] + 0.7)
        ax.set_ylim(-3, 103)
        ax.set_xlabel("ordem n da cadeia", fontsize=9)
        ax.set_ylabel("%", fontsize=9)
        ax.set_title(f"{TEXTURE_TITLES[texture]} — resumo por ordem", fontsize=10, color=INK, loc="left")
        ax.grid(axis="x", visible=False)
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, frameon=False, labelcolor=INK_2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pieces", type=int, default=60, help="peças geradas por ordem (padrão: 60)")
    p.add_argument("--phrases", type=int, default=4, help="frases por peça (padrão: 4)")
    p.add_argument("--mode", choices=["major", "minor"], default="major")
    p.add_argument("--out", type=Path, default=Path("docs"))
    p.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    args = p.parse_args(argv)

    raws = load_raw_chorales(args.cache_dir)
    all_rows = []
    for texture in ("melody", "satb"):
        print(f"Textura: {texture}")
        rows, baseline = run(texture, args.mode, raws, args.pieces, args.phrases)
        all_rows += rows + ([baseline] if baseline else [])

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "order_experiment.csv"
    fields = [k for k in all_rows[0] if k != "curve"] + ["parallels_per100"] + [f"copied_k{k}" for k in K_VALUES["satb"]]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        for row in all_rows:
            w.writerow({**{k: v for k, v in row.items() if k != "curve"},
                        **{f"copied_k{k}": round(v, 3) for k, v in row.get("curve", {}).items()}})
    plot(all_rows, args.out / "order_tradeoff.png")
    print(f"Gravado: {csv_path} e {args.out / 'order_tradeoff.png'}")


if __name__ == "__main__":
    main()
