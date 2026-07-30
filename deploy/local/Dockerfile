# Veritas, containerized for in-house/local use — NOT the public wedge.
#
# Unlike deploy/fly/, this does not nest a dockerd. A Fly Machine is a bare
# Firecracker microVM with no daemon at all, so deploy/fly/ has to bring its
# own. A local dev box running Docker Desktop already has a daemon; we mount
# its socket instead. engine/executor.py's ContainerExecutor just shells out
# to whatever `docker` binary/daemon it finds, so this is a zero-code-change
# fit — no nested daemon, no duplicate image cache, no start.sh wait-loop.
#
# Caveat (accepted, not hidden): a container with the host socket mounted has
# effective root-equivalent control over the host's Docker. Fine for a
# single-operator local box, the same way deploy/fly/'s DinD is fine because
# the microVM is the trust boundary there. See README.md.
FROM python:3.12-slim

# Debian's docker.io apt package bundles a full daemon we don't need; instead
# grab just Docker's static CLI binary (no daemon, no containerd, no GPG-key
# apt-repo dance).
ARG DOCKER_CLI_VERSION=27.3.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
       | tar -xz --strip-components=1 -C /usr/local/bin docker/docker \
    && apt-get purge -y curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/veritas
COPY . /opt/veritas
RUN pip install --no-cache-dir ".[hub]"

# This is a private, single-operator instance, not the public wedge, so we
# deliberately omit VERITAS_ACCOUNTS/VERITAS_PUBLIC from deploy/fly/'s env
# block — the admin dashboard and unauthenticated APIs stay open.
ENV VERITAS_SANDBOX=container \
    VERITAS_MEMORY=sqlite \
    VERITAS_DATA=/data

EXPOSE 8099
CMD ["uvicorn", "hub.app:app", "--host", "0.0.0.0", "--port", "8099"]
