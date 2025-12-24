import contextlib
import datetime as dt
import logging
import socket
import threading
import time
import typing as tp

import amqp
import dramatiq
import kombu
import kombu.exceptions
import kombu.simple
import kombu.transport.pyamqp
from dramatiq import Broker
from dramatiq.common import current_millis

from .connection_holder import ConnectionHolder
from .consumer import DramatiqConsumer, ThreadSafeDramatiqConsumer
from .exceptions import DelayTooLongError
from .pooled_connection_holder import PooledConnectionHolder
from .shared_connection_holder import SharedConnectionHolder
from .topology import DefaultDramatiqTopology, RabbitMQTopology

DEFAULT_QUEUE_NAME = "default"


class KombuTransportOptions(tp.TypedDict, total=False):
    """
    max_retries (int): Maximum number of retries before we give up.
        If neither of this and timeout is set, we will retry forever.
        If one of this and timeout is reached, stop.
    interval_start (float): How long (in seconds) we start sleeping
        between retries.
    interval_step (float): By how much the interval is increased for
        each retry.
    interval_max (float): Maximum number of seconds to sleep
        between retries.
    connect_retries_timeout (int): Maximum seconds waiting before we give up.
    confirm_publish (bool): True - each message is confirmed, False - no delivery confirmation
    """

    max_retries: int
    interval_start: float
    interval_step: float
    interval_max: float
    connect_retries_timeout: float
    client_properties: dict
    confirm_publish: bool


class KombuConnectionOptions(tp.TypedDict, total=False):
    hostname: str
    userid: str
    port: int
    heartbeat: int
    password: str
    virtual_host: str
    connect_timeout: float
    ssl: bool
    transport_options: KombuTransportOptions


class KombuBroker(Broker):
    DramatiqConsumer = DramatiqConsumer

    connection_holder_cls: type[ConnectionHolder] | None = None
    connection_holder: ConnectionHolder
    topology: RabbitMQTopology

    def __init__(
        self,
        middleware=None,
        *,
        default_queue_name: str = DEFAULT_QUEUE_NAME,
        blocking_acknowledge: bool = True,
        connection_holder_options: dict | None = None,
        kombu_connection_options: KombuConnectionOptions,
        confirm_delivery: bool = True,
        max_priority: int | None = None,
        max_enqueue_attempts: int | None = None,
        max_declare_attempts: int | None = None,
        max_producer_acquire_timeout: float | None = 10,
        confirm_timeout: float | None = 5.0,
        topology: RabbitMQTopology | None = None,
    ):
        super().__init__(
            middleware=middleware,
        )

        transport_options = kombu_connection_options.pop("transport_options", None) or {}
        transport_options["confirm_publish"] = confirm_delivery

        client_properties = transport_options.setdefault("client_properties", {})
        client_properties.setdefault("connection_name", socket.gethostname())

        # Set heartbeat to detect dead connections
        kombu_connection_options.setdefault("heartbeat", 60)

        if self.connection_holder_cls is None:
            raise TypeError("connection_holder_cls can not be None")

        connection = kombu.Connection(
            **kombu_connection_options,
            transport_options=transport_options,
        )

        self.connection_holder = self._create_connection_holder(
            connection, connection_holder_options or {}
        )

        self._declare_lock = threading.RLock()
        self._max_declare_attempts = max_declare_attempts
        self._max_enqueue_attempts = max_enqueue_attempts
        self._max_producer_acquire_timeout = max_producer_acquire_timeout
        self._confirm_timeout = confirm_timeout

        self._default_queue_name = default_queue_name
        self._blocking_acknowledge = blocking_acknowledge

        # Use provided topology or create default with max_priority
        if topology is None:
            self.topology = DefaultDramatiqTopology(max_priority=max_priority)
        else:
            self.topology = topology

        self.queues_pending: set[str] = set()
        self.queues: set[str] = set()  # should contain only canonical names

        # Callbacks for lifecycle events (useful for testing)
        self._on_consume_started_callbacks: list[tp.Callable[[str], None]] = []
        self._on_close_callbacks: list[tp.Callable[[], None]] = []

    def _create_connection_holder(
        self, connection: kombu.Connection, options: dict[str, tp.Any]
    ) -> ConnectionHolder:
        assert self.connection_holder_cls is not None
        return self.connection_holder_cls(connection, **options)

    def on_consume_started(self, callback: tp.Callable[[str], None]) -> None:
        """Register callback to be called when consume() creates a consumer.

        Args:
            callback: Function that receives queue_name as argument.
        """
        self._on_consume_started_callbacks.append(callback)

    def on_close(self, callback: tp.Callable[[], None]) -> None:
        """Register callback to be called when broker closes.

        Args:
            callback: Function with no arguments.
        """
        self._on_close_callbacks.append(callback)

    def close(self):
        try:
            self.connection_holder.close()
        finally:
            for callback in self._on_close_callbacks:
                callback()

    def declare_actor(self, actor: dramatiq.Actor):
        if actor.queue_name == "default" and actor.queue_name != self._default_queue_name:
            self.logger.debug(
                "[declare_actor] Replace queue_name ('default') for actor (%r)", actor.actor_name
            )
            actor.queue_name = self._default_queue_name
        super().declare_actor(actor)

    def get_queue_message_counts(self, queue_name):
        """Get the number of messages in a queue.  This method is only
        meant to be used in unit and integration tests.

        Parameters
        ----------
          queue_name(str): The queue whose message counts to get.

        Returns
        -------
          tuple: A triple representing the number of messages in the
          queue, its delayed queue and its dead letter queue.
        """
        delay_queue_name = self.topology.get_delay_queue_name(queue_name)
        dead_letter_queue_name = self.topology.get_dead_letter_queue_name(queue_name)

        counts = []

        with self.connection_holder.acquire_consumer_channel() as channel:
            for queue_name in (queue_name, delay_queue_name, dead_letter_queue_name):
                qsize: int
                _, qsize, _ = kombu.Queue(queue_name).queue_declare(passive=True, channel=channel)

                counts.append(qsize)

        return tuple(counts)

    def join(self, queue_name, min_successes=2, idle_time=100, *, timeout=None):  # pragma: no cover
        """Wait for all the messages on the given queue to be
        processed.  This method is only meant to be used in tests to
        wait for all the messages in a queue to be processed.

        Warning:
          This method doesn't wait for unacked messages so it may not
          be completely reliable.  Use the stub broker in your unit
          tests and only use this for simple integration tests.

        Parameters
        ----------
          queue_name(str): The queue to wait on.
          min_successes(int): The minimum number of times all the
            polled queues should be empty.
          idle_time(int): The number of milliseconds to wait between
            counts.
          timeout(Optional[int]): The max amount of time, in
            milliseconds, to wait on this queue.
        """
        deadline = timeout and time.monotonic() + timeout / 1000
        successes = 0
        while successes < min_successes:
            start = time.monotonic()
            if deadline and time.monotonic() >= deadline:
                raise dramatiq.QueueJoinTimeout(queue_name)

            total_messages = sum(self.get_queue_message_counts(queue_name)[:-1])
            if total_messages == 0:
                successes += 1
            else:
                successes = 0

            if successes < min_successes:  # do not sleep on last iteration
                time.sleep(idle_time / 1000)

    def declare_queue(self, queue_name, *, ensure=False):
        canonical_qname = self.topology.get_canonical_queue_name(queue_name)

        if canonical_qname not in self.queues:
            with self._declare_lock:
                if canonical_qname not in self.queues:
                    self.emit_before("declare_queue", queue_name)
                    self.queues.add(canonical_qname)
                    self.queues_pending.add(canonical_qname)
                    self.emit_after("declare_queue", queue_name)

                    delayed_name = self.topology.get_delay_queue_name(queue_name)
                    self.delay_queues.add(delayed_name)
                    self.emit_after("declare_delay_queue", delayed_name)

        if ensure:
            with self._declare_lock:
                self._ensure_queue(canonical_qname)

    def _declare_queue(self, queue_name) -> kombu.Queue:
        queue_name = self.topology.get_canonical_queue_name(queue_name)
        with self.connection_holder.acquire_consumer_channel() as channel:
            queue = self.topology.declare_canonical_queue(
                channel, queue_name, ignore_different_topology=True
            )

        self.queues.add(queue_name)
        self.queues_pending.discard(queue_name)
        return queue

    def _declare_dq_queue(self, queue_name):
        """Delay queue"""
        queue_name = self.topology.get_delay_queue_name(queue_name)
        with self.connection_holder.acquire_consumer_channel() as channel:
            queue = self.topology.declare_delay_queue(
                channel, queue_name, ignore_different_topology=True
            )

        self.queues.add(queue_name)
        self.queues_pending.discard(queue_name)
        return queue

    def _declare_xq_queue(self, queue_name):
        """DLX queue"""
        queue_name = self.topology.get_dead_letter_queue_name(queue_name)

        with self.connection_holder.acquire_consumer_channel() as channel:
            queue = self.topology.declare_dead_letter_queue(
                channel, queue_name, ignore_different_topology=True
            )

        self.queues.add(queue_name)
        self.queues_pending.discard(queue_name)
        return queue

    @classmethod
    def on_connection_error_errback(cls, exc, slept_interval):
        logging.getLogger("KombuBroker").warning(
            "Broker connection error, trying again in %s seconds: %r.",
            slept_interval,
            exc,
            exc_info=True,
        )

    @classmethod
    def on_connection_error_errback_over_time(cls, exc, interval_range, retries) -> float:
        """
        :param exc: exception instance
        :param interval_range: iterator
            which return the time in seconds to sleep next
        :param retries: number of previous retries
        :return: seconds to sleep
        """
        next_sleep = next(interval_range)
        cls.on_connection_error_errback(exc, next_sleep)
        return next_sleep

    def _ensure_queue(self, queue_name):
        def _ensure(func, *args, **kwargs):
            try:
                return self.connection_holder.retry_connection_errors_over_time(
                    func,
                    max_retries=self._max_declare_attempts,
                    errback=self.on_connection_error_errback_over_time,
                )(*args, **kwargs)
            except dramatiq.errors.ConnectionError as exc:
                # support dramatiq RabbitMQ broker behaviour
                raise dramatiq.errors.ConnectionClosed(exc.__cause__) from None

        q_names = self.topology.get_queue_name_tuple(queue_name)
        if queue_name != q_names.canonical:
            raise RuntimeError("You can ensure only canonical queue name. Given: %r" % queue_name)

        if q_names.canonical in self.queues_pending:
            self.queues_pending.add(q_names.delayed)
            self.queues_pending.add(q_names.dead_letter)

        if q_names.delayed in self.queues_pending:
            _ensure(self._declare_dq_queue, q_names.canonical)

        if q_names.dead_letter in self.queues_pending:
            _ensure(self._declare_xq_queue, q_names.canonical)

        if q_names.canonical in self.queues_pending:
            _ensure(self._declare_queue, q_names.canonical)

    def enqueue(self, message, *, delay=None):  # pragma: no cover
        queue_name = message.queue_name
        self.declare_queue(queue_name, ensure=True)

        if delay is not None:
            # Validate delay against topology max_delay_time (fail-fast)
            if self.topology.max_delay_time is not None:
                max_delay_ms = int(self.topology.max_delay_time.total_seconds() * 1000)
                if delay > max_delay_ms:
                    raise DelayTooLongError(
                        f"Message delay {delay}ms exceeds max_delay_time "
                        f"{max_delay_ms}ms configured in topology for queue '{queue_name}'",
                        delay=delay,
                        max_delay=max_delay_ms,
                        queue_name=queue_name,
                    )

            queue_name = self.topology.get_delay_queue_name(queue_name)
            message_eta = current_millis() + delay
            message = message.copy(
                queue_name=queue_name,
                options={
                    "eta": message_eta,
                },
            )

        self.logger.debug("Enqueueing message %r on queue %r.", message.message_id, queue_name)
        self.emit_before("enqueue", message, delay)

        try:
            self._enqueue_message(queue_name, message, delay=delay)
        except amqp.exceptions.ChannelError as exc:
            if exc.reply_code != 312:  # 312 - no-route
                raise

            with self._declare_lock:
                self.queues.discard(self.topology.get_canonical_queue_name(queue_name))
                self.declare_queue(queue_name, ensure=True)

            self._enqueue_message(queue_name, message, delay=delay)

        self.emit_after("enqueue", message, delay)
        return message

    def _enqueue_message(self, queue_name, message, *, delay=None):
        publish_kwargs = {
            "exchange": "",
            "routing_key": queue_name,
            "body": message.encode(),
            "delivery_mode": 2,
            "priority": message.options.get("broker_priority"),
            "retry": True,
            "retry_policy": {
                "max_retries": self._max_enqueue_attempts,
                "errback": self.on_connection_error_errback,
            },
            # will raise amqp.exceptions.ChannelError(312, ...) when route not found (e.g.: queue not exists)
            "mandatory": True,
            # Timeout for waiting publish confirmation from RabbitMQ.
            # Prevents deadlock when connection dies during confirm wait.
            "confirm_timeout": self._confirm_timeout,
        }

        # Set per-message TTL for delayed messages
        # Note: RabbitMQ per-message TTL has ordering limitations - messages expire
        # only when they reach the head of the queue. This means a message with
        # longer TTL can block messages with shorter TTL behind it.
        if delay is not None:
            # Convert delay (milliseconds) to TTL (seconds) for RabbitMQ expiration.
            # When message TTL expires in delay queue, RabbitMQ DLX automatically
            # routes it to the canonical queue for processing.
            message_ttl_seconds = delay / 1000.0
            publish_kwargs["expiration"] = message_ttl_seconds

        with self.connection_holder.acquire_producer(
            block=True,
            timeout=self._max_producer_acquire_timeout,
        ) as producer:
            return producer.publish(**publish_kwargs)

    def get_declared_queues(self):
        """Get all declared queues.

        Returns
        -------
          set[str]: The names of all the queues declared so far on
          this Broker.
        """
        return self.queues.copy()

    def flush(self, queue_name):
        """Drop all the messages from a queue.

        Parameters
        ----------
          queue_name(str): The queue to flush.
        """
        q_names = self.topology.get_queue_name_tuple(queue_name)

        with self.connection_holder.acquire_consumer_channel() as channel:
            for name in (q_names.canonical, q_names.delayed, q_names.dead_letter):
                if queue_name not in self.queues_pending:
                    channel.queue_purge(name)

    def flush_all(self):
        """Drop all messages from all declared queues."""
        for queue_name in self.queues:
            self.flush(queue_name)

    def delete_queue(self, queue_name, if_unused: bool = False, if_empty: bool = False):
        q_names = self.topology.get_queue_name_tuple(queue_name)

        with self._declare_lock:
            for name in (q_names.canonical, q_names.delayed, q_names.dead_letter):
                with (
                    contextlib.suppress(amqp.exceptions.NotAllowed),
                    self.connection_holder.acquire_consumer_channel() as channel,
                ):
                    channel.queue_delete(name, if_unused=if_unused, if_empty=if_empty)

            self.queues.discard(queue_name)
            self.queues_pending.add(queue_name)

    def delete_all(self, include_pending: bool = False):
        queues = self.queues.copy()

        if include_pending:
            queues |= self.queues_pending

        uniq_names = set(self.topology.get_canonical_queue_name(qname) for qname in queues)

        for queue_name in uniq_names:
            self.delete_queue(queue_name)

    def consume(self, queue_name, prefetch=1, timeout=5000):
        timeout = dt.timedelta(milliseconds=timeout)
        consumer = self.DramatiqConsumer(
            self.connection_holder.acquire_consumer_channel(),
            queue_name,
            prefetch,
            timeout,
            blocking_acknowledge=self._blocking_acknowledge,
        )

        try:
            consumer.check()
        except amqp.exceptions.NotFound:
            self.logger.info("Queue %s does not exists, ensure declaring", queue_name)
            with self._declare_lock:
                self.queues.discard(queue_name)
                self.declare_queue(queue_name, ensure=True)
        else:
            with self._declare_lock:
                self.queues_pending.discard(queue_name)

        for callback in self._on_consume_started_callbacks:
            callback(queue_name)
        return consumer


class ConnectionPooledKombuBroker(KombuBroker):
    connection_holder_cls = PooledConnectionHolder
    connection_holder: PooledConnectionHolder


class ConnectionSharedKombuBroker(KombuBroker):
    connection_holder_cls = SharedConnectionHolder
    connection_holder: SharedConnectionHolder
    DramatiqConsumer = ThreadSafeDramatiqConsumer
