# Delivery Guarantees

When you send a task with `task.send()`, dramatiq-kombu-broker provides two parameters to control delivery reliability: `confirm_delivery` and `blocking_acknowledge`.

## Quick Reference

| Parameter | Default | Stage | What It Does |
|-----------|---------|-------|--------------|
| `confirm_delivery` | `True` | Publishing | RabbitMQ confirms message reached queue |
| `confirm_timeout` | `5.0` | Publishing | Timeout for publish confirmation (deadlock protection) |
| `blocking_acknowledge` | `True` | Processing | Worker waits for ACK confirmation |
| `mandatory` | `True` | Publishing | Reject if queue doesn't exist |

**Recommended for production:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": os.environ["RABBITMQ_URL"],
        "transport_options": {
            "confirm_publish": True,
        },
    },
    confirm_delivery=True,         # Ensure delivery
    confirm_timeout=5.0,           # Prevent deadlocks (default)
    blocking_acknowledge=True,     # Ensure processing
)
```

## confirm_delivery: Publishing Guarantees

**Default:** `True`

Controls whether RabbitMQ confirms that published messages were accepted and routed to queues using [Publisher Confirms](https://www.rabbitmq.com/docs/confirms).

### With confirm_delivery=True

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,  # Default
)

@dramatiq.actor
def send_email(email):
    ...

# Raises exception if RabbitMQ doesn't confirm
send_email.send("user@example.com")
```

**Guarantees:**
- Message reached RabbitMQ broker
- Message was routed to a queue (via `mandatory=True`)
- Synchronous errors on failure

**Trade-off:** Slightly slower publishing

### With confirm_delivery=False

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "...",
        "transport_options": {
            "confirm_publish": False,
        },
    },
    confirm_delivery=False,
)
```

**When to use:**
- Very high throughput (thousands of tasks/second)
- Non-critical tasks (logging, analytics)
- Can tolerate message loss

**Risks:**
- Messages lost on network issues
- Messages lost on RabbitMQ restart
- No error notification

### confirm_timeout: Deadlock Protection

**Default:** `5.0` seconds

When `confirm_delivery=True`, the broker waits for RabbitMQ to confirm message receipt. If the connection drops during this wait, the thread can block indefinitely - a **deadlock**. The `confirm_timeout` parameter prevents this.

**The Problem:**

```
1. Publisher sends message to RabbitMQ
2. Publisher waits for confirmation...
3. Connection drops (network issue, RabbitMQ restart, etc.)
4. Without timeout: Publisher waits FOREVER
5. Worker thread is stuck, cannot process other work
```

**The Solution:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,
    confirm_timeout=5.0,  # Default: 5 seconds
)
```

After 5 seconds without confirmation, the broker raises an exception instead of blocking forever.

**How it works with heartbeat:**

Both `confirm_timeout` and `heartbeat` protect against connection issues, but at different levels:

| Parameter | Level | Protects Against |
|-----------|-------|------------------|
| `heartbeat=60` | Transport | Dead connections (no activity for 60s) |
| `confirm_timeout=5.0` | Application | Blocked publish confirmation |

They are **complementary**:
- `heartbeat` detects dead connections during idle periods
- `confirm_timeout` prevents blocking during active publishing

**Configuration examples:**

```python
# Production (recommended)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq:5672/",
        "heartbeat": 60,  # Detect dead connections
    },
    confirm_delivery=True,
    confirm_timeout=5.0,  # Prevent publish deadlocks
)

# High-latency network
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@remote-rabbitmq:5672/",
        "heartbeat": 60,
    },
    confirm_delivery=True,
    confirm_timeout=30.0,  # More time for slow confirmations
)
```

**When timeout triggers:**

If `confirm_timeout` expires, an exception is raised. This is the expected behavior - it's better to fail fast than hang forever. The message should be retried by the calling code.

**See [Troubleshooting](troubleshooting.md#publish-deadlocks) if you experience timeout issues.**

## blocking_acknowledge: Processing Guarantees

**Default:** `True`

Controls when worker sends ACK (acknowledgment) to RabbitMQ after processing a message.

### With blocking_acknowledge=True (Recommended)

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=True,  # Default
)

@dramatiq.actor
def process_order(order_id):
    result = heavy_computation(order_id)
    # Worker sends ACK and WAITS for confirmation
    # Only then takes next message
    return result
```

**Use for:**
- Financial operations
- Critical tasks
- Tasks with side effects (emails, database changes)
- At-least-once delivery requirements

**Trade-off:** Worker waits for ACK confirmation before next message

### With blocking_acknowledge=False

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=False,
)

@dramatiq.actor
def process_order(order_id):
    result = heavy_computation(order_id)
    # Worker queues ACK and IMMEDIATELY takes next message
    # ACK sent later, asynchronously
    return result
```

**Use for:**
- High-throughput systems
- Idempotent tasks (safe to run twice)
- Low-priority tasks

**Risks:**
- ACK lost on network failure
- Message may be processed twice
- Errors logged but don't block execution

## Configuration Patterns

### Maximum Reliability (Production Default)

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq:5672/",
        "transport_options": {
            "confirm_publish": True,
        },
    },
    confirm_delivery=True,        # Confirm publishing
    blocking_acknowledge=True,    # Confirm processing
)
```

**Guarantees:** At-least-once delivery, all errors raised

**Trade-off:** Slightly lower throughput

### Maximum Throughput (Non-Critical Tasks Only)

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq:5672/",
        "transport_options": {
            "confirm_publish": False,
        },
    },
    confirm_delivery=False,       # Skip confirmation
    blocking_acknowledge=False,   # Async ACK
)
```

**Benefits:** Maximum speed, minimal latency

**Risks:** Messages may be lost, tasks may run twice

### Hybrid Approach

Use different brokers for different task types:

```python
# Critical tasks: reliable
main_broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,
    blocking_acknowledge=True,
)

# Analytics: fast
analytics_broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=False,
    blocking_acknowledge=False,
)

@dramatiq.actor(broker=main_broker)
def charge_payment(amount):
    ...

@dramatiq.actor(broker=analytics_broker)
def track_event(event_type, data):
    ...
```

## Common Issues

### Tasks Running Twice

This is normal with at-least-once delivery. Make tasks idempotent:

```python
@dramatiq.actor
def process_payment(payment_id):
    payment = Payment.objects.get(id=payment_id)
    if payment.status == "processed":
        return  # Already done

    charge_card(payment)
    payment.status = "processed"
    payment.save()
```

### Low Throughput

If you have thousands of small tasks per second:

**Option 1:** Use `blocking_acknowledge=False` for idempotent tasks

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,         # Keep for reliability
    blocking_acknowledge=False,    # Speed up processing
)
```

**Option 2:** Scale workers instead

```bash
dramatiq tasks --processes 8 --threads 4
```

### Connection Closed During ACK

**With blocking_acknowledge=True:**
- Exception raised immediately
- Message stays in queue
- Task retried after reconnection

**With blocking_acknowledge=False:**
- Error logged
- Worker already processing next message
- May cause duplicate processing

**Solution:** Use `blocking_acknowledge=True` for critical tasks and ensure idempotency.

## Monitoring

Track delivery failures:

```python
from prometheus_client import Counter

delivery_failures = Counter(
    'dramatiq_delivery_failures_total',
    'Failed message deliveries',
)

@dramatiq.actor
def important_task(data):
    try:
        result = process(data)
    except Exception:
        delivery_failures.inc()
        raise
    return result
```

Monitor in RabbitMQ Management UI:
- **Ready** - Messages in queue
- **Unacked** - Messages taken but not ACKed
- **Publish rate** - Throughput
- **Consumer count** - Active workers

## Memory and Performance Implications

### Delayed Messages and Memory

When Dramatiq sends delayed messages, they stay **unacked** in RabbitMQ until the delay expires. This creates memory pressure:

- **Unacked messages accumulate** - Each delayed message [consumes RAM](https://www.rabbitmq.com/docs/confirms) on the RabbitMQ server
- **Transaction log grows** - [Quorum queues maintain WAL logs](https://www.rabbitmq.com/docs/quorum-queues) for all unacked messages, consuming disk space
- **Performance degradation** - High volumes of long-lived delayed messages impact RabbitMQ performance and can [overwhelm consumers](https://www.cloudamqp.com/blog/part1-rabbitmq-best-practice.html)
- **Memory exhaustion risk** - Very long delays (days/weeks) can [trigger memory alarms](https://github.com/rabbitmq/rabbitmq-server/issues/1164)

This is different from immediate messages, which are acknowledged quickly after processing.

### Protection with max_delay_time

Configure `max_delay_time` to prevent memory issues from long delays:

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, DefaultDramatiqTopology
import datetime as dt

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq:5672/",
        "transport_options": {
            "confirm_publish": True,
        },
    },
    topology=DefaultDramatiqTopology(
        max_delay_time=dt.timedelta(hours=3)  # Fail-fast protection
    ),
    confirm_delivery=True,
    blocking_acknowledge=True,
)
```

**How it works:**

1. **Application validation** - Broker raises `DelayTooLongError` when delay exceeds limit
2. **RabbitMQ failsafe** - Queue-level TTL (`x-message-ttl`) as backup protection
3. **Defense in depth** - Two layers ensure protection even if one fails

### Monitoring

Track rejected messages due to excessive delay:

```python
from prometheus_client import Counter
from dramatiq_kombu_broker import DelayTooLongError

delay_too_long_errors = Counter(
    'dramatiq_delay_too_long_errors_total',
    'Messages rejected due to excessive delay',
    ['queue'],
)

@dramatiq.actor
def process_task(task_id):
    ...

# When sending with delay
try:
    process_task.send_with_options(args=(123,), delay=delay_ms)
except DelayTooLongError as e:
    delay_too_long_errors.labels(queue=e.queue_name).inc()
    logger.error(
        f"Rejected task: delay {e.delay}ms exceeds max {e.max_delay}ms"
    )
    raise
```

**What to monitor:**

- `DelayTooLongError` exceptions - indicates delays exceeding limits
- RabbitMQ memory usage - watch for growth with delayed messages
- Queue depths - monitor `*.DQ` (delay queue) sizes
- Unacked message counts - high counts indicate memory pressure

### Recommendations

| Scenario | max_delay_time | Monitoring | Notes |
|----------|---------------|------------|-------|
| Critical production | 3 hours | Alert on `DelayTooLongError` | Conservative limit, prevents memory issues |
| Background jobs | 24 hours | Log and track trends | Suitable for daily tasks |
| Development/testing | None | Optional | No restrictions, easier testing |
| High-volume delayed tasks | 1-6 hours | Alert + memory monitoring | Lower limit for high message volumes |

**Configuration examples:**

```python
# Conservative production setup
topology = DefaultDramatiqTopology(
    max_delay_time=dt.timedelta(hours=3)
)

# Background job setup
topology = DefaultDramatiqTopology(
    max_delay_time=dt.timedelta(hours=24)
)

# Development (no limits)
topology = DefaultDramatiqTopology()  # max_delay_time=None (default)
```

### When NOT to Use Delayed Messages

Delayed messages are powerful but have limitations. Use alternatives in these cases:

| Scenario | Why Not Delayed Messages | Alternative |
|----------|-------------------------|-------------|
| Delays > 24 hours | Memory pressure, inefficient | Cron jobs, APScheduler, Celery Beat |
| High-precision timing | RabbitMQ TTL has ~1s precision | Dedicated scheduler, database polling |
| Very high volume delays | Memory exhaustion risk | Batch processing, time-series database |
| Delays > weeks | Extremely inefficient | Calendar-based scheduling systems |
| Dynamic rescheduling | Messages can't be modified once queued | Database-backed task queue |

**Example: Wrong approach**

```python
# DON'T: Use delayed messages for weekly reports
@dramatiq.actor
def send_weekly_report(user_id):
    ...

# This will hold messages unacked for 7 days!
send_weekly_report.send_with_options(
    args=(user_id,),
    delay=7*24*60*60*1000  # 7 days in ms
)
```

**Example: Right approach**

```python
# DO: Use cron or APScheduler for recurring tasks
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

@scheduler.scheduled_job('cron', day_of_week='mon', hour=9)
def generate_weekly_reports():
    for user_id in get_active_users():
        send_weekly_report.send(user_id)  # Immediate execution

scheduler.start()
```

### Performance Trade-offs

**With max_delay_time protection:**

| Aspect | Impact | Mitigation |
|--------|--------|------------|
| Publishing | Minimal (one int comparison) | Negligible performance impact |
| Memory | Reduced (prevents long delays) | Lower RabbitMQ memory usage |
| Reliability | Higher (fail-fast on issues) | Better error visibility |
| Queue creation | One-time TTL setup | No ongoing overhead |

**Without max_delay_time (default):**

| Aspect | Impact | Risk |
|--------|--------|------|
| Publishing | Slightly faster (no validation) | No protection from excessive delays |
| Memory | Can grow unbounded | RabbitMQ memory exhaustion |
| Reliability | No early error detection | Silent failures, debugging harder |
| Operations | No limits | Requires manual monitoring |

## Further Reading

**Delivery Guarantees:**
- [RabbitMQ Publisher Confirms](https://www.rabbitmq.com/docs/confirms) - Publishing guarantees and acknowledgements
- [RabbitMQ Consumer Acknowledgements](https://www.rabbitmq.com/docs/confirms#consumer-acknowledgements) - Processing guarantees
- [RabbitMQ Reliability Guide](https://www.rabbitmq.com/docs/reliability) - Overall reliability patterns
- [RabbitMQ Mandatory Flag](https://www.compilenrun.com/docs/middleware/rabbitmq/rabbitmq-reliability/rabbitmq-mandatory-messages/) - Message routing guarantees

**Memory and Performance:**
- [Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues) - Write-ahead-log (WAL) and memory management
- [RabbitMQ Best Practices - CloudAMQP](https://www.cloudamqp.com/blog/part1-rabbitmq-best-practice.html) - Managing unacked messages
- [How to Handle High Memory Usage - CloudAMQP](https://www.cloudamqp.com/blog/identify-and-protect-against-high-cpu-and-memory-usage.html) - Memory troubleshooting
- [Key Metrics for RabbitMQ Monitoring - Datadog](https://www.datadoghq.com/blog/rabbitmq-monitoring/) - Monitoring memory and unacked messages

**Delayed Messages:**
- [Time-To-Live and Expiration](https://www.rabbitmq.com/docs/ttl) - TTL behavior and limitations
- [Delayed Messages Documentation - CloudAMQP](https://www.cloudamqp.com/docs/delayed-messages.html) - Best practices for delayed messages
- [RabbitMQ Message TTL - Compile N Run](https://www.compilenrun.com/docs/middleware/rabbitmq/rabbitmq-queue-management/rabbitmq-message-ttl/) - TTL ordering issues

**Troubleshooting:**
- [13 Common RabbitMQ Mistakes - CloudAMQP](https://www.cloudamqp.com/blog/part4-rabbitmq-13-common-errors.html) - Common pitfalls
- [GitHub Issue #1164](https://github.com/rabbitmq/rabbitmq-server/issues/1164) - Real-world memory alarm case
