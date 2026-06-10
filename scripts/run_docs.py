"""A real Docs Studio run against a local Ollama model.

    python scripts/run_docs.py "python list comprehensions"

The writer proposes a Markdown explainer; the deterministic gates decide — and the
star gate actually EXECUTES every code example. Same engine as the software studio,
different cast. If an example doesn't run, the document is rejected into failure memory.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from engine.memory import MemoryStore
from engine.model import OllamaProvider
from orgs.docs_studio.pipeline import build_doc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("topic", nargs="?", default="python list comprehensions")
    parser.add_argument("--model", default=os.environ.get("VERITAS_MODEL", "llama3.1:8b"))
    args = parser.parse_args()

    memory = MemoryStore(Path("./.demo_memory"))
    print(f"topic: {args.topic}")
    print(f"model: {args.model}\n")
    result = build_doc(args.topic, OllamaProvider(model=args.model), memory)

    outline = result.outline_outcome
    print(f"OUTLINE  -> {'ACCEPTED' if outline.accepted else 'REJECTED'}")
    for gr in outline.artifact.provenance.gate_results:
        print(f"           [{gr.gate_name}] {'pass' if gr.passed else 'FAIL'}: {gr.evidence}")

    if result.doc_outcome is None:
        print("\nDOCUMENT -> not attempted (outline rejected)")
        return

    doc = result.doc_outcome
    print(f"\nDOCUMENT -> {'ACCEPTED' if doc.accepted else 'REJECTED'}  "
          f"({doc.memory_path.parent.name}/{doc.memory_path.name})")
    for gr in doc.artifact.provenance.gate_results:
        print(f"           [{gr.gate_name}] {'pass' if gr.passed else 'FAIL'}: {gr.evidence}")
    print("\n--- document ---")
    print(doc.artifact.payload)


if __name__ == "__main__":
    main()
