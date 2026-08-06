#!/usr/bin/env python3
"""Packages taichi-academy projects into the vending machine: gate -> build -> persist, per
project. Each product only enters the machine if the academy's own checker passes; a gate or
build failure is reported and skipped, never shipped.

Usage:
  .venv/bin/python3 scripts/package_academy.py               # every available project
  .venv/bin/python3 scripts/package_academy.py --project 01-reaction-diffusion
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.memory import default_memory_store  # noqa: E402
from products.academy.container import (  # noqa: E402
    ACADEMY_ROOT,
    AcademyPackagingError,
    academy_record,
    build_academy_image,
    chapter_titles,
    list_academy_projects,
    run_academy_gate,
)

DATA_ROOT = Path(__file__).resolve().parent.parent / "hub_data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", help="package just this project id")
    args = parser.parse_args()

    store = default_memory_store(DATA_ROOT / "memory" / "academy")
    projects = list_academy_projects(ACADEMY_ROOT)
    if args.project:
        projects = [p for p in projects if p.id == args.project]
        if not projects:
            print(f"no available project {args.project!r}", file=sys.stderr)
            return 1

    packaged = failed = 0
    for project in projects:
        try:
            evidence = run_academy_gate(project.id, ACADEMY_ROOT)
            tag = build_academy_image(project, ACADEMY_ROOT)
            chapters = chapter_titles(project.id, ACADEMY_ROOT)
            record = academy_record(project, evidence, tag, chapters)
            store.persist(record)
            packaged += 1
            print(f"PASS  {project.id} -> {tag}  ({len(chapters)} chapter(s))")
        except AcademyPackagingError as exc:
            failed += 1
            print(f"FAIL  {project.id}: {exc}", file=sys.stderr)
    print(f"\n{packaged} packaged, {failed} failed/refused", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
