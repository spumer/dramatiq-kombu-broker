import kombu
import kombu.resource
from kombu.utils.functional import lazy

from . import ConnectionPooledKombuBroker, ConnectionSharedKombuBroker


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
