import contextlib

import dramatiq
import kombu
import kombu.resource
from kombu.utils.functional import lazy

from . import ConnectionPooledKombuBroker, ConnectionSharedKombuBroker
from .topology import RabbitMQTopology


def get_kombu_resource_objects(resource: kombu.resource.Resource) -> list:
    return list(resource._dirty) + [r for r in resource._resource.queue if not isinstance(r, lazy)]


def ensure_consumer_connection_rabbitmq(broker):
    with broker.connection_holder.acquire_consumer_channel() as channel:
        assert channel.connection.connected


def ensure_producer_conneciton_rabbitmq(broker):
    with broker.connection_holder.acquire_producer() as producer:
        assert producer.connection.connected


def get_consumer_connections(broker):
    if isinstance(broker, ConnectionSharedKombuBroker):
        return [broker.connection_holder._consumer_connection]

    if isinstance(broker, ConnectionPooledKombuBroker):
        resource = broker.connection_holder._consumer_conn_pool
        return get_kombu_resource_objects(resource)

    raise TypeError(broker.__class__.__name__)


def assert_consumer_connections_one(broker) -> kombu.Connection:
    connections = get_consumer_connections(broker)
    assert len(connections) == 1
    return connections[0]


def get_producer_connections(broker):
    if isinstance(broker, ConnectionSharedKombuBroker):
        return [broker.connection_holder._producer_connection]

    if isinstance(broker, ConnectionPooledKombuBroker):
        resource = broker.connection_holder._producer_conn_pool
        return get_kombu_resource_objects(resource)

    raise TypeError(broker.__class__.__name__)


class PytestKombuBroker(contextlib.ContextDecorator):
    """
    Provides a context manager to set up and tear down a Kombu broker for testing.

    The class ensures that the specified broker is properly initialized and cleaned up
    before and after usage, preventing potential interference between tests. This
    includes setting up the broker connection, emitting a process boot event, setting
    it as the current broker, and cleaning up queues after execution.

    :ivar broker: The Kombu broker instance to be managed.
    :type broker: ConnectionPooledKombuBroker | ConnectionSharedKombuBroker
    """

    def __init__(self, broker: ConnectionPooledKombuBroker | ConnectionSharedKombuBroker):
        self.broker = broker

    def __enter__(self):
        broker = self.broker
        ensure_consumer_connection_rabbitmq(broker)
        broker.emit_after("process_boot")
        dramatiq.set_broker(broker)

        broker.delete_queue(broker._default_queue_name)  # cleanup after process kill
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        broker = self.broker
        broker.delete_all(include_pending=True)
        broker.close()


def create_pytest_kombu_broker(
    rabbitmq_dsn: str,
    kombu_broker_cls: type[ConnectionPooledKombuBroker] | type[ConnectionSharedKombuBroker],
    kombu_max_declare_attempts: int | None = None,
    kombu_max_enqueue_attempts: int | None = None,
    kombu_max_priority: int | None = None,
    kombu_broker_connection_holder_options: dict | None = None,
    kombu_broker_topology: RabbitMQTopology | None = None,
) -> PytestKombuBroker:
    broker = kombu_broker_cls(
        kombu_connection_options={"hostname": rabbitmq_dsn},
        max_declare_attempts=kombu_max_declare_attempts,
        max_enqueue_attempts=kombu_max_enqueue_attempts,
        max_priority=kombu_max_priority,
        connection_holder_options=kombu_broker_connection_holder_options or {},
        topology=kombu_broker_topology,
    )
    return PytestKombuBroker(broker)
