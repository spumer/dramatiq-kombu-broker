# Message Processing

How messages flow through the broker and workers.

## Message Lifecycle

1. **Enqueue** - Actor sends message to broker
2. **Route** - Broker puts message in appropriate queue
3. **Consume** - Worker pulls message from queue
4. **Process** - Actor function executes
5. **Acknowledge** - Worker ACKs or NACKs message

## Sending Messages

### Immediate Send

```python
@dramatiq.actor
def send_email(email: str):
    pass

# Basic send
send_email.send("user@example.com")

# Equivalent to
send_email.send_with_options(args=("user@example.com",))
```

### Delayed Send

```python
# Delay 5 seconds
send_email.send_with_options(
    args=("user@example.com",),
    delay=5000  # milliseconds
)
```

### Priority Send

```python
# High priority
send_email.send_with_options(
    args=("urgent@example.com",),
    broker_priority=10
)
```

## Message Format

Messages are JSON-serialized by default:

```json
{
  "queue_name": "default",
  "actor_name": "send_email",
  "args": ["user@example.com"],
  "kwargs": {},
  "options": {
    "eta": 1234567890,
    "broker_priority": 5
  },
  "message_id": "unique-id",
  "message_timestamp": 1234567890
}
```

## Acknowledgments

### Auto-ACK (Default)

Worker automatically ACKs after successful processing:

```python
@dramatiq.actor
def my_task(data):
    process(data)
    # Automatically ACKed
```

### Manual ACK

Control acknowledgment in middleware:

```python
class ManualAckMiddleware:
    def after_process_message(self, broker, message, *, result=None, exception=None):
        if exception:
            message.nack()  # Reject and requeue
        else:
            message.ack()  # Acknowledge
```

### Check ACK Status

```python
from dramatiq import Message

def process_message(broker, message: Message):
    # Do something
    if message.acknowledged:
        print("Already ACKed")
```

## Message TTL

### Queue-Level TTL

Set TTL on entire queue (not recommended for work queues):

```python
# This is set by topology for dead letter queues
dead_letter_message_ttl = dt.timedelta(days=7)
```

### Message-Level TTL

Set TTL per message via `expiration` property (used for delays):

```python
# Dramatiq sets this automatically for delays
channel.basic_publish(
    body=message.encode(),
    properties={"expiration": "5000"}  # 5 seconds
)
```

## Dead Letter Queue

Failed messages go to dead letter queue (DLQ):

```python
# For queue "tasks":
# - tasks       - Main queue
# - tasks.DQ    - Delay queue
# - tasks.XQ    - Dead letter queue (failed messages)
```

### Inspecting DLQ

```python
def check_dlq(broker, queue_name):
    dlq_name = broker.topology.get_dead_letter_queue_name(queue_name)
    _, count, _ = broker.get_queue_message_counts(queue_name)
    print(f"Messages in DLQ: {count}")
```

### Reprocessing DLQ

Manually move messages from DLQ back to main queue via RabbitMQ management UI or:

```bash
# Via rabbitmqadmin
rabbitmqadmin get queue=tasks.XQ requeue=false count=10 | \
rabbitmqadmin publish routing_key=tasks
```

## Message Persistence

Messages are persistent by default (`delivery_mode=2`):

```python
# In broker.py
producer.publish(
    body=message.encode(),
    delivery_mode=2,  # Persistent
)
```

This ensures messages survive RabbitMQ restart.

## Confirm Delivery

See [Delivery Guarantees](delivery-guarantees.md) for how to configure message delivery confirmation.

## Message Routing

### Standard Flow

```
Actor.send() → Main Queue → Worker
```

### Delayed Flow

```
Actor.send_with_options(delay=X) → Delay Queue (wait) → Main Queue → Worker
```

### Failed Message Flow

```
Worker (exception) → Dead Letter Queue
```

## Queue Depths

Monitor queue depths:

```python
def monitor_queues(broker):
    for queue_name in broker.get_declared_queues():
        main, delay, dlq = broker.get_queue_message_counts(queue_name)
        print(f"{queue_name}:")
        print(f"  Main: {main}")
        print(f"  Delay: {delay}")
        print(f"  DLQ: {dlq}")
```

## Troubleshooting

### Messages Not Processing

Check:
1. Worker is running
2. Worker consuming from correct queue
3. No exceptions in worker logs
4. RabbitMQ connection is healthy

### Messages Stuck in Delay Queue

Check:
- Delay queue has dead-letter configuration
- Dead-letter routing key matches main queue name
- Main queue exists

### Messages Going to DLQ

Check worker logs for exceptions. Common causes:
- Unhandled exceptions
- Message deserialization errors
- Actor not found

## Best Practices

1. **Use delays sparingly** - Don't delay millions of messages
2. **Monitor queue depths** - Alert on growing queues
3. **Check DLQ regularly** - Failed messages need attention
4. **Set reasonable TTLs** - Don't let messages sit forever
5. **Enable confirm_delivery** - Ensure reliable delivery
6. **Handle exceptions** - Log errors before they reach DLQ

## Next Steps

- [Examples](examples.md) - Message processing examples
- [Troubleshooting](troubleshooting.md) - Fix message issues
- [Configuration](configuration.md) - Configure message handling
