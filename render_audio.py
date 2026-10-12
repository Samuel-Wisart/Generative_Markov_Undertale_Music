#!/usr/bin/env python
"""Converte um arquivo .mid em .wav (apenas para audição).

    python render_audio.py output/meu_coral.mid                 # cria output/meu_coral.wav
    python render_audio.py meu_coral.mid -o saida.wav --sample-rate 44100
    python render_audio.py musica.mid --timbre chiptune        # timbres: organ (padrão), piano, chiptune

Usa o sintetizador embutido (órgão aditivo + reverb, só NumPy). Se preferir um timbre
mais realista, use o FluidSynth com um soundfont -- veja a seção "Áudio" do README.
"""
import argparse
from pathlib import Path

from markov_music.audio import TIMBRES, render_wav
from markov_music.midi_io import read_midi_seconds


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("midi", type=Path, help="arquivo .mid de entrada")
    p.add_argument("-o", "--output", type=Path, default=None, help="arquivo .wav de saída")
    p.add_argument("--sample-rate", type=int, default=22050)
    p.add_argument("--timbre", choices=list(TIMBRES), default="organ", help="timbre do sintetizador (padrão: organ)")
    args = p.parse_args()
    out = args.output or args.midi.with_suffix(".wav")
    seconds = render_wav(read_midi_seconds(args.midi), out, args.sample_rate, timbre=args.timbre)
    print(f"{out}  ({seconds:.0f}s)")


if __name__ == "__main__":
    main()
