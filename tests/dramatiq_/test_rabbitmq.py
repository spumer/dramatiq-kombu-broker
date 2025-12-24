"""
Copy of original testset

Removed tests:
    - test_urlrabbitmq_creates_instances_of_rabbitmq_broker
    - test_rabbitmq_broker_raises_an_error_if_given_invalid_parameter_combinations
    - test_rabbitmq_broker_can_be_passed_a_list_of_parameters_for_failover
    - test_rabbitmq_consumers_ignore_unknown_messages_in_ack_and_nack
"""

import os
import time
from threading import Event
from unittest.mock import patch

import amqp.exceptions
import dramatiq
import kombu
import pytest
from dramatiq import Message, Middleware, QueueJoinTimeout, Worker
from dramatiq.common import current_millis
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, ConnectionSharedKombuBroker
from dramatiq_kombu_broker.testing import (
    ensure_consumer_connection_rabbitmq,
    ensure_producer_conneciton_rabbitmq,
    get_consumer_connections,
    get_producer_connections,
)


def assert_producer_connections_one(broker) -> kombu.Connection:
    connections = get_producer_connections(broker)
    assert len(connections) == 1
    return connections[0]


def test_kombu_broker_can_be_passed_a_semicolon_separated_list_of_uris(
    rabbitmq_dsn,
    kombu_broker_cls,
):
    # Given a string with a list of RabbitMQ connection URIs, including an invalid one
    # When I pass those URIs to RabbitMQ broker as a ;-separated string
    broker = kombu_broker_cls(
        kombu_connection_options={
            "hostname": "amqp://127.0.0.1:55672" + ";" + rabbitmq_dsn,
        }
    )
    ensure_consumer_connection_rabbitmq(broker)

    # The the broker should connect to the host that is up
    connections = get_consumer_connections(broker)
    assert len(connections) == 1
    connection = connections[0]
    assert connection.connected
    assert connection.alt == ["amqp://127.0.0.1:55672", rabbitmq_dsn]


def test_rabbitmq_actors_can_be_sent_messages(kombu_broker, kombu_worker):
    # Given that I have a database
    database = {}

    # And an actor that can write data to that database
    @dramatiq.actor
    def put(key, value):
        database[key] = value

    # If I send that actor many async messages
    for i in range(10):
        assert put.send("key-%d" % i, i)

    # And I give the workers time to process the messages
    kombu_broker.join(put.queue_name, min_successes=2)
    kombu_worker.join()

    # I expect the database to be populated
    assert len(database) == 10


def test_rabbitmq__retries_middleware__actors_retry_with_backoff_on_failure(
    kombu_broker, kombu_worker
):
    # Given that I have a database
    failure_time, success_time = 0, 0
    succeeded = Event()

    min_backoff = 20
    max_backoff = 50

    # And an actor that fails the first time it's called
    @dramatiq.actor(min_backoff=min_backoff, max_backoff=max_backoff)
    def do_work():
        nonlocal failure_time, success_time
        if not failure_time:
            failure_time = current_millis()
            raise RuntimeError("First failure.")
        success_time = current_millis()
        succeeded.set()

    # If I send it a message
    do_work.send()

    # Then wait for the actor to succeed
    succeeded.wait(timeout=3)

    # I expect both failure and success to have occurred
    assert failure_time > 0, "Actor should have failed at least once"
    assert success_time > 0, "Actor should have succeeded after retry"
    assert success_time > failure_time, "Success should come after failure"


def test_rabbitmq__retries_middleware__actors_can_retry_multiple_times(kombu_broker, kombu_worker):
    # Given that I have a database
    attempts = []

    done = Event()

    # And an actor that fails 3 times then succeeds
    @dramatiq.actor(min_backoff=100, max_backoff=200)
    def do_work():
        attempts.append(1)
        if sum(attempts) < 4:
            raise RuntimeError("Failure #%d" % sum(attempts))
        done.set()

    # If I send it a message
    do_work.send()

    # Then join on the queue
    done.wait(timeout=10)
    kombu_worker.join()

    # I expect it to have been attempted 4 times
    assert sum(attempts) == 4


def test_rabbitmq_actors_can_have_their_messages_delayed(kombu_broker, kombu_worker):
    # Given that I have a database
    start_time, run_time = current_millis(), None

    # And an actor that records the time it ran
    @dramatiq.actor
    def record():
        nonlocal run_time
        run_time = current_millis()

    # If I send it a delayed message
    delay_ms = 50
    record.send_with_options(delay=delay_ms)

    # Then join on the queue
    kombu_broker.join(record.queue_name, timeout=3000)
    kombu_worker.join()

    # I expect that message to have been processed at least delayed milliseconds later
    assert run_time is not None
    assert run_time - start_time >= delay_ms


def test_rabbitmq_actors_can_delay_messages_independent_of_each_other(kombu_broker):
    # Given that I have a database
    results = []

    # And an actor that appends a number to the database
    @dramatiq.actor
    def append(x):
        results.append(x)

    # And a worker
    broker = kombu_broker
    worker = Worker(broker, worker_threads=1)

    try:
        # And I send it a delayed message
        append.send_with_options(args=(1,), delay=1500)

        # And then another delayed message with a smaller delay
        append.send_with_options(args=(2,), delay=1000)

        # Then resume the worker and join on the queue
        worker.start()
        broker.join(append.queue_name, min_successes=20)
        worker.join()

        # I expect the latter message to have been run first
        assert results == [2, 1]
    finally:
        worker.stop()


def test_rabbitmq_actors_can_have_retry_limits(kombu_broker, kombu_worker):
    # Given that I have an actor that always fails

    @dramatiq.actor(max_retries=0)
    def do_work():
        raise RuntimeError("failed")

    # If I send it a message
    do_work.send()

    # Then join on its queue
    kombu_broker.join(do_work.queue_name)
    kombu_worker.join()

    # I expect the message to get moved to the dead letter queue
    _, _, xq_count = kombu_broker.get_queue_message_counts(do_work.queue_name)
    assert xq_count == 1


@pytest.mark.parametrize("kombu_broker_cls", ["conn-share"], indirect=True)
def test_kombu_broker__conn_share___connections_are_lazy(
    rabbitmq_dsn,
    kombu_broker_cls: type[ConnectionSharedKombuBroker],
):
    # When I create an RMQ broker
    broker = kombu_broker_cls(
        kombu_connection_options={"hostname": rabbitmq_dsn},
    )

    def get_connection():
        return broker.connection_holder._get_consumer_connection(ensure=False)

    # Then it shouldn't immediately connect to the server
    assert not get_connection().connected

    # When I declare a queue
    broker.declare_queue("some-queue")

    # Then it shouldn't connect either
    assert not get_connection().connected

    # When I create a consumer on that queue
    broker.consume("some-queue", timeout=1)

    # Then it should connect
    assert get_connection().connected


@pytest.mark.parametrize("kombu_broker_cls", ["conn-pool"], indirect=True)
def test_kombu_broker__conn_pool___connections_are_lazy(
    rabbitmq_dsn,
    kombu_broker_cls: type[ConnectionPooledKombuBroker],
):
    # When I create an RMQ broker
    broker = kombu_broker_cls(
        kombu_connection_options={"hostname": rabbitmq_dsn},
    )

    consumer_connection_pool = broker.connection_holder._consumer_conn_pool
    producer_connection_pool = broker.connection_holder._producer_conn_pool

    # Then it shouldn't immediately connect to the server
    assert not consumer_connection_pool._dirty
    assert not producer_connection_pool._dirty

    # When I declare a queue
    broker.declare_queue("some-queue")

    # Then it shouldn't connect either
    assert not consumer_connection_pool._dirty
    assert not producer_connection_pool._dirty

    # When I create a consumer on that queue
    broker.consume("some-queue", timeout=1)

    # Then it should connect
    assert len(consumer_connection_pool._dirty) == 1
    assert not producer_connection_pool._dirty

    connection = list(consumer_connection_pool._dirty)[0]
    assert connection.connected


@pytest.mark.parametrize("kombu_max_declare_attempts", [2], indirect=True)
def test_kombu_broker_stops_retrying_declaring_queues_when_max_attempts_reached(
    kombu_broker, kombu_max_declare_attempts
):
    # Given that I have a rabbit instance that lost its connection
    with patch.object(
        kombu_broker,
        "_declare_queue",
        side_effect=amqp.exceptions.RecoverableConnectionError,
    ):
        # When I declare and use an actor
        # Then a ConnectionClosed error should be raised
        with pytest.raises(dramatiq.errors.ConnectionClosed):

            @dramatiq.actor(queue_name="flaky_queue")
            def do_work():
                pass

            do_work.send()


def test_rabbitmq_messages_belonging_to_missing_actors_are_rejected(kombu_broker, kombu_worker):
    # Given that I have a broker without actors
    # If I send it a message
    message = Message(
        queue_name="some-queue",
        actor_name="some-actor",
        args=(),
        kwargs={},
        options={},
    )
    kombu_broker.declare_queue(message.queue_name)
    kombu_broker.enqueue(message)

    # Then join on the queue
    kombu_broker.join(message.queue_name)
    kombu_worker.join()

    # I expect the message to end up on the dead letter queue
    _, _, dead = kombu_broker.get_queue_message_counts(message.queue_name)
    assert dead == 1


def test_kombu_broker__producer_reconnects_after_enqueue_failure(kombu_broker):
    # Given that I have an actor
    @dramatiq.actor
    def do_nothing():
        pass

    ensure_producer_conneciton_rabbitmq(kombu_broker)
    connection = assert_producer_connections_one(kombu_broker)
    assert connection.connected

    # If I close my connection
    kombu_broker.close()
    assert not connection.connected

    # Then send my actor a message
    # I expect the message to be enqueued
    assert do_nothing.send()

    # And the connection be reopened
    connection = assert_producer_connections_one(kombu_broker)
    assert connection.connected


@pytest.mark.skip(
    reason="RabbitMQ Start/Stop required: https://pypi.org/project/pytest-docker-tools/"
)
def test_kombu_workers_handle_rabbit_failures_gracefully(kombu_broker, kombu_worker):
    # Given that I have an attempts database
    attempts = []

    # And an actor that adds 1 to the attempts database
    @dramatiq.actor
    def do_work():
        attempts.append(1)
        time.sleep(1)

    # If I send that actor a delayed message
    do_work.send_with_options(delay=1000)

    # If I stop the RabbitMQ app
    os.system("rabbitmqctl stop_app")

    # Then start the app back up
    os.system("rabbitmqctl start_app")

    # And join on the queue
    del kombu_broker.channel
    del kombu_broker.connection
    kombu_broker.join(do_work.queue_name)
    kombu_worker.join()

    # I expect the work to have been attempted at least once
    assert sum(attempts) >= 1


def test_kombu_broker_can_be_closed_multiple_times(kombu_broker):
    ensure_consumer_connection_rabbitmq(kombu_broker)
    ensure_producer_conneciton_rabbitmq(kombu_broker)

    assert all(c.connected for c in get_consumer_connections(kombu_broker))
    assert all(c.connected for c in get_producer_connections(kombu_broker))

    kombu_broker.close()
    kombu_broker.close()

    assert not any(c.connected for c in get_consumer_connections(kombu_broker))
    assert not any(c.connected for c in get_producer_connections(kombu_broker))


def test_kombu_broker_can_join_with_timeout(kombu_broker, kombu_worker):
    # Given that I have an actor that takes a long time to run
    @dramatiq.actor
    def do_work():
        time.sleep(0.1)

    # When I send that actor a message
    do_work.send()

    # And join on its queue with a timeout
    # Then I expect a QueueJoinTimeout to be raised
    with pytest.raises(QueueJoinTimeout):
        kombu_broker.join(do_work.queue_name, min_successes=10, timeout=50)


def test_kombu_broker_can_flush_queues(kombu_broker):
    # Given that I have an actor
    @dramatiq.actor
    def do_work():
        pass

    # When I send that actor a message
    do_work.send()

    # And then tell the broker to flush all queues
    kombu_broker.flush_all()

    # And then join on the actors's queue
    # Then it should join immediately
    assert kombu_broker.join(do_work.queue_name, min_successes=1, timeout=200) is None


@pytest.mark.parametrize("kombu_max_priority", [10], indirect=True)
def test_kombu_broker_can_enqueue_messages_with_priority(kombu_broker, kombu_max_priority):
    max_priority = kombu_max_priority
    message_processing_order = []
    queue_name = "prioritized"

    # Given that I have an actor that store priorities
    @dramatiq.actor(queue_name=queue_name)
    def do_work(message_priority):
        message_processing_order.append(message_priority)

    worker = Worker(kombu_broker, worker_threads=1)
    worker.queue_prefetch = 1
    worker.start()
    worker.pause()

    try:
        # When I send that actor messages with increasing priorities
        for priority in range(max_priority):
            do_work.send_with_options(args=(priority,), broker_priority=priority)

        # And then tell the broker to wait for all messages
        worker.resume()
        kombu_broker.join(queue_name, min_successes=2, timeout=30000)
        worker.join()

        # I expect the stored priorities to be saved in decreasing order
        assert message_processing_order == list(reversed(range(max_priority))), (
            message_processing_order
        )
    finally:
        worker.stop()


def test_kombu_broker_retries_declaring_queues_when_connection_related_errors_occur(
    kombu_broker,
):
    executed, declare_called = False, False
    original_declare = kombu_broker._declare_queue

    def flaky_declare_queue(*args, **kwargs):
        nonlocal declare_called
        if not declare_called:
            declare_called = True
            raise amqp.exceptions.RecoverableConnectionError
        return original_declare(*args, **kwargs)

    # Given that I have a flaky connection to a rabbitmq server
    with patch.object(kombu_broker, "_declare_queue", flaky_declare_queue):
        # When I declare an actor
        @dramatiq.actor(queue_name="flaky_queue")
        def do_work():
            nonlocal executed
            executed = True

        # And I send that actor a message
        do_work.send()

        # And wait for the worker to process the message
        worker = Worker(kombu_broker, worker_threads=1)
        worker.start()

        try:
            kombu_broker.join(do_work.queue_name, timeout=5000)
            worker.join()

            # Then the queue should eventually be declared and the message executed
            assert declare_called
            assert executed
        finally:
            worker.stop()


def test_kombu_broker_retries_declaring_queues_when_declared_queue_disappears(kombu_broker):
    executed = False

    # Given that I have an actor on a flaky queue
    flaky_queue_name = "flaky_queue"
    with kombu_broker.connection_holder.acquire_consumer_channel() as channel:
        channel.queue_delete(flaky_queue_name)

    @dramatiq.actor(queue_name=flaky_queue_name)
    def do_work():
        nonlocal executed
        executed = True

    # When I start a server
    worker = Worker(kombu_broker, worker_threads=1)
    worker.start()

    declared_ev = Event()

    class DeclaredMiddleware(Middleware):
        def after_declare_queue(self, broker, queue_name):
            if queue_name == flaky_queue_name:
                declared_ev.set()

    # I expect that queue to be declared
    kombu_broker.add_middleware(DeclaredMiddleware())
    assert declared_ev.wait(timeout=5)

    # If I delete the queue
    with kombu_broker.connection_holder.acquire_consumer_channel() as channel:
        channel.queue_delete(do_work.queue_name)

        with pytest.raises(amqp.exceptions.NotFound):
            channel.queue_declare(do_work.queue_name, passive=True)

    # And I send that actor a message
    do_work.send()
    try:
        kombu_broker.join(do_work.queue_name, timeout=20000)
        worker.join()
    finally:
        worker.stop()

    # Then the queue should be declared and the message executed
    assert executed


def test_rabbitmq_messages_that_failed_to_decode_are_rejected(kombu_broker, kombu_worker):
    # Given that I have an Actor
    @dramatiq.actor(max_retries=0)
    def do_work(_):
        pass

    old_encoder = dramatiq.get_encoder()

    # And an encoder that may fail to decode
    class BadEncoder(type(old_encoder)):
        def decode(self, data):
            if "xfail" in str(data):
                raise RuntimeError("xfail")
            return super().decode(data)

    dramatiq.set_encoder(BadEncoder())

    try:
        # When I send a message that will fail to decode
        do_work.send("xfail")

        # And I join on the queue
        kombu_broker.join(do_work.queue_name)
        kombu_worker.join()

        # Then I expect the message to get moved to the dead letter queue
        q_count, dq_count, xq_count = kombu_broker.get_queue_message_counts(do_work.queue_name)

        assert q_count == dq_count == 0
        assert xq_count == 1
    finally:
        dramatiq.set_encoder(old_encoder)


def test_rabbitmq_queues_only_contains_canonical_name(kombu_broker, kombu_worker):
    assert len(kombu_broker.queues) == 0

    @dramatiq.actor
    def put():
        pass

    assert len(kombu_broker.queues) == 1
    assert put.queue_name in kombu_broker.queues
