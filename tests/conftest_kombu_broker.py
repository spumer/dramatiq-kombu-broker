import pytest
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, ConnectionSharedKombuBroker
from dramatiq_kombu_broker.testing import (
    ensure_consumer_connection_rabbitmq,
)

import dramatiq
from dramatiq import Worker


@pytest.fixture(params=[None])
def kombu_max_declare_attempts(request):
    assert isinstance(request.param, int) or request.param is None
    return request.param


@pytest.fixture(params=[None])
def kombu_max_enqueue_attempts(request):
    assert isinstance(request.param, int) or request.param is None
    return request.param


@pytest.fixture(params=[None])
def kombu_max_priority(request):
    assert isinstance(request.param, int) or request.param is None
    return request.param


@pytest.fixture(params=[None])
def kombu_broker_connection_holder_options(request) -> dict:
    if request.param is None:
        return {}
    return request.param


@pytest.fixture(params=["conn-pool", "conn-share"])
def kombu_broker_cls(request):
    if request.param == "conn-pool":
        return ConnectionPooledKombuBroker

    if request.param == "conn-share":
        return ConnectionSharedKombuBroker

    raise NotImplementedError(request.param)


@pytest.fixture()
def kombu_broker(
    rabbitmq_dsn,
    kombu_max_declare_attempts,
    kombu_max_enqueue_attempts,
    kombu_max_priority,
    kombu_broker_cls,
    kombu_broker_connection_holder_options,
):
    broker = kombu_broker_cls(
        kombu_connection_options={"hostname": rabbitmq_dsn},
        max_declare_attempts=kombu_max_declare_attempts,
        max_enqueue_attempts=kombu_max_enqueue_attempts,
        max_priority=kombu_max_priority,
        connection_holder_options=kombu_broker_connection_holder_options,
    )
    ensure_consumer_connection_rabbitmq(broker)
    broker.emit_after("process_boot")
    dramatiq.set_broker(broker)

    broker.delete_queue(broker._default_queue_name)  # cleanup after process kill
    yield broker
    broker.delete_all(include_pending=True)
    broker.close()


@pytest.fixture()
def kombu_worker(kombu_broker):
    worker = Worker(kombu_broker, worker_threads=2)
    worker.start()
    yield worker
    worker.stop()
