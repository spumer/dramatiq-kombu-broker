# API Reference

Complete API documentation for dramatiq-kombu-broker.

## Broker Classes

### ConnectionPooledKombuBroker

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    middleware=None,
    default_queue_name="default",
    blocking_acknowledge=True,
    connection_holder_options=None,
    kombu_connection_options={},
    confirm_delivery=True,
    max_priority=None,
    max_enqueue_attempts=None,
    max_declare_attempts=None,
    max_producer_acquire_timeout=10.0,
    confirm_timeout=5.0,
    topology=None,
)
```

**Parameters:**
- `middleware` - List of middleware instances
- `default_queue_name` - Default queue name (default: `"default"`)
- `blocking_acknowledge` - Block on message acknowledgment (default: `True`)
- `connection_holder_options` - Dict with `max_connections` key
- `kombu_connection_options` - Connection parameters (see below)
- `confirm_delivery` - Wait for broker confirmation (default: `True`)
- `max_priority` - Max priority value for priority queues
- `max_enqueue_attempts` - Retry count for enqueue operations
- `max_declare_attempts` - Retry count for queue declarations
- `max_producer_acquire_timeout` - Timeout for acquiring producer (seconds)
- `confirm_timeout` - Timeout for RabbitMQ publish confirmation (default: `5.0` seconds)
- `topology` - Custom topology instance

### ConnectionSharedKombuBroker

Same parameters as `ConnectionPooledKombuBroker`, but `connection_holder_options` accepts:

```python
connection_holder_options={
    "consumer_channel_pool_size": 5  # Channel pool size
}
```

## Kombu Connection Options

```python
kombu_connection_options = {
    # Connection
    "hostname": "amqp://user:pass@host:5672/vhost",  # Or separate params:
    "hostname": "localhost",
    "port": 5672,
    "userid": "guest",
    "password": "guest",
    "virtual_host": "/",

    # SSL/TLS
    "ssl": False,
    "ssl_options": {
        "ca_certs": "/path/to/ca.pem",
        "certfile": "/path/to/cert.pem",
        "keyfile": "/path/to/key.pem",
    },

    # Timeouts
    "heartbeat": 60,  # Default value
    "connect_timeout": 10,

    # Transport options
    "transport_options": {
        "max_retries": 3,
        "interval_start": 0,
        "interval_step": 2,
        "interval_max": 30,
        "confirm_publish": True,
        "client_properties": {
            "connection_name": "my-app",
        },
    },
}
```

## Topology Classes

### DefaultDramatiqTopology

```python
from dramatiq_kombu_broker import DefaultDramatiqTopology

topology = DefaultDramatiqTopology(
    logger=None,
    dlx_exchange_name="",
    durable=True,
    auto_delete=False,
    max_priority=None,
    dead_letter_message_ttl=timedelta(days=7),
)
```

**Methods:**
- `get_canonical_queue_name(queue_name)` - Returns main queue name
- `get_delay_queue_name(queue_name)` - Returns delay queue name
- `get_dead_letter_queue_name(queue_name)` - Returns DLQ name
- `get_queue_name_tuple(queue_name)` - Returns `QueueName(canonical, delayed, dead_letter)`

### DLXRoutingTopology

```python
from dramatiq_kombu_broker import DLXRoutingTopology
import datetime as dt

topology = DLXRoutingTopology(
    max_delay_time=dt.timedelta(hours=24),
    dead_letter_message_ttl=None,
    # ... plus all DefaultDramatiqTopology parameters
)
```

Routes delay queue → DLX → canonical queue.

## Broker Methods

### declare_queue

```python
broker.declare_queue(queue_name, ensure=False)
```

Declare a queue. If `ensure=True`, creates queues immediately.

### get_queue_message_counts

```python
main, delay, dlq = broker.get_queue_message_counts("myqueue")
```

Returns tuple of message counts in (main, delay, dead_letter) queues.

### flush

```python
broker.flush("myqueue")  # Clear all messages
```

### flush_all

```python
broker.flush_all()  # Clear all queues
```

### delete_queue

```python
broker.delete_queue("myqueue")
```

Delete queue and associated delay/DLQ queues.

### close

```python
broker.close()
```

Close all connections.

## Testing Utilities

### ensure_consumer_connection_rabbitmq

```python
from dramatiq_kombu_broker.testing import ensure_consumer_connection_rabbitmq

try:
    ensure_consumer_connection_rabbitmq(broker)
    print("Connection healthy")
except Exception as e:
    print(f"Connection failed: {e}")
```

Tests broker connection health.

## Type Definitions

### QueueName

```python
from dramatiq_kombu_broker.topology import QueueName

names = QueueName(
    canonical="myqueue",
    delayed="myqueue.DQ",
    dead_letter="myqueue.XQ"
)

print(names.canonical)  # "myqueue"
print(names.delayed)    # "myqueue.DQ"
print(names.dead_letter)  # "myqueue.XQ"
```

### KombuConnectionOptions

```python
from dramatiq_kombu_broker import KombuConnectionOptions

options: KombuConnectionOptions = {
    "hostname": "localhost",
    "port": 5672,
    # ... other connection params
}
```

### KombuTransportOptions

```python
from dramatiq_kombu_broker import KombuTransportOptions

transport_options: KombuTransportOptions = {
    "max_retries": 3,
    "interval_start": 0,
    # ... other transport params
}
```

## Exports

Module `dramatiq_kombu_broker` exports:

```python
from dramatiq_kombu_broker import (
    # Brokers
    KombuBroker,
    ConnectionPooledKombuBroker,
    ConnectionSharedKombuBroker,

    # Topologies
    DefaultDramatiqTopology,
    DLXRoutingTopology,

    # Types
    KombuConnectionOptions,
    KombuTransportOptions,
    MessageProxy,
)
```

## Environment Variables

### DRAMATIQ_DEAD_MESSAGE_TTL

TTL for dead letter queue messages (milliseconds):

```bash
export DRAMATIQ_DEAD_MESSAGE_TTL=604800000  # 7 days
```

## Django Integration

### Settings

```python
# settings.py
DRAMATIQ_BROKER = {
    "BROKER": "dramatiq_kombu_broker.broker.ConnectionSharedKombuBroker",
    "OPTIONS": {
        "kombu_connection_options": {...},
        "connection_holder_options": {...},
        # ... other broker options
    },
}
```

## Next Steps

- [Examples](examples.md) - See API usage examples
- [Configuration](configuration.md) - Detailed configuration guide
- [Topologies](topologies.md) - Queue topology configuration
