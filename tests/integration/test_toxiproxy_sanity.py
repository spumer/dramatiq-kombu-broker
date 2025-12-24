"""Infrastructure validation tests for Toxiproxy integration.

Tests verify that Toxiproxy infrastructure is working correctly before
running deadlock tests. All tests are marked as integration tests.
"""

import pytest
from dramatiq import Message
from testing.toxiproxy_client import ToxiproxyClient


@pytest.mark.integration
def test_toxiproxy_connection(toxiproxy_client: ToxiproxyClient):
    """Verify Toxiproxy server is accessible and responding.

    This test validates basic connectivity to Toxiproxy API.
    """
    # Act
    version = toxiproxy_client.version()

    # Assert
    assert isinstance(version, dict), "Version should be a dictionary"
    assert version, "Version should not be empty"


@pytest.mark.integration
def test_rabbitmq_proxy_creation(rabbitmq_proxy):
    """Verify RabbitMQ proxy exists with correct configuration.

    The proxy should be configured to listen on port 35672
    and forward to RabbitMQ on port 5672.
    """
    # Assert
    assert rabbitmq_proxy.name == "rabbitmq_integration"
    # Toxiproxy may return IPv4 (0.0.0.0:35672) or IPv6 ([::]:35672) format
    assert rabbitmq_proxy.listen.endswith(":35672"), (
        f"Expected port 35672, got {rabbitmq_proxy.listen}"
    )
    assert rabbitmq_proxy.upstream == "rabbitmq:5672"
    assert rabbitmq_proxy.enabled is True


@pytest.mark.integration
def test_toxic_lifecycle(rabbitmq_proxy, clean_toxics):
    """Verify toxics can be added and removed successfully.

    Tests the fundamental toxic management operations:
    - Adding a timeout toxic
    - Verifying toxic is in proxy's toxic list
    - Removing toxic
    - Verifying toxic is no longer in proxy's toxic list
    """
    # Act: Add toxic
    toxic = rabbitmq_proxy.add_toxic(
        name="test_timeout",
        toxic_type="timeout",
        attributes={"timeout": 100},
    )

    # Assert: Toxic added
    toxic_names = [t.name for t in rabbitmq_proxy.toxics]
    assert "test_timeout" in toxic_names, "Toxic should be in proxy's toxic list"

    # Act: Remove toxic
    toxic.remove()

    # Assert: Toxic removed
    toxic_names_after = [t.name for t in rabbitmq_proxy.toxics]
    assert "test_timeout" not in toxic_names_after, (
        "Toxic should be removed from proxy's toxic list"
    )


@pytest.mark.integration
def test_rabbitmq_connection_through_proxy(
    broker_with_confirm_timeout,
    test_queue_name,
    clean_toxics,
):
    """Verify broker can connect to RabbitMQ through Toxiproxy.

    This test validates that basic RabbitMQ operations work
    when connecting through the Toxiproxy proxy.
    """
    # Arrange
    queue_name = test_queue_name
    message = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "data"},
        options={},
    )

    # Act: Declare queue
    broker_with_confirm_timeout.declare_queue(queue_name)

    # Act: Publish message
    broker_with_confirm_timeout.enqueue(message)

    # Assert: No exceptions raised means success
    # (message successfully published through proxy)
