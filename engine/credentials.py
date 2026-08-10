"""Where the Anthropic credential comes from, and where a new one goes.

The value never lives in this process's own state, in a settings file, or in
any object that could land in a traceback. It lives in the macOS Keychain —
the *same* service `entropy-os/scripts/keytracker_cli.py` already writes to,
so a key added at the terminal and a key pasted into the model page are one
key rather than two that drift apart.

Two rules shape the resolution order.

**The environment wins.** An operator who exported `ANTHROPIC_API_KEY` for a
shell decided something about that shell; a key stored through a web form must
not quietly override it. So env is read first and the Keychain is the fallback,
never the other way around.

**Status is not the secret.** `status()` answers "is there a key, and where did
it come from" without handing the value to a caller that only wanted to render
a badge. The only fragment it exposes is the last four characters, which is
what makes "which key is this?" answerable without making it copyable.
"""

from __future__ import annotations

import os
import subprocess

# The keytracker's own service name and the account it files the Anthropic key
# under. Hard-coded rather than imported because that CLI lives in a different
# repository and this module must not depend on it — they agree on a Keychain
# convention, which is a smaller coupling than an import.
SERVICE = "entropy-keytracker"
ACCOUNT = f"{SERVICE}:anthropic-primary"

ENV_VAR = "ANTHROPIC_API_KEY"


def _keychain_read() -> str:
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-a", ACCOUNT, "-s", SERVICE, "-w"],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # Not found, locked, or not macOS — all mean "no key from here".
        return ""
    return proc.stdout.strip()


def resolve() -> str:
    """The key this run should use, or "" when there is none.

    Empty is a legitimate answer, not an error: the Anthropic SDK does its own
    resolution (env, then an `ant auth login` profile), so handing it nothing
    is how a caller says "use whatever you already know about".
    """
    return os.environ.get(ENV_VAR, "").strip() or _keychain_read()


def store(value: str) -> None:
    """Put a key in the Keychain, replacing any key already filed there.

    The value is passed as an argument to `security`, which is visible in the
    process table for the instant the command runs. That is the same exposure
    `keytracker_cli.py` accepts for the same reason: the alternative (a
    temporary file) trades a momentary process-table entry for bytes on disk.
    """
    value = value.strip()
    if not value:
        raise ValueError("refusing to store an empty key")
    subprocess.run(
        ["security", "add-generic-password", "-a", ACCOUNT, "-s", SERVICE,
         "-w", value, "-U"],
        check=True, capture_output=True, timeout=10,
    )


def forget() -> bool:
    """Delete the stored key. True if one was there, False if nothing to do."""
    proc = subprocess.run(
        ["security", "delete-generic-password", "-a", ACCOUNT, "-s", SERVICE],
        capture_output=True, timeout=10,
    )
    return proc.returncode == 0


def status() -> dict[str, object]:
    """Whether a credential exists and where it came from — never the value.

    `tail` is the last four characters, which is enough to tell two keys apart
    when rotating and not enough to be one.
    """
    env = os.environ.get(ENV_VAR, "").strip()
    key = env or _keychain_read()
    return {
        "present": bool(key),
        "source": "environment" if env else ("keychain" if key else "none"),
        "tail": key[-4:] if key else "",
        # An environment key cannot be replaced from a web form — the process
        # would have to mutate its own environment, and the next restart would
        # silently undo it. Say so rather than accepting an edit that does
        # nothing.
        "editable": not env,
    }
