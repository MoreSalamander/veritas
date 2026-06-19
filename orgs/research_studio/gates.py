"""P16 — the Research Studio gates: a report is verified by GROUNDING, not execution.

This is a genuinely different verification model — the org's reason to exist as a peer of the
software and web orgs rather than a role inside one. The hard floor is everything about
grounding that is a fact: every claim is attributed, every citation resolves to a real source,
every quoted span actually appears in that source. What stays out of the floor — does the
source *semantically support* the claim — is judgment, and gets a SOFT gate (P16b).

None of these ask whether the writing is good. They ask whether it is grounded.
"""

from __future__ import annotations

from engine.artifact import Artifact, Determinism, GateResult
from engine.gate import Gate
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
