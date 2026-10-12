"""Sintetizador simples (só NumPy) para OUVIR os arquivos .mid gerados.

Não é um sintetizador realista: cada nota é uma soma de harmônicos com ataque/soltura suaves,
mais uma reverberação. Três timbres: "organ" (órgão, bom para corais), "piano" (decaimento
natural) e "chiptune" (onda quadrada, estilo videogame).
O arquivo .mid continua sendo o resultado "oficial" do sistema; o áudio é só para audição.
Para um timbre mais realista, abra o .mid num programa com soundfont (MuseScore, FluidSynth, um DAW).
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Dict, Sequence, Tuple

import numpy as np

# Timbres disponíveis. `partials`: (número do harmônico, amplitude); `decay`: queda exponencial por segundo
# (0 = som sustentado); `tilt`: harmônicos agudos decaem `tilt` vezes mais rápido por harmônico (piano).
TIMBRES = {
    # órgão: lembra um registro com 8', 4', 2 2/3', 2', 1 1/3' e 1'
    "organ": dict(partials=((1, 1.00), (2, 0.50), (3, 0.28), (4, 0.30), (6, 0.12), (8, 0.06)),
                  attack=0.025, release=0.18, decay=0.0, tilt=0.0),
    # piano: ataque rápido e decaimento natural (notas longas "morrem" sozinhas)
    "piano": dict(partials=((1, 1.00), (2, 0.55), (3, 0.40), (4, 0.25), (5, 0.15), (6, 0.10), (7, 0.06), (8, 0.04)),
                  attack=0.004, release=0.12, decay=1.4, tilt=0.35),
    # chiptune: onda quadrada (harmônicos ímpares, amplitude 1/h), típica de música de videogame
    "chiptune": dict(partials=tuple((h, 1.0 / h) for h in (1, 3, 5, 7, 9, 11, 13, 15)),
                     attack=0.003, release=0.04, decay=0.25, tilt=0.0),
}
VOICE_PAN = (0.62, 0.54, 0.46, 0.38)          # 0 = esquerda, 1 = direita (soprano um pouco à direita)

NoteTuple = Tuple[float, float, int, int, int]            # (início_s, duração_s, altura, velocity, trilha)


def _note_wave(pitch: int, duration: float, sr: int, timbre: str = "organ") -> np.ndarray:
    """Forma de onda de uma nota (inclui o trecho de soltura depois da duração)."""
    tb = TIMBRES[timbre]
    attack, release = tb["attack"], tb["release"]
    freq = 440.0 * 2.0 ** ((pitch - 69) / 12.0)
    n = int((duration + release) * sr)
    t = np.arange(n) / sr
    wave_ = np.zeros(n)
    for harmonic, amp in tb["partials"]:
        if freq * harmonic < sr / 2.2:                    # evita aliasing
            partial = amp * np.sin(2 * np.pi * freq * harmonic * t)
            if tb["decay"]:                               # decaimento (mais rápido nos harmônicos agudos)
                partial = partial * np.exp(-tb["decay"] * (1.0 + tb["tilt"] * (harmonic - 1)) * t)
            wave_ += partial
    env = np.minimum(1.0, t / attack)                      # ataque linear
    hold = max(duration - 0.02, attack)                    # pequena pausa entre notas repetidas
    env = np.where(t > hold, np.maximum(0.0, 1.0 - (t - hold) / release), env)
    return wave_ * env


def _reverb_impulse(sr: int, seconds: float = 1.8, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    noise = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)      # decai ~60 dB
    kernel = np.ones(8) / 8                                              # leve filtro passa-baixa
    return np.convolve(noise, kernel, mode="same")


def _fft_convolve(signal: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    size = 1 << int(np.ceil(np.log2(len(signal) + len(kernel) - 1)))
    out = np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(kernel, size), size)
    return out[: len(signal)]


def render_wav(
    notes: Sequence[NoteTuple],
    path: Path,
    sample_rate: int = 22050,
    reverb: float = 0.28,
    timbre: str = "organ",
) -> float:
    """Sintetiza `notes` e grava um WAV estéreo de 16 bits. Devolve a duração em segundos."""
    if not notes:
        raise ValueError("Nenhuma nota para sintetizar.")
    if timbre not in TIMBRES:
        raise ValueError(f"timbre inválido: {timbre!r} (use {list(TIMBRES)})")
    total = max(s + d for s, d, *_ in notes) + TIMBRES[timbre]["release"]
    pad = int(2.0 * sample_rate)                           # espaço para a cauda da reverberação
    left = np.zeros(int(total * sample_rate) + pad)
    right = np.zeros_like(left)
    cache: Dict[Tuple[int, int], np.ndarray] = {}

    for start, dur, pitch, velocity, voice in notes:
        key = (pitch, round(dur * 1000))
        if key not in cache:
            cache[key] = _note_wave(pitch, dur, sample_rate, timbre)
        w = cache[key] * (velocity / 127.0)
        i = int(start * sample_rate)
        pan = VOICE_PAN[voice % len(VOICE_PAN)]
        left[i:i + len(w)] += w * np.cos(pan * np.pi / 2)  # pan de potência constante
        right[i:i + len(w)] += w * np.sin(pan * np.pi / 2)

    ir = _reverb_impulse(sample_rate)
    ir /= np.sqrt(np.sum(ir ** 2))
    left = (1 - reverb) * left + reverb * _fft_convolve(left, ir)
    right = (1 - reverb) * right + reverb * _fft_convolve(right, ir[::-1].copy())    # decorrela L/R

    stereo = np.stack([left, right], axis=1)
    stereo *= 0.9 / max(1e-9, np.abs(stereo).max())        # normaliza (sem clipping)
    pcm = (stereo * 32767).astype("<i2")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.tobytes())
    return len(pcm) / sample_rate
