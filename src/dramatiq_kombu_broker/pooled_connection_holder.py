import logging
import threading

import kombu
import kombu.pools
from kombu.connection import ConnectionPool

from .connection_holder import ConnectionHolder

logger = logging.getLogger(__name__)


class AutoConnectionReleaseChannel:
    """Channel interface for connection object.

    Kombu does not have .release() method for channel and calling .close()
    This class change this behaviour and call .release() when channel should be closed.
    .release() method just return Connection to their pool instead closing the channel
    """

    def __init__(self, connection: kombu.Connection):
        super().__setattr__("_AutoConnectionReleaseChannel__connection", connection)
        super().__setattr__("_AutoConnectionReleaseChannel__channel", connection.default_channel)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def __getattr__(self, item):
        return getattr(self.__channel, item)

    def __setattr__(self, key, value):
        assert key not in ("close", "release")
        return setattr(self.__channel, key, value)

    def close(self):
        self.release()

    def release(self):
        self.__connection.release()


class PooledConnectionHolder(ConnectionHolder):
    def __init__(
        self,
        connection: kombu.Connection,
        *,
        consumer_pool_size: int | None = 100,
        producer_pool_size: int | None = 10,
        connect_max_retries: int | None = None,
    ):
        """
        :param connection: connection info
        :param consumer_pool_size: how much opened connection allowed to consume from RabbitMQ
            (default: not limited, respect dramatiq behaviour)
        :param producer_pool_size: how much simultaneously opened connection allowed
            when producing (publishing) messages to RabbitMQ
            Do not make this value too high. In peak, you can open too many connection which will not be used after.
        :param connect_max_retries: maximum number of retries trying to re-establish the connection,
            if the connection is lost/unavailable.
        """
        self._consumer_conn_pool: ConnectionPool = kombu.pools.register_group(
            kombu.pools.Connections(limit=consumer_pool_size)
        )[connection]
        self._producer_conn_pool: ConnectionPool = kombu.pools.register_group(
            kombu.pools.Connections(limit=producer_pool_size)
        )[connection]

        self._setup_lock = threading.Lock()

        self.recoverable_connection_errors = connection.recoverable_connection_errors
        self.recoverable_channel_errors = connection.recoverable_channel_errors
        self.connect_max_retries = connect_max_retries
        self.logger = logger.getChild(self.__class__.__name__)

    def _acquire_consumer_connection(
        self, ensure: bool = True, block=True, timeout=None
    ) -> kombu.Connection:
        conn = self._consumer_conn_pool.acquire(block=block, timeout=timeout)
        if ensure:
            conn.ensure_connection(
                errback=self.on_connection_error_errback,
                max_retries=self.connect_max_retries,
            )
        return conn

    def acquire_consumer_channel(self, block=True, timeout=None):
        conn = self._acquire_consumer_connection(ensure=True, block=block, timeout=timeout)
        return AutoConnectionReleaseChannel(conn)

    def acquire_producer(self, block=True, timeout: float | None = None):
        """Return Producer ready to produce messages.

        You MUST call .release() manually, or use context-manager
        """
        # ProducerPool do all required stuff,
        # e.g: acquire connection and return it to pool when Producer.release() called
        pool = kombu.pools.ProducerPool(self._producer_conn_pool)
        producer = pool.acquire(block=block, timeout=timeout)
        producer.connection.ensure_connection(
            errback=self.on_connection_error_errback,
            max_retries=self.connect_max_retries,
        )
        return producer

    def close(self):
        with self._setup_lock:
            self._consumer_conn_pool.resize(
                limit=self._consumer_conn_pool.limit,
                reset=True,
                ignore_errors=True,
            )
            # https://github.com/celery/kombu/issues/2018
            self._consumer_conn_pool._closed = False

            self._producer_conn_pool.resize(
                limit=self._producer_conn_pool.limit,
                reset=True,
                ignore_errors=True,
            )
            # https://github.com/celery/kombu/issues/2018
            self._producer_conn_pool._closed = False
