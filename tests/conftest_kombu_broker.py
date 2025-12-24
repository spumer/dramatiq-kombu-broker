from collections.abc import Generator
from typing import Any, TypeVar

import pytest
from dramatiq import Worker
from dramatiq_kombu_broker import (
    ConnectionPooledKombuBroker,
    ConnectionSharedKombuBroker,
    KombuBroker,
    RabbitMQTopology,
)
from dramatiq_kombu_broker.testing import create_pytest_kombu_broker

T = TypeVar("T")


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


@pytest.fixture(params=[None])
def kombu_broker_topology(request) -> RabbitMQTopology | None:
    assert request.param is None or isinstance(request.param, RabbitMQTopology)
    return request.param


@pytest.fixture
def kombu_broker(
    rabbitmq_dsn,
    kombu_max_declare_attempts,
    kombu_max_enqueue_attempts,
    kombu_max_priority,
    kombu_broker_cls,
    kombu_broker_connection_holder_options,
    kombu_broker_topology,
) -> Generator[KombuBroker, Any, None]:
    pytest_broker = create_pytest_kombu_broker(
        rabbitmq_dsn,
        kombu_broker_cls,
        kombu_max_declare_attempts=kombu_max_declare_attempts,
        kombu_max_enqueue_attempts=kombu_max_enqueue_attempts,
        kombu_max_priority=kombu_max_priority,
        kombu_broker_connection_holder_options=kombu_broker_connection_holder_options,
        kombu_broker_topology=kombu_broker_topology,
    )

    with pytest_broker:
        yield pytest_broker.broker


@pytest.fixture
def kombu_worker(kombu_broker):
    worker = Worker(kombu_broker, worker_threads=2)
    worker.start()
    yield worker
    worker.stop()
