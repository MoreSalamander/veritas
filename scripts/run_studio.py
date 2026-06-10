"""A real Software Studio run against a local Ollama model.

    python scripts/run_studio.py "a function that returns the nth Fibonacci number"
    python scripts/run_studio.py --model qwen2.5-coder "reverse a string"

This is where a real LLM proposes and the deterministic gates decide. If the model
hands back a bad spec or wrong code, you'll watch it get rejected into failure
memory — which is the system working, not failing.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from engine.memory import MemoryStore
from engine.model import OllamaProvider
from orgs.software_studio.pipeline import build_software


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "goal",
        nargs="?",
        default="a function that returns the nth Fibonacci number (0-indexed)",
    )
    parser.add_argument("--model", default=os.environ.get("VERITAS_MODEL", "llama3.1:8b"))
    args = parser.parse_args()

    provider = OllamaProvider(model=args.model)
    memory = MemoryStore(Path("./.demo_memory"))

    print(f"goal : {args.goal}")
    print(f"model: {args.model}\n")
    result = build_software(args.goal, provider, memory)

    spec = result.spec_outcome
    print(f"SPEC  -> {'ACCEPTED' if spec.accepted else 'REJECTED'}  "
          f"({spec.memory_path.parent.name}/{spec.memory_path.name})")
    for gr in spec.artifact.provenance.gate_results:
        print(f"        [{gr.gate_name}] {'pass' if gr.passed else 'FAIL'}: {gr.evidence}")

    if result.code_outcome is None:
        print("\nCODE  -> not attempted (spec rejected first)")
    else:
        code = result.code_outcome
        print(f"\nCODE  -> {'ACCEPTED' if code.accepted else 'REJECTED'}  "
              f"({code.memory_path.parent.name}/{code.memory_path.name})")
        for gr in code.artifact.provenance.gate_results:
            print(f"        [{gr.gate_name}] {'pass' if gr.passed else 'FAIL'}: {gr.evidence}")
        print("\n--- proposed code ---")
        print(code.artifact.payload)

    print(f"\nRESULT: {'shipped to memory' if result.accepted else 'not accepted'}")


if __name__ == "__main__":
    main()
