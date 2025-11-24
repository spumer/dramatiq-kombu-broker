# Queue Topologies

Topologies define how queues are structured and how messages flow between them.

## Overview

When Dramatiq sends a delayed message, it goes to a "delay queue" first. After the delay expires, the message needs to get to the main queue where workers pick it up. The topology controls this routing.

## Default Topology

The standard topology (`DefaultDramatiqTopology`) works like the regular Dramatiq broker:

```
Message → Delay Queue (waits) → Main Queue → Worker
```

When a message's TTL expires in the delay queue, RabbitMQ's dead-letter mechanism routes it directly to the main queue.

### Usage

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

# Default topology is used automatically
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."}
)
```

### Queue Structure

For a queue named "tasks":

- `tasks` - Main queue where workers consume
- `tasks.DQ` - Delay queue for delayed messages
- `tasks.XQ` - Dead letter queue for failed messages

## DLX Routing Topology

Alternative topology that routes expired delay messages through the dead letter queue first:

```
Message → Delay Queue (waits) → Dead Letter Queue → Main Queue → Worker
```

This adds a hop but gives you a place to monitor/log all delayed messages as they transition.

### When To Use

Use `DLXRoutingTopology` if you need to:

- Monitor all delayed messages as they expire
- Add custom processing before messages reach workers
- Maintain an audit trail of delayed message transitions

### Usage

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, DLXRoutingTopology
import datetime as dt

topology = DLXRoutingTopology(
    delay_queue_ttl=dt.timedelta(hours=24),  # Max delay: 24 hours
    dead_letter_message_ttl=None,  # No TTL on DLX
)

broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=topology,
)
```

### Configuration

```python
DLXRoutingTopology(
    # Maximum TTL for delay queue (optional)
    delay_queue_ttl=dt.timedelta(hours=3),

    # TTL for messages in dead letter queue (optional)
    dead_letter_message_ttl=None,

    # Queue durability
    durable=True,

    # Auto-delete queues when unused
    auto_delete=False,

    # Max priority for priority queues
    max_priority=None,
)
```

## Comparison

| Aspect | DefaultDramatiqTopology | DLXRoutingTopology |
|--------|------------------------|-------------------|
| Delay routing | Direct to main queue | Via DLX |
| Message hops | 2 (delay → main) | 3 (delay → DLX → main) |
| Monitoring | Limited | Full visibility in DLX |
| Performance | Faster | Slightly slower |
| Use case | Standard workflows | Audit/monitoring needs |

## Custom Topologies

You can create your own topology by subclassing `DefaultDramatiqTopology`:

```python
import dataclasses
import datetime as dt
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology

@dataclasses.dataclass
class MyTopology(DefaultDramatiqTopology):
    def _get_delay_queue_arguments(self, queue_name: str) -> dict:
        """Customize delay queue configuration."""
        args = super()._get_delay_queue_arguments(queue_name)

        # Add custom arguments
        args["x-max-length"] = 10000  # Limit queue size

        return args

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        """Customize main queue configuration."""
        args = super()._get_canonical_queue_arguments(queue_name, dlx)

        # Example: different routing for specific queues
        if queue_name == "critical":
            args["x-max-priority"] = 255

        return args
```

Then use it:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=MyTopology(max_priority=10),
)
```

## Queue Arguments

Each topology method returns queue arguments dict that gets passed to RabbitMQ. Common arguments:

### Dead Letter Configuration

```python
{
    "x-dead-letter-exchange": "",  # Default exchange
    "x-dead-letter-routing-key": "tasks",  # Target queue
}
```

### TTL Configuration

```python
{
    "x-message-ttl": 60000,  # 60 seconds in milliseconds
}
```

### Priority Configuration

```python
{
    "x-max-priority": 10,  # Priorities 0-10
}
```

### Queue Length Limits

```python
{
    "x-max-length": 1000,  # Max 1000 messages
    "x-overflow": "reject-publish",  # Reject new messages when full
}
```

## Topology Methods

When creating custom topologies, override these methods:

### `_get_canonical_queue_arguments(queue_name, dlx=True)`

Returns arguments for the main work queue.

- `queue_name`: The queue name
- `dlx`: Whether to add dead-letter configuration

### `_get_delay_queue_arguments(queue_name)`

Returns arguments for the delay queue.

### `_get_dead_letter_queue_arguments(queue_name)`

Returns arguments for the dead letter queue.

## Migration Between Topologies

**Warning:** Changing topologies requires restarting workers and may cause issues with existing messages.

Steps to migrate:

1. Stop all workers
2. Process or purge existing messages
3. Update broker configuration with new topology
4. Restart workers

RabbitMQ will reject the new topology if it conflicts with existing queues. Options:

- Delete queues manually via RabbitMQ management UI
- Use different queue names
- Set `ignore_different_topology=True` in broker (not recommended for production)

## Examples

### High-Priority Queue with Limits

```python
@dataclasses.dataclass
class LimitedPriorityTopology(DefaultDramatiqTopology):
    max_queue_length: int = 10000

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)
        args["x-max-length"] = self.max_queue_length
        args["x-overflow"] = "reject-publish"
        return args

topology = LimitedPriorityTopology(
    max_priority=10,
    max_queue_length=5000,
)
```

### Separate DLX Per Environment

```python
@dataclasses.dataclass
class EnvironmentTopology(DefaultDramatiqTopology):
    environment: str = "production"

    @property
    def dlx_exchange_name(self):
        return f"dlx.{self.environment}"

topology = EnvironmentTopology(environment="staging")
```

## Best Practices

1. **Keep it simple** - Use `DefaultDramatiqTopology` unless you have specific needs
2. **Test topology changes** - Always test in staging first
3. **Document custom logic** - Add docstrings explaining why you're customizing
4. **Don't modify the topology object** - Pass a configured instance to the broker
5. **Monitor queue depths** - Watch for messages stuck in delay or DLX queues

## Troubleshooting

### PreconditionFailed Error

```
amqp.exceptions.PreconditionFailed: inequivalent arg 'x-dead-letter-exchange'
```

This means queue arguments don't match. Either:

- Delete the queue and let it recreate
- Use the same arguments as before
- Change the queue name

### Messages Not Routing

Check RabbitMQ logs and management UI:

1. Verify dead-letter exchange is correct (usually empty string)
2. Check dead-letter routing key matches target queue name
3. Ensure target queue exists before messages expire

### Delayed Messages Not Working

Common issues:

- Delay queue missing dead-letter parameters (use `DefaultDramatiqTopology`)
- TTL not set correctly on messages
- Wrong routing key in dead-letter configuration

## Next Steps

- [Custom Topologies Guide](custom-topologies.md) - Detailed guide for building custom topologies
- [Migration Guide](migration.md) - Migrate from standard broker
- [Examples](examples.md) - Real-world topology examples
