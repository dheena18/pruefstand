"""Lint compose files against the Prüfstand rules (CLAUDE.md §8, docker.md §3, T0.3 S5, Y1.4).

A compose file fails when

 * a service with an ``image`` is not pinned by digest (``@sha256:<64 hex>`` at the end);
   ``build:`` without ``image:`` is exempt, its base images are pinned in the Dockerfile (hadolint);
 * a published port does not bind ``127.0.0.1`` explicitly;
 * a published host port is a literal instead of ``${<NAME>_PORT:-<default>}``;
 * a service has no (enabled) ``healthcheck``;
 * an environment variable named like a secret (key, token, secret, password) has a literal value.

Usage: ``python scripts/check_compose.py [FILE ...]``; without arguments it checks
``docker-compose.yml`` and ``infra/**/compose*.yml``. Exit code 0 = clean, 1 = findings.
"""

import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
LOOPBACK = "127.0.0.1"
HOST_PORT_VAR = re.compile(r"^\$\{[A-Z][A-Z0-9_]*_PORT:-\d+\}$")
DIGEST_PIN = re.compile(r"@sha256:[0-9a-f]{64}$")
VAR_DEFAULT = re.compile(r"\$\{[^}:?-]*:?-([^}]+)\}")
SECRET_NAME = re.compile(r"(?i)(key|token|secret|password)")
VAR_REF = re.compile(r"\$\{[^}]*\}")
SHORT_WITH_IP = 3
SHORT_WITH_HOST = 2


class _ComposeLoader(yaml.SafeLoader):
    """Safe loader that tolerates compose merge tags such as ``!reset`` and ``!override``."""


def _ignore_tag(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node) -> object:  # noqa: ARG001
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node) if isinstance(node, yaml.ScalarNode) else None


_ComposeLoader.add_multi_constructor("!", _ignore_tag)


def _split_port(spec: str) -> list[str]:
    """Split ``ip:host:container`` on colons that are not inside a ``${...}`` reference."""
    refs: list[str] = []

    def protect(match: re.Match[str]) -> str:
        refs.append(match.group(0))
        return f"\x00{len(refs) - 1}\x00"

    parts = VAR_REF.sub(protect, spec).split(":")
    return [re.sub(r"\x00(\d+)\x00", lambda m: refs[int(m.group(1))], part) for part in parts]


def _port_parts(entry: object) -> tuple[str | None, str | None]:
    """Return ``(host ip, published host port)`` of one ``ports`` entry; ``None`` if absent."""
    if isinstance(entry, Mapping):
        ip = entry.get("host_ip")
        published = entry.get("published")
        return (None if ip is None else str(ip)), (None if published is None else str(published))
    spec = str(entry)
    if spec.startswith("["):  # bracketed IPv6 host: returned as is, rejected by _check_ports
        end = spec.find("]")
        return (spec, None) if end < 0 else (spec[: end + 1], _split_port(spec[end + 2 :])[0])
    parts = _split_port(spec)
    if len(parts) >= SHORT_WITH_IP:
        return parts[0], parts[1]
    if len(parts) == SHORT_WITH_HOST:
        return None, parts[0]
    return None, None


def _check_ports(name: str, service: Mapping[str, object]) -> Iterator[str]:
    ports = service.get("ports")
    if not isinstance(ports, Sequence) or isinstance(ports, str):
        return
    for entry in ports:
        ip, host_port = _port_parts(entry)
        if ip != LOOPBACK:
            ipv6 = ip is not None and (ip.startswith("[") or ":" in ip)
            kind = "binds all interfaces or uses an IPv6 host" if ipv6 else "binds all interfaces"
            yield f"{name}: port {entry!r} {kind} (use 127.0.0.1:...)"
        if host_port is not None and not HOST_PORT_VAR.match(host_port):
            yield f"{name}: literal host port in {entry!r} (use ${{<NAME>_PORT:-<default>}})"


def _check_image(name: str, service: Mapping[str, object]) -> Iterator[str]:
    image = service.get("image")
    if image is not None and not DIGEST_PIN.search(str(image)):
        yield f"{name}: image not pinned by digest"


def _check_healthcheck(name: str, service: Mapping[str, object]) -> Iterator[str]:
    health = service.get("healthcheck")
    test = health.get("test") if isinstance(health, Mapping) else None
    none_test = test == "NONE" or (isinstance(test, Sequence) and list(test) == ["NONE"])
    if not isinstance(health, Mapping) or health.get("disable") is True or none_test:
        yield f"{name}: no healthcheck"


def _env_pairs(environment: object) -> Iterator[tuple[str, str | None]]:
    if isinstance(environment, Mapping):
        for key, value in environment.items():
            yield str(key), None if value is None else str(value)
    elif isinstance(environment, Sequence) and not isinstance(environment, str):
        for item in environment:
            key, sep, value = str(item).partition("=")
            yield key, value if sep else None


def _check_secrets(name: str, service: Mapping[str, object]) -> Iterator[str]:
    for key, value in _env_pairs(service.get("environment")):
        if not SECRET_NAME.search(key) or not value:
            continue
        if "${" not in value:
            yield f"{name}: environment {key} looks like a secret with a literal value"
        elif any(m.group(1).strip() for m in VAR_DEFAULT.finditer(value)):
            yield f"{name}: environment {key} is a secret with a literal default in {value!r}"


def check_compose(data: Mapping[str, object]) -> list[str]:
    """Return the rule violations of one parsed compose document.

    Args:
        data: The parsed YAML mapping (``services:`` at the top level).

    Returns:
        One message per violation, prefixed with the service name; empty when clean.

    Examples:
        >>> svc = {"image": "x", "healthcheck": {"test": ["CMD", "true"]}}
        >>> check_compose({"services": {"a": svc}})
        ['a: image not pinned by digest']
    """
    services = data.get("services")
    if not isinstance(services, Mapping):
        return []
    problems: list[str] = []
    for name, service in services.items():
        if not isinstance(service, Mapping):
            continue
        for check in (_check_image, _check_ports, _check_healthcheck, _check_secrets):
            problems.extend(check(str(name), service))
    return problems


def check_file(path: Path) -> list[str]:
    """Parse ``path`` and return its violations (see :func:`check_compose`).

    Args:
        path: A compose YAML file.

    Returns:
        The violations; empty when clean.

    Raises:
        OSError: if the file cannot be read.
        yaml.YAMLError: if it is not valid YAML.
    """
    text = path.read_text(encoding="utf-8")
    loader = _ComposeLoader(text)
    try:
        data = loader.get_single_data()
    finally:
        loader.dispose()
    return check_compose(data) if isinstance(data, Mapping) else []


def _default_files() -> list[Path]:
    files = [REPO / "docker-compose.yml", *sorted((REPO / "infra").glob("**/compose*.yml"))]
    return [f for f in files if f.is_file()]


def main(argv: Sequence[str] | None = None) -> int:
    """Check the given compose files (default: the repo's) and print findings.

    Args:
        argv: File paths; ``None`` reads ``sys.argv``.

    Returns:
        0 when clean, 1 when any file has findings.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    files = [Path(a) for a in args] or _default_files()
    failed = False
    for path in files:
        for problem in check_file(path):
            print(f"{path}: {problem}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
