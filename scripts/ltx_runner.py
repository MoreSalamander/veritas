#!/usr/bin/env python3
"""LTX-Video clip renderer — runs UNDER a Python 3.12 venv that has torch + diffusers (NOT Veritas's
3.14 env). Veritas calls this as a subprocess via `LocalLtxBackend`; this is the only place torch is
imported.

    python ltx_runner.py --prompt "a neon city at night" --out clip.mp4 \
        --seconds 4 --fps 24 --width 768 --height 512 [--image ref.png] [--seed 123]

Text-to-video uses `LTXPipeline`; if --image is given it conditions on that still (image-to-video via
`LTXConditionPipeline`) — the mechanism for keeping an entity's look stable across shots. Defaults
target the *distilled* LTX weights (guidance_scale=1.0, few steps), the variant that fits ~24 GB on
Apple Silicon. The model is downloaded on first run.

This file is intentionally NOT imported by Veritas and NOT type-checked by its mypy run; it lives on
the far side of the subprocess seam. First-run on the user's machine confirms the exact diffusers LTX
API for the installed version and pulls the weights.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any


def _round_to(value: int, multiple: int) -> int:
    """LTX wants spatial dims divisible by 32; clamp up to at least one multiple."""
    return max(multiple, (value // multiple) * multiple)


def _round_frames(n: int) -> int:
    """LTX wants num_frames of the form 8*k + 1."""
    n = max(9, n)
    return ((n - 1) // 8) * 8 + 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Render one LTX-Video clip.")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=512)
    ap.add_argument("--image", default=None, help="optional reference still → image-to-video")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--model", default="Lightricks/LTX-Video")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--guidance", type=float, default=1.0, help="1.0 for distilled weights")
    ap.add_argument("--negative", default="worst quality, blurry, distorted, deformed, jittery, "
                    "flickering, watermark, text, static, low detail",
                    help="negative prompt — only used when guidance > 1.0 (base weights)")
    args = ap.parse_args()

    import torch
    from diffusers.utils import export_to_video, load_image

    device = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device in ("mps", "cuda") else torch.float32

    width = _round_to(args.width, 32)
    height = _round_to(args.height, 32)
    num_frames = _round_frames(int(args.seconds * args.fps))

    generator = None
    if args.seed is not None:
        # Seed on CPU for cross-device reproducibility; MPS generators are finicky.
        generator = torch.Generator(device="cpu").manual_seed(args.seed)

    common = dict(
        prompt=args.prompt,
        width=width,
        height=height,
        num_frames=num_frames,
        num_inference_steps=args.steps,
        guidance_scale=args.guidance,
        generator=generator,
    )
    if args.guidance > 1.0 and args.negative:  # CFG-only; distilled (g=1.0) ignores it
        common["negative_prompt"] = args.negative

    def _fit(pipe: Any) -> Any:
        """Fit ~24 GB unified memory: offload each submodule to the GPU only while it's in use (peak
        memory ≈ the largest module, not the sum of T5-XXL + transformer + VAE), and tile the VAE so a
        long latent doesn't spike on decode. Falls back to a plain .to(device) if offload is unusable."""
        try:
            pipe.enable_model_cpu_offload(device=device)
        except Exception:  # noqa: BLE001 — best-effort; any failure just means no offload
            try:
                pipe.to(device)
            except Exception:  # noqa: BLE001
                pass
        try:
            pipe.vae.enable_tiling()
        except Exception:  # noqa: BLE001
            pass
        return pipe

    if args.image:
        from diffusers import LTXConditionPipeline
        from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition

        pipe = _fit(LTXConditionPipeline.from_pretrained(args.model, torch_dtype=dtype))
        ref = load_image(args.image)
        condition = LTXVideoCondition(image=ref, frame_index=0)
        result = pipe(conditions=[condition], **common)
    else:
        from diffusers import LTXPipeline

        pipe = _fit(LTXPipeline.from_pretrained(args.model, torch_dtype=dtype))
        result = pipe(**common)

    frames = result.frames[0]
    export_to_video(frames, args.out, fps=args.fps)
    print(f"wrote {args.out} ({width}x{height}, {num_frames} frames @ {args.fps}fps)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
