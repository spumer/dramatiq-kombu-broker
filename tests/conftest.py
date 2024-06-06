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
def rabbitmq_dsn(rabbitmq_username, rabbitmq_password):
    return f"amqp://{rabbitmq_username}:{rabbitmq_password}@127.0.0.1:5672/"
