# Base image for Python tasks (task-spec.md "Images"), tagged evalh-base-python:<content hash>.
#
# The official python image, pinned by the digest of its multi-architecture index, so arm64 (the
# Mac) and amd64 (CI) both resolve it (D20). It is glibc-based and is the full variant, which
# already has git, find, tar and the coreutils Inspect's tool helper needs (D27, D32), so nothing
# is installed with unpinned versions. Python 3.12.16 on Debian 12 when pinned.
FROM python:3.12-bookworm@sha256:4209fae09a3e20afd863e528bfddc235da5fd5977983e1996cd54cc9a72e6267

# The non-root user every sandbox container runs as (design.md 2).
RUN useradd --create-home --uid 1000 --user-group --shell /bin/bash agent \
 && mkdir /work \
 && chown agent:agent /work

ENV TZ=UTC \
    LANG=C.UTF-8 \
    PYTHONHASHSEED=0

# Each task image installs its test dependencies into a virtual environment at /opt/venv.
# Inspect's bash tool runs `bash --login`, and Debian's /etc/profile resets PATH, so the venv is
# put on PATH both for plain commands (ENV) and for login shells (/etc/profile.d).
ENV PATH=/opt/venv/bin:$PATH
RUN printf 'export PATH=/opt/venv/bin:$PATH\n' > /etc/profile.d/evalh-venv.sh
