# Dramatiq Kombu Broker

A Kombu-based broker for [Dramatiq](https://dramatiq.io/) with connection pooling and better RabbitMQ integration.

## What This Does

`dramatiq-kombu-broker` replaces Dramatiq's standard RabbitMQ broker with one built on [Kombu](https://kombu.readthedocs.io/). The main benefits:

**Connection pooling** - The standard broker creates many connections that can overwhelm RabbitMQ. This broker pools connections properly.

**Channel pooling** - Via [kombu-pyamqp-threadsafe](https://github.com/spumer/kombu-pyamqp-threadsafe), you won't hit "Connection limit reached" errors in threaded applications.

**Topology management** - Change queue configurations without breaking your existing setup. The broker handles topology mismatches gracefully.

## Installation

```bash
pip install dramatiq-kombu-broker
```

## Quick Example

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker
import dramatiq

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/"
    }
)
dramatiq.set_broker(broker)

@dramatiq.actor
def process_task(task_id: int):
    print(f"Processing task {task_id}")

process_task.send(42)
```

## Other Features

- Hostname automatically added to connection properties (visible in RabbitMQ management UI)
- [Change default queue name](configuration.md#default_queue_name) without modifying all actors
- Built-in consumer healthchecks
- Message acknowledgment tracking (`Message.acknowledged`)
- No Pika dependency (cleaner logs)
- **Memory protection for delayed messages** - Configure `max_delay_time` to prevent RabbitMQ memory exhaustion from long-lived delayed messages
- **Deadlock protection** - `confirm_timeout` prevents infinite blocking when connection fails during publish confirmation

## When To Use This

Use this broker if you're:

- Running into connection limit issues
- Using threaded workers or applications
- Need reliable delayed message delivery
- Want better visibility into your connections
- Migrating from standard broker and hitting topology errors

Stick with the standard broker if you're:

- Just starting with Dramatiq (use standard until you hit limits)
- Running a single-threaded worker with low traffic

## Documentation

- [Installation](installation.md)
- [Quick Start](quickstart.md)
- [Configuration](configuration.md)
- [Topologies](topologies.md)
- [Examples](examples.md)
- [Migration Guide](migration.md)

## Support

- Report bugs: [GitHub Issues](https://github.com/spumer/dramatiq-kombu-broker/issues)
- Ask questions: [GitHub Discussions](https://github.com/spumer/dramatiq-kombu-broker/discussions)
