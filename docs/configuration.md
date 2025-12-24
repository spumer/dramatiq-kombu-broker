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
    "heartbeat": 60,  # Heartbeat interval in seconds (default: 60)
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

**How it works:**

When an actor is declared, the broker checks if its `queue_name` equals `"default"`. If so, it automatically replaces it with the configured `default_queue_name`. This happens at actor declaration time, so no code changes are needed in your actors.

**When replacement happens:**

| Actor Definition | default_queue_name | Resulting Queue |
|-----------------|-------------------|-----------------|
| `@dramatiq.actor` | `"myapp"` | `"myapp"` |
| `@dramatiq.actor(queue_name="default")` | `"myapp"` | `"myapp"` |
| `@dramatiq.actor(queue_name="critical")` | `"myapp"` | `"critical"` |

**Example:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    default_queue_name="myapp",
)
dramatiq.set_broker(broker)

# This actor uses "default" queue by default
# It will be automatically changed to "myapp"
@dramatiq.actor
def send_email(to: str, subject: str):
    pass

# This actor explicitly uses "critical" queue
# It will NOT be changed (keeps "critical")
@dramatiq.actor(queue_name="critical")
def urgent_notification(message: str):
    pass
```

**Use cases:**

- **Migration**: Replace queue names when migrating from another broker without touching actor code
- **Multi-tenant**: Run separate instances with different queue prefixes
- **Namespacing**: Prefix queues with application name to avoid conflicts in shared RabbitMQ

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

### confirm_timeout

Timeout for waiting RabbitMQ publish confirmation (default: `5.0` seconds):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_timeout=5.0,  # Default: 5 seconds
)
```

When `confirm_delivery=True`, the broker waits for RabbitMQ to confirm that the message was received. Without a timeout, this wait can block indefinitely if the connection drops during publishing, causing a **deadlock**.

**Why this matters:**

- Prevents worker threads from hanging forever on connection failures
- Works in conjunction with `heartbeat=60` (different protection levels)
- `heartbeat` detects dead connections at the transport level
- `confirm_timeout` prevents blocking at the application level during publish

**Recommended values:**

| Scenario | confirm_timeout | Notes |
|----------|-----------------|-------|
| Production (default) | `5.0` | Good balance of safety and responsiveness |
| High-latency networks | `10.0` - `30.0` | Allow more time for slow confirmations |
| Local development | `5.0` | Default is usually sufficient |
| Disable timeout | `None` | **Not recommended** - can cause deadlocks |

**Relationship with other parameters:**

- `confirm_delivery=True` - Required for `confirm_timeout` to have effect
- `heartbeat=60` - Detects dead connections (complementary protection)
- `max_producer_acquire_timeout` - Timeout for getting producer from pool (different stage)

**See [Delivery Guarantees](delivery-guarantees.md#confirm_timeout-deadlock-protection) for detailed explanation.**

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
    confirm_timeout=5.0,  # Deadlock protection
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
- ✅ Set `confirm_timeout` for deadlock protection (default: 5.0s is usually sufficient)
- ✅ Heartbeat set to 60s by default - adjust for unreliable networks if needed
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
