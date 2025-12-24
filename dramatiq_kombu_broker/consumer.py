import collections
import contextlib
import datetime as dt
import functools
import threading

import dramatiq
import kombu
import kombu.simple
import kombu.transport.pyamqp
from amqp import RecoverableConnectionError
from dramatiq import Consumer as BaseConsumer
from dramatiq import get_logger
from kombu.transport.virtual import Channel
from kombu.utils.debug import Logwrapped
from kombu_pyamqp_threadsafe import ThreadSafeChannel

from ._types import ReleasableChannel


class QueueReader(kombu.simple.SimpleBase):
    """Простой способ прочитать все сообщения из очереди"""

    def __init__(
        self,
        channel: Channel,
        *,
        queue_name: str,
        prefetch_count: int | None = None,
    ):
        queue = kombu.Queue(queue_name, channel=channel, no_declare=True)
        consumer = kombu.Consumer(channel, queue, prefetch_count=prefetch_count)
        producer = kombu.Producer(channel, routing_key=queue_name)
        self.__connection__: kombu.Connection = channel.connection.client

        super().__init__(channel, producer, consumer)

    def __repr__(self):
        return f"QueueReader('{self.queue.name}', channel_id={self.channel.channel_id}) using {self.__connection__}"

    def check(self):
        """Check queue can be consumed

        raise amqp.exceptions.NotFound
        """
        if self._consuming:
            raise RuntimeError("You should use this method before any other")

        try:
            self._consume()
            try:
                self.channel.connection.client.drain_events(timeout=0)
            except TimeoutError:
                pass
        finally:
            # to prevent consuming hang after _failed check_ we need restart it
            # guarantee consumer will be started again in any case
            self._consuming = False
            self.consumer.cancel()

    def pop(self, timeout: float = 0) -> kombu.Message | None:
        """Убрать сообщение из буфера"""
        try:
            return self.get(timeout=timeout)
        except (self.Empty, TimeoutError):
            return None
        except Exception:
            # to prevent consuming hang after channel close we need restart it
            # guarantee consumer will be started again in any case
            self._consuming = False
            try:
                self.consumer.cancel()
            except Exception:  # ; try-except-pass
                pass

            raise


class MessageProxy(dramatiq.MessageProxy):
    last_acknowledge_error: Exception | None

    def __init__(self, dramatiq_message: dramatiq.Message, *, kombu_message: kombu.Message):
        super().__init__(dramatiq_message)
        self._kombu_message = kombu_message
        self.last_acknowledge_error = None

    @property
    def acknowledged(self):
        return self._kombu_message.acknowledged

    def ack(self) -> bool:
        """Ack message

        Returns False if it's not possible
        Raise exception if ack fails
        """
        if self._kombu_message.acknowledged:
            if self.failed:
                return False
            return True

        try:
            self._kombu_message.ack()
        except Exception as exc:
            self.last_acknowledge_error = exc
            raise

        return True

    def nack(self, requeue: bool = False) -> bool:
        """Nack (reject) message

        Returns False if it's not possible
        Raise exception if nack (reject) fails
        """
        if self._kombu_message.acknowledged:
            if not self.failed:
                return False
            return True

        try:
            self._kombu_message.reject(requeue=requeue)
        except Exception as exc:
            self.last_acknowledge_error = exc
            raise

        return True


class DramatiqConsumer(BaseConsumer):
    MessageProxy = MessageProxy
    QueueReader = QueueReader

    #: when job done the DramatiqConsumer.ack() and .nack() called in WorkerThread
    #: This is bringing us to situation when WorkerThread can use kombu.Channel associated with Consumer
    #: To prevent this we can move ack/nack to same Thread where messaged was consumed
    channel_threadsafe: bool = False

    def __init__(
        self,
        channel: ReleasableChannel,
        queue_name: str,
        prefetch_count: int,
        read_timeout: dt.timedelta,
        blocking_acknowledge: bool = False,
    ):
        connection = channel.connection
        if connection is None:
            raise RecoverableConnectionError("connection already closed") from None

        self._reader = self.QueueReader(
            channel,
            queue_name=queue_name,
            prefetch_count=prefetch_count,
        )
        self.__connection__: kombu.Connection = connection.client
        self._ack_queue: collections.deque = collections.deque()
        self._nack_queue: collections.deque = collections.deque()

        self._owner_id = threading.get_ident()

        self.channel = channel
        self.read_timeout = read_timeout
        self.blocking_acknowledge = blocking_acknowledge
        self.logger = get_logger(self.__module__, f"{self.__class__.__name__}({queue_name})")

    def _is_threadsafe(self):
        """Check operation can be applied in current thread"""
        return self.channel_threadsafe or (
            threading.current_thread().ident
            == self._owner_id  # we are in ConsumerThread, protect from deadlock
        )

    def check(self):
        self._reader.check()

    def _ack_or_log_error(self, message: MessageProxy) -> None:  # type: ignore[valid-type]
        try:
            message.ack()  # type: ignore[attr-defined]
        except Exception:
            self.logger.warning("Failed to ack message.", exc_info=True)

    def ack(
        self,
        message: MessageProxy,  # type: ignore[valid-type]
        *,
        block: bool | None = None,
        timeout: float | None = None,
    ):
        if block is None:
            block = self.blocking_acknowledge

        if self._is_threadsafe() and block:
            self._ack_or_log_error(message)
            return

        if not block:
            self._ack_queue.append((message, None))
        else:
            done = threading.Event()
            self._ack_queue.append((message, done))
            done.wait(timeout)

    def _nack_or_log_error(self, message: MessageProxy) -> None:  # type: ignore[valid-type]
        try:
            message.nack()  # type: ignore[attr-defined]
        except Exception:
            self.logger.warning("Failed to nack message.", exc_info=True)

    def nack(
        self,
        message: MessageProxy,  # type: ignore[valid-type]
        *,
        block: bool | None = None,
        timeout: float | None = None,
    ):
        if block is None:
            block = self.blocking_acknowledge

        if self._is_threadsafe() and block:
            self._nack_or_log_error(message)
            return

        if not block:
            self._nack_queue.append((message, None))
        else:
            done = threading.Event()
            self._nack_queue.append((message, done))
            done.wait(timeout)

    def close(self):
        with contextlib.suppress(Exception):
            if self._reader._consuming:
                self._reader.close()

        with contextlib.suppress(Exception):
            self.channel.release()

    @functools.cached_property
    def _conn_errors(self) -> tuple:
        return tuple(self.__connection__.connection_errors) + tuple(
            self.__connection__.channel_errors
        )

    def _process_queued_ack_events(self):
        while self._ack_queue:
            message, done_event = self._ack_queue.popleft()
            self._ack_or_log_error(message)
            if done_event is not None:
                done_event.set()

    def _process_queued_nack_events(self):
        while self._nack_queue:
            message, done_event = self._nack_queue.popleft()
            self._nack_or_log_error(message)
            if done_event is not None:
                done_event.set()

    def __next__(self) -> MessageProxy | None:  # type: ignore[valid-type]
        """Consume message from RMQ and return it"""
        try:
            self._process_queued_ack_events()
            self._process_queued_nack_events()

            message: kombu.Message | None = self._reader.pop(
                timeout=self.read_timeout.total_seconds()
            )
            if message is None:
                conn = self.channel.connection
                if conn is not None and conn.client is not None:
                    conn.client.heartbeat_check()
                return None
        except self._conn_errors as exc:
            # dramatiq.Worker expect this error
            # without it error will be logged as unhandled exception
            raise dramatiq.ConnectionError(exc) from None

        try:
            dramatiq_message = dramatiq.Message.decode(message.body)
        except dramatiq.DecodeError:
            self.logger.exception(
                "Failed to decode message using encoder %r.", dramatiq.get_encoder()
            )
            message.reject_log_error(self.logger, errors=(Exception,))
            return None

        message_proxy = self.MessageProxy(
            dramatiq_message,
            kombu_message=message,
        )

        return message_proxy


class ThreadSafeDramatiqConsumer(DramatiqConsumer):
    channel_threadsafe: bool = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        channel = self.channel
        if isinstance(channel, Logwrapped):
            channel = channel.instance

        if not isinstance(channel, ThreadSafeChannel):
            raise ValueError("Channel must be ThreadSafeChannel")


class GeventDramatiqConsumer(ThreadSafeDramatiqConsumer):
    """Gevent-compatible Dramatiq consumer

    Since we are thread-safe no need additional work in that
    """
