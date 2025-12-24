"""Pytest configuration for integration tests.

Provides broker fixtures and test utilities for integration testing
with Toxiproxy fault injection.
"""

import uuid

import pytest
from dramatiq_kombu_broker import ConnectionSharedKombuBroker

# Import base RabbitMQ credentials from root conftest
from tests.conftest import rabbitmq_hostname, rabbitmq_password, rabbitmq_username

# Import all toxiproxy fixtures
from .fixtures_toxiproxy import (
    add_toxic_bandwidth,
    add_toxic_latency,
    add_toxic_reset_peer,
    add_toxic_timeout,
    clean_toxics,
    network_failure,
    rabbitmq_proxy,
    requires_toxiproxy,
    toxiproxy_client,
)

# Expose fixtures for pytest discovery
__all__ = [
    "add_toxic_bandwidth",
    "add_toxic_latency",
    "add_toxic_reset_peer",
    "add_toxic_timeout",
    "clean_toxics",
    "network_failure",
    "rabbitmq_hostname",
    "rabbitmq_password",
    "rabbitmq_proxy",
    "rabbitmq_username",
    "requires_toxiproxy",
    "toxiproxy_client",
]


@pytest.fixture(scope="session")
def proxied_rabbitmq_dsn(rabbitmq_username, rabbitmq_password, rabbitmq_hostname):
    """RabbitMQ DSN pointing to Toxiproxy (port 35672).

    Use this fixture for integration tests that require fault injection.
    Regular tests should use rabbitmq_dsn from root conftest (port 5672).
    """
    return f"amqp://{rabbitmq_username}:{rabbitmq_password}@{rabbitmq_hostname}:35672/"


@pytest.fixture
def broker_with_confirm_timeout(proxied_rabbitmq_dsn):
    """ConnectionSharedKombuBroker with confirm_timeout=5.0.

    This broker will timeout on publish operations after 5 seconds,
    preventing infinite blocking when RabbitMQ becomes unavailable.
    """
    broker = ConnectionSharedKombuBroker(
        kombu_connection_options={"hostname": proxied_rabbitmq_dsn},
        confirm_timeout=5.0,
    )
    yield broker
    broker.close()


@pytest.fixture
def broker_without_confirm_timeout(proxied_rabbitmq_dsn):
    """ConnectionSharedKombuBroker without confirm_timeout (None).

    This broker will block indefinitely on publish operations
    when RabbitMQ becomes unavailable. Used to reproduce deadlock scenario.
    """
    broker = ConnectionSharedKombuBroker(
        kombu_connection_options={"hostname": proxied_rabbitmq_dsn},
        confirm_timeout=None,
    )
    yield broker
    broker.close()


@pytest.fixture
def test_queue_name(request):
    """Generate unique queue name for each test.

    Prevents queue conflicts between parallel tests.
    Format: {test-name}{uuid4_hex}
    """
    return f"{request.node.name}_{uuid.uuid4().hex[-8:]}"
