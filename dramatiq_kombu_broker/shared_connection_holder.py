import logging
import threading

import kombu.exceptions
from kombu_pyamqp_threadsafe import KombuConnection as SharedKombuConnection
from kombu_pyamqp_threadsafe import ThreadSafeChannel

from .connection_holder import ConnectionHolder
from .producer import AutoChannelReleaseProducer

logger = logging.getLogger(__name__)


class SharedConnectionHolder(ConnectionHolder):
    def __init__(
        self,
        connection: kombu.Connection,
        *,
        consumer_channel_pool_size: int = 100,
        producer_channel_pool_size: int = 100,
        connect_max_retries=None,
    ):
        """
        :param connection: connection info
        :param consumer_channel_pool_size: maximum number of channels created in consumer connection (default: 100)
        :param producer_channel_pool_size: maximum number of channels created in producer connection (default: 100)
        :param connect_max_retries: maximum number of retries trying to re-establish the connection,
            if the connection is lost/unavailable.
        """
        connection = SharedKombuConnection.from_kombu_connection(connection)

        self._consumer_connection = connection.clone(
            default_channel_pool_size=consumer_channel_pool_size
        )
        self._producer_connection = connection.clone(
            default_channel_pool_size=producer_channel_pool_size
        )
        self._conn_lock = threading.RLock()
        self._consumer_channel_pool = None
        self._producer_channel_pool = None

        self.recoverable_connection_errors = connection.recoverable_connection_errors
        self.recoverable_channel_errors = connection.recoverable_channel_errors
        self.connect_max_retries = connect_max_retries
        self.logger = logger.getChild(self.__class__.__name__)

    def _get_consumer_connection(self, ensure: bool = True) -> SharedKombuConnection:
        conn = self._consumer_connection

        if ensure:
            with self._conn_lock:  # TODO: Condition, ensure only by one thread
                conn.ensure_connection(
                    errback=self.on_connection_error_errback,
                    max_retries=self.connect_max_retries,
                )

        return conn

    def _get_producer_connection(self, ensure: bool = True) -> SharedKombuConnection:
        conn = self._producer_connection

        if ensure:
            with self._conn_lock:
                conn.ensure_connection(
                    errback=self.on_connection_error_errback,
                    max_retries=self.connect_max_retries,
                )

        return conn

    def acquire_producer(self, block: bool = True, timeout: float | None = None):
        """Return kombu.Producer bind to produce connection

        You MUST call `.release()` manually or use context-manager
        """
        with self._conn_lock:
            conn = self._get_producer_connection(ensure=False)
            acquire = conn.ensure(  # TODO: make ensure threadsafe + use self._conn_lock on ensure
                conn,
                lambda *a, **kw: conn.default_channel_pool.acquire(*a, **kw),
                errback=self.on_connection_error_errback,
                max_retries=self.connect_max_retries,
            )
            channel = acquire(block=block, timeout=timeout)
            assert channel.is_open
            return AutoChannelReleaseProducer(channel)

    def acquire_consumer_channel(
        self,
        block: bool = False,
        timeout: float | None = None,
    ) -> ThreadSafeChannel:
        """Return Channel bind to consume connection

        You MUST call `.release()` manually or use context-manager
        """
        with self._conn_lock:
            conn = self._get_consumer_connection(ensure=False)
            acquire = conn.ensure(
                conn,
                lambda *a, **kw: conn.default_channel_pool.acquire(*a, **kw),
                errback=self.on_connection_error_errback,
                max_retries=self.connect_max_retries,
            )
            channel = acquire(block=block, timeout=timeout)
            assert channel.is_open
            return channel

    def close(self) -> None:
        if self._consumer_connection.connected:
            with self.reraise_as_library_errors():
                self._consumer_connection.close()

        if self._producer_connection.connected:
            with self.reraise_as_library_errors():
                self._producer_connection.close()
