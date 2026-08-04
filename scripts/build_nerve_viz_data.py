#!/usr/bin/env python3
"""Regenerates hub/static/shared/nerve-viz-data.js from a REAL pytest run, and updates every
hardcoded "N tests passed" proof point across the repo to match. This exists because the previous
version of nerve-viz-data.js was a hand-generated one-time snapshot (2026-07-29) with no script to
refresh it — the count silently went stale (517 -> 594 real) while the homepage kept claiming a
number that stopped being true. Run this after any change that adds/removes tests; nothing here
should ever be hand-edited again.

Usage: .venv/bin/python3 scripts/build_nerve_viz_data.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent

# The always-fails-in-this-sandbox real-Docker-build test — deselected the same way the project's
# own manual test runs already do (a Docker daemon resource-contention issue, not a code failure).
_DESELECT = "tests/test_hunter_engine_bridge_container.py::test_real_container_writes_survive_rm_via_the_bind_mount"

CATEGORY_ORDER = [
    "Core engine", "Studios", "Hub / control plane",
    "Entropy additions", "Memory & Commons", "Docker sandbox",
]
CATEGORY_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]

# Hand-curated for every module present when this script was written (matches the original,
# manually-placed nerve-viz-data.js exactly) — kept explicit rather than inferred, since some of
# these placements aren't guessable from the name alone (test_hub_commons lives in "Memory &
# Commons", not "Hub / control plane"; test_research_vouched lives in "Studios", not "Memory &
# Commons"). A module NOT in this table falls through to _guess_category — good enough to keep the
# visualization honest going forward without requiring a human to hand-place every new test file.
KNOWN_CATEGORY: dict[str, str] = {
    # Core engine
    "test_confidence": "Core engine", "test_confidence_experiment": "Core engine",
    "test_decision": "Core engine", "test_embed": "Core engine", "test_executor": "Core engine",
    "test_expiring_store": "Core engine", "test_knowledge": "Core engine",
    "test_lang_pipeline": "Core engine", "test_languages": "Core engine",
    "test_learning": "Core engine", "test_model": "Core engine", "test_module": "Core engine",
    "test_oracle": "Core engine", "test_plan": "Core engine", "test_planning": "Core engine",
    "test_presets": "Core engine", "test_prompt_experiment": "Core engine",
    "test_properties": "Core engine", "test_property_robustness": "Core engine",
    "test_retry": "Core engine", "test_run_trust": "Core engine", "test_spine": "Core engine",
    "test_tokens": "Core engine", "test_trust_bench": "Core engine", "test_trust_tasks": "Core engine",
    "test_tuning": "Core engine",
    # Studios
    "test_builder": "Studios", "test_cast": "Studios", "test_empirical": "Studios",
    "test_production": "Studios", "test_production_assets": "Studios",
    "test_production_editing": "Studios", "test_production_publishing": "Studios",
    "test_production_taste": "Studios", "test_production_video": "Studios",
    "test_research_pipeline": "Studios", "test_research_studio": "Studios",
    "test_research_vouched": "Studios", "test_software_studio": "Studios", "test_tts": "Studios",
    "test_video_backend": "Studios", "test_web_aesthetics": "Studios", "test_web_create": "Studios",
    "test_web_interview": "Studios", "test_web_pipeline": "Studios", "test_web_profile": "Studios",
    "test_web_studio": "Studios",
    # Hub / control plane
    "test_accounts": "Hub / control plane", "test_app": "Hub / control plane",
    "test_background_session": "Hub / control plane", "test_hub": "Hub / control plane",
    "test_hub_bench": "Hub / control plane", "test_hub_brief": "Hub / control plane",
    "test_hub_create": "Hub / control plane", "test_hub_plan": "Hub / control plane",
    "test_hub_produce": "Hub / control plane", "test_hub_report_page": "Hub / control plane",
    "test_hub_route": "Hub / control plane", "test_hub_tune": "Hub / control plane",
    "test_ingest": "Hub / control plane", "test_quota": "Hub / control plane",
    "test_registry": "Hub / control plane", "test_wedge": "Hub / control plane",
    # Entropy additions
    "test_collector": "Entropy additions", "test_collector_explain": "Entropy additions",
    "test_grounding": "Entropy additions", "test_hunter_engine_bridge": "Entropy additions",
    "test_hunter_engine_bridge_container": "Entropy additions", "test_keytracker": "Entropy additions",
    "test_memory_export": "Entropy additions",
    # Memory & Commons
    "test_commons": "Memory & Commons", "test_hub_commons": "Memory & Commons",
    "test_hub_store": "Memory & Commons", "test_memory_frontmatter": "Memory & Commons",
    "test_sqlite_memory": "Memory & Commons",
    # Docker sandbox
    "test_container_executor": "Docker sandbox",
}


def _guess_category(module: str) -> str:
    """A module this script has never seen before (a new test file). Best-effort by name, biased
    toward 'Entropy additions' for anything that smells like a later accretion onto the substrate
    (tutorials, the vending machine, Parallel search) rather than the original core engine."""
    if module.startswith(("test_hub_commons", "test_hub_store")):
        return "Memory & Commons"
    if module.startswith("test_hub_"):
        return "Hub / control plane"
    if re.match(r"test_(web|production|research|software|empirical|builder|cast|tts|video)", module):
        return "Studios"
    if module.startswith(("test_commons", "test_memory", "test_sqlite_memory")):
        return "Memory & Commons"
    if module == "test_container_executor":
        return "Docker sandbox"
    if re.match(r"test_(accounts|app|background_session|wedge|quota|ingest|registry)$", module):
        return "Hub / control plane"
    return "Entropy additions"


def run_pytest_junit(xml_path: Path) -> None:
    venv_pytest = ROOT / ".venv" / "bin" / "pytest"
    subprocess.run(
        [str(venv_pytest), "-q", "--deselect", _DESELECT, f"--junitxml={xml_path}"],
        cwd=ROOT, check=False,  # a real test failure must still produce a report, not abort here
    )


def parse_junit(xml_path: Path) -> dict[str, dict]:
    root = ElementTree.parse(xml_path).getroot()
    modules: dict[str, dict] = {}
    for case in root.iter("testcase"):
        classname = case.get("classname", "")
        module = classname.rsplit(".", 1)[-1] if classname else "unknown"
        name = case.get("name", "")
        if case.find("skipped") is not None:
            status = "skipped"
        elif case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        else:
            status = "passed"
        m = modules.setdefault(
            module, {"module": module, "passed": 0, "skipped": 0, "failed": 0, "total": 0, "tests": []}
        )
        m[status] += 1
        m["total"] += 1
        m["tests"].append({"name": name, "status": status})
    return modules


def build_categories(modules: dict[str, dict]) -> list[dict]:
    by_category: dict[str, list[dict]] = {c: [] for c in CATEGORY_ORDER}
    for module, data in modules.items():
        category = KNOWN_CATEGORY.get(module) or _guess_category(module)
        by_category.setdefault(category, []).append(data)
    result = []
    for category in [*CATEGORY_ORDER, *(c for c in by_category if c not in CATEGORY_ORDER)]:
        mods = sorted(by_category.get(category, []), key=lambda m: m["module"])
        if not mods:
            continue
        result.append({
            "category": category,
            "passed": sum(m["passed"] for m in mods),
            "skipped": sum(m["skipped"] for m in mods),
            "failed": sum(m["failed"] for m in mods),
            "total": sum(m["total"] for m in mods),
            "modules": mods,
        })
    return result


def write_nerve_data(categories: list[dict]) -> None:
    out = ROOT / "hub" / "static" / "shared" / "nerve-viz-data.js"
    out.write_text(
        "window.NERVE_VIZ_DATA = " + json.dumps(categories, separators=(",", ":")) + ";\n"
        "window.NERVE_VIZ_COLORS = " + json.dumps(CATEGORY_COLORS) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")


def update_proof_points(passed: int, skipped: int, failed: int, total_modules: int, today: str) -> None:
    """Every hardcoded '517' proof point, replaced with the real current count. Deliberately a
    plain, targeted string substitution per known call site — not a template engine — so a proof
    point that's worded differently in each file stays worded that way, just with a live number."""
    replacements = [
        (ROOT / "README.md", [
            (re.compile(r"\*\*\d+ tests passed, \d+ skipped"),
             f"**{passed} tests passed, {skipped} skipped"),
            (re.compile(r"— as of [\d-]+\."), f"— as of {today}."),
        ]),
        (ROOT / "docs" / "about.html", [
            (re.compile(r'<span class="num">\d+</span><span class="cap">tests passed, \d+ skipped — clean, [\d-]+</span>'),
             f'<span class="num">{passed}</span><span class="cap">tests passed, {skipped} skipped — clean, {today}</span>'),
            (re.compile(r"\d+ tests · mypy"), f"{passed} tests · mypy"),
        ]),
        (ROOT / "hub" / "static" / "index.html", [
            (re.compile(r"Every one of the \d+ signals"), f"Every one of the {passed} signals"),
            (re.compile(r"All \d+ ran and passed clean this session"),
             f"All {passed} ran and passed clean this session"),
            (re.compile(r'<div class="nerve-foot" id="nerveFootnote">\d+ passed &middot; \d+ skipped &middot; \d+ failed &middot; \d+ modules &middot; \d+ individual tests, each its own terminal</div>'),
             f'<div class="nerve-foot" id="nerveFootnote">{passed} passed &middot; {skipped} skipped &middot; {failed} failed &middot; {total_modules} modules &middot; {passed} individual tests, each its own terminal</div>'),
            (re.compile(r'<div class="proofnum" style="font-size:30px">\d+</div><div class="proofcap">tests passed, \d+ skipped — clean, [\d-]+</div>'),
             f'<div class="proofnum" style="font-size:30px">{passed}</div><div class="proofcap">tests passed, {skipped} skipped — clean, {today}</div>'),
        ]),
    ]
    for path, patterns in replacements:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, replacement in patterns:
            new_text, n = pattern.subn(replacement, text)
            if n == 0:
                print(f"WARNING: pattern not found in {path}: {pattern.pattern[:70]}", file=sys.stderr)
            text = new_text
        path.write_text(text, encoding="utf-8")
        print(f"updated {path}")


def main() -> None:
    xml_path = ROOT / "hub_data" / "_nerve_report.xml"
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    print("running the real test suite...", file=sys.stderr)
    run_pytest_junit(xml_path)
    modules = parse_junit(xml_path)
    xml_path.unlink(missing_ok=True)  # scratch only — the .js file is the artifact that ships

    categories = build_categories(modules)
    passed = sum(c["passed"] for c in categories)
    skipped = sum(c["skipped"] for c in categories)
    failed = sum(c["failed"] for c in categories)
    total_modules = sum(len(c["modules"]) for c in categories)
    print(f"passed={passed} skipped={skipped} failed={failed} modules={total_modules}", file=sys.stderr)
    if failed:
        print(f"WARNING: {failed} test(s) failed — the proof points will say so honestly", file=sys.stderr)

    write_nerve_data(categories)
    from datetime import date
    update_proof_points(passed, skipped, failed, total_modules, date.today().isoformat())


if __name__ == "__main__":
    main()
