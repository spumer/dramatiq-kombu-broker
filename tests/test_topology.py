import dataclasses

import amqp.exceptions
import pytest
from dramatiq_kombu_broker.consumer import QueueReader
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology


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


def test_delay_queue_has_dead_letter_parameters(queue_name, topology, channel_factory):
    """Test that delay queues have x-dead-letter-exchange and x-dead-letter-routing-key.

    This is required for delayed message delivery to work properly. When a message
    expires in the delay queue (after its TTL), it should be routed to the canonical
    queue via the dead-letter mechanism.

    Addresses issues #6 and #7.
    """
    canonical_queue_name = topology.get_canonical_queue_name(queue_name)
    delay_queue_name = topology.get_delay_queue_name(queue_name)

    # Declare the delay queue
    with channel_factory() as channel:
        topology.declare_delay_queue(channel, delay_queue_name)

        # Get queue info to inspect arguments
        # Using passive=True to just query without redeclaring
        name, message_count, consumer_count = channel.queue_declare(
            queue=delay_queue_name, passive=True
        )

        # Access the queue object to get arguments
        # We need to use the channel's basic_get or inspect via management API
        # Actually, we can check by trying to redeclare with the expected arguments
        # and it should succeed if they match

        # Expected arguments for delay queue
        expected_args = {
            "x-dead-letter-exchange": topology.dlx_exchange_name,
            "x-dead-letter-routing-key": canonical_queue_name,
        }

        if topology.max_priority:
            expected_args["x-max-priority"] = topology.max_priority

        # Try to redeclare with expected arguments - should succeed if current matches
        import kombu
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
