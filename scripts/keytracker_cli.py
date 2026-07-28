#!/usr/bin/env python3
"""keytracker_cli.py — the ONLY place a real API key value is ever typed,
stored, or displayed in this repo.

Real values never touch hub/keytracker.py's SQLite file, never go through a
web form, never appear as a CLI argument (so they never land in shell
history) — they're entered via `getpass` and stored in the macOS Keychain
via the `security` command-line tool. This script only ever moves a value
between three places: your terminal's hidden input, the Keychain, and a
target repo's own `.env` file (the exact same file format every app already
reads — no application code changes needed).

Commands:
  keytracker_cli.py add <id> --provider anthropic --env-var ANTHROPIC_API_KEY --repos crypto-hunter,collectible-hunter
  keytracker_cli.py import <id> --provider anthropic --env-var ANTHROPIC_API_KEY --repos crypto-hunter --from-repo crypto-hunter
  keytracker_cli.py rotate <id>
  keytracker_cli.py sync [<id>]
  keytracker_cli.py list
  keytracker_cli.py revoke <id>
"""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.keytracker import KeyRecord, KeyTrackerStore  # noqa: E402

SERVICE = "entropy-keytracker"
REPO_ROOT = Path.home() / "MoreSalamander"
DB_PATH = Path(__file__).resolve().parent.parent / "hub_data" / "keytracker.sqlite3"


def _keychain_account(key_id: str) -> str:
    return f"{SERVICE}:{key_id}"


def _keychain_store(key_id: str, value: str) -> None:
    account = _keychain_account(key_id)
    subprocess.run(
        ["security", "add-generic-password", "-a", account, "-s", SERVICE, "-w", value, "-U"],
        check=True, capture_output=True,
    )


def _keychain_read(key_id: str) -> str:
    account = _keychain_account(key_id)
    proc = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", SERVICE, "-w"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.rstrip("\n")


def _upsert_env_line(env_path: Path, var_name: str, value: str) -> None:
    """Replace `var_name`'s line in `env_path` if present, else append it —
    every other line is preserved untouched."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    new_line = f"{var_name}={value}"
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{var_name}="):
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n")


def _read_env_value(env_path: Path, var_name: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{var_name}="):
            return line.split("=", 1)[1]
    return None


def cmd_add(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    if store.get(args.id) is not None:
        print(f"[keytracker] '{args.id}' already exists — use `rotate` to change its value.")
        return
    value = getpass.getpass(f"Paste the secret value for '{args.id}' (hidden, not echoed): ")
    if not value.strip():
        print("[keytracker] empty value — aborted, nothing stored.")
        return
    _keychain_store(args.id, value)
    store.upsert(KeyRecord(
        id=args.id, label=args.label or args.id, provider=args.provider,
        keychain_account=_keychain_account(args.id), env_var_name=args.env_var,
        used_by_repos=args.repos.split(",") if args.repos else [],
    ))
    print(f"[keytracker] stored '{args.id}' in Keychain and recorded its metadata. "
          f"Run `sync {args.id}` to write it into the tracked repos' .env files.")


def cmd_import(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    """Bootstrap from a repo's CURRENT .env value — does not touch any .env file."""
    if store.get(args.id) is not None:
        print(f"[keytracker] '{args.id}' already exists.")
        return
    env_path = REPO_ROOT / args.from_repo / ".env"
    value = _read_env_value(env_path, args.env_var)
    if value is None:
        print(f"[keytracker] {args.env_var} not found in {env_path} — nothing imported.")
        return
    _keychain_store(args.id, value)
    store.upsert(KeyRecord(
        id=args.id, label=args.label or args.id, provider=args.provider,
        keychain_account=_keychain_account(args.id), env_var_name=args.env_var,
        used_by_repos=args.repos.split(",") if args.repos else [],
    ))
    print(f"[keytracker] imported '{args.id}' from {env_path} into Keychain. "
          f"No .env file was modified.")


def cmd_rotate(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    record = store.get(args.id)
    if record is None:
        print(f"[keytracker] unknown id '{args.id}'.")
        return
    value = getpass.getpass(f"Paste the NEW secret value for '{args.id}' (hidden, not echoed): ")
    if not value.strip():
        print("[keytracker] empty value — aborted, nothing changed.")
        return
    _keychain_store(args.id, value)
    store.mark_rotated(args.id)
    print(f"[keytracker] rotated '{args.id}'. Run `sync {args.id}` to push it to its repos.")


def cmd_sync(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    records = [store.get(args.id)] if args.id else store.list_all()
    for record in records:
        if record is None:
            print(f"[keytracker] unknown id '{args.id}'.")
            continue
        if record.status != "active":
            print(f"[keytracker] skipping '{record.id}' — status is {record.status}.")
            continue
        value = _keychain_read(record.id)
        key_id_env_name = f"ENTROPY_KEY_ID_{record.provider.upper()}"
        for repo in record.used_by_repos:
            env_path = REPO_ROOT / repo / ".env"
            _upsert_env_line(env_path, record.env_var_name, value)
            _upsert_env_line(env_path, key_id_env_name, record.id)
            print(f"[keytracker] synced '{record.id}' -> {env_path}")


def cmd_list(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    from datetime import datetime, timezone

    records = store.list_all()
    if not records:
        print("[keytracker] no keys tracked yet — `add` or `import` one.")
        return
    now = datetime.now(timezone.utc)
    for r in records:
        rotated = r.last_rotated_at or r.created_at
        days = (now - rotated).days
        repos = ", ".join(r.used_by_repos) or "(none)"
        print(f"{r.id:24} {r.provider:10} {r.status:8} {days:4}d since rotation  repos: {repos}")


def cmd_revoke(store: KeyTrackerStore, args: argparse.Namespace) -> None:
    if store.revoke(args.id) is None:
        print(f"[keytracker] unknown id '{args.id}'.")
        return
    print(f"[keytracker] '{args.id}' marked revoked (left in Keychain for audit history — "
          f"delete it manually via Keychain Access.app if you also want it gone).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("add")
    ap.add_argument("id")
    ap.add_argument("--provider", required=True)
    ap.add_argument("--env-var", required=True)
    ap.add_argument("--repos", default="")
    ap.add_argument("--label", default=None)

    ip = sub.add_parser("import")
    ip.add_argument("id")
    ip.add_argument("--provider", required=True)
    ip.add_argument("--env-var", required=True)
    ip.add_argument("--repos", default="")
    ip.add_argument("--from-repo", required=True)
    ip.add_argument("--label", default=None)

    rp = sub.add_parser("rotate")
    rp.add_argument("id")

    sp = sub.add_parser("sync")
    sp.add_argument("id", nargs="?", default=None)

    sub.add_parser("list")

    vp = sub.add_parser("revoke")
    vp.add_argument("id")

    args = p.parse_args()
    store = KeyTrackerStore(DB_PATH)

    {
        "add": cmd_add, "import": cmd_import, "rotate": cmd_rotate,
        "sync": cmd_sync, "list": cmd_list, "revoke": cmd_revoke,
    }[args.cmd](store, args)


if __name__ == "__main__":
    main()
