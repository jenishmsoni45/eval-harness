# Base image for Go tasks (task-spec.md "Images"), tagged evalh-base-go:<content hash>.
#
# The official golang image, pinned by the digest of its multi-architecture index, so arm64 (the
# Mac) and amd64 (CI) both resolve it (D20). It is glibc-based (Debian 12) and built on
# buildpack-deps:bookworm-scm, so it already has git, find, tar and the coreutils Inspect's tool
# helper needs (D27); nothing is installed with unpinned versions. Go 1.27.3, the version in
# job-queue's go.mod at the snapshot commit.
FROM golang:1.27.3-bookworm@sha256:dc0963f32053e4bc451d24d87e3892d42d01021b61f093e98eb95c0352bb84b0

# The non-root user every sandbox container runs as (design.md 2).
RUN useradd --create-home --uid 1000 --user-group --shell /bin/bash agent \
 && mkdir /work \
 && chown agent:agent /work

# Offline Go (task-spec.md "Images"): never fetch a module or a toolchain, and never edit go.mod.
# A task image downloads its modules from go.sum once, while it builds, by overriding GOPROXY for
# that one step; afterwards the module cache (GOPATH=/go) and the agent's build cache are warm.
ENV TZ=UTC \
    LANG=C.UTF-8 \
    PYTHONHASHSEED=0 \
    GOTOOLCHAIN=local \
    GOFLAGS=-mod=readonly \
    GOPROXY=off

# Inspect's bash tool runs `bash --login`, and Debian's /etc/profile resets PATH, so the Go tools
# are put on PATH for login shells too (the image's ENV covers plain commands).
RUN printf 'export PATH=/usr/local/go/bin:/go/bin:$PATH\n' > /etc/profile.d/evalh-go.sh
