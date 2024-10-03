import kombu.exceptions
import pytest
from dramatiq_kombu_broker.broker import ConnectionSharedKombuBroker
from dramatiq_kombu_broker.testing import get_consumer_connections


@pytest.mark.parametrize("kombu_broker_cls", ["conn-share"], indirect=True)
@pytest.mark.parametrize(
    "kombu_broker_connection_holder_options", [{"consumer_channel_pool_size": 1}], indirect=True
)
def test_connection_restored(
    kombu_broker_cls,
    kombu_broker: ConnectionSharedKombuBroker,
    kombu_broker_connection_holder_options,
):
    """Test internal connection ensured if closed"""
    with kombu_broker.connection_holder.acquire_consumer_channel() as channel:
        assert channel.is_open

    connection = get_consumer_connections(kombu_broker)[0]

    assert connection.connected
    kombu_broker.connection_holder.close()
    assert not connection.connected

    # ensure can open new channel
    with kombu_broker.connection_holder.acquire_consumer_channel() as channel:
        assert channel.is_open

    assert connection.connected


@pytest.mark.parametrize("kombu_broker_cls", ["conn-share"], indirect=True)
@pytest.mark.parametrize(
    "kombu_broker_connection_holder_options", [{"consumer_channel_pool_size": 1}], indirect=True
)
def test_consumer_channel_pool__limit_exceeded__error(
    kombu_broker_cls,
    kombu_broker: ConnectionSharedKombuBroker,
    kombu_broker_connection_holder_options,
):
    with (
        kombu_broker.connection_holder.acquire_consumer_channel() as _
    ):  # now free channels is zero
        with pytest.raises(kombu.exceptions.ChannelLimitExceeded):
            with kombu_broker.connection_holder.acquire_consumer_channel() as _:  # no free channels
                pass

    # now all channels in pool again, can acquire
    with kombu_broker.connection_holder.acquire_consumer_channel() as _:
        pass
