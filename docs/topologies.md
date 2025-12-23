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

Alternative topology that routes expired delay messages to the dead letter queue:

```
Message → Delay Queue (waits) → Dead Letter Queue (stops here)
```

Messages remain in the dead letter queue and are **not** automatically forwarded to the main queue. This gives you full control over what happens to delayed messages after they expire.

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
    max_delay_time=dt.timedelta(hours=24),  # Max delay: 24 hours
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
    # Maximum delay time for messages (optional)
    max_delay_time=dt.timedelta(hours=3),

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

## Managing Long-Lived Delayed Messages

### The Problem

Dramatiq uses worker-side delayed messages - messages stay unacked in RabbitMQ until their delay expires. When workers consume messages with `delay`, they hold them in memory without acknowledging. This creates issues:

- **Memory exhaustion** - Long delays (days/weeks) accumulate [unacked messages in RAM](https://www.cloudamqp.com/blog/part1-rabbitmq-best-practice.html), potentially triggering [memory alarms](https://github.com/rabbitmq/rabbitmq-server/issues/1164)
- **Transaction log growth** - [Quorum queues maintain WAL (write-ahead-log)](https://www.rabbitmq.com/docs/quorum-queues) for unacked messages, consuming disk space until messages are acknowledged
- **Performance degradation** - High volumes of delayed messages impact RabbitMQ performance and can [overwhelm consumers](https://www.rabbitmq.com/docs/confirms)

### The Solution: Defense in Depth

The `max_delay_time` feature provides two-layer protection:

**Layer 1: Application Validation** - Fail-fast at publishing time. When you try to enqueue a message with `delay` exceeding `max_delay_time`, the broker raises `DelayTooLongError` immediately.

**Layer 2: RabbitMQ Failsafe** - Queue-level TTL (`x-message-ttl`) as backup. Even if validation is bypassed, RabbitMQ automatically expires messages after the configured TTL.

### Usage Examples

#### Conservative Limit (3 hours)

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker, DefaultDramatiqTopology
import datetime as dt

topology = DefaultDramatiqTopology(
    max_delay_time=dt.timedelta(hours=3)  # Conservative limit
)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=topology,
)

# This works - 2 hour delay
task.send_with_options(delay=2*60*60*1000)  # 2 hours in ms

# This raises DelayTooLongError - exceeds limit
task.send_with_options(delay=5*60*60*1000)  # 5 hours in ms
```

#### Moderate Limit (24 hours)

```python
topology = DefaultDramatiqTopology(
    max_delay_time=dt.timedelta(hours=24)  # Moderate limit for background jobs
)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=topology,
)
```

#### Unlimited (Backward Compatible)

```python
topology = DefaultDramatiqTopology()  # max_delay_time=None (default)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={"hostname": "amqp://..."},
    topology=topology,
)
# No limit - same as before
```

### Exception Handling

```python
from dramatiq_kombu_broker import DelayTooLongError

try:
    task.send_with_options(delay=7*24*60*60*1000)  # 1 week
except DelayTooLongError as e:
    logger.error(
        f"Delay {e.delay}ms exceeds max {e.max_delay}ms for queue {e.queue_name}"
    )
    # Handle: reduce delay, reject request, or queue differently
```

### DLXRoutingTopology Configuration

Use `max_delay_time` to configure the maximum delay for `DLXRoutingTopology`:

```python
from dramatiq_kombu_broker import DLXRoutingTopology

topology = DLXRoutingTopology(
    max_delay_time=dt.timedelta(hours=5),  # Recommended approach
)
# Actual limit: 5 hours
```

!!! warning "Deprecated: delay_queue_ttl"
    The `delay_queue_ttl` parameter is **deprecated** and will be removed in a future version.
    Use `max_delay_time` instead.

    For backward compatibility, if both parameters are provided, `delay_queue_ttl` takes precedence:

    ```python
    # Legacy code (deprecated - migrate to max_delay_time)
    topology = DLXRoutingTopology(
        delay_queue_ttl=dt.timedelta(hours=1),   # Deprecated, but takes precedence
        max_delay_time=dt.timedelta(hours=5),    # Ignored when delay_queue_ttl is set
    )
    # Actual limit: 1 hour
    ```

### Migration Guide

**Existing Applications:**

- Default: `max_delay_time=None` - no changes needed
- Existing queues continue working without modification
- No queue deletion required

**To Enable Protection:**

1. Update topology configuration:
```python
topology = DefaultDramatiqTopology(max_delay_time=dt.timedelta(hours=3))
```

2. **Test in staging first** - verify your delays fit within the limit

3. Deploy with new configuration:
   - New queues created with TTL automatically
   - Existing queues continue working (no TTL enforcement until recreated)

4. **Optional:** Recreate existing delay queues to apply TTL:
   - Stop workers
   - Delete delay queues via RabbitMQ management UI (`*.DQ` queues)
   - Restart workers (queues recreated with TTL)

**Note:** If you try to redeclare queues with different TTL, RabbitMQ raises `PreconditionFailed`. Either delete the queue first or use `ignore_different_topology=True` (not recommended for production).

### Best Practices

| Delay Range | Recommended max_delay_time | Rationale |
|-------------|---------------------------|-----------|
| Minutes to hours | 3-6 hours | Safe for most use cases, prevents memory issues |
| Hours to days | 24 hours | Suitable for background jobs and daily tasks |
| Days to weeks | **Not recommended** | Use cron jobs or scheduled task systems instead |
| Unlimited | `None` (default) | Only if you understand the memory risks |

**Key Recommendations:**

- **Start conservative** - Use 3-6 hours initially, increase if needed
- **Monitor delays** - Track `DelayTooLongError` exceptions to identify patterns
- **Use alternatives for long delays** - Cron jobs or schedulers for delays > 24 hours
- **Make tasks idempotent** - Messages may be processed twice if TTL expires before delivery
- **Test limits in staging** - Verify your actual delay patterns before production

### Further Reading

**Official RabbitMQ Documentation:**

- [Consumer Acknowledgements and Publisher Confirms](https://www.rabbitmq.com/docs/confirms) - How unacked messages affect memory
- [Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues) - Write-ahead-log (WAL) and message acknowledgment
- [Time-To-Live and Expiration](https://www.rabbitmq.com/docs/ttl) - TTL behavior and ordering considerations

**Best Practices and Troubleshooting:**

- [RabbitMQ Best Practices - CloudAMQP](https://www.cloudamqp.com/blog/part1-rabbitmq-best-practice.html) - Memory management with unacked messages
- [Delayed Messages Documentation - CloudAMQP](https://www.cloudamqp.com/docs/delayed-messages.html) - Implementing delayed messages correctly
- [13 Common RabbitMQ Mistakes](https://www.cloudamqp.com/blog/part4-rabbitmq-13-common-errors.html) - Avoiding common pitfalls
- [Key Metrics for RabbitMQ Monitoring - Datadog](https://www.datadoghq.com/blog/rabbitmq-monitoring/) - Monitoring unacked messages and queue depth

**Real-World Issues:**

- [GitHub Issue #1164](https://github.com/rabbitmq/rabbitmq-server/issues/1164) - Memory alarm with many unacked messages

## Comparison

| Aspect | DefaultDramatiqTopology | DLXRoutingTopology |
|--------|------------------------|-------------------|
| Delay routing | Direct to main queue | To DLX (stops there) |
| Message hops | 2 (delay → main) | 2 (delay → DLX) |
| Final destination | Main queue (auto) | DLX (manual processing required) |
| Monitoring | Limited | Full visibility in DLX |
| Use case | Standard workflows | Audit/monitoring/custom pipelines |

## Advanced: Custom Topologies

### When to Create Custom Topologies

Default topology works for most cases. Create custom topology when you need:

- Different routing strategies
- Custom queue arguments
- Environment-specific configurations
- Special monitoring requirements

### Basic Example

```python
import dataclasses
from dramatiq_kombu_broker.topology import DefaultDramatiqTopology

@dataclasses.dataclass
class MyTopology(DefaultDramatiqTopology):
    def _get_delay_queue_arguments(self, queue_name: str) -> dict:
        """Customize delay queue."""
        args = super()._get_delay_queue_arguments(queue_name)
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

### Override Methods

#### _get_canonical_queue_arguments

Main work queue configuration:

```python
def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
    args = super()._get_canonical_queue_arguments(queue_name, dlx)

    if queue_name == "critical":
        args["x-max-priority"] = 255  # Higher priority range

    return args
```

#### _get_delay_queue_arguments

Delay queue configuration:

```python
def _get_delay_queue_arguments(self, queue_name: str) -> dict:
    args = super()._get_delay_queue_arguments(queue_name)
    args["x-message-ttl"] = 86400000  # 24 hours max
    return args
```

#### _get_dead_letter_queue_arguments

Dead letter queue configuration:

```python
def _get_dead_letter_queue_arguments(self, queue_name: str) -> dict:
    args = super()._get_dead_letter_queue_arguments(queue_name)
    args["x-max-length"] = 1000  # Limit DLQ size
    return args
```

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

### Real-World Examples

#### Queue Size Limits

Limit queue size using [x-max-length](https://www.rabbitmq.com/docs/maxlength#definition-using-x-args):

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

#### Environment-Based Configuration

```python
@dataclasses.dataclass
class EnvironmentTopology(DefaultDramatiqTopology):
    environment: str = "production"

    @property
    def dlx_exchange_name(self):
        return f"dlx.{self.environment}"

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)

        if self.environment == "development":
            args["x-message-ttl"] = 3600000  # 1 hour in dev

        return args

topology = EnvironmentTopology(environment="staging")
```

#### Per-Queue Configuration

```python
@dataclasses.dataclass
class PerQueueTopology(DefaultDramatiqTopology):
    queue_configs: dict = dataclasses.field(default_factory=dict)

    def _get_canonical_queue_arguments(self, queue_name: str, dlx: bool = True) -> dict:
        args = super()._get_canonical_queue_arguments(queue_name, dlx)
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

#### Monitoring Topology

!!! info "Difference from DLXRoutingTopology"
    Unlike `DLXRoutingTopology` which stops messages in DLX, this custom topology
    automatically forwards messages from DLX to the canonical queue using
    `x-dead-letter-routing-key` on the DLX queue itself.

Routes everything through DLX for monitoring, then forwards to canonical queue:

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
        }
```

### Testing Custom Topologies

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
2. **Test topology changes** - Always test in staging first
3. **Document custom logic** - Add docstrings explaining why you're customizing
4. **Keep it simple** - Complex routing is hard to debug
5. **Don't modify the topology object** - Pass a configured instance to the broker
6. **Monitor queue depths** - Watch for messages stuck in delay or DLX queues

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

- [Configuration](configuration.md) - Configure topology parameter
- [Migration Guide](migration.md) - Migrate from standard broker
- [Examples](examples.md) - Real-world topology examples
- [API Reference](api-reference.md) - Topology API details
