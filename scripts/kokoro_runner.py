#!/usr/bin/env python3
"""Kokoro TTS renderer — runs UNDER a Python 3.12 venv that has the `kokoro` package (NOT Veritas's
3.14 env). Veritas calls this as a subprocess via `KokoroBackend`; this is the only place kokoro/torch
is imported.

    python kokoro_runner.py --text "Hello there." --out line.wav --voice af_heart [--speed 1.0]

Writes a real 24 kHz mono 16-bit WAV. Voice prefix picks the language pack: a*=American, b*=British
(e.g. af_heart, am_michael, bf_emma, bm_george). The model + voice download on first use.
"""

from __future__ import annotations

import argparse
import sys
import wave


def main() -> int:
    ap = argparse.ArgumentParser(description="Render one Kokoro narration WAV.")
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--lang", default="", help="lang_code; inferred from the voice prefix if blank")
    ap.add_argument("--speed", type=float, default=1.0)
    args = ap.parse_args()

    lang = args.lang or (args.voice[0] if args.voice[:1] in ("a", "b") else "a")

    import numpy as np
    from kokoro import KPipeline

    pipe = KPipeline(lang_code=lang)
    chunks = []
    for _graphemes, _phonemes, audio in pipe(args.text.strip() or " ", voice=args.voice, speed=args.speed):
        arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        chunks.append(arr.astype(np.float32).reshape(-1))
    if not chunks:
        print("kokoro produced no audio", file=sys.stderr)
        return 1

    audio = np.concatenate(chunks)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm.tobytes())
    print(f"wrote {args.out} ({len(audio) / 24000:.2f}s, voice={args.voice}, lang={lang})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
