#!/usr/bin/env python
"""Gera a figura, a tabela e as macros de números do resumo ISMIR.

    python paper/make_figures.py            (rode da raiz do projeto)

Entradas:  docs/undertale_orders.csv  (experiment_midi.py)  e  docs/order_experiment.csv  (experiment_orders.py, Bach)
Saídas:    paper/figs/novelty.pdf, paper/results_table.tex e paper/numbers.tex
Nenhum número dos experimentos é digitado à mão no .tex: tudo vem dos CSVs (via macros em numbers.tex).
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
CSV_UT = HERE.parent / "docs" / "undertale_orders.csv"
CSV_BACH = HERE.parent / "docs" / "order_experiment.csv"

# Rampa ordinal (um matiz, claro -> escuro) validada para 4 passos: legível também em escala de cinza.
COLORS = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
TEXTURES = (("melody", "Melody", "(a) Melody only"), ("outer", "Melody+bass", "(b) Melody + bass"),
            ("piano", "Piano", "(c) Full piano"))
ORDER_WORD = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
INK, INK_2, GRID = "#111111", "#444444", "#dddddd"

plt.rcParams.update({
    "pdf.fonttype": 42,                      # fontes embutidas (exigência do ISMIR)
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8,
})


def load(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


def pct(x):
    return "n/a" if x in ("", None) else f"{100 * float(x):.0f}"


def figure(rows):
    fig, axes = plt.subplots(1, 3, figsize=(6.8, 1.65), sharey=True)
    handles = None
    for ax, (texture, _, title) in zip(axes, TEXTURES):
        rs = [r for r in rows if r["texture"] == texture]
        ks = sorted(int(c[8:]) for c in rs[0] if c.startswith("copied_k") and c[8:].isdigit() and rs[0][c] != "")
        ends = []
        for r, color in zip(rs, COLORS):
            ys = [100 * float(r[f"copied_k{k}"]) for k in ks]
            ax.plot(ks, ys, color=color, linewidth=1.6, solid_capstyle="round", label=f"$n={r['order']}$")
            ends.append(ys[-1])
        for i, (r, y) in enumerate(zip(rs, ends)):             # rótulo direto só onde as curvas terminam bem separadas
            if all(abs(y - other) >= 6 for j, other in enumerate(ends) if j != i):
                ax.text(ks[-1] + 0.2, y, f"$n={r['order']}$", fontsize=6.5, color=INK_2, va="center")
        ax.set_xlim(ks[0], ks[-1] + 2.2)
        ax.set_ylim(-3, 104)
        ax.set_xticks(ks[::2])
        ax.set_xlabel("window length $k$ (events)")
        ax.set_title(title, fontsize=8, loc="left", color=INK)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=2.5, labelsize=7)
        handles = ax.get_legend_handles_labels()
    axes[0].set_ylabel("windows found in corpus (%)")
    fig.legend(*handles, loc="lower center", ncol=4, fontsize=7, frameon=False, handlelength=1.6,
               bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(pad=0.3, w_pad=0.6, rect=(0, 0.1, 1, 1))
    (HERE / "figs").mkdir(exist_ok=True)
    fig.savefig(HERE / "figs" / "novelty.pdf")
    fig.savefig(HERE / "figs" / "novelty_preview.png", dpi=220)        # só para conferir a figura a olho
    plt.close(fig)


def table(rows):
    """Linhas da tabela LaTeX (table* de duas colunas); `\\hline` inicial e final ficam no .tex principal."""
    out = []
    for texture, label, _ in TEXTURES:
        rs = [r for r in rows if r["texture"] == texture]
        if texture != "melody":
            out.append(r"\hline")
        for i, r in enumerate(rs):
            contexts = f"{int(r['contexts']):,}".replace(",", "{,}")
            out.append(
                f"{label if i == 0 else ''} & {r['order']} & {contexts} & {pct(r['heldout_coverage'])} & "
                f"{pct(r['copied_kgram'])} & {pct(r['whole_sections_copied'])} & "
                f"{r['tau_feasible_seeds']}/{r['tau_seeds']} & {pct(r['tau_copied_kgram'])}"
                + ("" if (texture == "piano" and i == len(rs) - 1) else r" \\")
            )
    with open(HERE / "results_table.tex", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))


def numbers(ut, bach):
    """Macros \\ut<Textura><Ordem><Métrica> e \\bach<...>: os números citados no texto, direto dos CSVs."""
    macros = {}
    names = {"melody": "Melody", "outer": "Outer", "piano": "Piano"}
    for r in ut:
        base = f"ut{names[r['texture']]}{ORDER_WORD[int(r['order'])]}"
        macros[base + "Cov"] = pct(r["heldout_coverage"])
        macros[base + "Win"] = pct(r["copied_kgram"])
        macros[base + "Sec"] = pct(r["whole_sections_copied"])
        macros[base + "Feas"] = r["tau_feasible_seeds"]
        macros[base + "Rem"] = pct(r["tau_copied_kgram"])
    for r in bach:
        if r["order"] == "corpus":
            macros["bachCorpusPar"] = f"{float(r['parallels_per100']):.2f}"
            continue
        base = f"bach{'Melody' if r['texture'] == 'melody' else 'Satb'}{ORDER_WORD[int(r['order'])]}"
        macros[base + "Cov"] = pct(r["heldout_coverage"])
        macros[base + "Phr"] = pct(r["whole_phrases_copied"])
        if r["parallels_per100"] != "":
            macros[base + "Par"] = f"{float(r['parallels_per100']):.2f}"
    lines = ["% Gerado por paper/make_figures.py a partir de docs/*.csv. NÃO edite à mão."]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(macros.items())]
    with open(HERE / "numbers.tex", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    ut, bach = load(CSV_UT), load(CSV_BACH)
    figure(ut)
    table(ut)
    numbers(ut, bach)
    print("ok:", HERE / "figs" / "novelty.pdf", ",", HERE / "results_table.tex", "e", HERE / "numbers.tex")
