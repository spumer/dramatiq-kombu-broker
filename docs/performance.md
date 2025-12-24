# Performance Tuning

Optimize dramatiq-kombu-broker for your workload.

## Connection Pooling

### Pooled Broker

Best for multiple worker processes:

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    connection_holder_options={
        "max_connections": 20,  # Tune based on worker count
    },
)
```

**Rule of thumb:** `max_connections = number of worker processes × 2`

### Shared Broker

Best for threaded applications:

```python
from dramatiq_kombu_broker import ConnectionSharedKombuBroker

broker = ConnectionSharedKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    connection_holder_options={
        "consumer_channel_pool_size": 10,  # Tune based on thread count
    },
)
```

**Rule of thumb:** `channel_pool_size = number of threads / 2`

## Worker Configuration

### Thread Count

```bash
# CPU-bound tasks
dramatiq tasks --threads $(nproc)

# I/O-bound tasks
dramatiq tasks --threads $(($(nproc) * 2))

# High-concurrency
dramatiq tasks --threads 20
```

### Prefetch Count

How many messages worker pulls at once:

```bash
# Low prefetch (fairness, better for slow tasks)
dramatiq tasks --prefetch 1

# High prefetch (throughput, better for fast tasks)
dramatiq tasks --prefetch 10
```

**Trade-off:**
- Low prefetch: Better load balancing, lower throughput
- High prefetch: Higher throughput, worse load balancing

## Message Processing

### Batch Operations

**Before (slow):**
```python
@dramatiq.actor
def process_item(item_id):
    item = db.get(item_id)
    item.process()
    db.save(item)

# Sends 1000 messages
for item_id in range(1000):
    process_item.send(item_id)
```

**After (fast):**
```python
@dramatiq.actor
def process_batch(item_ids):
    items = db.get_many(item_ids)  # Single query
    for item in items:
        item.process()
    db.save_many(items)  # Single query

# Sends 10 messages
batch_size = 100
for i in range(0, 1000, batch_size):
    process_batch.send(list(range(i, i + batch_size)))
```

### Async I/O

For I/O-bound tasks, use async:

```python
import asyncio
import dramatiq

@dramatiq.actor
def fetch_urls(urls):
    asyncio.run(fetch_all(urls))

async def fetch_all(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(session, url) for url in urls]
        return await asyncio.gather(*tasks)
```

## RabbitMQ Configuration

### Queue Arguments

Limit queue size:

```python
@dataclasses.dataclass
class LimitedTopology(DefaultDramatiqTopology):
    def _get_canonical_queue_arguments(self, queue_name, dlx=True):
        args = super()._get_canonical_queue_arguments(queue_name, dlx)
        args["x-max-length"] = 10000  # Max 10k messages
        args["x-overflow"] = "reject-publish"  # Reject when full
        return args
```

### Message TTL

Don't let messages sit forever:

```python
topology = DefaultDramatiqTopology(
    dead_letter_message_ttl=dt.timedelta(days=3),  # DLQ messages expire after 3 days
)
```

## Network Optimization

### Heartbeat

Heartbeat is set to **60 seconds by default**. Adjust only if needed:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "heartbeat": 30,  # Override default (60s) for unstable networks
    },
)
```

- Lower (30s): Better for unstable networks
- Higher (120s): Less overhead, use if network is stable

### Confirm Delivery

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    confirm_delivery=True,  # Reliability vs speed trade-off
)
```

- `True`: Slower, but guarantees delivery
- `False`: Faster, but may lose messages on broker restart

## Monitoring

### Queue Depths

```python
def monitor(broker):
    for queue in broker.get_declared_queues():
        main, delay, dlq = broker.get_queue_message_counts(queue)
        if main > 1000:
            alert(f"Queue {queue} backlog: {main}")
```

### Connection Count

Check RabbitMQ management UI or:

```bash
rabbitmqctl list_connections | wc -l
```

### Memory Usage

```bash
# Worker memory
ps aux | grep dramatiq

# RabbitMQ memory
rabbitmqctl status | grep memory
```

## Benchmarking

### Simple Benchmark

```python
import time
import dramatiq

@dramatiq.actor
def noop():
    pass

start = time.time()
for _ in range(10000):
    noop.send()
duration = time.time() - start

print(f"Enqueued {10000/duration:.0f} messages/sec")
```

### Load Testing

```bash
# Start multiple workers
for i in {1..10}; do
    dramatiq tasks --threads 5 &
done

# Send messages
python benchmark.py

# Monitor
watch -n 1 'rabbitmqctl list_queues name messages'
```

## Optimization Checklist

**Connection:**
- ✅ Use appropriate broker type (Pooled vs Shared)
- ✅ Tune pool/channel sizes
- ✅ Enable confirm_delivery for important messages

**Workers:**
- ✅ Match thread count to workload type
- ✅ Tune prefetch based on task duration
- ✅ Run multiple worker processes for CPU-bound tasks

**Code:**
- ✅ Batch database operations
- ✅ Use async for I/O-bound tasks
- ✅ Profile slow actors
- ✅ Cache expensive computations

**Queues:**
- ✅ Set max queue length to prevent memory issues
- ✅ Use priority queues strategically
- ✅ Monitor queue depths

**RabbitMQ:**
- ✅ Use fast disks (SSD) for persistent messages
- ✅ Increase memory limit if needed
- ✅ Enable lazy queues for large backlogs

## Common Bottlenecks

### Database

**Problem:** N+1 queries

**Solution:** Batch operations, eager loading

### External APIs

**Problem:** Blocking I/O

**Solution:** Use async, connection pooling

### CPU

**Problem:** CPU-intensive tasks

**Solution:** More worker processes, multiprocessing

### Memory

**Problem:** Large messages, memory leaks

**Solution:** Process in chunks, profile memory usage

## Production Tips

1. **Start small, scale up** - Begin with default settings, measure, then optimize
2. **Monitor everything** - Queue depths, worker memory, RabbitMQ stats
3. **Test under load** - Simulate production traffic in staging
4. **Use separate queues** - Critical vs background tasks
5. **Set timeouts** - Don't let tasks run forever
6. **Graceful degradation** - Handle overload scenarios

## Next Steps

- [Monitoring](examples.md#monitoring-with-prometheus) - Set up Prometheus
- [Troubleshooting](troubleshooting.md) - Fix performance issues
- [Configuration](configuration.md) - All tuning options
