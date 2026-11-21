"""Building and naming the evalh images (task-spec.md "Images").

- Base images: `evalh-base-<language>:<hash>`, built from images/<language>/.
- Task images: `evalh-task-<id>:<hash>`, built with `docker build -f task_bank/<id>/Dockerfile
  task_bank/<id>/repo`, so nothing outside repo/ can reach a layer (D26).

Each tag is a content hash of the build inputs: every file of the build context, the Dockerfile,
and for a task image the base image's tag. Same inputs, same tag; any change, a new tag.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from harness.tasks import REPO_ROOT, Task

IMAGES_DIR = REPO_ROOT / "images"
HASH_LENGTH = 16


def _hash_tree(digest: hashlib._Hash, root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix().encode()
            digest.update(len(rel).to_bytes(8, "big") + rel)
            data = path.read_bytes()
            digest.update(len(data).to_bytes(8, "big") + data)


def base_image_tag(language: str) -> str:
    digest = hashlib.sha256(b"evalh-base\0")
    _hash_tree(digest, IMAGES_DIR / language)
    return f"evalh-base-{language}:{digest.hexdigest()[:HASH_LENGTH]}"


def task_image_tag(task: Task) -> str:
    digest = hashlib.sha256(b"evalh-task\0")
    digest.update(base_image_tag(task.language).encode() + b"\0")
    dockerfile = task.dockerfile.read_bytes()
    digest.update(len(dockerfile).to_bytes(8, "big") + dockerfile)
    _hash_tree(digest, task.repo_dir)
    return f"evalh-task-{task.id}:{digest.hexdigest()[:HASH_LENGTH]}"


def image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _build(tag: str, dockerfile: Path, context: Path, build_args: dict[str, str]) -> None:
    args = ["docker", "build", "--quiet", "--tag", tag, "--file", str(dockerfile)]
    for key, value in build_args.items():
        args += ["--build-arg", f"{key}={value}"]
    result = subprocess.run([*args, str(context)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"docker build of {tag} failed:\n{result.stderr[-4000:]}")


def build_base_image(language: str) -> str:
    tag = base_image_tag(language)
    if not image_exists(tag):
        context = IMAGES_DIR / language
        _build(tag, context / "Dockerfile", context, {})
    return tag


def build_task_image(task: Task) -> str:
    """Build the task image (and its base image) unless an image with the same content hash
    already exists. The build context is repo/ alone (D26)."""
    base = build_base_image(task.language)
    tag = task_image_tag(task)
    if not image_exists(tag):
        _build(tag, task.dockerfile, task.repo_dir, {"BASE_IMAGE": base})
    return tag
