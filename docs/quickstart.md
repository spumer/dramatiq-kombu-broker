# Quick Start

Get up and running with dramatiq-kombu-broker in 5 minutes!

## Basic Setup

### 1. Install the Package

```bash
pip install dramatiq-kombu-broker
```

### 2. Create Your First Actor

Create a file `tasks.py`:

```python
import dramatiq
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

# Configure the broker
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/"
    }
)

# Set as the default broker
dramatiq.set_broker(broker)

# Define an actor
@dramatiq.actor
def send_email(email: str, subject: str, body: str):
    print(f"Sending email to {email}: {subject}")
    # Your email sending logic here
    return True
```

### 3. Start a Worker

In your terminal:

```bash
dramatiq tasks
```

You should see:

```
[INFO] Dramatiq '1.17.0' is booting up.
[INFO] Discovered actors:
[INFO]   - send_email
[INFO] Worker process is ready for action.
```

### 4. Send Tasks

In Python REPL or another script:

```python
from tasks import send_email

# Send immediately
send_email.send("user@example.com", "Hello", "Welcome!")

# Send with delay (5 seconds)
send_email.send_with_options(
    args=("user@example.com", "Hello", "Welcome!"),
    delay=5000  # milliseconds
)

# Send with priority
send_email.send_with_options(
    args=("urgent@example.com", "URGENT", "Alert!"),
    broker_priority=10
)
```

## Django Integration

### 1. Install Django Dramatiq

```bash
pip install dramatiq-kombu-broker django-dramatiq
```

### 2. Configure Django Settings

In `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    'django_dramatiq',
]

DRAMATIQ_BROKER = {
    "BROKER": "dramatiq_kombu_broker.broker.ConnectionSharedKombuBroker",
    "OPTIONS": {
        "kombu_connection_options": {
            "hostname": "amqp://guest:guest@localhost:5672/",
        },
        "max_priority": 10,
    },
}

# Optional: Configure middleware
DRAMATIQ_BROKER["OPTIONS"]["middleware"] = [
    "dramatiq.middleware.Prometheus",
    "dramatiq.middleware.AgeLimit",
    "dramatiq.middleware.TimeLimit",
    "dramatiq.middleware.Callbacks",
    "dramatiq.middleware.Retries",
    "django_dramatiq.middleware.DbConnectionsMiddleware",
]
```

### 3. Create Tasks

Create `myapp/tasks.py`:

```python
import dramatiq

@dramatiq.actor
def process_order(order_id: int):
    from myapp.models import Order
    order = Order.objects.get(id=order_id)
    order.process()
    return True
```

### 4. Run Worker

```bash
python manage.py rundramatiq
```

### 5. Enqueue Tasks

In your Django views or management commands:

```python
from myapp.tasks import process_order

# In a view
def create_order(request):
    order = Order.objects.create(user=request.user)
    process_order.send(order.id)
    return redirect('order_success')
```

## Advanced Configuration

### Connection Pooling

For high-throughput applications:

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/",
        # heartbeat=60 is set by default, no need to specify
        "ssl": False,
    },
    connection_holder_options={
        "max_connections": 10,  # Connection pool size
    },
    max_priority=10,
    confirm_delivery=True,  # Ensure messages are delivered
)
```

### Thread-Safe Shared Connection

For applications with many threads:

```python
from dramatiq_kombu_broker import ConnectionSharedKombuBroker

broker = ConnectionSharedKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/",
    },
    connection_holder_options={
        "consumer_channel_pool_size": 5,  # Channel pool size
    },
)
```

### Custom Queue Name

Change the default queue from "default" to something else without modifying actor code:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    default_queue_name="myapp",  # Instead of "default"
)

# This actor will use "myapp" queue (replacement happens automatically)
@dramatiq.actor
def my_task():
    pass

# This actor keeps its explicit queue "critical" (no replacement)
@dramatiq.actor(queue_name="critical")
def urgent_task():
    pass
```

See [Configuration](configuration.md#default_queue_name) for detailed explanation.

## Message Delays

Dramatiq supports delayed message delivery:

```python
@dramatiq.actor
def send_reminder(user_id: int):
    print(f"Reminder for user {user_id}")

# Send after 1 hour
send_reminder.send_with_options(
    args=(123,),
    delay=3600000  # 1 hour in milliseconds
)

# Send after 5 minutes
send_reminder.send_with_options(
    args=(456,),
    delay=300000  # 5 minutes
)
```

## Health Checks

Check if your broker connection is healthy:

```python
from dramatiq_kombu_broker.testing import ensure_consumer_connection_rabbitmq

# In your health check endpoint
try:
    ensure_consumer_connection_rabbitmq(broker)
    return {"status": "healthy"}
except Exception as e:
    return {"status": "unhealthy", "error": str(e)}
```

## Common Patterns

### Retry Configuration

```python
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def flaky_task(data):
    # This will retry up to 3 times with exponential backoff
    api_call(data)
```

### Time Limits

```python
@dramatiq.actor(time_limit=30000)  # 30 seconds
def long_running_task():
    # Task will be cancelled if it runs longer than 30 seconds
    process_data()
```

### Multiple Queues

```python
@dramatiq.actor(queue_name="high_priority")
def urgent_task():
    pass

@dramatiq.actor(queue_name="low_priority")
def background_task():
    pass

# Start workers for specific queues
# dramatiq tasks --queues high_priority
# dramatiq tasks --queues low_priority
```

## Next Steps

- [Configuration Guide](configuration.md) - Deep dive into all configuration options
- [Topologies](topologies.md) - Learn about queue routing strategies
- [Examples](examples.md) - More real-world examples
- [Migration Guide](migration.md) - Migrate from standard dramatiq broker
