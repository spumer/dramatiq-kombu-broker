## v0.2.2 (2024-10-21)

## v0.2.1 (2024-10-03)

## v0.2.0 (2024-10-03)

### Feat

- **KombuBroker**: now RabbitMQ return error when message published to non-existing queue, previously the message was discarded; (use mandatory=True)
- **KombuBroker**: now you can ensure `.XQ` and `.DQ` queues when canonical declared before. Just place queue name to `broker.queues_pending` and call declare with ensure=True

### Fix

- **KombuBroker**: do not close channels each time, use channel context manager instead (all channels are support our ReleasableChannel protocol)
- **topology**: now declare_*_queue re-raise PreconditionFailed when it's not topology difference error (e.g. invalid arguments)
- **topology**: x-message-ttl now passed correclty (previous we can pass float instead int; rabbitmq not allow float)

### Refactor

- **broker**: add _enqueue_message function; now enqueue can be overrided or reused internally
- explicit use canonical queue name where it required; use queue names from given Topology

## v0.1.1 (2024-06-13)

### Fix

- **topology**: respect dramatiq_dead_message_ttl env by default

## v0.1.0 (2024-06-12)

### Feat

- publish to internet

### Refactor

- python >= 3.9
