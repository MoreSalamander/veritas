"""P16 — the Research Studio gates: a report is verified by GROUNDING, not execution.

This is a genuinely different verification model — the org's reason to exist as a peer of the
software and web orgs rather than a role inside one. The hard floor is everything about
grounding that is a fact: every claim is attributed, every citation resolves to a real source,
every quoted span actually appears in that source. What stays out of the floor — does the
source *semantically support* the claim — is judgment, and gets a SOFT gate (P16b).

None of these ask whether the writing is good. They ask whether it is grounded.
"""

from __future__ import annotations

import json

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
from engine.model import ModelProvider
from orgs.research_studio.report import Corpus, ReportParseError, normalize, parse_report


class ReportScorerGate(Gate):
    """HARD: the report is structured (parses, has claims) — otherwise there's nothing to
    ground. The grounding analogue of the spec-scorer."""

    name = "report-scorer"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            report = parse_report(artifact.payload)
        except ReportParseError as exc:
            return self._result(False, f"report not usable: {exc}")
        return self._result(True, f"{len(report.claims)} claim(s) to ground")


class ClaimsCitedGate(Gate):
    """HARD: every claim carries at least one citation. No naked assertions."""

    name = "every-claim-cited"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact) -> GateResult:
        try:
            report = parse_report(artifact.payload)
        except ReportParseError as exc:
            return self._result(False, f"report not usable: {exc}")
        uncited = [c.text for c in report.claims if not c.citations]
        if uncited:
            return self._result(False, f"{len(uncited)} uncited claim(s); first: {uncited[0][:60]!r}")
        return self._result(True, f"all {len(report.claims)} claim(s) carry a citation")


class CitationsResolveGate(Gate):
    """HARD: every cited source resolves in the pinned corpus — no dangling references."""

    name = "citations-resolve"
    determinism = Determinism.HARD

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def check(self, artifact: Artifact) -> GateResult:
        try:
            report = parse_report(artifact.payload)
        except ReportParseError as exc:
            return self._result(False, f"report not usable: {exc}")
        dangling = sorted(
            {cit.source for c in report.claims for cit in c.citations if cit.source not in self.corpus}
        )
        if dangling:
            return self._result(False, f"citation(s) to unknown source(s): {', '.join(dangling)}")
        n = sum(len(c.citations) for c in report.claims)
        return self._result(True, f"all {n} citation(s) resolve to the corpus")


class QuotesVerbatimGate(Gate):
    """HARD: every quoted span actually appears, verbatim (whitespace-insensitive), in its
    cited source. This is what makes a quote a fact and not a paraphrase passed off as one."""

    name = "quotes-verbatim"
    determinism = Determinism.HARD

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus

    def check(self, artifact: Artifact) -> GateResult:
        try:
            report = parse_report(artifact.payload)
        except ReportParseError as exc:
            return self._result(False, f"report not usable: {exc}")
        checked = 0
        for c in report.claims:
            for cit in c.citations:
                if not cit.quote.strip():
                    continue
                source_text = self.corpus.get(cit.source, "")
                if normalize(cit.quote) not in normalize(source_text):
                    return self._result(
                        False, f"misquote of {cit.source}: {cit.quote[:60]!r} not found in source"
                    )
                checked += 1
        if checked == 0:
            return self._result(True, "no quoted spans to verify")
        return self._result(True, f"all {checked} quoted span(s) appear verbatim in their source")


JUDGE_SYSTEM = (
    "You are a fact-checker. For each numbered claim you are given the text of the source it "
    "cites. Decide ONLY from that source text whether it SUPPORTS the claim. Respond with ONLY "
    'a JSON array: [{"index": <n>, "verdict": "SUPPORTED" | "UNSUPPORTED"}]. No prose.'
)


class SupportGate(Gate):
    """SOFT: does the cited source actually *support* the claim? That is judgment — the source
    resolving and the quote being verbatim are facts (hard gates already own those); whether the
    quote backs the assertion is an LLM's opinion, so it is advisory, never a block. (Use a
    judge model separate from the researcher for real judge-separation.)"""

    name = "support"
    determinism = Determinism.SOFT

    def __init__(self, provider: ModelProvider, corpus: Corpus) -> None:
        self.provider = provider
        self.corpus = corpus

    def check(self, artifact: Artifact) -> GateResult:
        try:
            report = parse_report(artifact.payload)
        except ReportParseError:
            return self._result(True, "report unparseable — support not judged (advisory)")
        cited = [c for c in report.claims if c.citations]
        if not cited:
            return self._result(True, "no cited claims to judge")

        lines = []
        for i, c in enumerate(cited):
            excerpts = " | ".join(self.corpus.get(cit.source, "")[:500] for cit in c.citations)
            lines.append(f"[{i}] CLAIM: {c.text}\n    SOURCE: {excerpts}")
        prompt = "\n\n".join(lines)
        try:
            raw = self.provider.propose(role="judge", prompt=prompt, system=JUDGE_SYSTEM)
            verdicts = json.loads(raw[raw.find("[") : raw.rfind("]") + 1])
        except Exception:
            return self._result(True, "judge produced no usable verdict (advisory)")

        unsupported = [
            v.get("index") for v in verdicts
            if isinstance(v, dict) and str(v.get("verdict", "")).upper() == "UNSUPPORTED"
        ]
        if unsupported:
            return self._result(
                False,
                f"judge flagged {len(unsupported)} claim(s) as unsupported by their source "
                f"(advisory, unverified): indices {unsupported}",
            )
        return self._result(True, f"judge: all {len(cited)} cited claim(s) supported (advisory)")
