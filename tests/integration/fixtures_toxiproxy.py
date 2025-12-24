"""Pytest fixtures for Toxiproxy integration testing.

Adapted from kombu-pyamqp-threadsafe for dramatiq-kombu-broker.
Provides fixtures for fault injection testing using Toxiproxy.
"""

import os

import pytest
from testing.toxiproxy_client import (
    NetworkFailure,
    Toxic,
    ToxiproxyClient,
    ToxiproxyConnectionError,
    toxic_bandwidth,
    toxic_latency,
    toxic_reset_peer,
    toxic_timeout,
)

# ====================
# Pytest Fixtures
# ====================


@pytest.fixture(scope="session")
def requires_toxiproxy():
    """Skip test if Toxiproxy is not available.

    Usage: add `requires_toxiproxy` to test function arguments.
    """
    host = os.getenv("TOXIPROXY_HOST", "127.0.0.1")
    port = int(os.getenv("TOXIPROXY_PORT", "8474"))

    client = ToxiproxyClient(host=host, port=port)
    try:
        client.version()
    except ToxiproxyConnectionError:
        pytest.skip(
            "Toxiproxy not available (run: docker compose -f docker-compose.test.yml up -d)"
        )


@pytest.fixture(scope="session")
def toxiproxy_client(requires_toxiproxy):
    """Toxiproxy client for fault injection.

    Requires Toxiproxy server running on localhost:8474.
    Start with: docker compose -f docker-compose.test.yml up -d
    """
    host = os.getenv("TOXIPROXY_HOST", "127.0.0.1")
    port = int(os.getenv("TOXIPROXY_PORT", "8474"))

    return ToxiproxyClient(host=host, port=port)


@pytest.fixture(scope="session")
def rabbitmq_proxy(toxiproxy_client):
    """Get or create RabbitMQ proxy for integration tests on port 35672.

    Uses separate port to avoid conflicts with regular tests.
    Port 35672 must be exposed in docker-compose.test.yml.
    """
    proxy = toxiproxy_client.get_or_create_proxy(
        name="rabbitmq_integration",
        listen="0.0.0.0:35672",
        upstream="rabbitmq:5672",
    )
    yield proxy
    # Cleanup on session end
    proxy.remove_all_toxics()


@pytest.fixture
def clean_toxics(rabbitmq_proxy):
    """Ensure proxy has no toxics before and after test."""
    rabbitmq_proxy.remove_all_toxics()
    yield rabbitmq_proxy
    rabbitmq_proxy.remove_all_toxics()


@pytest.fixture
def network_failure(rabbitmq_proxy):
    """Context manager for simulating network failures.

    Usage:
        with network_failure.reset_peer():
            # Connection will be reset
            ...

        with network_failure.timeout(5000):
            # No data for 5 seconds
            ...

        with network_failure.latency(1000, jitter=500):
            # 1000ms +/- 500ms latency
            ...
    """
    return NetworkFailure(rabbitmq_proxy)


@pytest.fixture
def add_toxic_latency(rabbitmq_proxy):
    """Factory for adding latency toxic.

    Usage:
        toxic = add_toxic_latency(100, jitter_ms=50)
        # ... do something
        toxic.remove()
    """

    def _add(latency_ms: int, jitter_ms: int = 0) -> Toxic:
        return toxic_latency(rabbitmq_proxy, latency_ms, jitter_ms)

    return _add


@pytest.fixture
def add_toxic_timeout(rabbitmq_proxy):
    """Factory for adding timeout toxic."""

    def _add(timeout_ms: int = 0) -> Toxic:
        return toxic_timeout(rabbitmq_proxy, timeout_ms)

    return _add


@pytest.fixture
def add_toxic_reset_peer(rabbitmq_proxy):
    """Factory for adding reset_peer toxic."""

    def _add(timeout_ms: int = 0) -> Toxic:
        return toxic_reset_peer(rabbitmq_proxy, timeout_ms)

    return _add


@pytest.fixture
def add_toxic_bandwidth(rabbitmq_proxy):
    """Factory for adding bandwidth toxic."""

    def _add(rate_kb: int) -> Toxic:
        return toxic_bandwidth(rabbitmq_proxy, rate_kb)

    return _add
