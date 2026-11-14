#!/usr/bin/env python3
"""Generate effect IRs for the M-VAVE / Cuvave Cube Baby IR slots.

Each generated WAV is a 512-sample (10.7 ms @ 48 kHz) mono float32 impulse
response ready to write into one of the pedal's 8 IR slots (via CubeSuite,
cubeControl or cubebaby-editor). An IR slot is just a convolution kernel, so
anything you put in it becomes a filter/effect, not only cabinet sims.

Dependencies: numpy only.

Usage:
    python3 tools/make_irs.py                 # write the default set to ./irs/
    python3 tools/make_irs.py --out my_irs    # custom output directory
    python3 tools/make_irs.py --list          # list the recipes

Then: audition the WAVs by convolving them with your dry guitar in a DAW
(ReaVerb, any IR loader) before writing them to slots, and keep a backup of
each slot before overwriting it.
"""

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

SR = 48000
N = 512  # pedal hardware limit: 512 samples per IR (~10.7 ms)


def write_wav_float32(path: Path, samples: np.ndarray) -> None:
    """Write a mono IEEE-float WAV (format tag 3), readable by CubeSuite
    (float32 read as-is) and cubebaby-editor."""
    data = struct.pack(f"<{len(samples)}f", *samples)
    header = (
        b"RIFF" + struct.pack("<I", 38 + len(data)) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHHH", 18, 3, 1, SR, SR * 4, 4, 32, 0)
        + b"data" + struct.pack("<I", len(data))
    )
    path.write_bytes(header + data)


def normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def time_axis() -> np.ndarray:
    return np.arange(N) / SR


def base(dry: float = 0.0) -> np.ndarray:
    """Kernel starting with an optional direct (dry) impulse at t=0."""
    x = np.zeros(N)
    x[0] = dry
    return x


def resonator(freq: float, decay_ms: float, dry: float = 0.35) -> np.ndarray:
    """Tuned filter: exponentially decaying sine at `freq` Hz.
    Low decay = gentle EQ hump, high decay = ringing resonator/pedal steel."""
    t = time_axis()
    tau = decay_ms / 1000.0
    x = base(dry)
    x += np.sin(2 * np.pi * freq * t) * np.exp(-t / tau)
    return normalize(x)


def formant(f1: float, f2: float, f3: float = 0.0, decay_ms: float = 6.0,
            dry: float = 0.4) -> np.ndarray:
    """Vowel-ish filter: 2-3 parallel resonators (classic speech formants)."""
    t = time_axis()
    tau = decay_ms / 1000.0
    x = base(dry)
    for f in (f1, f2, f3):
        if f > 0:
            x += np.sin(2 * np.pi * f * t) * np.exp(-t / tau)
    return normalize(x)


def comb(delay_ms: float, gain: float, taps: int = 1, dry: float = 0.7) -> np.ndarray:
    """Comb filter / slapback: dry impulse plus `taps` delayed, attenuated
    copies. Short delay = metallic coloration, ~8-10 ms = slapback feel."""
    x = base(dry)
    step = max(1, int(delay_ms / 1000.0 * SR))
    for k in range(1, taps + 1):
        pos = step * k
        if pos < N:
            x[pos] += gain ** k
    return normalize(x)


def spring(decay_ms: float = 9.0, dry: float = 0.35) -> np.ndarray:
    """Cheap spring-reverb flavour: irregular decaying tap train."""
    x = base(dry)
    rng = np.random.default_rng(4)
    t = time_axis()
    tau = decay_ms / 1000.0
    for pos in rng.integers(3, N, size=40):
        x[pos] += (rng.uniform(-1, 1)) * np.exp(-t[pos] / tau)
    return normalize(x)


def room(decay_ms: float = 10.0, brightness: float = 0.5, dry: float = 0.3) -> np.ndarray:
    """Short room ambience: exponentially decaying filtered noise.
    `brightness` 0..1 tilts the decay toward dark or airy."""
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(N)
    kernel = np.ones(24) / 24.0
    dark = np.convolve(noise, kernel, mode="same")
    x = base(dry)
    t = time_axis()
    tau = decay_ms / 1000.0
    env = np.exp(-t / tau)
    x += ((1 - brightness) * dark + brightness * noise) * env
    return normalize(x)


def lofi(hiss: float = 0.25, dry: float = 0.8) -> np.ndarray:
    """Rough radio/lo-fi texture: dry signal plus a burst of band-limited
    junk at the very start of the kernel."""
    rng = np.random.default_rng(11)
    noise = rng.standard_normal(N)
    kernel = np.ones(8) / 8.0
    junk = np.convolve(noise, kernel, mode="same") * hiss
    junk[64:] *= 0.1
    x = base(dry) + junk
    return normalize(x)


def body(freq: float = 110.0, decay_ms: float = 8.0, dry: float = 0.5) -> np.ndarray:
    """Acoustic-body resonance: low-frequency resonator, adds bloom/wood
    behind an electric signal."""
    return resonator(freq, decay_ms, dry=dry)


RECIPES = {
    "resonator-A440": lambda: resonator(440, 9.0),
    "resonator-D294": lambda: resonator(294, 9.0),
    "body-bloom": lambda: body(110, 8.0),
    "vowel-ah": lambda: formant(700, 1220, 2600),
    "vowel-ee": lambda: formant(300, 2800, 3500),
    "vowel-oh": lambda: formant(450, 800, 2830),
    "comb-metallic": lambda: comb(1.2, 0.6, taps=3),
    "slapback": lambda: comb(9.0, 0.5, taps=1, dry=0.8),
    "spring-cheap": lambda: spring(),
    "room-tight": lambda: room(8.0, 0.4),
    "room-airy": lambda: room(10.0, 0.8),
    "lofi-radio": lambda: lofi(),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="irs", help="output directory (default: ./irs)")
    ap.add_argument("--list", action="store_true", help="list recipes and exit")
    args = ap.parse_args()

    if args.list:
        for name in RECIPES:
            print(name)
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in RECIPES.items():
        path = out / f"{name}.wav"
        write_wav_float32(path, fn())
        print(f"wrote {path} ({N} samples @ {SR} Hz, {N / SR * 1000:.1f} ms)")
    print(
        "\nNext steps:\n"
        " 1. Audition each WAV on your dry tone in a DAW IR loader before committing.\n"
        " 2. Write to a slot with CubeSuite / cubeControl / cubebaby-editor (backup first).\n"
        " 3. Set IR CAB to the slot number; try Distance at different values.\n"
        " 4. On the guitar model, try the same IR before vs after the amp/FX chain."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
