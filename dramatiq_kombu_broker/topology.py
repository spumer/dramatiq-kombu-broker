import abc
import dataclasses
import datetime as dt
import functools
import logging
import os
import typing as tp
import warnings

import amqp.exceptions
import dramatiq.common
import kombu
from kombu.transport.virtual import Channel

module_logger = logging.getLogger(__name__)

dramatiq_rabbitmq_dlq_ttl = dt.timedelta(
    milliseconds=int(os.getenv("dramatiq_dead_message_ttl", 86400000 * 7))
)


class QueueName(tp.NamedTuple):
    canonical: str
    delayed: str
    dead_letter: str


# Use functional syntax for TypedDict to support dash-keys (RabbitMQ convention)
# See:
# - https://www.rabbitmq.com/docs/queues
# - https://www.rabbitmq.com/docs/ttl
# - https://www.rabbitmq.com/docs/dlx
RabbitMQQueueArguments = tp.TypedDict(
    "RabbitMQQueueArguments",
    {
        # Message TTL in milliseconds. Messages older than TTL are dead-lettered or discarded.
        "x-message-ttl": int,
        # Exchange to route dead-lettered messages to.
        "x-dead-letter-exchange": str,
        # Routing key for dead-lettered messages.
        "x-dead-letter-routing-key": str,
        # Maximum priority level (1-255) the queue should support.
        "x-max-priority": int,
        # Queue auto-expires after being unused for this time (milliseconds).
        "x-expires": int,
        # Maximum number of ready messages in queue.
        "x-max-length": int,
        # Maximum total size of ready messages in bytes.
        "x-max-length-bytes": int,
        # Overflow behavior: "drop-head", "reject-publish", "reject-publish-dlx".
        "x-overflow": str,
        # Queue type: "classic" or "quorum".
        "x-queue-type": str,
        # Queue mode: "default" or "lazy".
        "x-queue-mode": str,
        # Enable single active consumer mode.
        "x-single-active-consumer": bool,
    },
    total=False,
)


class RabbitMQTopology(abc.ABC):
    """Base interface for Dramatiq queue topology implementations.

    Defines the contract for queue naming conventions and queue declaration
    operations that any topology implementation must support.
    """

    max_delay_time: dt.timedelta | None

    @classmethod
    @abc.abstractmethod
    def get_queue_name_tuple(cls, queue_name: str) -> QueueName:
        """Get all queue name variants for a given queue.

        :param queue_name: Base queue name
        :return: Named tuple with (canonical, delayed, dead_letter) queue names
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def get_canonical_queue_name(cls, queue_name: str) -> str:
        """Get the canonical queue name.

        :param queue_name: Base queue name
        :return: Canonical queue name
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def get_dead_letter_queue_name(cls, queue_name: str) -> str:
        """Get the dead letter queue name.

        :param queue_name: Base queue name
        :return: Dead letter queue name
        """
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def get_delay_queue_name(cls, queue_name: str) -> str:
        """Get the delay queue name.

        :param queue_name: Base queue name
        :return: Delay queue name
        """
        raise NotImplementedError

    @abc.abstractmethod
    def declare_canonical_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ) -> kombu.Queue:
        """Declare the canonical queue.

        :param channel: Kombu channel
        :param queue_name: Queue name to declare
        :param ignore_different_topology: If True, ignore PreconditionFailed errors
        :return: Declared queue object
        """
        raise NotImplementedError

    @abc.abstractmethod
    def declare_delay_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ) -> kombu.Queue:
        """Declare the delay queue.

        :param channel: Kombu channel
        :param queue_name: Queue name to declare
        :param ignore_different_topology: If True, ignore PreconditionFailed errors
        :return: Declared queue object
        """
        raise NotImplementedError

    @abc.abstractmethod
    def declare_dead_letter_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ) -> kombu.Queue:
        """Declare the dead letter queue.

        :param channel: Kombu channel
        :param queue_name: Queue name to declare
        :param ignore_different_topology: If True, ignore PreconditionFailed errors
        :return: Declared queue object
        """
        raise NotImplementedError


@dataclasses.dataclass
class DefaultDramatiqTopology(RabbitMQTopology):
    logger: logging.Logger = module_logger.getChild("Topology")
    dlx_exchange_name: str = ""
    durable: bool = True
    auto_delete: bool = False
    max_priority: int | None = None
    #: None - disable, timedelta - set given TTL as `x-message-ttl` argument
    dead_letter_message_ttl: dt.timedelta | None = dramatiq_rabbitmq_dlq_ttl
    #: Maximum delay time for delayed messages.
    #: None - unlimited (default, backward compatible)
    #: timedelta - raise DelayTooLongError if delay exceeds this value
    max_delay_time: dt.timedelta | None = None

    @classmethod
    @functools.lru_cache
    def get_queue_name_tuple(cls, queue_name: str) -> QueueName:
        """Fast shortcut to get all queue name varaiants

        :param queue_name:
        :return: named tuple with names, (canonical, delayed, dead_letter)
        Names can be accessed via attribute
        """
        canonical_name = cls.get_canonical_queue_name(queue_name)
        delay_name = cls.get_delay_queue_name(queue_name)
        dlq_name = cls.get_dead_letter_queue_name(queue_name)
        return QueueName(canonical_name, delay_name, dlq_name)

    @classmethod
    def get_canonical_queue_name(cls, queue_name):
        """Returns the canonical queue name for a given queue."""
        return dramatiq.common.q_name(queue_name)

    @classmethod
    def get_dead_letter_queue_name(cls, queue_name):
        """Returns the dead letter queue name for a given queue.  If the
        given queue name belongs to a delayed queue, the dead letter queue
        name for the original queue is generated.
        """
        return dramatiq.common.xq_name(queue_name)

    @classmethod
    def get_delay_queue_name(cls, queue_name):
        """Returns the delayed queue name for a given queue.  If the given
        queue name already belongs to a delayed queue, then it is returned
        unchanged.
        """
        return dramatiq.common.dq_name(queue_name)

    def _get_canonical_queue_arguments(
        self, queue_name: str, dlx: bool = True
    ) -> RabbitMQQueueArguments:
        queue_arguments: RabbitMQQueueArguments = {}

        if dlx:
            queue_arguments |= {
                "x-dead-letter-exchange": self.dlx_exchange_name,
                "x-dead-letter-routing-key": self.get_dead_letter_queue_name(queue_name),
            }

        if self.max_priority:
            queue_arguments["x-max-priority"] = self.max_priority

        return queue_arguments

    def _get_delay_queue_arguments(self, queue_name: str) -> RabbitMQQueueArguments:
        """Get arguments for delay queue.

        Delay queues must have dead-letter parameters to route expired messages
        back to the canonical queue. When a message's TTL expires in the delay queue,
        it is automatically routed to the canonical queue via the dead-letter mechanism.

        This method reuses canonical queue arguments (without DLX) so that any future
        canonical queue options automatically apply to delay queues.

        If max_delay_time is configured, sets x-message-ttl as a failsafe to prevent
        memory exhaustion from messages stuck in delay queue. RabbitMQ will automatically
        route messages to canonical queue via DLX when TTL expires.

        See issues #6 and #7.
        """
        # Start from canonical queue arguments (without DLX) to inherit common options
        queue_arguments = self._get_canonical_queue_arguments(queue_name, dlx=False)

        # Override DLX routing to point to the canonical queue
        canonical_queue_name = self.get_canonical_queue_name(queue_name)
        queue_arguments |= {
            "x-dead-letter-exchange": self.dlx_exchange_name,
            "x-dead-letter-routing-key": canonical_queue_name,
        }

        # Failsafe: Set queue TTL if max_delay_time is configured
        # This protects against memory issues from excessively delayed messages
        if self.max_delay_time is not None:
            ttl_ms = int(self.max_delay_time.total_seconds() * 1000)
            queue_arguments["x-message-ttl"] = ttl_ms

        return queue_arguments

    def _get_dead_letter_queue_arguments(self, queue_name: str) -> RabbitMQQueueArguments:
        if self.dead_letter_message_ttl is None:
            return {}

        # The value of the TTL argument or policy must be a non-negative integer (equal to or greater than zero),
        # describing the TTL period in milliseconds.
        ttl = int(self.dead_letter_message_ttl.total_seconds() * 1000)
        return {
            "x-message-ttl": ttl,
        }

    def _declare_queue(
        self,
        channel: Channel,
        queue_name: str,
        queue_arguments: RabbitMQQueueArguments,
        *,
        ignore_different_topology: bool = False,
    ) -> kombu.Queue:
        queue = kombu.Queue(
            queue_name,
            channel=channel,
            durable=self.durable,
            auto_delete=self.auto_delete,
            queue_arguments=queue_arguments,
        )

        self.logger.info("Declare queue %r (channel=%r)", queue_name, channel.channel_id)

        try:
            queue.declare()
        except amqp.exceptions.PreconditionFailed as exc:
            if not ignore_different_topology:
                raise

            errmsg = str(exc)
            is_inequivalent_args = "inequivalent arg" in errmsg.lower()
            if not is_inequivalent_args:
                raise

            self.logger.info(
                "Queue %r can not be declared with given topology (Precondition failed: %s)."
                " Skip declaring (ignore_different_topology=True)",
                queue_name,
                errmsg,
            )
        return queue

    def declare_canonical_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ):
        queue_arguments = self._get_canonical_queue_arguments(queue_name, dlx=True)
        return self._declare_queue(
            channel,
            queue_name,
            queue_arguments,
            ignore_different_topology=ignore_different_topology,
        )

    def declare_delay_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ):
        queue_arguments = self._get_delay_queue_arguments(queue_name)
        return self._declare_queue(
            channel,
            queue_name,
            queue_arguments,
            ignore_different_topology=ignore_different_topology,
        )

    def declare_dead_letter_queue(
        self,
        channel: Channel,
        queue_name: str,
        *,
        ignore_different_topology: bool = False,
    ):
        queue_arguments = self._get_dead_letter_queue_arguments(queue_name)
        return self._declare_queue(
            channel,
            queue_name,
            queue_arguments,
            ignore_different_topology=ignore_different_topology,
        )


@dataclasses.dataclass
class DLXRoutingTopology(DefaultDramatiqTopology):
    """Alternative topology that routes expired delay queue messages to DLX.

    This topology implements an alternative routing strategy where delayed messages
    that expire in the delay queue are routed to the dead letter queue (DLX)
    instead of directly to the canonical queue.

    Flow: delay_queue (expires) → dead_letter_queue (final destination)

    Messages remain in DLX and are NOT automatically forwarded to canonical queue.
    You need to process them manually (e.g., separate consumer for DLX queues).

    This can be useful for:
    - Monitoring/logging of delayed messages before manual processing
    - Custom processing pipelines with explicit control over message flow
    - Audit trails for delayed messages

    Note: This is NOT the standard dramatiq behavior. Use DefaultDramatiqTopology
    for standard behavior where delay_queue → canonical_queue directly.

    For automatic forwarding from DLX to canonical queue, create a custom topology
    (see MonitoringTopology example in docs/topologies.md).

    Attributes
    ----------
        max_delay_time: Maximum delay time for delayed messages.
            Sets x-message-ttl on delay queue. When a message exceeds this TTL,
            it is automatically routed to the dead letter queue via DLX.

    Example usage:
        broker = KombuBroker(
            topology=DLXRoutingTopology(
                max_delay_time=dt.timedelta(hours=3),
            ),
            ...
        )
    """

    #: Deprecated: use max_delay_time instead
    delay_queue_ttl: dataclasses.InitVar[dt.timedelta | None] = None

    #: no ttl on dlx, it's a final point for message
    dead_letter_message_ttl: dt.timedelta | None = None

    def __post_init__(self, delay_queue_ttl: dt.timedelta | None):
        # Migrate deprecated delay_queue_ttl to max_delay_time
        if delay_queue_ttl is not None:
            warnings.warn(
                "delay_queue_ttl is deprecated, use max_delay_time instead",
                DeprecationWarning,
                stacklevel=2,
            )
            # delay_queue_ttl takes priority when explicitly provided (backward compat)
            self.max_delay_time = delay_queue_ttl

    def _get_delay_queue_arguments(self, queue_name: str) -> RabbitMQQueueArguments:
        """Route expired delay queue messages to DLX instead of canonical queue.

        Sets x-message-ttl based on max_delay_time configuration.
        """
        # Start from canonical queue arguments (without DLX) to inherit common options
        queue_arguments = self._get_canonical_queue_arguments(queue_name, dlx=False)

        # Get the canonical and DLX queue names
        canonical_queue_name = self.get_canonical_queue_name(queue_name)
        dlx_queue_name = self.get_dead_letter_queue_name(canonical_queue_name)

        # Override DLX routing to point to DLX queue (not canonical)
        queue_arguments |= {
            "x-dead-letter-exchange": self.dlx_exchange_name,
            "x-dead-letter-routing-key": dlx_queue_name,
        }

        # Set queue TTL if max_delay_time is configured
        if self.max_delay_time is not None:
            ttl_ms = int(self.max_delay_time.total_seconds() * 1000)
            queue_arguments["x-message-ttl"] = ttl_ms

        return queue_arguments
