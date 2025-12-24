"""Tests for max_delay_time feature in broker validation."""

import datetime as dt

import dramatiq
import kombu
import pytest
from dramatiq_kombu_broker import DefaultDramatiqTopology, DelayTooLongError


@pytest.fixture
def channel_factory(kombu_broker):
    """Factory for creating channels."""

    def _inner():
        return kombu_broker.connection_holder.acquire_consumer_channel()

    return _inner


@pytest.fixture
def queue_name(request, kombu_broker):
    """Generate unique queue name and cleanup after test."""
    queue_name = request.node.name
    yield queue_name
    kombu_broker.delete_queue(queue_name)


def test_enqueue_delay_within_limit(kombu_broker):
    """Test that enqueue succeeds when delay is within max_delay_time limit."""
    # Create topology with max_delay_time
    topology = DefaultDramatiqTopology(max_delay_time=dt.timedelta(hours=1))
    kombu_broker.topology = topology

    @dramatiq.actor
    def test_actor():
        pass

    kombu_broker.declare_actor(test_actor)

    # Enqueue with delay under limit (10 seconds < 1 hour)
    message = test_actor.message()
    delay_ms = 10 * 1000  # 10 seconds in ms

    # Should NOT raise
    result = kombu_broker.enqueue(message, delay=delay_ms)
    assert result is not None


def test_enqueue_delay_exceeds_limit(kombu_broker):
    """Test that enqueue raises DelayTooLongError when delay exceeds max_delay_time."""
    # Create topology with max_delay_time = 10 seconds
    topology = DefaultDramatiqTopology(max_delay_time=dt.timedelta(seconds=10))
    kombu_broker.topology = topology

    @dramatiq.actor
    def test_actor():
        pass

    kombu_broker.declare_actor(test_actor)

    # Enqueue with delay over limit (20 seconds > 10 seconds)
    message = test_actor.message()
    delay_ms = 20 * 1000  # 20 seconds in ms

    # Should raise DelayTooLongError
    with pytest.raises(DelayTooLongError) as exc_info:
        kombu_broker.enqueue(message, delay=delay_ms)

    # Verify exception attributes
    exc = exc_info.value
    assert exc.delay == delay_ms
    assert exc.max_delay == 10 * 1000  # 10 seconds in ms
    assert exc.queue_name == message.queue_name


def test_enqueue_no_max_delay_time(kombu_broker):
    """Test backward compatibility: no max_delay_time means no validation."""
    # Default topology has max_delay_time=None
    topology = DefaultDramatiqTopology(max_delay_time=None)
    kombu_broker.topology = topology

    @dramatiq.actor
    def test_actor():
        pass

    kombu_broker.declare_actor(test_actor)

    # Enqueue with very large delay
    message = test_actor.message()
    delay_ms = 365 * 24 * 60 * 60 * 1000  # 1 year in ms

    # Should NOT raise (backward compatibility)
    result = kombu_broker.enqueue(message, delay=delay_ms)
    assert result is not None


def test_enqueue_no_delay_with_max_delay_time(kombu_broker):
    """Test that max_delay_time doesn't affect non-delayed messages."""
    # Create topology with max_delay_time
    topology = DefaultDramatiqTopology(max_delay_time=dt.timedelta(seconds=1))
    kombu_broker.topology = topology

    @dramatiq.actor
    def test_actor():
        pass

    kombu_broker.declare_actor(test_actor)

    # Enqueue WITHOUT delay
    message = test_actor.message()

    # Should NOT raise (validation only for delayed messages)
    result = kombu_broker.enqueue(message, delay=None)
    assert result is not None


def test_delay_queue_ttl_failsafe_integration(
    queue_name, channel_factory, kombu_broker, queue_reader_factory
):
    """Integration test: verify RabbitMQ queue TTL works as failsafe.

    When max_delay_time is configured, the delay queue should have x-message-ttl
    set. This test verifies that RabbitMQ enforces this TTL and routes messages
    to canonical queue via DLX after expiration.
    """
    # Create topology with max_delay_time = 1 second
    topology = DefaultDramatiqTopology(max_delay_time=dt.timedelta(seconds=1))
    kombu_broker.topology = topology

    # Declare queues
    kombu_broker.declare_queue(queue_name, ensure=True)
    q_names = topology.get_queue_name_tuple(queue_name)

    test_message_body = b"test_ttl_failsafe"

    with channel_factory() as channel:
        # Publish message to delay queue WITHOUT per-message TTL
        # (simulating a message that bypassed application validation)
        producer = kombu.Producer(channel)
        producer.publish(
            body=test_message_body,
            routing_key=q_names.delayed,
            exchange="",
            delivery_mode=2,
            # NO expiration here - relying on queue TTL
        )

        # Wait for queue TTL to expire message (1 second + buffer)
        canonical_reader = queue_reader_factory(channel, queue_name=q_names.canonical)
        msg = canonical_reader.pop(timeout=1.5)

        assert msg, (
            f"Message did not appear in canonical queue {q_names.canonical} "
            f"after queue TTL expiration"
        )
        assert msg.body == test_message_body
