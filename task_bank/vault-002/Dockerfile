# Task image for vault-002 (task-spec.md "Images"). Built with this file outside the build context:
#   docker build -f task_bank/vault-002/Dockerfile --build-arg BASE_IMAGE=evalh-base-rust:<hash> \
#     task_bank/vault-002/repo
# The context is repo/ alone, so hidden tests, patches and task.yaml cannot reach a layer (D26).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY --chown=agent:agent . /work/repo
USER agent
WORKDIR /work/repo

# The crates in Cargo.lock, checked against its checksums, fetched from crates.io while the image
# builds; the base image keeps cargo offline for everything after (CARGO_NET_OFFLINE=true). Then
# every test target is built once, without running any, so target/ is warm. --locked fails the
# build if cargo would rewrite Cargo.lock, a protected file (D41).
RUN CARGO_NET_OFFLINE=false cargo fetch --locked \
 && cargo test --locked --no-run

# A fresh repository with exactly one commit of the shipped snapshot: no source history (V3).
# The build output is excluded through .git/info/exclude, which is not part of the committed tree.
RUN git init --quiet --initial-branch=main \
 && printf '%s\n' /target/ > .git/info/exclude \
 && git add --all \
 && GIT_AUTHOR_NAME=evalh GIT_AUTHOR_EMAIL=evalh@localhost \
    GIT_COMMITTER_NAME=evalh GIT_COMMITTER_EMAIL=evalh@localhost \
    GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \
    git commit --quiet --message "Snapshot"
