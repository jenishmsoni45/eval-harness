# Task image for risk-004 (task-spec.md "Images"). Built with this file outside the build context:
#   docker build -f task_bank/risk-004/Dockerfile --build-arg BASE_IMAGE=evalh-base-python:<hash> \
#     task_bank/risk-004/repo
# The context is repo/ alone, so hidden tests, patches and task.yaml cannot reach a layer (D26).
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Test dependencies from the snapshot's hash-locked requirements, so tests run offline. The base
# image puts /opt/venv/bin on PATH, for login shells too.
COPY --chown=root:root requirements.txt /opt/requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      --requirement /opt/requirements.txt \
 && rm /opt/requirements.txt

COPY --chown=agent:agent . /work/repo
USER agent
WORKDIR /work/repo

# A fresh repository with exactly one commit of the shipped snapshot: no source history (V3).
# Caches are excluded through .git/info/exclude, which is not part of the committed tree.
RUN git init --quiet --initial-branch=main \
 && printf '%s\n' __pycache__/ .pytest_cache/ .hypothesis/ '*.pyc' > .git/info/exclude \
 && git add --all \
 && GIT_AUTHOR_NAME=evalh GIT_AUTHOR_EMAIL=evalh@localhost \
    GIT_COMMITTER_NAME=evalh GIT_COMMITTER_EMAIL=evalh@localhost \
    GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \
    git commit --quiet --message "Snapshot"
