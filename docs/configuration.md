# Configuration

Complete reference for configuring dramatiq-kombu-broker.

## Broker Types

dramatiq-kombu-broker provides three broker implementations:

### ConnectionPooledKombuBroker

Uses a connection pool for multiple connections to RabbitMQ.

**Best for:** High-throughput applications, multiple workers

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    connection_holder_options={
        "max_connections": 10,
    },
)
```

### ConnectionSharedKombuBroker

Uses a single shared connection with channel pooling.

**Best for:** Thread-heavy applications, Django applications

```python
from dramatiq_kombu_broker import ConnectionSharedKombuBroker

broker = ConnectionSharedKombuBroker(
    kombu_connection_options={...},
    connection_holder_options={
        "consumer_channel_pool_size": 5,
    },
)
```

### KombuBroker

Base broker class. Use specific implementations above.

## Connection Options

### kombu_connection_options

Dictionary with connection parameters:

```python
kombu_connection_options = {
    # Connection URL (alternative to individual params)
    "hostname": "amqp://user:pass@localhost:5672/vhost",

    # Or individual parameters:
    "hostname": "localhost",
    "port": 5672,
    "userid": "guest",
    "password": "guest",
    "virtual_host": "/",

    # SSL/TLS
    "ssl": True,
    "ssl_options": {
        "ca_certs": "/path/to/ca.pem",
        "certfile": "/path/to/cert.pem",
        "keyfile": "/path/to/key.pem",
    },

    # Timeouts
    "heartbeat": 60,  # Heartbeat interval in seconds
    "connect_timeout": 10,  # Connection timeout

    # Transport options
    "transport_options": {
        "max_retries": 3,
        "interval_start": 0,
        "interval_step": 2,
        "interval_max": 30,
        "confirm_publish": True,
    },
}
```

### Connection URL Format

```
amqp://username:password@hostname:port/virtual_host
```

Examples:

```python
# Local development
"hostname": "amqp://guest:guest@localhost:5672/"

# Production with SSL
"hostname": "amqps://user:pass@prod.rabbitmq.com:5671/production"

# With query parameters
"hostname": "amqp://user:pass@host:5672/?heartbeat=60"
```

## Broker Parameters

### default_queue_name

Change the default queue name (default: `"default"`):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    default_queue_name="myapp",  # Instead of "default"
)
```

### blocking_acknowledge

Whether to block when acknowledging messages (default: `True`):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=True,  # Wait for ACK confirmation
)
```

When `True`, worker waits for RabbitMQ to confirm that the message was acknowledged before processing the next message. This provides stronger delivery guarantees but slightly lower throughput.

**See [Delivery Guarantees](delivery-guarantees.md) for detailed explanation and best practices.**

### confirm_delivery

Confirm message delivery with RabbitMQ (default: `True`):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,  # Ensures messages are persisted
)
```

When `True`, RabbitMQ confirms that published messages were received and routed to queues. This uses [RabbitMQ Publisher Confirms](https://www.rabbitmq.com/docs/confirms) mechanism.

**See [Delivery Guarantees](delivery-guarantees.md) for detailed explanation and best practices.**

### max_priority

Enable priority queues with maximum priority value:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    max_priority=10,  # Priorities 0-10
)

# Usage:
@dramatiq.actor
def my_task():
    pass

my_task.send_with_options(args=(), broker_priority=10)  # High priority
```

### max_enqueue_attempts

Maximum retries when enqueuing messages (default: `None` - unlimited):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    max_enqueue_attempts=3,
)
```

### max_declare_attempts

Maximum retries when declaring queues (default: `None` - unlimited):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    max_declare_attempts=5,
)
```

### max_producer_acquire_timeout

Timeout for acquiring a producer from the pool (default: 10 seconds):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    max_producer_acquire_timeout=30.0,  # 30 seconds
)
```

### topology

Custom topology for queue routing (see [Topologies](topologies.md)):

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, DLXRoutingTopology
import datetime as dt

topology = DLXRoutingTopology(
    delay_queue_ttl=dt.timedelta(hours=3),
)

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    topology=topology,  # Use custom topology
)
```

## Connection Holder Options

### For ConnectionPooledKombuBroker

```python
connection_holder_options = {
    "max_connections": 10,  # Pool size
}
```

### For ConnectionSharedKombuBroker

```python
connection_holder_options = {
    "consumer_channel_pool_size": 5,  # Channel pool size
}
```

## Complete Example

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker
import dramatiq

broker = ConnectionPooledKombuBroker(
    # Connection settings
    kombu_connection_options={
        "hostname": "amqp://myapp:secret@rabbitmq.prod:5672/production",
        "heartbeat": 60,
        "ssl": True,
        "ssl_options": {
            "ca_certs": "/etc/ssl/certs/ca.pem",
        },
        "transport_options": {
            "max_retries": 3,
            "confirm_publish": True,
        },
    },

    # Pool settings
    connection_holder_options={
        "max_connections": 20,
    },

    # Broker settings
    default_queue_name="myapp",
    max_priority=10,
    confirm_delivery=True,
    blocking_acknowledge=True,
    max_enqueue_attempts=3,
    max_declare_attempts=5,
    max_producer_acquire_timeout=30.0,
)

dramatiq.set_broker(broker)
```

## Environment Variables

You can use environment variables for configuration:

```python
import os

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": os.environ["RABBITMQ_URL"],
    },
    max_priority=int(os.environ.get("RABBITMQ_MAX_PRIORITY", "10")),
)
```

Example `.env` file:

```bash
RABBITMQ_URL=amqp://guest:guest@localhost:5672/
RABBITMQ_MAX_PRIORITY=10
```

## Django Settings

For Django applications with django-dramatiq:

```python
# settings.py
import os

DRAMATIQ_BROKER = {
    "BROKER": "dramatiq_kombu_broker.broker.ConnectionSharedKombuBroker",
    "OPTIONS": {
        "kombu_connection_options": {
            "hostname": os.environ["RABBITMQ_URL"],
            "heartbeat": 60,
        },
        "connection_holder_options": {
            "consumer_channel_pool_size": 5,
        },
        "default_queue_name": "django_app",
        "max_priority": 10,
        "confirm_delivery": True,
    },
}
```

## Testing Configuration

For tests, use a separate RabbitMQ instance or vhost:

```python
# conftest.py
import pytest
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

@pytest.fixture
def broker():
    broker = ConnectionPooledKombuBroker(
        kombu_connection_options={
            "hostname": "amqp://guest:guest@localhost:5672/test",  # /test vhost
        },
    )
    yield broker
    broker.flush_all()  # Clean up after tests
    broker.close()
```

## Production Checklist

- ✅ Use SSL/TLS for production connections
- ✅ Enable `confirm_delivery` for reliability
- ✅ Set appropriate `heartbeat` (60 seconds recommended)
- ✅ Configure connection pooling based on workload
- ✅ Set `max_priority` if using priority queues
- ✅ Use separate vhosts for different environments
- ✅ Monitor connection count in RabbitMQ management UI
- ✅ Set `max_enqueue_attempts` and `max_declare_attempts` for resilience
- ✅ Configure proper retry policies in transport_options

## Next Steps

- [Topologies](topologies.md) - Learn about queue routing
- [Performance Tuning](performance.md) - Optimize for your workload
- [Examples](examples.md) - See real-world configurations
