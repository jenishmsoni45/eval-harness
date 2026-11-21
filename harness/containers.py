"""Finding containers this project left behind (D25, design.md 10).

This Mac runs other projects' containers, so every lookup here matches only names that start
with `evalh-` (containers this repo starts itself) or `inspect-evalh-` (compose projects Inspect
starts for the `evalh` task). Nothing else is ever listed or touched.

    python -m harness.containers    # exit 1 and list them if any remain
"""

from __future__ import annotations

import subprocess
import sys

PREFIXES = ("evalh-", "inspect-evalh-")


def leftover_containers() -> list[str]:
    """Names of every container, running or stopped, whose name starts with one of PREFIXES."""
    result = subprocess.run(
        ["docker", "ps", "--all", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(name for name in result.stdout.split() if name.startswith(PREFIXES))


def remove_containers(names: list[str]) -> None:
    """Force-remove the named containers; refuses any name without one of PREFIXES."""
    foreign = [n for n in names if not n.startswith(PREFIXES)]
    if foreign:
        raise ValueError(f"refusing to remove containers not owned by this project: {foreign}")
    if names:
        subprocess.run(["docker", "rm", "--force", *names], capture_output=True, check=False)


def main() -> int:
    left = leftover_containers()
    if left:
        sys.stderr.write("containers left behind:\n  " + "\n  ".join(left) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
