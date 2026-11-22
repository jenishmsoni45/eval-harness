# Task image for queue-002 (task-spec.md "Images"). Built with this file outside the build context:
#   docker build -f task_bank/queue-002/Dockerfile --build-arg BASE_IMAGE=evalh-base-go:<hash> \
#     task_bank/queue-002/repo
# The context is repo/ alone, so hidden tests, patches and task.yaml cannot reach a layer (D26).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY --chown=agent:agent . /work/repo
USER agent
WORKDIR /work/repo

# The package needs nothing beyond the standard library, so nothing is fetched. The tests are
# built once, without running any, so the agent's build cache is warm.
RUN go test -count=1 -run '^$' ./...

# A fresh repository with exactly one commit of the shipped snapshot: no source history (V3).
RUN git init --quiet --initial-branch=main \
 && git add --all \
 && GIT_AUTHOR_NAME=evalh GIT_AUTHOR_EMAIL=evalh@localhost \
    GIT_COMMITTER_NAME=evalh GIT_COMMITTER_EMAIL=evalh@localhost \
    GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \
    git commit --quiet --message "Snapshot"
