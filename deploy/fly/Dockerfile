# Veritas Dynamics — the hosted wedge, for Fly.io.
#
# A Fly Machine is a Firecracker microVM with its own kernel, so we can run the Docker daemon INSIDE
# it (Docker-in-Docker). The microVM is the hard isolation boundary around the whole tenant-facing app;
# the per-run container the sandbox spawns is defense-in-depth on top. ContainerExecutor is reused
# unchanged — it just talks to the local daemon that start.sh brings up.
#
# Build context is the repo root: from there, `fly deploy` (fly.toml points dockerfile here).

FROM python:3.12-slim

# docker.io = the daemon (dockerd); docker-cli = the client (/usr/bin/docker) the start script drives —
# it is NOT pulled in under --no-install-recommends, so name it explicitly. fuse-overlayfs gives dockerd
# a working storage driver in nested environments where overlay2 can't mount.
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io docker-cli fuse-overlayfs ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/veritas
COPY . /opt/veritas

# Only the hub extra (fastapi/uvicorn/anthropic) — no torch/ML; the wedge never needs it.
RUN pip install --no-cache-dir ".[hub]"

# The hosting posture baked in. Secrets (ANTHROPIC_API_KEY) come from `fly secrets`, not the image.
# fly.toml [env] can override any of these; they are sane defaults so the image is safe by itself.
ENV VERITAS_SANDBOX=container \
    VERITAS_MEMORY=sqlite \
    VERITAS_ACCOUNTS=1 \
    VERITAS_PUBLIC=1 \
    VERITAS_MODEL=sonnet \
    VERITAS_DATA=/data

EXPOSE 8099
CMD ["bash", "/opt/veritas/deploy/fly/start.sh"]
