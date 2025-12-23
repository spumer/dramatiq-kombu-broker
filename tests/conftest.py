import contextlib
import os
from collections.abc import Callable, Generator
from typing import Any

import pytest
from dramatiq_kombu_broker.consumer import QueueReader

pytest_plugins = [
    "dramatiq_kombu_broker.testing",
    "tests.conftest_kombu_broker",
]


@pytest.fixture(scope="session")
def rabbitmq_username():
    return "guest"


@pytest.fixture(scope="session")
def rabbitmq_password():
    return "guest"


@pytest.fixture(scope="session")
def rabbitmq_hostname():
    if hostname := os.getenv("PYTEST_RABBITMQ_HOST"):
        return hostname

    return "127.0.0.1"


@pytest.fixture(scope="session")
def rabbitmq_port():
    if port := os.getenv("PYTEST_RABBITMQ_PORT"):
        return int(port)

    return 5672


@pytest.fixture(scope="session")
def rabbitmq_dsn(rabbitmq_username, rabbitmq_password, rabbitmq_hostname, rabbitmq_port):
    return f"amqp://{rabbitmq_username}:{rabbitmq_password}@{rabbitmq_hostname}:{rabbitmq_port}/"


@pytest.fixture
def queue_reader_factory() -> Generator[Callable[..., QueueReader], Any, None]:
    close_readers = contextlib.ExitStack()

    def _circuit(*args, **kwargs):
        reader = QueueReader(*args, **kwargs)
        close_readers.enter_context(reader)
        return reader

    with close_readers:
        yield _circuit
