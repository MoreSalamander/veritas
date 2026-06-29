# Deploying the Veritas wedge to Fly.io

The hosted wedge lets anyone sign up and submit a goal; Veritas runs it **isolated** (a throwaway
container per run), **persisted** (per-tenant DB), **gated**, and **metered**. This is the from-scratch
runbook.

## Why Fly (and not Vercel/Render-free)

The sandbox spawns a Docker container per submission, so the host must be able to run Docker. A Fly
Machine is a **Firecracker microVM** with its own kernel, so we run `dockerd` *inside* it
(Docker-in-Docker). The microVM is the hard isolation boundary; the per-run container is
defense-in-depth. Serverless/PaaS platforms can't do this.

## What you need

- A [Fly.io](https://fly.io) account + `flyctl` installed (`brew install flyctl`), then `fly auth login`.
- An **Anthropic API key** (the model that proposes code). Hosted runs default to Claude Sonnet.
- ~10 minutes. Cost: a `shared-cpu-1x`/1GB Machine + a small Volume (a few $/mo) plus Claude tokens
  (~1–13¢ per build depending on tier).

## Steps

Run these from the repo root (`~/MoreSalamander/veritas`).

```bash
# 1. Create the app (pick a unique name; this writes/uses deploy/fly/fly.toml).
fly apps create veritas-wedge          # or: fly launch --no-deploy --copy-config -c deploy/fly/fly.toml
#    -> then edit `app = "..."` in deploy/fly/fly.toml to the name you chose, and set primary_region.

# 2. Create the persistent Volume (same name as [mounts].source in fly.toml; same region as the app).
fly volumes create veritas_data --region iad --size 3 -a veritas-wedge

# 3. Set the model secret (NOT in fly.toml — it's a secret).
fly secrets set ANTHROPIC_API_KEY=sk-ant-... -a veritas-wedge

# 4. Deploy (builds deploy/fly/Dockerfile, boots the Machine, brings up dockerd then the app).
fly deploy -c deploy/fly/fly.toml

# 5. Verify the sandbox actually came up (the wedge fails closed without it).
curl https://veritas-wedge.fly.dev/api/wedge/status
#    -> expect {"sandbox_active": true, "accounts": true, "metered": true, "open": true}
```

Then open **`https://veritas-wedge.fly.dev/wedge`** — sign up, submit a goal (e.g. *"reverse a
string"*), and watch the gate ledger decide. That URL is the thing to send people.

> First boot is slower: dockerd starts and pulls `python:3.12-slim` once. It's cached on the Volume
> afterward, so restarts are fast.

## A custom domain (optional)

```bash
fly certs add wedge.yourdomain.com -a veritas-wedge      # then add the shown DNS records
```

## Operating it

- **Logs:** `fly logs -a veritas-wedge` (watch for `dockerd did not come up` — that's the fail-closed guard).
- **Update after a push:** `fly deploy -c deploy/fly/fly.toml`.
- **Tune limits:** edit `[env]` in fly.toml (`VERITAS_WEDGE_QUOTA`, `VERITAS_MODEL`) and redeploy.
- **Data lives on the Volume** (`/data`: `accounts.db`, `usage.db`, per-tenant memory, the docker cache).
  Back it up with `fly volumes snapshots`.

## Security posture (already enforced)

- `VERITAS_PUBLIC=1` serves **only** the wedge — the admin dashboard and unauthenticated APIs 404.
- `VERITAS_SANDBOX=container` + the fail-closed check: **no live sandbox ⇒ no run** (HTTP 503).
- Each tenant is isolated by path (own DB, own memory). Quotas rate-limit and feed the usage ledger.
- `ANTHROPIC_API_KEY` is a Fly secret, never baked into the image.

## If Docker-in-Docker won't start on your Fly org

DinD inside a microVM is an established pattern but can depend on org settings. If `fly logs` shows
dockerd failing, the clean alternatives are:

1. **A plain Linux VM** (Hetzner/DO/EC2) with Docker installed and the app as a `systemd` service
   behind Caddy — guaranteed, since Docker runs natively. (Same env vars as `[env]` above.)
2. **A `FlyMachineExecutor`** — a new `Executor` backend that spawns a throwaway Fly *Machine* per run
   via the Machines API (hardware-isolated per run, the most Fly-native design). A future build.
