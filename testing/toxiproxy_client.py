"""Minimal Toxiproxy HTTP client for fault injection.

Provides:
- ToxiproxyClient: HTTP client for Toxiproxy API
- Proxy, Toxic: Data classes for proxy/toxic management
- NetworkFailure: Context managers for simulating network failures
- toxic_* functions: Convenience functions for common toxic patterns

Uses only stdlib - no external dependencies.

Usage:
    client = ToxiproxyClient()
    proxy = client.create_proxy("rabbitmq", listen="0.0.0.0:5672", upstream="rabbitmq:5672")
    toxic = proxy.add_toxic("latency", "latency", attributes={"latency": 1000})
    toxic.remove()
    proxy.destroy()
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

# ====================
# Exceptions
# ====================


class ToxiproxyError(Exception):
    """Base exception for Toxiproxy errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ToxiproxyConnectionError(ToxiproxyError):
    """Cannot connect to Toxiproxy server."""


class ToxiproxyAPIError(ToxiproxyError):
    """Toxiproxy API returned an error."""


# ====================
# Data Classes
# ====================


@dataclass
class Toxic:
    """Represents a Toxiproxy toxic."""

    name: str
    type: str
    stream: str  # "upstream" or "downstream"
    toxicity: float
    attributes: dict[str, Any]
    proxy_name: str
    client: ToxiproxyClient

    def update(self, **attributes: Any) -> None:
        """Update toxic attributes."""
        self.client._request(
            "PATCH",
            f"/proxies/{self.proxy_name}/toxics/{self.name}",
            {"attributes": attributes},
        )
        self.attributes.update(attributes)

    def remove(self) -> None:
        """Remove this toxic."""
        self.client._request("DELETE", f"/proxies/{self.proxy_name}/toxics/{self.name}")
        # Update local proxy toxics list
        if self.proxy_name in self.client._proxies:
            proxy = self.client._proxies[self.proxy_name]
            proxy.toxics = [t for t in proxy.toxics if t.name != self.name]


@dataclass
class Proxy:
    """Represents a Toxiproxy proxy."""

    name: str
    listen: str
    upstream: str
    enabled: bool
    client: ToxiproxyClient
    toxics: list[Toxic] = field(default_factory=list)

    def add_toxic(
        self,
        name: str,
        toxic_type: str,
        *,
        stream: str = "downstream",
        toxicity: float = 1.0,
        attributes: dict[str, Any] | None = None,
    ) -> Toxic:
        """Add a toxic to this proxy.

        Args:
            name: Unique name for this toxic
            toxic_type: Type of toxic. Options:
                - latency: Add latency (attributes: latency, jitter)
                - timeout: Stop all data and close after timeout (attributes: timeout)
                - reset_peer: Simulate TCP RST (attributes: timeout)
                - slow_close: Delay close (attributes: delay)
                - bandwidth: Limit bandwidth (attributes: rate)
                - slicer: Slice data into bits (attributes: average_size, size_variation, delay)
                - limit_data: Limit data then close (attributes: bytes)
            stream: "downstream" (server->client) or "upstream" (client->server)
            toxicity: Probability 0.0-1.0 of toxic being applied
            attributes: Toxic-specific attributes

        Returns
        -------
            Toxic instance
        """
        data = {
            "name": name,
            "type": toxic_type,
            "stream": stream,
            "toxicity": toxicity,
            "attributes": attributes or {},
        }
        response = self.client._request("POST", f"/proxies/{self.name}/toxics", data)
        toxic = Toxic(
            name=response["name"],
            type=response["type"],
            stream=response["stream"],
            toxicity=response["toxicity"],
            attributes=response["attributes"],
            proxy_name=self.name,
            client=self.client,
        )
        self.toxics.append(toxic)
        return toxic

    def remove_toxic(self, name: str) -> None:
        """Remove a toxic by name."""
        self.client._request("DELETE", f"/proxies/{self.name}/toxics/{name}")
        self.toxics = [t for t in self.toxics if t.name != name]

    def remove_all_toxics(self) -> None:
        """Remove all toxics from this proxy."""
        for toxic in list(self.toxics):
            self.remove_toxic(toxic.name)

    def enable(self) -> None:
        """Enable this proxy."""
        self.client._request("POST", f"/proxies/{self.name}", {"enabled": True})
        self.enabled = True

    def disable(self) -> None:
        """Disable this proxy (all connections fail immediately)."""
        self.client._request("POST", f"/proxies/{self.name}", {"enabled": False})
        self.enabled = False

    def destroy(self) -> None:
        """Delete this proxy."""
        self.client._request("DELETE", f"/proxies/{self.name}")


# ====================
# Client
# ====================


class ToxiproxyClient:
    """Minimal Toxiproxy HTTP client.

    Uses only stdlib urllib - no external dependencies.

    Usage:
        client = ToxiproxyClient()
        proxy = client.create_proxy("rabbitmq", listen="0.0.0.0:5672", upstream="rabbitmq:5672")
        toxic = proxy.add_toxic("latency", "latency", attributes={"latency": 1000})
        toxic.remove()
        proxy.destroy()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8474) -> None:
        """Initialize client.

        Args:
            host: Toxiproxy server host
            port: Toxiproxy server port (default 8474)
        """
        self.base_url = f"http://{host}:{port}"
        self._proxies: dict[str, Proxy] = {}

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Make HTTP request to Toxiproxy API."""
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}

        body = json.dumps(data).encode() if data else None

        request = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 204:  # No Content
                    return {}
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise ToxiproxyAPIError(
                f"{method} {path} failed: {e.code} {e.reason}: {error_body}",
                status_code=e.code,
            ) from e
        except urllib.error.URLError as e:
            raise ToxiproxyConnectionError(
                f"Cannot connect to Toxiproxy at {self.base_url}: {e.reason}"
            ) from e

    def version(self) -> dict[str, str]:
        """Get Toxiproxy server version."""
        return self._request("GET", "/version")

    def reset(self) -> None:
        """Reset all proxies: enable all and remove all toxics."""
        self._request("POST", "/reset")
        for proxy in self._proxies.values():
            proxy.enabled = True
            proxy.toxics.clear()

    def list_proxies(self) -> dict[str, Proxy]:
        """List all proxies."""
        response = self._request("GET", "/proxies")
        proxies = {}
        for name, data in response.items():
            proxy = Proxy(
                name=data["name"],
                listen=data["listen"],
                upstream=data["upstream"],
                enabled=data["enabled"],
                client=self,
            )
            proxies[name] = proxy
        self._proxies = proxies
        return proxies

    def get_proxy(self, name: str) -> Proxy:
        """Get a proxy by name."""
        data = self._request("GET", f"/proxies/{name}")
        proxy = Proxy(
            name=data["name"],
            listen=data["listen"],
            upstream=data["upstream"],
            enabled=data["enabled"],
            client=self,
        )
        self._proxies[name] = proxy
        return proxy

    def create_proxy(
        self,
        name: str,
        listen: str,
        upstream: str,
        *,
        enabled: bool = True,
    ) -> Proxy:
        """Create a new proxy.

        Args:
            name: Unique proxy name
            listen: Address to listen on (e.g., "0.0.0.0:15672")
            upstream: Address to proxy to (e.g., "rabbitmq:5672")
            enabled: Whether proxy is enabled

        Returns
        -------
            Proxy instance
        """
        data = {
            "name": name,
            "listen": listen,
            "upstream": upstream,
            "enabled": enabled,
        }
        response = self._request("POST", "/proxies", data)
        proxy = Proxy(
            name=response["name"],
            listen=response["listen"],
            upstream=response["upstream"],
            enabled=response["enabled"],
            client=self,
        )
        self._proxies[name] = proxy
        return proxy

    def get_or_create_proxy(
        self,
        name: str,
        listen: str,
        upstream: str,
    ) -> Proxy:
        """Get existing proxy or create new one."""
        try:
            return self.get_proxy(name)
        except ToxiproxyAPIError as e:
            if e.status_code == 404:
                return self.create_proxy(name, listen, upstream)
            raise

    def destroy_proxy(self, name: str) -> None:
        """Delete a proxy."""
        self._request("DELETE", f"/proxies/{name}")
        self._proxies.pop(name, None)

    def populate(self, proxies: list[dict[str, Any]]) -> list[Proxy]:
        """Create or replace multiple proxies at once.

        Args:
            proxies: List of proxy configs with name, listen, upstream keys

        Returns
        -------
            List of Proxy instances
        """
        response = self._request("POST", "/populate", proxies)
        result = []
        for data in response.get("proxies", []):
            proxy = Proxy(
                name=data["name"],
                listen=data["listen"],
                upstream=data["upstream"],
                enabled=data["enabled"],
                client=self,
            )
            self._proxies[data["name"]] = proxy
            result.append(proxy)
        return result


# ====================
# Toxic Helper Functions
# ====================


def toxic_latency(proxy: Proxy, latency_ms: int, jitter_ms: int = 0) -> Toxic:
    """Add latency toxic (delays all data)."""
    return proxy.add_toxic(
        name="latency",
        toxic_type="latency",
        attributes={"latency": latency_ms, "jitter": jitter_ms},
    )


def toxic_timeout(proxy: Proxy, timeout_ms: int = 0) -> Toxic:
    """Add timeout toxic (stops data, closes after timeout)."""
    return proxy.add_toxic(
        name="timeout",
        toxic_type="timeout",
        attributes={"timeout": timeout_ms},
    )


def toxic_reset_peer(proxy: Proxy, timeout_ms: int = 0) -> Toxic:
    """Add reset_peer toxic (simulates TCP RST - connection reset)."""
    return proxy.add_toxic(
        name="reset_peer",
        toxic_type="reset_peer",
        attributes={"timeout": timeout_ms},
    )


def toxic_slow_close(proxy: Proxy, delay_ms: int) -> Toxic:
    """Add slow_close toxic (delays connection close)."""
    return proxy.add_toxic(
        name="slow_close",
        toxic_type="slow_close",
        attributes={"delay": delay_ms},
    )


def toxic_bandwidth(proxy: Proxy, rate_kb: int) -> Toxic:
    """Add bandwidth toxic (limits to rate KB/s)."""
    return proxy.add_toxic(
        name="bandwidth",
        toxic_type="bandwidth",
        attributes={"rate": rate_kb},
    )


# ====================
# Network Failure Helper
# ====================


class NetworkFailure:
    """Context managers for simulating network failures."""

    def __init__(self, proxy: Proxy):
        self.proxy = proxy

    @contextmanager
    def reset_peer(self, timeout_ms: int = 0):
        """Simulate TCP RST (connection reset by peer)."""
        toxic = toxic_reset_peer(self.proxy, timeout_ms)
        try:
            yield
        finally:
            toxic.remove()

    @contextmanager
    def timeout(self, timeout_ms: int = 0):
        """Stop all data, close connection after timeout."""
        toxic = toxic_timeout(self.proxy, timeout_ms)
        try:
            yield
        finally:
            toxic.remove()

    @contextmanager
    def latency(self, latency_ms: int, jitter_ms: int = 0):
        """Add latency to all data."""
        toxic = toxic_latency(self.proxy, latency_ms, jitter_ms)
        try:
            yield
        finally:
            toxic.remove()

    @contextmanager
    def bandwidth(self, rate_kb: int):
        """Limit bandwidth to rate KB/s."""
        toxic = toxic_bandwidth(self.proxy, rate_kb)
        try:
            yield
        finally:
            toxic.remove()

    @contextmanager
    def disable(self):
        """Completely disable proxy (immediate failure)."""
        self.proxy.disable()
        try:
            yield
        finally:
            self.proxy.enable()
