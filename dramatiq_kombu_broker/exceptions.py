"""Custom exceptions for dramatiq-kombu-broker."""


class DelayTooLongError(Exception):
    """Raised when message delay exceeds max_delay_time configured in topology.

    This error indicates that the requested delay for a message is too long
    and could cause memory issues in RabbitMQ. Reduce the delay or increase
    max_delay_time in topology configuration.

    Attributes
    ----------
        delay: Requested delay in milliseconds
        max_delay: Maximum allowed delay in milliseconds (from topology)
        queue_name: Queue where message was being enqueued

    Example:
        >>> from datetime import timedelta
        >>> from dramatiq_kombu_broker import DefaultDramatiqTopology, KombuBroker, DelayTooLongError
        >>> topology = DefaultDramatiqTopology(max_delay_time=timedelta(hours=3))
        >>> broker = KombuBroker(topology=topology)
        >>> # This will raise DelayTooLongError:
        >>> broker.enqueue(message, delay=4*60*60*1000)  # 4 hours in ms
    """

    def __init__(
        self,
        message: str,
        *,
        delay: int | None = None,
        max_delay: int | None = None,
        queue_name: str | None = None,
    ):
        super().__init__(message)
        self.delay = delay
        self.max_delay = max_delay
        self.queue_name = queue_name
