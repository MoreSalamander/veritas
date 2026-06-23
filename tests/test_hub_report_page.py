"""The grounded report rendered as a viewable document page (/report/{run_id}).

A real research run is produced through the hub (offline, ScriptedProvider), then the document
route is fetched and asserted to render the claims and — the point — the verbatim grounding quote
on the page, so the verification model is visible, not buried in JSON.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from engine.model import ScriptedProvider
from hub.app import create_app

REPORT = json.dumps({
    "topic": "Bald eagles",
    "claims": [{"text": "Bald eagles fly up to 30 mph.",
                "citations": [{"source": "src1", "quote": "fly at speeds of up to 30 mph"}]}],
})


def _run_research(tmp_path) -> tuple[TestClient, str]:
    provider = ScriptedProvider({"researcher": REPORT,
                                 "judge": json.dumps([{"index": 0, "verdict": "SUPPORTED"}])})
    client = TestClient(create_app(data_dir=tmp_path, provider=provider))
    run = client.post("/api/runs", json={
        "goal": "how fast do bald eagles fly", "org": "research",
        "sources": ["Bald eagles can fly at speeds of up to 30 mph and dive at over 100 mph."],
    }).json()
    assert run["accepted"] is True
    return client, run["id"]


def test_report_document_renders_claims_and_grounding(tmp_path):
    client, run_id = _run_research(tmp_path)
    resp = client.get(f"/report/{run_id}")
    assert resp.status_code == 200 and "text/html" in resp.headers["content-type"]
    page = resp.text
    assert "Bald eagles fly up to 30 mph." in page          # the claim
    assert "fly at speeds of up to 30 mph" in page           # the verbatim grounding quote, on the page
    assert "src1" in page and "grounded" in page.lower()


def test_report_page_404s_for_unknown_or_non_research_run(tmp_path):
    client, _ = _run_research(tmp_path)
    assert client.get("/report/does-not-exist").status_code == 404
