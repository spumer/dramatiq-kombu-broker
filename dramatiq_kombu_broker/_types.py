import typing as tp

import kombu
from kombu_pyamqp_threadsafe import ThreadSafeChannel

from .pooled_connection_holder import AutoConnectionReleaseChannel


class _ReleasableChannelProto(tp.Protocol):
    connection: kombu.Connection | None
    channel_id: int

    def release(self) -> None: ...

    def close(self): ...

    def queue_delete(
        self,
        queue: str = "",
        if_unused: bool = False,
        if_empty: bool = False,
        nowait: bool = False,
        argsig="Bsbbb",
    ): ...

    def __enter__(self) -> "_ReleasableChannelProto": ...
    def __exit__(self, exc_type, exc_val, exc_tb): ...


ReleasableChannel = tp.Union[
    ThreadSafeChannel, AutoConnectionReleaseChannel, _ReleasableChannelProto
]
