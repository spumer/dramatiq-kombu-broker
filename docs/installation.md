# Installation

## Requirements

- Python 3.10 or higher
- RabbitMQ 3.7 or higher (recommended: 3.12+)
- dramatiq >= 1.17.0

## Install from PyPI

The simplest way to install dramatiq-kombu-broker is via pip:

```bash
pip install dramatiq-kombu-broker
```

## Install with Django Support

If you're using Django with django-dramatiq:

```bash
pip install dramatiq-kombu-broker django-dramatiq
```

## Install from Source

For development or to get the latest features:

```bash
git clone https://github.com/spumer/dramatiq-kombu-broker.git
cd dramatiq-kombu-broker
pip install -e .
```

## Verify Installation

```python
import dramatiq_kombu_broker
print(dramatiq_kombu_broker.__version__)
```

## Setting Up RabbitMQ

### Using Docker

The quickest way to get RabbitMQ running:

```bash
docker run -d \
  --name rabbitmq \
  -p 5672:5672 \
  -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=guest \
  -e RABBITMQ_DEFAULT_PASS=guest \
  rabbitmq:3.12-management
```

Access the management UI at http://localhost:15672 (guest/guest)

### Using Docker Compose

Create `docker-compose.yml`:

```yaml
version: "3.9"

services:
  rabbitmq:
    image: rabbitmq:3.12-management
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    healthcheck:
      test: rabbitmq-diagnostics -q ping
      interval: 10s
      timeout: 5s
      retries: 5
```

Start RabbitMQ:

```bash
docker-compose up -d
```

### System Package Managers

=== "Ubuntu/Debian"

    ```bash
    sudo apt-get install rabbitmq-server
    sudo systemctl enable rabbitmq-server
    sudo systemctl start rabbitmq-server
    ```

=== "macOS"

    ```bash
    brew install rabbitmq
    brew services start rabbitmq
    ```

=== "CentOS/RHEL"

    ```bash
    sudo yum install rabbitmq-server
    sudo systemctl enable rabbitmq-server
    sudo systemctl start rabbitmq-server
    ```

## Optional Dependencies

### Development Tools

For development, install additional dependencies:

```bash
pip install dramatiq-kombu-broker[dev]
```

This includes:
- pytest - Testing framework
- mypy - Type checking
- ruff - Linting and formatting
- pre-commit - Git hooks

### Connection Pooling

Connection pooling is built-in. For thread-safe channel pooling, the required dependency `kombu-pyamqp-threadsafe` is automatically installed.

## Next Steps

- [Quick Start Guide](quickstart.md) - Get started in 5 minutes
- [Configuration](configuration.md) - Configure your broker
- [Examples](examples.md) - See usage examples
