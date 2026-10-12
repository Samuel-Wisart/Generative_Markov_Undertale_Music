#!/usr/bin/env python
"""Gera música nova com cadeias de Markov treinadas num corpus MIDI SEU (ex.: Undertale).

Exemplos:
    python generate_midi.py --midi-dir "data/undertale/Undertale MIDI"
    python generate_midi.py --midi-dir data/undertale --texture melody --order 3 --timbre chiptune
    python generate_midi.py --midi-dir data/undertale --count 3 --seed 10 --max-copy 1   # sem anti-plágio

Para cada peça são gravados, em --out: .mid (resultado oficial), .wav (audição), .png (piano-roll)
e .json (parâmetros e métricas). A peça segue uma FORMA (padrão AABA): cada letra é uma seção de
--bars compassos sorteada da cadeia, e letras repetidas repetem a mesma seção, como num loop de jogo.

O corpus MIDI é de terceiros (direitos autorais): use só para estudo e NÃO o coloque no repositório.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from markov_music.audio import TIMBRES, render_wav
from markov_music.generator import Piece
from markov_music.midi_corpus import TEXTURES_MIDI
from markov_music.midi_io import HAND_NAMES, piece_to_notes_sets, read_midi_seconds, write_midi
from markov_music.plots import save_piano_roll
from markov_music.sections import train_section_model

DEFAULT_ORDER = {"melody": 2, "outer": 1, "piano": 1}      # justificativa: experiment_midi.py / README
DEFAULT_MAX_COPY = 0.3                                     # corpus de terceiros: anti-plágio ligado por padrão


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--midi-dir", type=Path, required=True, help="pasta com os arquivos .mid de treino")
    g = p.add_argument_group("modelo (hiperparâmetros da cadeia de Markov)")
    g.add_argument("--texture", choices=list(TEXTURES_MIDI), default="piano",
                   help="melody = só a nota mais aguda; outer = melodia + baixo; piano = todas as notas (padrão)")
    g.add_argument("--order", type=int, default=None,
                   help="ordem n da cadeia (padrão: 1 para piano, 2 para melody/outer)")
    g.add_argument("--temperature", type=float, default=1.0, help="<1 mais previsível; >1 mais aleatório")
    g.add_argument("--max-copy", type=float, default=DEFAULT_MAX_COPY, metavar="FRAÇÃO",
                   help="anti-plágio: recusa seções com mais que esta fração (0-1) de trechos copiados do corpus "
                        "(padrão: 0.3; use 1 para desligar)")
    g = p.add_argument_group("composição")
    g.add_argument("--form", default="AABA", help="forma da peça; cada letra = uma seção (padrão: AABA)")
    g.add_argument("--bars", type=int, default=4, help="compassos por seção (padrão: 4)")
    g.add_argument("--beats-per-bar", type=int, default=4,
                   help="tempos por compasso do corpus usado no treino: 4 (4/4 e 2/2), 3 (3/4 e 6/8)... (padrão: 4)")
    g.add_argument("--seed", type=int, default=1, help="semente aleatória (mesma semente = mesma música)")
    g.add_argument("--count", type=int, default=1, help="quantas peças gerar (sementes seed, seed+1, ...)")
    g = p.add_argument_group("saída")
    g.add_argument("--out", type=Path, default=Path("output"), help="pasta de saída (padrão: output)")
    g.add_argument("--name", default=None, help="prefixo dos arquivos (padrão: nome da pasta de MIDI)")
    g.add_argument("--bpm", type=int, default=120, help="andamento em semínimas por minuto (padrão: 120)")
    g.add_argument("--program", type=int, default=0, help="instrumento General MIDI 0-127 (padrão: 0 = piano)")
    g.add_argument("--timbre", choices=list(TIMBRES), default="piano", help="timbre do .wav (padrão: piano)")
    g.add_argument("--no-audio", action="store_true", help="não gera o .wav")
    g.add_argument("--no-plot", action="store_true", help="não gera o piano-roll .png")
    g.add_argument("--sample-rate", type=int, default=22050)
    g.add_argument("--cache-dir", type=Path, default=Path(".cache"))
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    order = args.order if args.order is not None else DEFAULT_ORDER[args.texture]
    label = args.name or re.sub(r"[^A-Za-z0-9]+", "_", args.midi_dir.resolve().name).strip("_").lower()

    print(f"Treinando: textura={args.texture}, ordem={order}, seções de {args.bars} compassos ...")
    model = train_section_model(str(args.midi_dir), order, args.texture, args.bars, args.beats_per_bar, args.cache_dir)
    chain = model.chain
    print(f"  {model.n_phrases_train} seções de treino | {chain.n_contexts} contextos | "
          f"média de {chain.mean_branching():.2f} continuações por contexto | "
          f"{chain.deterministic_fraction():.0%} dos contextos sem escolha")

    for k in range(args.count):
        seed = args.seed + k
        try:
            piece: Piece = model.compose(args.form, seed=seed, temperature=args.temperature, max_copy=args.max_copy)
        except RuntimeError as err:                    # restrições impossíveis (ex.: ordem alta + --max-copy baixo)
            print(f"ERRO (semente {seed}): {err}", file=sys.stderr)
            return 2
        two_hands = args.texture != "melody"
        notes = piece_to_notes_sets(piece, split_hands=two_hands)
        stem = f"{label}_{args.texture}_o{order}_T{args.temperature:g}"
        stem += f"_copy{args.max_copy:g}"
        stem += f"_{args.form}_seed{seed}"
        mid_path = args.out / f"{stem}.mid"
        names = HAND_NAMES if two_hands else ["Melodia"]
        write_midi(notes, mid_path, args.bpm, args.program, voice_names=names,
                   time_signature=f"{args.beats_per_bar}/4")

        seconds = max(n.start + n.dur for n in notes) * 60.0 / args.bpm
        copy = model.copy_rate(piece)
        info = {**piece.params, "beats_per_bar": args.beats_per_bar, "bpm": args.bpm, "program": args.program,
                "timbre": args.timbre, "events": len(piece.events), "notes": len(notes),
                "seconds": round(seconds, 1), "copy_k": model.copy_k, "copied_from_corpus": round(copy, 3)}
        (args.out / f"{stem}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        if not args.no_plot:
            save_piano_roll(notes, args.out / f"{stem}.png", title=stem,
                            labels=HAND_NAMES, initials=["D", "E"])
        if not args.no_audio:
            render_wav(read_midi_seconds(mid_path), args.out / f"{stem}.wav", args.sample_rate, timbre=args.timbre)

        print(f"[{k + 1}/{args.count}] {mid_path}  ({seconds:.0f}s, {len(notes)} notas, "
              f"{copy:.0%} dos trechos de {model.copy_k} eventos copiados do corpus)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
