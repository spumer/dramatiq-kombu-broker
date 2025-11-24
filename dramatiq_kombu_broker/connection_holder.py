import abc
import contextlib
import functools
import logging
import typing as tp

import dramatiq
import kombu
from kombu.utils.functional import retry_over_time

if tp.TYPE_CHECKING:
    # circular import possible
    from ._types import ReleasableChannel


class ConnectionHolder(abc.ABC):
    recoverable_connection_errors: tuple[Exception, ...]
    recoverable_channel_errors: tuple[Exception, ...]
    connect_max_retries: int | None
    logger: logging.Logger

    @abc.abstractmethod
    def __init__(self, connection: kombu.Connection, **kwargs):
        raise NotImplementedError

    def retry_connection_errors_over_time(
        self,
        func,
        max_retries,
        interval_start=2,
        interval_step=2,
        interval_max=30,
        errback=None,
        timeout=None,
        **retry_kwargs,
    ):
        retry_errors = self.recoverable_connection_errors + self.recoverable_channel_errors

        @functools.wraps(func)
        def _retry(*func_args, **func_kwargs):
            with self.reraise_as_library_errors():
                return retry_over_time(
                    func,
                    args=func_args,
                    kwargs=func_kwargs,
                    catch=retry_errors,
                    max_retries=max_retries,
                    interval_start=interval_start,
                    interval_step=interval_step,
                    interval_max=interval_max,
                    errback=errback,
                    timeout=timeout,
                    **retry_kwargs,
                )

        return _retry

    @contextlib.contextmanager
    def reraise_as_library_errors(
        self,
        ConnectionError=dramatiq.ConnectionError,  # noqa: N803,A002
        ChannelError=dramatiq.ConnectionError,  # noqa: N803
    ):
        try:
            yield
        except (ConnectionError, ChannelError):
            raise
        except self.recoverable_connection_errors as exc:
            raise ConnectionError(str(exc)) from exc
        except self.recoverable_channel_errors as exc:
            raise ChannelError(str(exc)) from exc

    def on_connection_error_errback(self, exc, slept_interval):
        self.logger.warning(
            "Broker connection error, trying again in %s seconds: %r.",
            slept_interval,
            exc,
            exc_info=True,
        )

    @abc.abstractmethod
    def acquire_producer(self, block=True, timeout: float | None = None):
        raise NotImplementedError

    @abc.abstractmethod
    def acquire_consumer_channel(
        self,
        block=True,
        timeout: float | None = None,
    ) -> "ReleasableChannel":
        raise NotImplementedError

    @abc.abstractmethod
    def close(self):
        raise NotImplementedError
