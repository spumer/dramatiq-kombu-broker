import dataclasses

import amqp.exceptions
import pytest
from dramatiq_kombu_broker.consumer import QueueReader
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology


@pytest.fixture()
def channel_factory(kombu_broker):
    def _inner():
        return kombu_broker.connection_holder.acquire_consumer_channel()

    return _inner


@pytest.fixture()
def topology(kombu_broker):
    return kombu_broker.topology


@pytest.fixture()
def queue_name(request, kombu_broker):
    queue_name = request.node.name
    yield queue_name
    kombu_broker.delete_queue(queue_name)


@pytest.fixture()
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
