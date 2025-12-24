"""Test dramatiq-kombu-broker."""

import dramatiq_kombu_broker


def test_import() -> None:
    """Test that the package can be imported."""
    assert isinstance(dramatiq_kombu_broker.__name__, str)


def test_delay_too_long_error_import() -> None:
    """Test that DelayTooLongError can be imported from public API."""
    from dramatiq_kombu_broker import DelayTooLongError

    assert DelayTooLongError is not None


def test_delay_too_long_error_initialization() -> None:
    """Test DelayTooLongError attributes."""
    from dramatiq_kombu_broker import DelayTooLongError

    exc = DelayTooLongError("Test message", delay=5000, max_delay=3000, queue_name="test_queue")

    assert str(exc) == "Test message"
    assert exc.delay == 5000
    assert exc.max_delay == 3000
    assert exc.queue_name == "test_queue"


def test_delay_too_long_error_optional_attributes() -> None:
    """Test DelayTooLongError with optional attributes."""
    from dramatiq_kombu_broker import DelayTooLongError

    exc = DelayTooLongError("Test message")

    assert exc.delay is None
    assert exc.max_delay is None
    assert exc.queue_name is None
