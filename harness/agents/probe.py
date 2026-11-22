"""The network probe agent (E2, design.md 1, D54).

It runs one shell script in its container and submits. The script tries DNS lookups of public
names, TCP connections to public IP literals and to Docker's host addresses, and HTTP to a name
and to an IP literal, each bounded by a timeout with its output thrown away, and prints one line
per check with the exit code. Then it prints the container's network state: each interface with
its flags, the interfaces that hold an IPv6 address or an IPv6 route, the number of IPv4 routes,
and every non-loopback address (`hostname -I`):

    evalh-probe <check> <exit code>
    evalh-probe-iface <name> <flags>
    evalh-probe-ipv6-addresses <interfaces>
    evalh-probe-ipv6-routes <interfaces>
    evalh-probe-ipv4-routes <count>
    evalh-probe-addresses-status <exit code of hostname -I>
    evalh-probe-addresses <addresses>

The kernel creates its fallback tunnel devices (gre0, sit0, tunl0, ...) in every new network
namespace, so the loopback interface is not the only one that exists; it must be the only one
that is up, has an address or has a route (D57).

`tests/invariants/test_e2_network.py` runs it in the agent's container through the agent's own
tools, and the same script in the scoring container, and expects every check to fail the way a
missing network makes it fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from inspect_ai.model import Model, ModelOutput

from harness.agents.scripted import Turn, scripted_model, submit, tool_call

NAME = "network-probe"
MODEL = f"mockllm/{NAME}"
CHECK_PREFIX = "evalh-probe"
IFF_UP = 0x1  # the "up" bit of an interface's flags (linux/if.h)

# How each kind of check fails with no network: getent's exit code 2 is "not found", bash's
# /dev/tcp gives 1 when it cannot connect, and curl gives 6 (could not resolve) or 7 (could not
# connect). A timeout (124) or a missing command (126, 127) would not prove anything.
EXPECTED_FAILURES = {"dns": {2}, "tcp": {1}, "http": {6, 7}}

# (check name, command). Each name starts with its kind.
CHECKS: tuple[tuple[str, str], ...] = (
    ("dns-public-name", "getent hosts example.com"),
    ("dns-package-index", "getent ahosts pypi.org"),
    ("dns-docker-host", "getent hosts host.docker.internal"),
    ("tcp-public-dns-1", "bash -c 'exec 3<>/dev/tcp/1.1.1.1/53'"),
    ("tcp-public-dns-2", "bash -c 'exec 3<>/dev/tcp/8.8.8.8/53'"),
    ("tcp-docker-bridge", "bash -c 'exec 3<>/dev/tcp/172.17.0.1/80'"),
    ("tcp-docker-desktop-host", "bash -c 'exec 3<>/dev/tcp/192.168.65.254/80'"),
    ("http-public-name", "curl --silent --max-time 5 --output /dev/null http://example.com/"),
    ("http-public-ip", "curl --silent --max-time 5 --output /dev/null http://1.1.1.1/"),
)
TIMEOUT_S = 10

PROBE_SCRIPT = "\n".join(
    [
        *(
            f'timeout {TIMEOUT_S} {command} >/dev/null 2>&1; echo "{CHECK_PREFIX} {name} $?"'
            for name, command in CHECKS
        ),
        'for i in /sys/class/net/*; do [ -d "$i" ] && '
        f'echo "{CHECK_PREFIX}-iface ${{i##*/}} $(cat "$i/flags")"; done',
        f"echo \"{CHECK_PREFIX}-ipv6-addresses $(awk '{{print $6}}' /proc/net/if_inet6 | sort -u "
        '| tr "\\n" " ")"',
        f"echo \"{CHECK_PREFIX}-ipv6-routes $(awk '{{print $10}}' /proc/net/ipv6_route | sort -u "
        '| tr "\\n" " ")"',
        f"echo \"{CHECK_PREFIX}-ipv4-routes $(awk 'NR > 1' /proc/net/route | wc -l)\"",
        f'a=$(hostname -I); echo "{CHECK_PREFIX}-addresses-status $?"',
        f'echo "{CHECK_PREFIX}-addresses $a"',
    ]
)


@dataclass(frozen=True)
class NetworkState:
    codes: dict[str, int]  # each check's exit code
    flags: dict[str, int]  # each interface's flags
    ipv6_addresses: list[str]  # interfaces with an IPv6 address
    ipv6_routes: list[str]  # interfaces with an IPv6 route
    ipv4_routes: int
    addresses: list[str]  # every address but loopback's
    addresses_status: int  # hostname -I's exit code: 0 shows the list above is real

    @property
    def up(self) -> list[str]:
        return sorted(name for name, flags in self.flags.items() if flags & IFF_UP)


def parse(output: str) -> NetworkState:
    """The script's output, read back."""
    codes: dict[str, int] = {}
    flags: dict[str, int] = {}
    fields: dict[str, list[str]] = {}
    for line in output.splitlines():
        words = line.split()
        if not words or not words[0].startswith(CHECK_PREFIX):
            continue
        key, rest = words[0].removeprefix(CHECK_PREFIX), words[1:]
        if key == "" and len(rest) == 2:
            codes[rest[0]] = int(rest[1])
        elif key == "-iface" and len(rest) == 2:
            flags[rest[0]] = int(rest[1], 16)
        else:
            fields[key] = rest
    return NetworkState(
        codes=codes,
        flags=flags,
        ipv6_addresses=fields["-ipv6-addresses"],
        ipv6_routes=fields["-ipv6-routes"],
        ipv4_routes=int(fields["-ipv4-routes"][0]),
        addresses=fields["-addresses"],
        addresses_status=int(fields["-addresses-status"][0]),
    )


STEPS = (tool_call(MODEL, "bash", command=PROBE_SCRIPT), submit(MODEL))


def policy(turn: Turn) -> ModelOutput:
    return STEPS[min(turn.step, len(STEPS) - 1)].model_copy(deep=True)


def probe_model() -> Model:
    return scripted_model(policy, NAME)
