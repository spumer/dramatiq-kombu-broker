# Alternatives Comparison

How dramatiq-kombu-broker compares to other solutions for RabbitMQ connection management.

## Overview

Different tools solve different problems:

- **dramatiq-kombu-broker** - Dramatiq broker with built-in pooling
- **AMQProxy** - Standalone proxy for connection pooling
- **AMQPStorm** - Low-level AMQP client library

## dramatiq-kombu-broker vs AMQProxy

### What is AMQProxy?

[AMQProxy](https://github.com/cloudamqp/amqproxy) is a standalone proxy that sits between your application and RabbitMQ. It pools connections and channels, so short-lived applications (like PHP scripts) don't create connection churn.

Architecture:
```
App → AMQProxy (localhost:5673) → RabbitMQ (host:5672)
```

### Key Differences

| Aspect | dramatiq-kombu-broker | AMQProxy |
|--------|----------------------|----------|
| **Type** | Python library | Standalone proxy |
| **Deployment** | In-process | Separate service |
| **Language** | Python | Crystal |
| **Scope** | Dramatiq only | Any AMQP client |
| **Pooling** | Native Python | Proxy-level |
| **Latency** | Direct connection | Extra proxy hop |
| **Maintenance** | Python package | Additional service |

### When to Use AMQProxy

Use AMQProxy if:

- You have **PHP or other short-lived** applications
- **Multiple languages** connect to same RabbitMQ
- Cannot modify application code
- Need **cross-platform** solution (works with any AMQP 0.9.1 client)
- Publishing **1 message per connection** (50x throughput improvement)

Example: PHP application that opens connection per request:
```php
// Without AMQProxy: opens new connection each time (slow)
$connection = new AMQPConnection(['host' => 'rabbitmq']);

// With AMQProxy: connection reused (fast)
$connection = new AMQPConnection(['host' => 'amqproxy', 'port' => 5673]);
```

### When to Use dramatiq-kombu-broker

Use dramatiq-kombu-broker if:

- You're using **Python and Dramatiq**
- Want **native integration** without external services
- Need **custom topology control**
- Running **long-lived Python workers**
- Prefer **fewer moving parts** in infrastructure

### Can You Use Both?

Yes, but typically unnecessary:

```python
# dramatiq-kombu-broker connecting through AMQProxy
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://localhost:5673/"  # AMQProxy address
    }
)
```

This adds an extra hop with minimal benefit for Python applications.

### Performance Comparison

**AMQProxy** ([source](https://www.cloudamqp.com/blog/maintaining-long-lived-connections-with-AMQProxy.html)):
- Publishing 1 message per connection (with TLS, 50ms RTT):
  - Without proxy: **0.50s** per message
  - With proxy: **0.01s** per message (50x faster!)

**dramatiq-kombu-broker**:
- Keeps connections open between messages
- No per-message connection overhead
- Similar performance to AMQProxy for Python apps

## dramatiq-kombu-broker vs AMQPStorm

### What is AMQPStorm?

[AMQPStorm](https://github.com/eandersson/amqpstorm) is a thread-safe Python AMQP 0.9.1 client library. It's a low-level library for working with RabbitMQ directly.

### Key Differences

| Aspect | dramatiq-kombu-broker | AMQPStorm |
|--------|----------------------|-----------|
| **Level** | High-level (Dramatiq broker) | Low-level (AMQP client) |
| **Task Queue** | Built-in (Dramatiq) | Not included |
| **Connection Management** | Automatic | Manual |
| **Threading** | Thread-safe channels | Thread-safe connections |
| **Retries** | Dramatiq handles | Manual implementation |
| **API** | Dramatiq actors | Direct AMQP operations |

### When to Use AMQPStorm

Use AMQPStorm if:

- Building **custom message patterns** (not task queue)
- Need **low-level AMQP control**
- Want **minimal dependencies**
- Implementing **your own** task queue
- **Not using Dramatiq** at all

Example AMQPStorm usage:
```python
import amqpstorm

# Direct AMQP operations
connection = amqpstorm.Connection('localhost', 'guest', 'guest')
channel = connection.channel()
channel.queue.declare('my_queue')
channel.basic.publish('Hello', 'my_queue')
```

### When to Use dramatiq-kombu-broker

Use dramatiq-kombu-broker if:

- You're using **Dramatiq** for task queue
- Want **high-level abstractions** (actors, retries, etc.)
- Need **production-ready** task processing
- Prefer **less boilerplate** code

Example dramatiq-kombu-broker:
```python
import dramatiq
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://localhost"}
)
dramatiq.set_broker(broker)

@dramatiq.actor
def send_email(email):
    # Automatically handles: retries, delays, priorities, etc.
    pass

send_email.send("user@example.com")
```

### Could You Build dramatiq-kombu-broker on AMQPStorm?

Theoretically yes, but Kombu already provides:

- Battle-tested AMQP abstraction
- Works with multiple brokers (RabbitMQ, Redis, etc.)
- Large ecosystem and community
- Thread-safe channel pooling (via kombu-pyamqp-threadsafe)

## Comparison Matrix

| Feature | dramatiq-kombu-broker | AMQProxy | AMQPStorm |
|---------|----------------------|----------|-----------|
| **Primary Use Case** | Dramatiq task queue | Cross-language pooling | Custom AMQP apps |
| **Connection Pooling** | ✅ Yes | ✅ Yes | ❌ Manual |
| **Channel Pooling** | ✅ Yes | ✅ Yes | ❌ Manual |
| **Language** | Python | Any AMQP client | Python |
| **Deployment** | Library | Standalone service | Library |
| **Task Queue** | ✅ Dramatiq | ❌ No | ❌ No |
| **Thread Safety** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Learning Curve** | Low (if using Dramatiq) | Low | Medium-High |
| **Latency** | Direct | +1 hop | Direct |
| **Management API** | Via Kombu | ❌ No | ✅ Yes |
| **SSL/TLS** | ✅ Yes | ✅ Yes | ✅ Yes |

## Real-World Scenarios

### Scenario 1: PHP + Python Mixed

**Setup:** PHP web app + Python workers

**Solution:** AMQProxy

- PHP publishes via AMQProxy (pools connections)
- Python workers consume directly or via AMQProxy
- Single pooling solution for all languages

### Scenario 2: Pure Python Task Queue

**Setup:** Django/Flask + Dramatiq workers

**Solution:** dramatiq-kombu-broker

- No external services needed
- Native Dramatiq integration
- Fewer moving parts

### Scenario 3: Custom Message Broker

**Setup:** Building your own pub/sub system

**Solution:** AMQPStorm

- Full AMQP control
- Implement custom patterns
- Direct access to protocol features

### Scenario 4: Short-Lived Scripts

**Setup:** Cron jobs publishing to RabbitMQ

**Solution:** AMQProxy or dramatiq-kombu-broker

- **AMQProxy:** If scripts in different languages
- **dramatiq-kombu-broker:** If all Python scripts

## Migration Paths

### From Standard Dramatiq → dramatiq-kombu-broker

Simple drop-in replacement. See [Migration Guide](migration.md).

### From AMQProxy → dramatiq-kombu-broker

```python
# Before: connecting through AMQProxy
RABBITMQ_URL = "amqp://localhost:5673/"

# After: direct connection with pooling
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://rabbitmq:5672/"  # Direct to RabbitMQ
    }
)
```

Then stop AMQProxy service.

### From AMQPStorm → dramatiq-kombu-broker

Requires rewriting code to use Dramatiq actors instead of direct AMQP calls. Worth it if you want task queue features.

## When to Use Each

**Use dramatiq-kombu-broker when:**
- Python + Dramatiq task queue
- Want integrated solution
- Need topology control
- Long-lived workers

**Use AMQProxy when:**
- Multiple languages
- Short-lived connections (PHP, etc.)
- Cannot change application code
- Need universal solution

**Use AMQPStorm when:**
- Building custom AMQP application
- Need low-level control
- Not using task queue
- Implementing custom patterns

## Sources

- [AMQProxy GitHub](https://github.com/cloudamqp/amqproxy)
- [AMQProxy Blog Post](https://www.cloudamqp.com/blog/maintaining-long-lived-connections-with-AMQProxy.html)
- [AMQPStorm GitHub](https://github.com/eandersson/amqpstorm)
- [AMQPStorm Documentation](https://amqpstorm.readthedocs.io/)

## Next Steps

- [Installation](installation.md) - Get started with dramatiq-kombu-broker
- [Configuration](configuration.md) - Configure connection pooling
- [Migration Guide](migration.md) - Migrate from other solutions
