import os

import pytest

pytest_plugins = [
    "dramatiq_kombu_broker.testing",
]


@pytest.fixture()
def rabbitmq_username():
    return "guest"


@pytest.fixture()
def rabbitmq_password():
    return "guest"


@pytest.fixture()
def rabbitmq_hostname():
    if hostname := os.getenv("PYTEST_RABBITMQ_HOST"):
        return hostname

    return '127.0.0.1'


@pytest.fixture()
def rabbitmq_dsn(rabbitmq_username, rabbitmq_password, rabbitmq_hostname):
    return f"amqp://{rabbitmq_username}:{rabbitmq_password}@{rabbitmq_hostname}:5672/"
