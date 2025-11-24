# Delivery Guarantees

Когда вы отправляете задачу через `task.send()`, важно понимать что происходит с сообщением и какие гарантии вы получаете. dramatiq-kombu-broker предоставляет два ключевых параметра для управления поведением: `confirm_delivery` и `blocking_acknowledge`.

## Два параметра, одна цель

Оба параметра отвечают за надежность, но работают на разных этапах:

- **`confirm_delivery`** — контролирует что происходит когда вы **отправляете** сообщение (publisher side)
- **`blocking_acknowledge`** — контролирует что происходит когда worker **обрабатывает** сообщение (consumer side)

## confirm_delivery: Гарантия отправки

### Что это такое

`confirm_delivery` использует механизм [Publisher Confirms](https://www.rabbitmq.com/docs/confirms) из RabbitMQ. Когда этот параметр включен, брокер RabbitMQ отправляет подтверждение что сообщение было принято и направлено в очередь.

**По умолчанию:** `True` (включено)

### Как это работает

```python
from dramatiq_kombu_broker import ConnectionPooledKombuBroker

# С confirm_delivery=True (по умолчанию)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,  # RabbitMQ подтверждает прием
)

@dramatiq.actor
def send_email(email):
    ...

# Если RabbitMQ не подтвердит прием, вы получите исключение здесь:
try:
    send_email.send("user@example.com")
except Exception as e:
    # Сообщение НЕ было доставлено в очередь
    log_failed_task(e)
```

### Что гарантирует confirm_delivery

Когда `confirm_delivery=True`, вы получаете три важных гарантии:

1. **Сообщение принято брокером** — RabbitMQ получил ваше сообщение
2. **Сообщение направлено в очередь** — благодаря `mandatory=True` (включен по умолчанию), сообщение не будет отброшено если очередь не найдена
3. **Синхронная ошибка** — если что-то пошло не так, исключение будет брошено прямо в `task.send()`

Важно понимать: Publisher Confirms **не** гарантируют что сообщение было обработано консьюмером. Они гарантируют только что сообщение достигло брокера и было помещено в очередь.

### mandatory=True по умолчанию

dramatiq-kombu-broker использует `mandatory=True` при публикации сообщений (см. [broker.py:368](../dramatiq_kombu_broker/broker.py#L368)). Это означает:

- Если очереди не существует, RabbitMQ вернет сообщение отправителю
- Вы получите исключение `amqp.exceptions.ChannelError(312, 'NO_ROUTE')`
- Сообщение не будет потеряно "в никуда"

Подробнее: [RabbitMQ Mandatory Messages](https://www.compilenrun.com/docs/middleware/rabbitmq/rabbitmq-reliability/rabbitmq-mandatory-messages/)

### Когда отключать confirm_delivery

```python
# Отключить для максимальной скорости (не рекомендуется для продакшна)
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "...",
        "transport_options": {
            "confirm_publish": False,  # Отключить на уровне транспорта
        },
    },
    confirm_delivery=False,  # И на уровне брокера
)
```

**Когда это нужно:**

- Очень высокая нагрузка (десятки тысяч задач в секунду)
- Задачи не критичны (логирование, аналитика)
- Вы готовы потерять сообщения при сбоях

**Что вы теряете:**

- Сообщение может быть потеряно при проблемах с сетью
- Сообщение может быть потеряно при перезапуске RabbitMQ
- Вы не узнаете об ошибках до тех пор пока задача не будет обработана (или не будет)

## blocking_acknowledge: Гарантия обработки

### Что это такое

`blocking_acknowledge` контролирует когда worker отправляет ACK (подтверждение обработки) обратно в RabbitMQ после выполнения задачи.

**По умолчанию:** `True` (блокирующий режим)

### Как это работает

Когда worker обрабатывает сообщение, он должен отправить ACK чтобы RabbitMQ удалил сообщение из очереди. Есть два способа:

**Блокирующий режим (blocking_acknowledge=True):**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=True,  # По умолчанию
)

@dramatiq.actor
def process_order(order_id):
    # 1. Задача выполняется
    result = heavy_computation(order_id)

    # 2. Worker отправляет ACK и ЖДЕТ подтверждения от RabbitMQ
    # 3. Только после подтверждения берет следующее сообщение
    return result
```

**Неблокирующий режим (blocking_acknowledge=False):**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=False,  # Асинхронный ACK
)

@dramatiq.actor
def process_order(order_id):
    # 1. Задача выполняется
    result = heavy_computation(order_id)

    # 2. Worker помещает ACK в очередь и СРАЗУ берет следующее сообщение
    # 3. ACK будет отправлен позже, перед получением нового сообщения
    return result
```

### Разница в поведении

Рассмотрим пример с ошибкой сети:

```python
# blocking_acknowledge=True
@dramatiq.actor
def important_task():
    result = charge_credit_card()
    # Worker пытается отправить ACK
    # Если сеть упала — worker получит исключение ЗДЕСЬ
    # Сообщение останется в очереди
    # После переподключения задача будет выполнена снова
    return result

# blocking_acknowledge=False
@dramatiq.actor
def important_task():
    result = charge_credit_card()
    # Worker помещает ACK в очередь и берет следующую задачу
    # Если сеть упадет до отправки ACK — сообщение останется в очереди
    # Но вы уже начали обрабатывать следующее сообщение
    return result
```

### Когда использовать blocking_acknowledge=True

**Используйте по умолчанию для:**

- Финансовых операций
- Критически важных задач
- Задач с побочными эффектами (отправка email, изменение базы данных)
- Когда важна гарантия "at-least-once delivery"

**Преимущества:**

- Гарантия что ACK был отправлен и подтвержден
- Исключение при проблемах с сетью происходит сразу
- Меньше риска потери данных

**Недостатки:**

- Немного медленнее (worker ждет подтверждения ACK)
- Worker не может взять следующее сообщение пока не получит подтверждение

### Когда использовать blocking_acknowledge=False

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=False,
)
```

**Используйте для:**

- Высоконагруженных систем
- Идемпотентных задач (можно выполнить повторно без проблем)
- Задач с низким приоритетом

**Преимущества:**

- Выше throughput (worker не ждет подтверждения)
- Worker сразу берет следующее сообщение

**Недостатки:**

- ACK может быть потерян при сбое сети
- Сообщение может быть обработано дважды
- Ошибки ACK логируются, но не блокируют выполнение

## Комбинирование параметров

### Максимальная надежность (рекомендуется для продакшна)

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq.prod:5672/",
        "transport_options": {
            "confirm_publish": True,  # Publisher confirms
        },
    },
    confirm_delivery=True,        # Подтверждение отправки
    blocking_acknowledge=True,    # Подтверждение обработки
)
```

**Гарантии:**

- Сообщение точно попало в очередь
- Worker точно отправил ACK
- Исключения при любых проблемах
- At-least-once delivery

**Недостаток:** немного ниже производительность

### Максимальная скорость (только для некритичных задач)

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": "amqp://user:pass@rabbitmq.prod:5672/",
        "transport_options": {
            "confirm_publish": False,  # Без подтверждения
        },
    },
    confirm_delivery=False,        # Без подтверждения отправки
    blocking_acknowledge=False,    # Без блокирующего ACK
)
```

**Преимущества:**

- Максимальный throughput
- Минимальная задержка

**Недостатки:**

- Сообщения могут быть потеряны
- Задачи могут быть обработаны дважды
- Нет исключений при проблемах

### Гибридный подход

```python
# Основной брокер: надежность
main_broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,
    blocking_acknowledge=True,
)

# Брокер для аналитики: скорость
analytics_broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=False,
    blocking_acknowledge=False,
)

# Критичные задачи
@dramatiq.actor(broker=main_broker)
def charge_payment(amount):
    ...

# Некритичные задачи
@dramatiq.actor(broker=analytics_broker)
def track_event(event_type, data):
    ...
```

## Как работает ACK под капотом

Посмотрим на код из [consumer.py](../dramatiq_kombu_broker/consumer.py):

```python
def ack(self, message, *, block=None, timeout=None):
    if block is None:
        block = self.blocking_acknowledge

    if self._is_threadsafe() and block:
        # Блокирующий ACK: отправляем сразу
        self._ack_or_log_error(message)
        return

    if not block:
        # Неблокирующий: добавляем в очередь
        self._ack_queue.append((message, None))
    else:
        # Блокирующий но в другом потоке: ждем через Event
        done = threading.Event()
        self._ack_queue.append((message, done))
        done.wait(timeout)
```

Когда `blocking_acknowledge=False`, ACK добавляется в очередь `_ack_queue` и отправляется позже в методе `__next__()` перед получением следующего сообщения:

```python
def __next__(self):
    # Сначала обрабатываем накопившиеся ACK/NACK
    self._process_queued_ack_events()
    self._process_queued_nack_events()

    # Потом получаем новое сообщение
    message = self._reader.pop(timeout=...)
    return message
```

Это позволяет worker не ждать подтверждения от RabbitMQ и сразу перейти к следующей задаче.

## Проблемы и решения

### Проблема: "connection already closed" при ACK

Эта ошибка возникает когда соединение разорвалось между получением сообщения и отправкой ACK.

**С blocking_acknowledge=True:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=True,
)

# Worker бросит исключение при попытке ACK
# Сообщение останется в очереди
# После переподключения задача будет обработана снова
```

**С blocking_acknowledge=False:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    blocking_acknowledge=False,
)

# ACK будет помещен в очередь
# Ошибка будет залогирована позже
# Worker уже начал обрабатывать следующее сообщение
```

**Решение:** Используйте `blocking_acknowledge=True` для критичных задач и убедитесь что ваши задачи идемпотентны (можно выполнить повторно).

### Проблема: Низкая производительность при большом количестве мелких задач

Если у вас тысячи мелких задач в секунду, `blocking_acknowledge=True` может стать узким горлышком.

**Решение 1:** Используйте `blocking_acknowledge=False` если задачи идемпотентны

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={...},
    confirm_delivery=True,         # Оставляем для надежности отправки
    blocking_acknowledge=False,    # Отключаем для скорости
)
```

**Решение 2:** Увеличьте количество workers вместо отключения блокирующего ACK

```bash
# Запустите больше процессов
dramatiq tasks --processes 8 --threads 4
```

### Проблема: Задачи выполняются дважды

Это нормальное поведение для систем с гарантией "at-least-once delivery". Сообщение может быть обработано дважды если:

1. Worker выполнил задачу
2. Отправил ACK
3. Сеть упала до подтверждения
4. RabbitMQ не получил ACK и вернул сообщение в очередь
5. Другой worker взял сообщение и выполнил снова

**Решение:** Делайте задачи идемпотентными

```python
@dramatiq.actor
def process_payment(payment_id):
    # Проверяем что платеж еще не обработан
    payment = Payment.objects.get(id=payment_id)
    if payment.status == "processed":
        return  # Уже обработан, ничего не делаем

    # Обрабатываем
    charge_card(payment)
    payment.status = "processed"
    payment.save()
```

## Мониторинг и метрики

Важно отслеживать проблемы с доставкой сообщений:

```python
from prometheus_client import Counter

delivery_failures = Counter(
    'dramatiq_delivery_failures_total',
    'Number of failed message deliveries',
)

@dramatiq.actor
def important_task(data):
    try:
        result = process(data)
    except Exception as e:
        delivery_failures.inc()
        raise
    return result
```

В RabbitMQ Management UI отслеживайте:

- **Ready messages** — сообщения в очереди
- **Unacked messages** — сообщения взятые worker'ами но еще не подтвержденные
- **Publish rate** — скорость отправки
- **Consumer count** — количество активных consumers

## Ссылки и дополнительная информация

- [RabbitMQ Publisher Confirms](https://www.rabbitmq.com/docs/confirms) — официальная документация о publisher confirms
- [RabbitMQ Consumer Acknowledgements](https://www.rabbitmq.com/docs/confirms#consumer-acknowledgements) — как работают consumer acknowledgements
- [RabbitMQ Reliability Guide](https://www.rabbitmq.com/docs/reliability) — общее руководство по надежности
- [RabbitMQ Mandatory Flag](https://www.compilenrun.com/docs/middleware/rabbitmq/rabbitmq-reliability/rabbitmq-mandatory-messages/) — подробно о mandatory флаге
- [Kombu Documentation](https://docs.celeryq.dev/projects/kombu/en/latest/) — документация Kombu
- [Dramatiq Documentation](https://dramatiq.io/) — документация Dramatiq

## Быстрая справка

| Параметр | По умолчанию | Этап | Гарантия |
|----------|--------------|------|----------|
| `confirm_delivery` | `True` | Отправка | Сообщение попало в очередь |
| `blocking_acknowledge` | `True` | Обработка | ACK был подтвержден RabbitMQ |
| `mandatory` | `True` | Отправка | Сообщение не будет отброшено |

**Рекомендация для продакшна:**

```python
broker = ConnectionPooledKombuBroker(
    kombu_connection_options={
        "hostname": os.environ["RABBITMQ_URL"],
        "heartbeat": 60,
        "transport_options": {
            "confirm_publish": True,
            "max_retries": 3,
        },
    },
    confirm_delivery=True,
    blocking_acknowledge=True,
    max_enqueue_attempts=3,
)
```

Эта конфигурация дает максимальную надежность с приемлемой производительностью для большинства приложений.
