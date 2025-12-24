import amqp.exceptions
from dramatiq import Message


def test_enqueue__missing_queue__redeclare(
    mocker,
    kombu_broker_cls,
    kombu_broker,
):
    message = Message(
        queue_name="some-queue",
        actor_name="some-actor",
        args=(),
        kwargs={},
        options={},
    )

    enqueue_exception = None
    _enqueue_message_orig = kombu_broker._enqueue_message

    def _no_route_enqueue_message(queue_name, message, *, delay=None):
        nonlocal enqueue_exception
        nonlocal _enqueue_message_mock

        # ensure mock called once
        # restore original behaviour
        _enqueue_message_mock.side_effect = _enqueue_message_orig

        # silently delete queue
        # ensure enqueue impossible (no queue = no route)
        with kombu_broker.connection_holder.acquire_consumer_channel() as channel:
            channel.queue_delete(queue_name, if_unused=False, if_empty=False)

        try:
            return _enqueue_message_orig(queue_name, message, delay=delay)
        except Exception as exc:
            enqueue_exception = exc
            raise

    _enqueue_message_mock = mocker.patch.object(
        kombu_broker,
        "_enqueue_message",
        side_effect=_no_route_enqueue_message,
    )

    kombu_broker.enqueue(message)

    assert message.queue_name in kombu_broker.queues

    queue_len, _, _ = kombu_broker.get_queue_message_counts(message.queue_name)
    assert queue_len == 1

    # ensure it was "mandatory=True"
    assert isinstance(enqueue_exception, amqp.exceptions.ChannelError)
    assert enqueue_exception.reply_code == 312  # 312 - no-route
