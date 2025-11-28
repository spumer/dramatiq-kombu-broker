import dataclasses
import datetime as dt
import time

import amqp.exceptions
import kombu
import pytest
from dramatiq_kombu_broker.broker import ConnectionPooledKombuBroker
from dramatiq_kombu_broker.consumer import QueueReader
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology, DLXRoutingTopology


@pytest.fixture
def channel_factory(kombu_broker):
    def _inner():
        return kombu_broker.connection_holder.acquire_consumer_channel()

    return _inner


@pytest.fixture
def topology(kombu_broker):
    return kombu_broker.topology


@pytest.fixture
def queue_name(request, kombu_broker):
    queue_name = request.node.name
    yield queue_name
    kombu_broker.delete_queue(queue_name)


@pytest.fixture
def check_queue_exists(channel_factory):
    def _check_queue_exists(queue_name):
        with channel_factory() as channel:
            reader = QueueReader(channel, queue_name=queue_name)
            try:
                reader.check()
            except amqp.exceptions.NotFound:
                return False
            return True

    return _check_queue_exists


@pytest.fixture
def dlx_broker(kombu_broker):
    """Create a broker with DLXRoutingTopology for testing."""
    dlx_topology = DLXRoutingTopology(delay_queue_ttl=dt.timedelta(seconds=1))

    broker = ConnectionPooledKombuBroker(
        kombu_connection_options=kombu_broker.connection_holder.connection.as_uri(),
        topology=dlx_topology,
    )

    yield broker

    broker.close()


def test_ok(kombu_broker, check_queue_exists, queue_name, topology):
    q_names = topology.get_queue_name_tuple(queue_name)

    kombu_broker.declare_queue(queue_name)
    assert not check_queue_exists(q_names.canonical)
    assert not check_queue_exists(q_names.delayed)
    assert not check_queue_exists(q_names.dead_letter)

    kombu_broker.declare_queue(queue_name, ensure=True)
    assert q_names.canonical == queue_name

    assert check_queue_exists(q_names.canonical)
    assert check_queue_exists(q_names.delayed)
    assert check_queue_exists(q_names.dead_letter)


def test_empty_rabbit__dlq__ok(queue_name, topology, channel_factory):
    queue_name = topology.get_dead_letter_queue_name(queue_name)

    with channel_factory() as channel:
        topology.declare_dead_letter_queue(channel, queue_name)

        reader = QueueReader(channel, queue_name=queue_name)
        reader.check()


def test_empty_rabbit__delay_queue__ok(queue_name, topology, channel_factory):
    queue_name = topology.get_delay_queue_name(queue_name)

    with channel_factory() as channel:
        topology.declare_delay_queue(channel, queue_name)

    reader = QueueReader(channel, queue_name=queue_name)
    reader.check()


def test_empty_rabbit__canonical_queue__ok(queue_name, topology, channel_factory):
    queue_name = topology.get_canonical_queue_name(queue_name)

    with channel_factory() as channel:
        topology.declare_canonical_queue(channel, queue_name)

    reader = QueueReader(channel, queue_name=queue_name)
    reader.check()


def test_invalid_arg_value__error(queue_name, channel_factory, check_queue_exists):
    """Ensure ignore_different_topology=True do not skip PRECONDITION_FAILED
    when queue does not exists. Only inequivalent
    """

    @dataclasses.dataclass
    class InvalidTopology(DefaultDramatiqTopology):
        def _get_dead_letter_queue_arguments(self, queue_name):
            return {"x-message-ttl": 0.1}

    assert not check_queue_exists(queue_name)

    invalid_topology = InvalidTopology()
    queue_name = invalid_topology.get_dead_letter_queue_name(queue_name)

    with channel_factory() as channel:
        with pytest.raises(
            amqp.exceptions.PreconditionFailed, match=r".*?invalid arg 'x-message-ttl'.*?"
        ):
            invalid_topology.declare_dead_letter_queue(channel, queue_name)


def test_delay_queue_has_dead_letter_parameters(queue_name, channel_factory):
    """Test that delay queues have x-dead-letter-exchange and x-dead-letter-routing-key.

    This is required for delayed message delivery to work properly. When a message
    expires in the delay queue (after its TTL), it should be routed to the canonical
    queue via the dead-letter mechanism.

    Addresses issues #6 and #7.
    """
    # Create topology without max_priority to avoid conditional
    topology = DefaultDramatiqTopology()
    canonical_queue_name = topology.get_canonical_queue_name(queue_name)
    delay_queue_name = topology.get_delay_queue_name(queue_name)

    # Declare the delay queue
    with channel_factory() as channel:
        topology.declare_delay_queue(channel, delay_queue_name)

        # Expected arguments for delay queue
        expected_args = {
            "x-dead-letter-exchange": topology.dlx_exchange_name,
            "x-dead-letter-routing-key": canonical_queue_name,
        }

        # Try to redeclare with expected arguments - should succeed if current matches
        queue = kombu.Queue(
            delay_queue_name,
            channel=channel,
            durable=topology.durable,
            auto_delete=topology.auto_delete,
            queue_arguments=expected_args,
        )
        # This will raise PreconditionFailed if arguments don't match
        queue.declare()


def test_delay_queue_arguments_method():
    """Test that _get_delay_queue_arguments returns dead-letter parameters.

    This is a unit test for the internal method that builds delay queue arguments.
    Addresses issues #6 and #7.
    """
    # Create topology without needing a broker
    topology = DefaultDramatiqTopology()
    queue_name = "test_queue"

    canonical_queue_name = topology.get_canonical_queue_name(queue_name)
    delay_args = topology._get_delay_queue_arguments(queue_name)

    # Delay queue must have dead-letter parameters to route expired messages
    # to the canonical queue
    assert "x-dead-letter-exchange" in delay_args
    assert delay_args["x-dead-letter-exchange"] == topology.dlx_exchange_name

    assert "x-dead-letter-routing-key" in delay_args
    assert delay_args["x-dead-letter-routing-key"] == canonical_queue_name


def test_delay_queue_arguments_without_max_priority():
    """Verify delay queue arguments omit x-max-priority when max_priority is None."""
    topology = DefaultDramatiqTopology(max_priority=None)
    queue_name = "test_queue"

    delay_args = topology._get_delay_queue_arguments(queue_name)

    assert "x-max-priority" not in delay_args


@pytest.mark.parametrize("max_priority", [5, 10, 255])
def test_delay_queue_arguments_with_max_priority(max_priority):
    """Verify delay queue arguments include x-max-priority when max_priority is configured.

    Ensures explicit coverage for the priority-specific behavior and prevents silent regressions.
    """
    topology = DefaultDramatiqTopology(max_priority=max_priority)
    queue_name = "test_queue"

    delay_args = topology._get_delay_queue_arguments(queue_name)

    assert "x-max-priority" in delay_args
    assert delay_args["x-max-priority"] == max_priority


def test_delay_queue_message_routing_integration(
    queue_name, topology, channel_factory, kombu_broker
):
    """Integration test: verify messages expire in delay queue and route to canonical queue.

    This test verifies the complete delayed message flow:
    1. Declare all queues (canonical, delay, dead-letter)
    2. Publish message to delay queue with short TTL
    3. Verify message appears in delay queue
    4. Wait for TTL to expire
    5. Verify message gets routed to canonical queue via dead-letter mechanism

    This confirms that issues #6 and #7 are properly fixed.
    """
    # Ensure all queues are declared
    kombu_broker.declare_queue(queue_name, ensure=True)

    canonical_queue_name = topology.get_canonical_queue_name(queue_name)
    delay_queue_name = topology.get_delay_queue_name(queue_name)

    # Publish a test message to the delay queue with a short TTL (100ms)
    test_message_body = b"test_delayed_message"
    with channel_factory() as channel:
        # Publish to delay queue with expiration
        producer = kombu.Producer(channel)
        producer.publish(
            body=test_message_body,
            routing_key=delay_queue_name,
            exchange="",
            delivery_mode=2,
            expiration="100",  # 100ms TTL
        )

        # Give it a moment to be published
        time.sleep(0.05)

        # Verify message is in delay queue
        delay_queue_info = channel.queue_declare(queue=delay_queue_name, passive=True)
        assert delay_queue_info[1] > 0, "Message should be in delay queue"

        # Wait for message to expire and be routed to canonical queue
        # Add some buffer time for processing
        time.sleep(0.2)

        # Verify message was routed to canonical queue
        canonical_queue_info = channel.queue_declare(queue=canonical_queue_name, passive=True)
        assert canonical_queue_info[1] > 0, "Expired message should be in canonical queue"

        # Consume the message to verify it's the correct one
        method, properties, body = channel.basic_get(queue=canonical_queue_name)
        assert body == test_message_body, "Message body should match original"
        assert method is not None, "Should have received a message"

        # Acknowledge the message
        channel.basic_ack(method.delivery_tag)

        # Verify delay queue is now empty
        delay_queue_info = channel.queue_declare(queue=delay_queue_name, passive=True)
        assert delay_queue_info[1] == 0, "Delay queue should be empty after expiration"


def test_delay_queue_migration_compatibility(queue_name, topology, channel_factory):
    """Integration test: verify compatibility with standard dramatiq RabbitMQ broker topology.

    This test simulates the migration scenario from issue #6 where queues were
    declared by standard dramatiq broker and then need to be compatible with
    Kombu broker.

    The test verifies that redeclaring a delay queue with the correct parameters
    succeeds (no PreconditionFailed error).
    """
    delay_queue_name = topology.get_delay_queue_name(queue_name)
    canonical_queue_name = topology.get_canonical_queue_name(queue_name)

    with channel_factory() as channel:
        # First, declare the delay queue with our topology
        topology.declare_delay_queue(channel, delay_queue_name)

        # Now try to redeclare it with the same parameters
        # This should succeed if parameters are correct
        # (simulates what happens during migration)
        expected_args = {
            "x-dead-letter-exchange": topology.dlx_exchange_name,
            "x-dead-letter-routing-key": canonical_queue_name,
        }

        if topology.max_priority:
            expected_args["x-max-priority"] = topology.max_priority

        # This should NOT raise PreconditionFailed
        queue = kombu.Queue(
            delay_queue_name,
            channel=channel,
            durable=topology.durable,
            auto_delete=topology.auto_delete,
            queue_arguments=expected_args,
        )
        queue.declare()  # Should succeed

        # Verify we can also declare with topology method again
        topology.declare_delay_queue(channel, delay_queue_name)  # Should succeed


def test_dlx_routing_topology_configuration():
    """Test that DLXRoutingTopology routes delay queue to DLX instead of canonical queue.

    This tests the alternative topology for users who need delayed messages
    to route through the dead letter queue for monitoring or custom processing.
    """
    import datetime as dt

    topology = DLXRoutingTopology(delay_queue_ttl=dt.timedelta(hours=3))
    queue_name = "test_queue"

    canonical_queue_name = topology.get_canonical_queue_name(queue_name)
    dlx_queue_name = topology.get_dead_letter_queue_name(canonical_queue_name)
    delay_args = topology._get_delay_queue_arguments(queue_name)

    # Delay queue should route to DLX, not canonical queue
    assert "x-dead-letter-exchange" in delay_args
    assert delay_args["x-dead-letter-exchange"] == topology.dlx_exchange_name

    assert "x-dead-letter-routing-key" in delay_args
    assert delay_args["x-dead-letter-routing-key"] == dlx_queue_name  # Routes to DLX!

    # Should have the configured TTL
    assert "x-message-ttl" in delay_args
    assert delay_args["x-message-ttl"] == 3 * 60 * 60 * 1000  # 3 hours in ms


def test_dlx_routing_topology_integration(queue_name, channel_factory, dlx_broker):
    """Integration test: verify DLXRoutingTopology routes through DLX.

    This test verifies that with DLXRoutingTopology, expired messages from
    the delay queue go to the dead letter queue (not directly to canonical queue).
    """
    # Ensure all queues are declared
    dlx_broker.declare_queue(queue_name, ensure=True)

    dlx_topology = dlx_broker.topology
    canonical_queue_name = dlx_topology.get_canonical_queue_name(queue_name)
    delay_queue_name = dlx_topology.get_delay_queue_name(queue_name)
    dlx_queue_name = dlx_topology.get_dead_letter_queue_name(canonical_queue_name)

    # Publish a test message to the delay queue with short TTL
    test_message_body = b"test_dlx_routing"
    with channel_factory() as channel:
        producer = kombu.Producer(channel)
        producer.publish(
            body=test_message_body,
            routing_key=delay_queue_name,
            exchange="",
            delivery_mode=2,
            expiration="100",  # 100ms TTL
        )

        time.sleep(0.05)

        # Verify message is in delay queue
        delay_info = channel.queue_declare(queue=delay_queue_name, passive=True)
        assert delay_info[1] > 0, "Message should be in delay queue"

        # Wait for expiration
        time.sleep(0.2)

        # With DLXRoutingTopology, message should go to DLX, not canonical queue
        dlx_info = channel.queue_declare(queue=dlx_queue_name, passive=True)
        assert dlx_info[1] > 0, "Expired message should be in DLX queue"

        # Canonical queue should be empty (different from default behavior!)
        canonical_info = channel.queue_declare(queue=canonical_queue_name, passive=True)
        assert canonical_info[1] == 0, "Canonical queue should be empty with DLXRoutingTopology"

        # Clean up - consume from DLX
        method, properties, body = channel.basic_get(queue=dlx_queue_name)
        assert body == test_message_body
        channel.basic_ack(method.delivery_tag)
