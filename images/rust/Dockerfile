# Base image for Rust tasks (task-spec.md "Images"), tagged evalh-base-rust:<content hash>.
#
# The official rust image, pinned by the digest of its multi-architecture index, so arm64 (the
# Mac) and amd64 (CI) both resolve it (D20). It is glibc-based (Debian 12) and built on
# buildpack-deps:bookworm, so it already has git, find, tar and the coreutils Inspect's tool
# helper needs (D27); nothing is installed with unpinned versions. Rust 1.86.0, the version
# vaultline's CI pins at the snapshot commit.
FROM rust:1.86-bookworm@sha256:300ec56abce8cc9448ddea2172747d048ed902a3090e6b57babb2bf19f754081

# The non-root user every sandbox container runs as (design.md 2).
RUN useradd --create-home --uid 1000 --user-group --shell /bin/bash agent \
 && mkdir /work \
 && chown agent:agent /work

# Offline Rust (task-spec.md "Images"). The toolchain stays where the official image put it
# (RUSTUP_HOME=/usr/local/rustup, binaries in /usr/local/cargo/bin). Cargo's own home, with the
# crate registry, belongs to the agent, because cargo takes a lock file there even offline. A task
# image fetches its crates from Cargo.lock once, while it builds, by overriding CARGO_NET_OFFLINE
# for that one step; afterwards the registry and the repo's target/ are warm.
ENV TZ=UTC \
    LANG=C.UTF-8 \
    PYTHONHASHSEED=0 \
    CARGO_HOME=/home/agent/.cargo \
    CARGO_NET_OFFLINE=true \
    CARGO_TERM_COLOR=never

# Inspect's bash tool runs `bash --login`, and Debian's /etc/profile resets PATH, so the Rust
# tools are put on PATH for login shells too (the image's ENV covers plain commands).
RUN printf 'export PATH=/usr/local/cargo/bin:$PATH\n' > /etc/profile.d/evalh-rust.sh
