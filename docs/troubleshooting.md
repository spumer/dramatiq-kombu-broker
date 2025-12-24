# Troubleshooting

Common issues and how to fix them.

## Connection Issues

### Connection Refused

**Error:** `ConnectionRefusedError: [Errno 111] Connection refused`

**Causes:**
- RabbitMQ not running
- Wrong hostname/port
- Firewall blocking connection

**Fix:**
```bash
# Check RabbitMQ is running
systemctl status rabbitmq-server

# Check port is open
telnet localhost 5672

# Check connection string
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/"  # Verify this
    }
)
```

### Connection Limit Reached

**Error:** `connection_limit_reached`

**Fix 1 - Use Shared Connection:**
```python
# Instead of ConnectionPooledKombuBroker
from dramatiq_kombu_broker import ConnectionSharedKombuBroker

broker = ConnectionSharedKombuBroker(...)
```

**Fix 2 - Reduce Pool Size:**
```python
broker = ConnectionPooledKombuBroker(
    connection_holder_options={
        "max_connections": 5,  # Lower than default
    }
)
```

**Fix 3 - Increase RabbitMQ Limit:**
```bash
# In rabbitmq.conf
connection_max = 1000
```

### Heartbeat Failures

**Error:** Connection drops unexpectedly

By default, heartbeat is set to 60 seconds. To reduce it for unreliable networks:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "heartbeat": 30,  # Lower than default 60s
    }
)
```

### Publish Deadlocks

**Symptoms:**
- Worker threads hang indefinitely
- Message publishing never completes
- Application becomes unresponsive during RabbitMQ issues

**Cause:** When `confirm_delivery=True`, the broker waits for RabbitMQ to confirm message receipt. If the connection drops during this wait (before heartbeat detects it), the thread can block forever.

**Solution:** Use `confirm_timeout` (enabled by default):

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "heartbeat": 60,  # Transport-level protection
    },
    confirm_delivery=True,
    confirm_timeout=5.0,  # Application-level protection (default)
)
```

**If you're getting timeout errors:**

1. **Check network latency** - High-latency networks may need longer timeout:
   ```python
   confirm_timeout=30.0  # For slow networks
   ```

2. **Check RabbitMQ load** - Overloaded RabbitMQ may delay confirmations. Monitor RabbitMQ metrics.

3. **Check connection stability** - Frequent timeouts indicate connection issues. Investigate network or RabbitMQ health.

**Relationship with heartbeat:**

| Parameter | Purpose | When It Helps |
|-----------|---------|---------------|
| `heartbeat=60` | Detects dead connections | Idle connections, no activity |
| `confirm_timeout=5.0` | Prevents publish blocking | Active publishing, connection drops mid-publish |

Both parameters work together to provide comprehensive connection protection.

**See [Delivery Guarantees](delivery-guarantees.md#confirm_timeout-deadlock-protection) for more details.**

## Queue Issues

### Precondition Failed

**Error:** `amqp.exceptions.PreconditionFailed: inequivalent arg 'x-dead-letter-exchange'`

**Cause:** Queue already exists with different arguments

**Fix:** Delete queue and recreate
```bash
# Via rabbitmqctl
rabbitmqctl delete_queue myqueue
rabbitmqctl delete_queue myqueue.DQ
rabbitmqctl delete_queue myqueue.XQ

# Or via management UI
# Queues tab → Select queue → Delete
```

### Delayed Messages Not Working

**Symptoms:**
- Messages sent with delay never appear
- Delay queue has messages stuck

**Check 1 - Delay Queue Configuration:**
```python
# Ensure using DefaultDramatiqTopology (not custom)
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(...)  # Uses DefaultDramatiqTopology
```

**Check 2 - Dead Letter Parameters:**
```bash
# Check delay queue has x-dead-letter-routing-key
rabbitmqctl list_queues name arguments | grep ".DQ"
```

Should show:
```
myqueue.DQ  [{<<"x-dead-letter-routing-key">>,<<"myqueue">>}...]
```

**Fix:** Delete delay queue, let it recreate with correct parameters

### Messages Going to Wrong Queue

**Check routing key:**
```python
def debug_message(broker, message):
    print(f"Queue: {message.queue_name}")
    print(f"Routing key: {message.options.get('routing_key')}")
```

## Worker Issues

### Worker Not Processing

**Check 1 - Worker Running:**
```bash
ps aux | grep dramatiq
```

**Check 2 - Correct Queue:**
```bash
dramatiq tasks --queues myqueue  # Specify queue
```

**Check 3 - Actor Discovered:**
```bash
dramatiq tasks --verbose  # Shows discovered actors
```

### High Memory Usage

**Causes:**
- Too many worker threads
- Memory leaks in actors
- Large messages

**Fix 1 - Reduce Threads:**
```bash
dramatiq tasks --threads 2  # Default: CPU count
```

**Fix 2 - Process Messages in Batches:**
```python
@dramatiq.actor
def process_large_dataset(chunk_ids):
    for chunk_id in chunk_ids:
        process_chunk(chunk_id)
        # Free memory between chunks
        del chunk_data
```

### Slow Processing

**Profile actor:**
```python
import cProfile

@dramatiq.actor
def slow_task(data):
    profiler = cProfile.Profile()
    profiler.enable()

    # Your code
    process(data)

    profiler.disable()
    profiler.print_stats()
```

**Check:**
- Database queries (N+1 problem)
- External API calls
- CPU-intensive operations

## Message Issues

### Messages Lost

**Check 1 - Confirm Delivery:**
```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    confirm_delivery=True,  # Ensure this is True
)
```

**Check 2 - Message Persistence:**
Messages are persistent by default. Check RabbitMQ logs for crashes during publishing.

**Check 3 - Dead Letter Queue:**
```python
def check_dlq(broker, queue_name):
    main, delay, dlq = broker.get_queue_message_counts(queue_name)
    print(f"DLQ has {dlq} messages")
```

### Messages Stuck in DLQ

**View DLQ messages:**
```bash
# Via rabbitmqadmin
rabbitmqadmin get queue=myqueue.XQ count=10
```

**Reprocess:**
```bash
# Move back to main queue
rabbitmqadmin get queue=myqueue.XQ requeue=false count=1 | \
rabbitmqadmin publish routing_key=myqueue
```

### Deserialization Errors

**Error:** `JSONDecodeError` or similar

**Causes:**
- Message format changed
- Corrupted message

**Fix:**
```python
@dramatiq.actor
def my_task(data):
    try:
        process(data)
    except (ValueError, TypeError) as e:
        # Log and skip bad message
        logger.error(f"Bad message: {e}")
        return  # Don't raise, let it ACK
```

## Django Issues

### Django DB Connection Errors

**Error:** `OperationalError: server closed the connection`

**Fix - Use DB Middleware:**
```python
DRAMATIQ_BROKER["OPTIONS"]["middleware"] = [
    "django_dramatiq.middleware.DbConnectionsMiddleware",
    # ... other middleware
]
```

### App Not Found

**Error:** `django.core.exceptions.AppRegistryNotReady`

**Fix - Ensure Django Setup:**
```python
# tasks.py
import django
django.setup()

import dramatiq
```

## Performance Issues

### High Latency

**Check 1 - Connection Pool:**
```python
# Increase pool size
connection_holder_options={"max_connections": 20}
```

**Check 2 - Worker Threads:**
```bash
dramatiq tasks --threads 10  # More threads
```

**Check 3 - Prefetch:**
```bash
dramatiq tasks --prefetch 10  # Default: 1
```

### Queue Backlog

**Symptoms:** Messages piling up

**Fix 1 - More Workers:**
```bash
# Start multiple worker processes
for i in {1..5}; do
    dramatiq tasks &
done
```

**Fix 2 - Optimize Actors:**
- Remove unnecessary work
- Batch operations
- Use asyncio for I/O-bound tasks

## Debugging

### Enable Verbose Logging

```bash
PYTHONUNBUFFERED=1 dramatiq tasks --verbose
```

### Python Debugging

```python
@dramatiq.actor
def debug_task(data):
    import pdb; pdb.set_trace()  # Breakpoint
    process(data)
```

### RabbitMQ Management UI

Access at `http://localhost:15672` (guest/guest)

- View queue depths
- Inspect messages
- Check connection count
- Monitor memory usage

### Connection Info

```python
def debug_connections(broker):
    with broker.connection_holder.acquire_consumer_channel() as channel:
        print(f"Connection: {channel.connection}")
        print(f"Is open: {channel.connection.connected}")
```

## Getting Help

If you're still stuck:

1. **Check logs** - Worker logs, RabbitMQ logs
2. **Minimal reproducer** - Isolate the problem
3. **Search issues** - [GitHub Issues](https://github.com/spumer/dramatiq-kombu-broker/issues)
4. **Ask for help** - [GitHub Discussions](https://github.com/spumer/dramatiq-kombu-broker/discussions)

When asking for help, include:
- dramatiq-kombu-broker version
- RabbitMQ version
- Python version
- Full error message and traceback
- Minimal code to reproduce

## Common Solutions Summary

| Issue | Quick Fix |
|-------|-----------|
| Connection refused | Check RabbitMQ is running |
| Connection limit | Use ConnectionSharedKombuBroker |
| Publish deadlock | Use `confirm_timeout=5.0` (default) |
| Precondition failed | Delete queue, let it recreate |
| Delays not working | Delete .DQ queue, use DefaultDramatiqTopology |
| High memory | Reduce worker threads |
| Slow processing | Profile code, optimize |
| Messages lost | Enable confirm_delivery |
| Queue backlog | More workers, optimize actors |

## Next Steps

- [Configuration](configuration.md) - Tune settings
- [Performance](performance.md) - Optimize performance
- [Examples](examples.md) - See working code
