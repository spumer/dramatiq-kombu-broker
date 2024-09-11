import pytest
from dramatiq_kombu_broker.consumer import QueueReader


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
