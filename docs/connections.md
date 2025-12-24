# Connection Management

Operational guide for managing RabbitMQ connections: how connections are created, monitored, troubleshooted, and maintained at runtime.

For configuration parameters, see [Configuration](configuration.md).

## Broker Types

dramatiq-kombu-broker provides two connection strategies:

- **ConnectionPooledKombuBroker**: Multiple connections, each reused for operations
- **ConnectionSharedKombuBroker**: Single shared connection with channel pooling

See [Configuration - Broker Types](configuration.md#broker-types) for detailed parameters and usage examples.

## Connection Lifecycle

1. Broker creates connection holder on init
2. Connection holder manages connections/channels
3. Operations acquire connection/channel from pool
4. After use, connection/channel returns to pool
5. On broker close, all connections are closed

## Heartbeats

Heartbeats keep connections alive and detect dead connections. By default, heartbeat is set to **60 seconds** - no configuration needed for most use cases.

To override the default heartbeat interval:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "heartbeat": 30,  # Override: reduce for unreliable networks
    },
)
```

If network is unreliable, reduce heartbeat interval (e.g., 30 seconds).

## Connection Retries

Configure retry behavior:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "transport_options": {
            "max_retries": 3,  # Retry 3 times
            "interval_start": 0,  # Start immediately
            "interval_step": 2,  # Add 2 seconds each retry
            "interval_max": 30,  # Max 30 seconds between retries
        },
    },
)
```

## Connection Visibility

The broker automatically adds hostname to connection properties, making it easy to identify connections in RabbitMQ management UI:

![Connection hostname in RabbitMQ UI](../media/connection_hostname.png)

You can also set a custom connection name:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://...",
        "transport_options": {
            "client_properties": {
                "connection_name": "my-app-worker",  # Custom name
            },
        },
    },
)
```

If not set, uses system hostname automatically.

## SSL/TLS

Secure connections:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqps://...",  # Note: amqps
        "ssl": True,
        "ssl_options": {
            "ca_certs": "/path/to/ca.pem",
            "certfile": "/path/to/client-cert.pem",
            "keyfile": "/path/to/client-key.pem",
        },
    },
)
```

## Monitoring

Check connection health:

```python
from dramatiq_kombu_broker.testing import ensure_consumer_connection_rabbitmq

try:
    ensure_consumer_connection_rabbitmq(broker)
    print("Connection OK")
except Exception as e:
    print(f"Connection failed: {e}")
```

Use in health check endpoints:

```python
# Flask example
@app.route('/health')
def health():
    try:
        ensure_consumer_connection_rabbitmq(broker)
        return {"status": "healthy"}, 200
    except Exception:
        return {"status": "unhealthy"}, 503
```

## Connection Limits

RabbitMQ has connection limits. Monitor in management UI or via API:

```bash
# Check connection count
rabbitmqctl list_connections

# Check limits
rabbitmqctl environment | grep connection
```

Increase limits if needed:

```ini
# rabbitmq.conf
connection_max = 1000
```

## Troubleshooting

### Too Many Connections

Symptom: `connection_limit_reached` errors

Solutions:
- Use `ConnectionSharedKombuBroker` instead of `ConnectionPooledKombuBroker`
- Reduce `max_connections` in pool
- Increase RabbitMQ connection limit

### Connection Refused

Symptom: `ConnectionRefusedError`

Check:
- RabbitMQ is running
- Firewall allows port 5672 (or 5671 for SSL)
- Correct hostname/port in connection string
- User has permissions on vhost

### Heartbeat Failures

Symptom: Connections drop unexpectedly

Try:
- Reduce heartbeat interval (30 instead of 60)
- Check network stability
- Increase RabbitMQ heartbeat timeout

### Channel Errors

Symptom: `ChannelError: 406, PRECONDITION_FAILED`

Usually topology mismatches. See [Topologies](topologies.md).

## Best Practices

1. **Use connection pooling** for multi-process workers
2. **Use shared connection** for threaded apps
3. **Heartbeats enabled by default** (60s) - adjust if needed for your network
4. **Configure retries** for reliability
5. **Monitor connection count** in RabbitMQ UI
6. **Use SSL** in production
7. **Set connection names** for debugging

## Next Steps

- [Configuration](configuration.md) - Full connection options
- [Performance Tuning](performance.md) - Optimize connection usage
- [Troubleshooting](troubleshooting.md) - Fix connection issues
