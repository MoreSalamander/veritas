"""The execution boundary behaves deterministically and reports failures honestly."""

from __future__ import annotations

from engine.executor import LocalSubprocessExecutor


def test_clean_code_runs_ok():
    result = LocalSubprocessExecutor().run("print('hi')", {}, timeout=5)
    assert result.ok and not result.timed_out
    assert "hi" in result.stdout


def test_failing_code_reports_stderr():
    result = LocalSubprocessExecutor().run("raise AssertionError('boom')", {}, timeout=5)
    assert not result.ok
    assert "boom" in result.stderr


def test_runaway_code_times_out():
    result = LocalSubprocessExecutor().run("while True: pass", {}, timeout=1)
    assert not result.ok and result.timed_out


def test_env_is_passed_through():
    import os

    env = {**os.environ, "VERITAS_X": "42"}
    result = LocalSubprocessExecutor().run(
        "import os; print(os.environ['VERITAS_X'])", env, timeout=5
    )
    assert result.ok and "42" in result.stdout
