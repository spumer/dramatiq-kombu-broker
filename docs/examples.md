# Examples

Real-world usage examples for dramatiq-kombu-broker.

## Basic Task Processing

```python
import dramatiq
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://guest:guest@localhost:5672/"
    }
)
dramatiq.set_broker(broker)

@dramatiq.actor
def send_welcome_email(user_id: int, email: str):
    # Send email logic here
    print(f"Sending welcome email to {email}")
    return True

# Usage
send_welcome_email.send(123, "user@example.com")
```

## Delayed Tasks

```python
@dramatiq.actor
def send_reminder(user_id: int):
    print(f"Sending reminder to user {user_id}")

# Send after 1 hour
send_reminder.send_with_options(
    args=(123,),
    delay=3600000  # 1 hour in milliseconds
)

# Send tomorrow at 9 AM
import datetime
now = datetime.datetime.now()
tomorrow_9am = now.replace(hour=9, minute=0, second=0) + datetime.timedelta(days=1)
delay_ms = int((tomorrow_9am - now).total_seconds() * 1000)

send_reminder.send_with_options(args=(123,), delay=delay_ms)
```

## Priority Queue

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    max_priority=10,  # Enable priorities 0-10
)
dramatiq.set_broker(broker)

@dramatiq.actor
def process_order(order_id: int):
    print(f"Processing order {order_id}")

# Normal priority (0)
process_order.send(100)

# High priority (10)
process_order.send_with_options(args=(200,), broker_priority=10)

# Low priority (1)
process_order.send_with_options(args=(300,), broker_priority=1)
```

## Multiple Queues

```python
@dramatiq.actor(queue_name="critical")
def urgent_task(data):
    print(f"Processing urgent: {data}")

@dramatiq.actor(queue_name="background")
def slow_task(data):
    print(f"Processing background: {data}")

# Start workers for specific queues:
# dramatiq tasks --queues critical
# dramatiq tasks --queues background
```

## Custom Default Queue Name

Replace the default queue name for all actors without changing their code:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    default_queue_name="myapp",  # Replace "default" with "myapp"
)
dramatiq.set_broker(broker)

# This actor will use "myapp" queue (automatically replaced from "default")
@dramatiq.actor
def send_email(to: str, subject: str):
    print(f"Sending email to {to}")

# This actor keeps its explicit "notifications" queue (no replacement)
@dramatiq.actor(queue_name="notifications")
def send_push_notification(user_id: int, message: str):
    print(f"Push to user {user_id}: {message}")

# Usage
send_email.send("user@example.com", "Welcome!")  # Goes to "myapp" queue
send_push_notification.send(123, "Hello!")       # Goes to "notifications" queue
```

**When to use:**

- Namespace queues by application name in shared RabbitMQ
- Migrate from another broker that used different queue naming
- Run multiple environments (dev, staging, prod) on same RabbitMQ

See [Configuration](configuration.md#default_queue_name) for detailed explanation.

## Retries and Error Handling

```python
@dramatiq.actor(
    max_retries=3,
    min_backoff=1000,  # Start with 1 second
    max_backoff=60000,  # Max 60 seconds
)
def flaky_api_call(url: str):
    import requests
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()

# Will retry up to 3 times with exponential backoff
flaky_api_call.send("https://api.example.com/data")
```

## Django Integration

```python
# settings.py
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
        "connection_holder_options": {
            "consumer_channel_pool_size": 5,
        },
        "max_priority": 10,
    },
}

# myapp/tasks.py
import dramatiq

@dramatiq.actor
def process_user_signup(user_id: int):
    from myapp.models import User
    user = User.objects.get(id=user_id)
    # Send welcome email, create profile, etc.

# myapp/views.py
from myapp.tasks import process_user_signup

def signup_view(request):
    user = User.objects.create(...)
    process_user_signup.send(user.id)
    return HttpResponse("Signup successful!")
```

## Batch Processing

```python
@dramatiq.actor
def process_batch(item_ids: list[int]):
    for item_id in item_ids:
        process_item(item_id)

# Send batches
items = list(range(1000))
batch_size = 100

for i in range(0, len(items), batch_size):
    batch = items[i:i + batch_size]
    process_batch.send(batch)
```

## Periodic Tasks

```python
# Use APScheduler with Dramatiq
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()

@dramatiq.actor
def daily_report():
    # Generate and send daily report
    print("Generating daily report...")

@scheduler.scheduled_job('cron', hour=9, minute=0)
def schedule_daily_report():
    daily_report.send()

# Run scheduler
scheduler.start()
```

## Chain Tasks

```python
@dramatiq.actor
def download_file(url: str) -> str:
    # Download and return file path
    return "/tmp/downloaded_file.pdf"

@dramatiq.actor
def process_file(file_path: str) -> dict:
    # Process file and return results
    return {"processed": True, "path": file_path}

@dramatiq.actor
def send_notification(results: dict):
    print(f"Processing complete: {results}")

# Chain using callbacks
from dramatiq.middleware import Callbacks

download_file.send_with_options(
    args=("https://example.com/file.pdf",),
    on_success=process_file.message(),
)
```

## Custom Topology

```python
from dramatiq_kombu_broker import DLXRoutingTopology
import datetime as dt

# Route delayed messages through DLX for monitoring
topology = DLXRoutingTopology(
    delay_queue_ttl=dt.timedelta(hours=24),  # Max 24h delay
    dead_letter_message_ttl=None,  # No TTL on DLX
)

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=topology,
)
```

## Health Checks

```python
from flask import Flask, jsonify
from dramatiq_kombu_broker.testing import ensure_consumer_connection_rabbitmq

app = Flask(__name__)

@app.route('/health')
def health_check():
    try:
        ensure_consumer_connection_rabbitmq(broker)
        return jsonify({"status": "healthy", "broker": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503
```

## Production Configuration

```python
import os
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": os.environ["RABBITMQ_URL"],
        "heartbeat": 60,  # Default value, shown explicitly for documentation
        "ssl": True,
        "ssl_options": {
            "ca_certs": "/etc/ssl/certs/ca.pem",
        },
        "transport_options": {
            "max_retries": 3,
            "interval_start": 0,
            "interval_step": 2,
            "interval_max": 30,
            "confirm_publish": True,
        },
    },
    connection_holder_options={
        "max_connections": 20,
    },
    default_queue_name="myapp",
    max_priority=10,
    confirm_delivery=True,
    max_enqueue_attempts=3,
    max_declare_attempts=5,
)
```

## Testing

```python
import pytest
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

@pytest.fixture
def test_broker():
    broker = ConnectionPooledKombuBroker(
        kombu_connection_options={
            "hostname": "amqp://guest:guest@localhost:5672/test"
        }
    )
    yield broker
    broker.flush_all()  # Clean up
    broker.close()

def test_task_processing(test_broker):
    import dramatiq
    dramatiq.set_broker(test_broker)

    @dramatiq.actor
    def add(x, y):
        return x + y

    add.send(2, 3)

    # Process messages
    worker = dramatiq.Worker(test_broker, worker_threads=1)
    worker.start()
    test_broker.join(add.queue_name, timeout=5000)
    worker.stop()
```

## Monitoring with Prometheus

```python
from dramatiq.middleware import Prometheus

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    middleware=[
        Prometheus(http_host="0.0.0.0", http_port=9191),
        # ... other middleware
    ],
)

# Metrics available at http://localhost:9191
```

## Error Tracking with Sentry

```python
from dramatiq.middleware import Callbacks
import sentry_sdk

sentry_sdk.init(dsn="your-sentry-dsn")

@dramatiq.actor
def task_with_error_tracking(data):
    try:
        # Process data
        pass
    except Exception as e:
        sentry_sdk.capture_exception(e)
        raise
```

## More Examples

See the [tests](https://github.com/spumer/dramatiq-kombu-broker/tree/main/tests) directory for more examples.
