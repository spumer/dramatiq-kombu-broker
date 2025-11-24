# Custom Topologies

Build your own queue topologies for specific use cases.

## Why Custom Topologies?

Default topology works for most cases. Create custom topology when you need:

- Different routing strategies
- Custom queue arguments
- Environment-specific configurations
- Special monitoring requirements

## Basic Custom Topology

```python
import dataclasses
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology

@dataclasses.dataclass
class MyTopology(DefaultDramatiqTopology):
    def _get_delay_queue_arguments(self, queue_name: str) -> dict:
        """Customize delay queue."""
        args = super()._get_delay_queue_arguments(queue_name)

        # Add custom argument
        args["x-max-length"] = 5000  # Limit to 5000 messages

        return args
```

Use it:

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=MyTopology(),
)
```

## Override Methods

### _get_canonical_queue_arguments

Main work queue configuration:

```python
def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
    args = super()._get_canonical_queue_arguments(queue_name, dlx)

    # Custom logic
    if queue_name == "critical":
        args["x-max-priority"] = 255  # Higher priority range

    return args
```

### _get_delay_queue_arguments

Delay queue configuration:

```python
def _get_delay_queue_arguments(self, queue_name: str) -> dict:
    args = super()._get_delay_queue_arguments(queue_name)

    # Set max TTL
    args["x-message-ttl"] = 86400000  # 24 hours max

    return args
```

### _get_dead_letter_queue_arguments

Dead letter queue configuration:

```python
def _get_dead_letter_queue_arguments(self, queue_name: str) -> dict:
    args = super()._get_dead_letter_queue_arguments(queue_name)

    # Custom DLQ behavior
    args["x-max-length"] = 1000  # Limit DLQ size

    return args
```

## Examples

### Environment-Based Topology

```python
@dataclasses.dataclass
class EnvironmentTopology(DefaultDramatiqTopology):
    environment: str = "production"

    @property
    def dlx_exchange_name(self):
        # Different DLX per environment
        return f"dlx.{self.environment}"

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)

        if self.environment == "development":
            # Shorter TTL in dev
            args["x-message-ttl"] = 3600000  # 1 hour

        return args

# Usage
topology = EnvironmentTopology(environment="staging")
broker = ConnectionPooledKombuBroker(topology=topology, ...)
```

### Queue Size Limits

```python
@dataclasses.dataclass
class LimitedTopology(DefaultDramatiqTopology):
    max_queue_length: int = 10000
    overflow_behavior: str = "reject-publish"  # or "drop-head"

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)
        args["x-max-length"] = self.max_queue_length
        args["x-overflow"] = self.overflow_behavior
        return args

topology = LimitedTopology(max_queue_length=5000)
```

### Per-Queue Configuration

```python
@dataclasses.dataclass
class PerQueueTopology(DefaultDramatiqTopology):
    queue_configs: dict = dataclasses.field(default_factory=dict)

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)

        # Get config for this queue
        config = self.queue_configs.get(queue_name, {})

        if "max_length" in config:
            args["x-max-length"] = config["max_length"]

        if "max_priority" in config:
            args["x-max-priority"] = config["max_priority"]

        return args

# Usage
topology = PerQueueTopology(
    queue_configs={
        "critical": {"max_priority": 255, "max_length": 1000},
        "background": {"max_length": 50000},
    }
)
```

### Monitoring Topology

Routes everything through DLX for monitoring:

```python
@dataclasses.dataclass
class MonitoringTopology(DefaultDramatiqTopology):
    def _get_delay_queue_arguments(self, queue_name: str) -> dict:
        """Route through DLX for visibility."""
        canonical = self.get_canonical_queue_name(queue_name)
        dlx_name = self.get_dead_letter_queue_name(canonical)

        return {
            "x-dead-letter-exchange": self.dlx_exchange_name,
            "x-dead-letter-routing-key": dlx_name,  # To DLX first
        }

    def _get_dead_letter_queue_arguments(self, queue_name: str) -> dict:
        """DLX forwards to canonical queue."""
        canonical = self.get_canonical_queue_name(queue_name)

        return {
            "x-dead-letter-exchange": self.dlx_exchange_name,
            "x-dead-letter-routing-key": canonical,  # Then to canonical
            # No TTL - messages forwarded immediately
        }
```

## Queue Arguments Reference

Common RabbitMQ queue arguments:

### Dead Letter

```python
{
    "x-dead-letter-exchange": "",  # Exchange name
    "x-dead-letter-routing-key": "target-queue",  # Target queue
}
```

### TTL

```python
{
    "x-message-ttl": 60000,  # 60 seconds in milliseconds
    "x-expires": 3600000,  # Queue auto-deletes after 1 hour unused
}
```

### Length Limits

```python
{
    "x-max-length": 1000,  # Max messages
    "x-max-length-bytes": 1048576,  # Max bytes (1MB)
    "x-overflow": "reject-publish",  # or "drop-head"
}
```

### Priority

```python
{
    "x-max-priority": 10,  # Priorities 0-10
}
```

### Lazy Queues

```python
{
    "x-queue-mode": "lazy",  # Move to disk ASAP
}
```

## Testing Custom Topologies

```python
def test_custom_topology():
    topology = MyTopology()

    # Test queue arguments
    args = topology._get_canonical_queue_arguments("test")
    assert "x-dead-letter-exchange" in args

    # Test queue names
    names = topology.get_queue_name_tuple("test")
    assert names.canonical == "test"
    assert names.delayed == "test.DQ"
    assert names.dead_letter == "test.XQ"
```

## Best Practices

1. **Start with defaults** - Only override what you need
2. **Document changes** - Explain why custom topology is needed
3. **Test thoroughly** - Verify routing works as expected
4. **Keep it simple** - Complex routing is hard to debug
5. **Don't modify topology** - Broker should never modify topology instance

## Common Pitfalls

### Forgetting Dead Letter Parameters

```python
# WRONG - delay queue without dead-letter
def _get_delay_queue_arguments(self, queue_name: str) -> dict:
    return {}  # Messages will never leave delay queue!

# RIGHT - include dead-letter routing
def _get_delay_queue_arguments(self, queue_name: str) -> dict:
    return super()._get_delay_queue_arguments(queue_name)
```

### Circular Routing

```python
# WRONG - creates loop
def _get_delay_queue_arguments(self, queue_name: str) -> dict:
    delay_name = self.get_delay_queue_name(queue_name)
    return {
        "x-dead-letter-routing-key": delay_name,  # Routes to itself!
    }
```

### Modifying Topology After Creation

```python
# WRONG - broker should not modify topology
broker = ConnectionPooledKombuBroker(topology=my_topology, ...)
my_topology.max_priority = 10  # Don't do this!

# RIGHT - configure topology before passing to broker
my_topology = MyTopology(max_priority=10)
broker = ConnectionPooledKombuBroker(topology=my_topology, ...)
```

## Next Steps

- [Topologies](topologies.md) - Built-in topologies
- [API Reference](api-reference.md) - Topology API
- [Examples](examples.md) - More topology examples
