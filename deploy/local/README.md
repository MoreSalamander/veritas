# Running Veritas locally, in-house, in Docker

This is Veritas containerized for **your own machine** — not the public hosted wedge
(`deploy/fly/` is that). No accounts, no quotas, no public-only lockdown: this is a private,
single-operator instance with the admin dashboard open.

## Why this doesn't nest a Docker daemon

`deploy/fly/` runs its own `dockerd` inside the container because a Fly Machine is a bare
Firecracker microVM with no daemon at all — nesting one is how it gets Docker, and it's safe
because the microVM is already the isolation boundary.

Your Mac already has Docker Desktop running a daemon. So instead of nesting a second one, this
setup mounts the **host's** Docker socket (`/var/run/docker.sock`) into the Veritas container and
installs only the `docker` CLI binary (no `dockerd`, no `containerd`, no image-cache duplication,
no `start.sh` wait-loop). `engine/executor.py`'s `ContainerExecutor` already just shells out to
whatever `docker` binary/daemon it finds — it doesn't care whose daemon answers, so this is a
zero-code-change fit, and strictly less moving parts than copying the Fly approach.

**Security caveat, stated plainly, not hidden**: a container with the host socket mounted has
effective root-equivalent control over the host's Docker — it could launch privileged sibling
containers, mount the host filesystem via one, etc. This is accepted here the same way Fly's DinD
is accepted specifically because the microVM is the trust boundary there — for a single-operator
local dev box, the host socket is that boundary instead. Don't expose this container's port to
anything but your own machine.

## Env vars — the one deliberate divergence from `deploy/fly/`

```
VERITAS_SANDBOX=container   # use ContainerExecutor, not LocalSubprocessExecutor
VERITAS_MEMORY=sqlite
VERITAS_DATA=/data          # same convention deploy/fly/ uses, mounted on a named volume here
```

Deliberately **omitted** vs. `deploy/fly/fly.toml`: `VERITAS_ACCOUNTS=1` and `VERITAS_PUBLIC=1`.
Those exist to lock the hosted wedge down to a single public-facing surface with per-tenant
quotas. This is your own private instance — the full admin dashboard and every API stay reachable.

`ANTHROPIC_API_KEY` is read from your shell environment and passed through by
`docker-compose.yml` — set it before running `docker compose up`, it is never baked into the
image.

## Running it

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose -f deploy/local/docker-compose.yml up -d --build
```

Then open **http://localhost:8099**.

State (`accounts.db`, `usage.db`, `collector.sqlite3`, `keytracker.sqlite3`, per-org memory) lives
on the named `veritas_data` Docker volume mounted at `/data`, not baked into the image — it
survives `docker compose down`/rebuilds. If you'd rather inspect the sqlite files directly with
host tools, swap the `veritas_data:/data` line for a host bind mount (e.g. `./.local-data:/data`)
instead of the named volume; everything else is unchanged.

## Verifying the sandbox is actually live

```bash
curl localhost:8099/api/wedge/status
```

Expect `"sandbox_active": true` — this is the real end-to-end proof that `ContainerExecutor`
inside the Veritas container reached the host daemon through the mounted socket, not just that
the container started. This endpoint isn't gated behind `VERITAS_PUBLIC`, so it works as-is here.

## Confirming isolation still holds

`tests/test_container_executor.py` is excluded from the image by `.dockerignore`. To run it
against the real setup (the container driving sibling containers through the mounted host
socket — the actual mechanism this whole setup exists for):

```bash
docker compose -f deploy/local/docker-compose.yml exec veritas sh -c \
  "pip install pytest && python -m pytest tests/test_container_executor.py -v" \
  # (mount ./tests in, or copy it in, since it isn't part of the image — see .dockerignore)
```

It asserts two things: genuine isolation (no network, read-only root, a memory-cap kill actually
kills a bomb) and verdict parity (a gate run through the sandbox reaches the same accept/reject as
`LocalSubprocessExecutor`).

## Where this leaves the door open

Because `ContainerExecutor` is just "shell out to `docker run` against whatever daemon is
reachable," this same host-socket mechanism is exactly what a future in-container "engines as
disposable containers" orchestrator would reuse to launch sibling per-engine containers from
inside this same Veritas container — no redesign needed when that work starts. This setup is
scoped to containerizing Veritas correctly; it isn't building that orchestration, only avoiding
foreclosing it.
