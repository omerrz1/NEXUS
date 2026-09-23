"""Pytest configuration and global security fixtures for Nexus."""

import socket
from collections.abc import Generator

import pytest


class NetworkGuardError(RuntimeError):
    """Raised when non-loopback network egress is attempted."""


def _is_loopback(host: str) -> bool:
    """Check if a host string resolves to a loopback address or unix socket."""
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        addrinfo = socket.getaddrinfo(host, None)
        for _, _, _, _, sockaddr in addrinfo:
            ip = str(sockaddr[0])
            if not (ip.startswith("127.") or ip == "::1"):
                return False
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def guard_network_egress(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Intercept socket.socket.connect and block any non-loopback network calls."""
    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: tuple[str, int] | str | bytes) -> None:
        if isinstance(address, tuple):
            host = address[0]
            if not _is_loopback(host):
                raise NetworkGuardError(f"Outbound network access blocked to {host}:{address[1]}.")
        real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    yield
