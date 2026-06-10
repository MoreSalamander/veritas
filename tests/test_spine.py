"""Phase 0 definition-of-done.

The spine is real when a proposed artifact can be objectively ACCEPTED into
institutional memory by a gate, and objectively REJECTED into failure memory by a
gate — with a complete provenance trail either way, and no LLM anywhere. These
tests are the gate that proves the gate.
"""

from __future__ import annotations

from engine.artifact import Artifact, ArtifactStatus, Determinism
from engine.gate import Gate
from engine.memory import MemoryStore
from engine.run import Phase, Run


class _PassGate(Gate):
    name = "stub-pass"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact):
        return self._result(True, "stub: always passes")


class _FailGate(Gate):
    name = "stub-fail"
    determinism = Determinism.HARD

    def check(self, artifact: Artifact):
        return self._result(False, "stub: always fails")


class _SoftGate(Gate):
    name = "stub-soft"
    determinism = Determinism.SOFT

    def check(self, artifact: Artifact):
        return self._result(True, "judgment: reads fine")


def _artifact() -> Artifact:
    return Artifact.propose(
        type="code",
        owner="developer",
        payload="def greet():\n    return 'hi'\n",
        rationale="implements the greeting",
    )


def test_accepted_artifact_persists_with_provenance(tmp_path):
    run = Run(goal="say hi", memory=MemoryStore(tmp_path))
    out = run.submit(_artifact(), [_PassGate()])

    assert out.accepted
    assert out.artifact.status is ArtifactStatus.ACCEPTED
    assert out.artifact.provenance.accepted_because  # why it was accepted (Rule 5)
    assert len(out.artifact.provenance.gate_results) == 1

    assert out.memory_path.parent.name == "institutional"
    text = out.memory_path.read_text()
    assert "created_by: developer" in text  # who made it
    assert "accepted_because:" in text  # why accepted
    assert "stub-pass" in text  # what validated it


def test_rejected_artifact_lands_in_failure_memory(tmp_path):
    run = Run(goal="say hi", memory=MemoryStore(tmp_path))
    out = run.submit(_artifact(), [_FailGate()])

    assert not out.accepted
    assert out.artifact.status is ArtifactStatus.REJECTED
    assert out.memory_path.parent.name == "failures"
    assert "stub: always fails" in out.memory_path.read_text()


def test_one_failing_gate_rejects_the_whole(tmp_path):
    run = Run(goal="x", memory=MemoryStore(tmp_path))
    out = run.submit(_artifact(), [_PassGate(), _FailGate()])
    assert not out.accepted
    assert out.artifact.status is ArtifactStatus.REJECTED


def test_zero_gates_can_never_accept(tmp_path):
    # The core invariant: green must be EARNED by a gate. No gate, no acceptance.
    run = Run(goal="x", memory=MemoryStore(tmp_path))
    out = run.submit(_artifact(), [])
    assert not out.accepted
    assert out.artifact.status is ArtifactStatus.REJECTED


def test_gate_determinism_is_recorded_honestly(tmp_path):
    run = Run(goal="x", memory=MemoryStore(tmp_path))
    out = run.submit(_artifact(), [_SoftGate()])
    result = out.artifact.provenance.gate_results[0]
    assert result.determinism is Determinism.SOFT
    assert "determinism: soft" in out.memory_path.read_text()


def test_run_walks_to_complete_and_logs_verify(tmp_path):
    run = Run(goal="x", memory=MemoryStore(tmp_path))
    run.submit(_artifact(), [_PassGate()])
    assert run.phase is Phase.COMPLETE
    assert any(e.phase is Phase.VERIFY for e in run.log)
    assert any(e.phase is Phase.PERSIST for e in run.log)


def test_index_is_written(tmp_path):
    store = MemoryStore(tmp_path)
    run = Run(goal="x", memory=store)
    run.submit(_artifact(), [_PassGate()])
    assert store.index_path.exists()
    assert "institutional" in store.index_path.read_text()
