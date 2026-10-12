"""Gráficos: piano-roll (altura x tempo, uma cor por voz) e estilo comum às figuras do projeto.

Cores: paleta categórica validada (4 primeiros slots), superfície clara e tintas de texto
neutras. O texto nunca usa a cor da série: a identidade vem da marca colorida ao lado.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from .midi_io import NoteSpec

SURFACE = "#fcfcfb"
INK = "#0b0b0b"            # títulos
INK_2 = "#52514e"          # rótulos
INK_MUTED = "#898781"      # marcas de eixo
GRID = "#e1e0d9"           # grade (linha fina e contínua)
AXIS = "#c3c2b7"

VOICE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]          # soprano, contralto, tenor, baixo
VOICE_LABELS = ["Soprano", "Contralto", "Tenor", "Baixo"]
VOICE_INITIALS = ["S", "A", "T", "B"]
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def use_agg():
    """Backend sem janela (só grava arquivos) e retorna o pyplot."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def style_axes(ax) -> None:
    """Visual discreto: grade fina, sem bordas em cima/direita, tinta neutra."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK_MUTED, labelsize=8, length=3)
    ax.xaxis.label.set_color(INK_2)
    ax.yaxis.label.set_color(INK_2)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save_piano_roll(
    notes: Sequence[NoteSpec],
    path: Path,
    title: str = "",
    labels: Optional[Sequence[str]] = None,
    initials: Optional[Sequence[str]] = None,
) -> None:
    plt = use_agg()
    from matplotlib.patches import Patch

    labels = labels or VOICE_LABELS
    initials = initials or VOICE_INITIALS
    n_voices = max(n.voice for n in notes) + 1
    end = max(n.start + n.dur for n in notes)
    fig, ax = plt.subplots(figsize=(12, 3.8), facecolor=SURFACE)
    style_axes(ax)
    ax.grid(axis="y", visible=False)
    for n in notes:
        ax.barh(n.pitch, max(n.dur - 0.06, 0.02), left=n.start, height=0.82,
                color=VOICE_COLORS[n.voice % 4], edgecolor="none")

    lo, hi = min(n.pitch for n in notes), max(n.pitch for n in notes)
    ticks = [p for p in range(lo, hi + 1) if p % 12 in (0, 7)]           # marca Dó e Sol
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{NOTE_NAMES[p % 12]}{p // 12 - 1}" for p in ticks])
    ax.set_xlabel("tempo (semínimas)", fontsize=9)
    ax.set_ylim(lo - 1.5, hi + 3)
    ax.set_xlim(0, end + (1.2 if n_voices > 1 else 0.2))
    if title:
        ax.set_title(title, fontsize=10, color=INK, loc="left")

    if n_voices > 1:
        for v in range(n_voices):                         # rótulo direto no fim de cada voz
            last = max((n for n in notes if n.voice == v), key=lambda n: n.start)
            ax.text(end + 0.25, last.pitch, initials[v], fontsize=8, color=INK_2,
                    va="center", ha="left")
        ax.legend(handles=[Patch(color=VOICE_COLORS[v], label=labels[v]) for v in range(n_voices)],
                  loc="upper left", ncol=4, fontsize=8, frameon=False, labelcolor=INK_2,
                  bbox_to_anchor=(0.0, 1.0))
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    plt.close(fig)
