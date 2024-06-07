import kombu


class AutoChannelReleaseProducer(kombu.Producer):
    """Inherit kombu.Producer but try release internal channel if it's possible

    Very useful with ChannelPool's
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.__connection__ is None:
            # preserve connection instance to later ensure
            # due channel can miss it after close
            self.__connection__ = self._channel.connection.client

    def release(self):
        if hasattr(self.channel, "release"):
            self.channel.release()
