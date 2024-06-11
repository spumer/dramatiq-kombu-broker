import dataclasses
import datetime as dt
import logging
import typing as tp

import amqp.exceptions
import kombu
from kombu.transport.virtual import Channel

import dramatiq.common

module_logger = logging.getLogger(__name__)


@dataclasses.dataclass
class DefaultDramatiqTopology:
    logger: logging.Logger = module_logger.getChild("Topology")
    dlx_exchange_name: str = ""
    durable: bool = True
    auto_delete: bool = False
    max_priority: tp.Optional[int] = None
    dead_letter_message_ttl: tp.Optional[dt.timedelta] = None

    def get_canonical_queue_name(self, queue_name):
        """Returns the canonical queue name for a given queue."""
        return dramatiq.common.q_name(queue_name)

    def get_dead_letter_queue_name(self, queue_name):
        """Returns the dead letter queue name for a given queue.  If the
        given queue name belongs to a delayed queue, the dead letter queue
        name for the original queue is generated.
        """
        return dramatiq.common.xq_name(queue_name)

    def get_delay_queue_name(self, queue_name):
        """Returns the delayed queue name for a given queue.  If the given
        queue name already belongs to a delayed queue, then it is returned
        unchanged.
        """
        return dramatiq.common.dq_name(queue_name)

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        queue_arguments = {}

        if dlx:
            queue_arguments.update(
                {
                    "x-dead-letter-exchange": self.dlx_exchange_name,
                    "x-dead-letter-routing-key": self.get_dead_letter_queue_name(queue_name),
                }
            )

        if self.max_priority:
            queue_arguments["x-max-priority"] = self.max_priority

        return queue_arguments

    def _get_delay_queue_arguments(self, queue_name: str) -> dict:
        return self._get_canonical_queue_arguments(queue_name, dlx=False)

    def _get_dead_letter_queue_arguments(self, queue_name: str) -> dict:
        if self.dead_letter_message_ttl is None:
            return {}

        # The value of the TTL argument or policy must be a non-negative integer (equal to or greater than zero),
        # describing the TTL period in milliseconds.
        ttl = self.dead_letter_message_ttl.total_seconds() * 1000
        return {
            "x-message-ttl": ttl,
        }

    def _declare_queue(
        self,
        channel: Channel,
        queue_name: str,
        queue_arguments: dict,
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
            self.logger.info(
                "Queue %r exists with different topology (Precondition failed: %s). Skip declaring.",
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
