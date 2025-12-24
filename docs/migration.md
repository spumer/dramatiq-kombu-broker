# Migration Guide

How to migrate from Dramatiq's standard RabbitMQ broker to dramatiq-kombu-broker.

## Why Migrate?

Common reasons:

- Hitting connection limits
- Need better connection pooling
- Want topology flexibility
- Getting "Connection limit reached" errors
- Need channel pooling for threaded apps

## Quick Migration

### 1. Install

```bash
pip install dramatiq-kombu-broker
```

### 2. Update Broker

**Before:**
```python
from dramatiq.brokers.rabbitmq import RabbitmqBroker

broker = RabbitmqBroker(url="amqp://guest:guest@localhost:5672/")
```

**After:**
```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/"
    }
)
```

### 3. Test

Run your workers and verify messages process correctly.

## Django Migration

**Before (django-dramatiq):**
```python
DRAMATIQ_BROKER = {
    "BROKER": "dramatiq.brokers.rabbitmq.RabbitmqBroker",
    "OPTIONS": {
        "url": "amqp://guest:guest@localhost:5672/",
    },
}
```

**After:**
```python
DRAMATIQ_BROKER = {
    "BROKER": "dramatiq_kombu_broker.broker.ConnectionSharedKombuBroker",
    "OPTIONS": {
        "kombu_connection_options": {
            "hostname": "amqp://guest:guest@localhost:5672/",
        },
    },
}
```

## Parameter Mapping

### Connection URL

**Standard broker:**
```python
broker = RabbitmqBroker(url="amqp://user:pass@host:5672/vhost")
```

**Kombu broker:**
```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@host:5672/vhost"
    }
)
```

### Connection Parameters

**Standard broker:**
```python
broker = RabbitmqBroker(
    host="localhost",
    port=5672,
    credentials=pika.PlainCredentials("guest", "guest"),
    heartbeat=60,
)
```

**Kombu broker:**
```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "localhost",
        "port": 5672,
        "userid": "guest",
        "password": "guest",
        "heartbeat": 60,
    }
)
```

> **Note:** Starting from version 0.3.0 with default heartbeat, `heartbeat=60` is set automatically. You only need to specify it if you want a different value.

### Max Priority

**Standard broker:**
```python
broker = RabbitmqBroker(url="...", max_priority=10)
```

**Kombu broker:**
```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "..."},
    max_priority=10,
)
```

### Queue Name Migration

If your old setup used a different default queue name (e.g., `"dramatiq"` instead of `"default"`), you can migrate without changing actor code:

**Before (actors with explicit queue names):**
```python
# You had to specify queue_name on every actor
@dramatiq.actor(queue_name="dramatiq")
def task_one():
    pass

@dramatiq.actor(queue_name="dramatiq")
def task_two():
    pass
```

**After (using default_queue_name):**
```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "..."},
    default_queue_name="dramatiq",  # Replace "default" with "dramatiq"
)
dramatiq.set_broker(broker)

# No need to specify queue_name anymore - it's automatic
@dramatiq.actor
def task_one():
    pass

@dramatiq.actor
def task_two():
    pass

# Actors with explicit non-default queues still work as expected
@dramatiq.actor(queue_name="critical")
def urgent_task():
    pass
```

This approach:

- Removes boilerplate from actor definitions
- Centralizes queue naming in broker configuration
- Makes it easier to change queue names across all actors

See [Configuration](configuration.md#default_queue_name) for detailed explanation.

## Common Issues

### Issue: Topology Precondition Failed

**Error:**
```
amqp.exceptions.PreconditionFailed: inequivalent arg 'x-dead-letter-exchange'
```

**Cause:** Delay queues have different arguments between brokers.

**Solution 1 - Clean slate:**
```bash
# Delete existing queues via RabbitMQ management UI
# Or use rabbitmqctl:
rabbitmqctl delete_queue myqueue.DQ
rabbitmqctl delete_queue myqueue
rabbitmqctl delete_queue myqueue.XQ
```

**Solution 2 - Let broker handle it:**

The broker sets `ignore_different_topology=True` by default, which logs warnings but continues. This works if you're not changing queue structure.


### Issue: Connection Pools

Standard broker doesn't have real connection pooling. After migrating:

1. Monitor connection count in RabbitMQ UI
2. Adjust `max_connections` if needed
3. For Django, use `ConnectionSharedKombuBroker` instead

## Zero-Downtime Migration

For production with no downtime:

### Step 1: Run Both Brokers

Deploy new code that can use both brokers:

```python
# config.py
USE_NEW_BROKER = os.getenv("USE_NEW_BROKER", "false") == "true"

if USE_NEW_BROKER:
    broker = ConnectionPooledKombuBroker(...)
else:
    broker = RabbitmqBroker(...)
```

### Step 2: Test New Broker

Start one worker with new broker:

```bash
USE_NEW_BROKER=true dramatiq tasks
```

Monitor for errors. Leave it running for a while.

### Step 3: Gradual Rollout

Slowly increase workers using new broker:

```bash
# Old broker workers
dramatiq tasks &
dramatiq tasks &

# New broker workers
USE_NEW_BROKER=true dramatiq tasks &
```

### Step 4: Clean Up Queues

Once all workers use new broker and queues are empty:

```bash
# Delete old delay queues if topology changed
rabbitmqctl delete_queue myqueue.DQ
```

### Step 5: Remove Old Broker

After a week with no issues, remove old broker code.

## Testing Migration

Before production:

```python
# test_migration.py
import dramatiq
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/test"  # test vhost
    }
)
dramatiq.set_broker(broker)

@dramatiq.actor
def test_task(x):
    return x * 2

# Test immediate send
test_task.send(5)

# Test delayed send
test_task.send_with_options(args=(10,), delay=5000)

# Run worker
# dramatiq test_migration
```

## Rollback Plan

If issues occur:

1. Stop new broker workers
2. Revert code to old broker
3. Start old broker workers
4. Messages in queue will process normally

The queue structure is compatible, so rollback is safe.

## Feature Comparison

| Feature | Standard Broker | Kombu Broker            |
|---------|----------------|-------------------------|
| Connection pooling | Limited | Yes                     |
| Channel pooling | No | Yes (SharedKombuBroker) |
| Topology mismatch handling | Fails | Configurable            |
| Delayed messages | Works | Works                   |
| Priority queues | Yes | Yes                     |
| Middleware | Same | Same                    |
| Message format | Same | Same                    |

## Next Steps

After migration:

1. Monitor connection count
2. Check queue depths
3. Verify delayed messages work
4. Test retry logic
5. Update monitoring dashboards

## Getting Help

If you hit issues:

1. Check [Troubleshooting](troubleshooting.md)
2. Enable debug logging: `PYTHONUNBUFFERED=1 dramatiq tasks --verbose`
3. Ask on [GitHub Discussions](https://github.com/spumer/dramatiq-kombu-broker/discussions)
4. Report bugs on [GitHub Issues](https://github.com/spumer/dramatiq-kombu-broker/issues)
