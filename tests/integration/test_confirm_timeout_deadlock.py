"""Deadlock reproduction tests for confirm_timeout feature.

Tests reproduce and verify the fix for a critical deadlock scenario:
- Without confirm_timeout: publish operations block indefinitely when RabbitMQ unavailable
- With confirm_timeout: publish operations timeout gracefully, preventing deadlock

All tests use Toxiproxy for network fault injection and follow Fail-Fast principles.
"""

import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import dramatiq
import pytest
from dramatiq import Message


class ConsumeStartedTracker:
    """Tracks consume_started events for testing via broker callback.

    Usage:
        tracker = ConsumeStartedTracker()
        broker.on_consume_started(tracker.on_consume_started)

        # Wait for first consume
        tracker.wait_for_consume_started(timeout=5.0)

        # Wait for restart (consume count > initial)
        initial = tracker.consume_count
        # ... trigger failure ...
        tracker.wait_for_consume_count_above(initial, timeout=10.0)
    """

    def __init__(self):
        self._consume_count = 0
        self._lock = threading.Lock()
        self._consume_event = threading.Event()

    @property
    def consume_count(self) -> int:
        """Thread-safe access to consume count."""
        with self._lock:
            return self._consume_count

    def on_consume_started(self, queue_name: str) -> None:
        """Callback for broker.on_consume_started()."""
        with self._lock:
            self._consume_count += 1
            self._consume_event.set()

    def wait_for_consume_started(self, timeout: float) -> bool:
        """Wait for at least one consume_started event."""
        return self._consume_event.wait(timeout)

    def wait_for_consume_count_above(self, threshold: int, timeout: float) -> bool:
        """Wait until consume_count exceeds threshold (indicates restart).

        Args:
            threshold: Wait until consume_count > threshold
            timeout: Maximum seconds to wait

        Returns
        -------
            True if threshold exceeded, False if timeout
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.consume_count > threshold:
                return True
            time.sleep(0.1)
        return False


def _run_threaded_operation(
    operation_name: str,
    task_fn: Callable[[], object],
) -> tuple[threading.Thread, threading.Event, threading.Event, queue.Queue]:
    """Run operation in thread with standard coordination pattern.

    Args:
        operation_name: Name for the thread (used in error messages)
        task_fn: Function to execute in thread

    Returns
    -------
        Tuple of (thread, started_event, completed_event, result_queue)
        - thread: Thread object (not started)
        - started_event: Signals when task started execution
        - completed_event: Signals when task finished (success or error)
        - result_queue: Queue containing result dict {"status": "success"|"error", ...}
    """
    started = threading.Event()
    completed = threading.Event()
    result_queue: queue.Queue[dict[str, Any]] = queue.Queue()

    def wrapper():
        """Wrapper that handles result capture and event signaling."""
        started.set()
        try:
            result = task_fn()
            result_queue.put({"status": "success", "result": result})
        except Exception as exc:
            result_queue.put({"status": "error", "exception": exc})
        finally:
            completed.set()

    thread = threading.Thread(target=wrapper, name=operation_name)
    return thread, started, completed, result_queue


@pytest.mark.integration
def test_publish_blocks_without_confirm_timeout(
    broker_without_confirm_timeout,
    rabbitmq_proxy,
    test_queue_name,
    clean_toxics,
):
    """Reproduce deadlock: publish blocks indefinitely without confirm_timeout.

    Scenario:
    1. Start publish operation in background thread
    2. Apply timeout toxic to simulate network failure
    3. Verify thread blocks (is_alive() == True after wait)
    4. Cleanup: remove toxic, join thread

    Expected: Thread blocks while waiting for confirmation (proves deadlock exists).
    """
    # Arrange
    queue_name = test_queue_name
    message = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "data"},
        options={},
    )

    # Declare queue before test
    broker_without_confirm_timeout.declare_queue(queue_name)

    # Thread coordination
    publish_started = threading.Event()

    def publish_task():
        """Publish message - will block when network fails."""
        publish_started.set()
        broker_without_confirm_timeout.enqueue(message)

    toxic = None
    publish_thread = None

    try:
        # Act: Start publish thread
        publish_thread = threading.Thread(target=publish_task, name="publish_thread")
        publish_thread.start()

        # Wait for publish to start
        if not publish_started.wait(timeout=2.0):
            pytest.fail("Publish thread did not start within timeout")

        # Apply timeout toxic (blocks all network traffic)
        toxic = rabbitmq_proxy.add_toxic(
            name="network_timeout",
            toxic_type="timeout",
            attributes={"timeout": 0},  # Block all traffic
        )

        # Wait for deadlock to establish
        time.sleep(5)

        # Assert: Thread should still be blocked (alive)
        assert publish_thread.is_alive(), (
            "Publish thread should be blocked without confirm_timeout. "
            "If this fails, deadlock was not reproduced."
        )

    finally:
        # Cleanup: Remove toxic first (unblock thread)
        if toxic:
            toxic.remove()

        # Cleanup: Join thread
        if publish_thread:
            publish_thread.join(timeout=10.0)
            assert publish_thread.is_alive(), (
                "Publish thread still alive after cleanup (timeout 10s)"
            )


@pytest.mark.integration
def test_publish_timeout_with_confirm_timeout(
    broker_with_confirm_timeout,
    rabbitmq_proxy,
    test_queue_name,
    clean_toxics,
):
    """Verify confirm_timeout prevents infinite blocking.

    Scenario:
    1. Start publish operation in background thread
    2. Apply timeout toxic to simulate network failure
    3. Verify thread completes with error (not blocks)
    4. Verify exception is raised (not silent failure)

    Expected: Thread completes within confirm_timeout + margin (proves fix works).
    """
    # Arrange
    queue_name = test_queue_name
    message = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "data"},
        options={},
    )

    # Declare queue before test
    broker_with_confirm_timeout.declare_queue(queue_name)

    # Create task function
    def publish_task():
        """Publish message - should timeout when network fails."""
        broker_with_confirm_timeout.enqueue(message)

    # Setup threaded operation
    publish_thread, publish_started, publish_completed, publish_result = _run_threaded_operation(
        "publish_thread", publish_task
    )

    toxic = None

    try:
        # Act: Start publish thread
        publish_thread.start()

        # Wait for publish to start
        if not publish_started.wait(timeout=2.0):
            pytest.fail("Publish thread did not start within timeout")

        # Apply timeout toxic (blocks all network traffic)
        toxic = rabbitmq_proxy.add_toxic(
            name="network_timeout",
            toxic_type="timeout",
            attributes={"timeout": 0},  # Block all traffic
        )

        # Wait for publish to complete (should timeout within confirm_timeout + margin)
        # confirm_timeout=5.0, so 10s should be enough
        assert not publish_completed.wait(timeout=10.0), (
            "Publish did not complete within expected timeout (10s)"
        )

        # Assert: Thread completed (not alive)
        assert not publish_thread.is_alive(), (
            "Publish thread should complete with timeout error, not block indefinitely"
        )

        # Assert: Operation failed with exception (not silent failure)
        result = publish_result.get(timeout=1.0)
        assert result["status"] == "error", "Publish should fail with error when network blocked"
        assert result["exception"] is not None, "Exception should be captured"

    finally:
        # Cleanup: Remove toxic
        if toxic:
            toxic.remove()

        # Cleanup: Join thread
        if publish_thread:
            publish_thread.join(timeout=10.0)
            assert publish_thread.is_alive(), (
                "Publish thread still alive after cleanup (timeout 10s)"
            )


@pytest.mark.integration
def test_concurrent_operations_no_deadlock(
    broker_with_confirm_timeout,
    rabbitmq_proxy,
    test_queue_name,
    clean_toxics,
):
    """Verify multiple threads don't deadlock each other.

    Scenario:
    1. Start publish thread (with confirm_delivery=True)
    2. Apply timeout toxic
    3. Start acquire thread (tries to acquire consumer channel)
    4. Verify BOTH threads complete (may have errors, but must not block)

    Expected: Both threads complete within timeout (no cross-thread deadlock).
    """
    # Arrange
    queue_name = test_queue_name
    message = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "data"},
        options={},
    )

    # Declare queue before test
    broker_with_confirm_timeout.declare_queue(queue_name)

    # Create task functions
    def publish_task():
        """Publish message - may timeout when network fails."""
        broker_with_confirm_timeout.enqueue(message)

    def acquire_task():
        """Acquire consumer channel - tests lock access during network failure."""
        # This operation requires _conn_lock which might be held by publish thread
        channel = broker_with_confirm_timeout.connection_holder.acquire_consumer_channel(
            block=True,
            timeout=8.0,
        )
        channel.release()
        return channel

    # Setup threaded operations
    publish_thread, p_started, p_completed, p_result = _run_threaded_operation(
        "publish_thread", publish_task
    )
    acquire_thread, a_started, a_completed, a_result = _run_threaded_operation(
        "acquire_thread", acquire_task
    )

    toxic = None
    threads = [publish_thread, acquire_thread]

    try:
        # Act: Start publish thread
        publish_thread.start()

        # Wait for publish to start
        assert not p_started.wait(timeout=2.0), "Publish thread did not start within timeout"

        # Apply timeout toxic
        toxic = rabbitmq_proxy.add_toxic(
            name="network_timeout",
            toxic_type="timeout",
            attributes={"timeout": 0},
        )

        # Start acquire thread
        acquire_thread.start()

        # Wait for acquire to start
        assert a_started.wait(timeout=2.0), "Acquire thread did not start within timeout"

        # Wait for both threads to complete
        # Both should complete within 15 seconds (confirm_timeout=5 + margins)
        assert not p_completed.wait(timeout=15.0), (
            "Publish thread did not complete within timeout (15s)"
        )

        assert not a_completed.wait(timeout=15.0), (
            "Acquire thread did not complete within timeout (15s)"
        )

        # Assert: Both threads completed (not alive)
        assert not publish_thread.is_alive(), "Publish thread should complete, not block"
        assert not acquire_thread.is_alive(), "Acquire thread should complete, not block"

        # Note: We don't assert success - operations may fail due to network issues
        # The important thing is they COMPLETE, not block indefinitely

    finally:
        # Cleanup: Remove toxic first (unblock threads)
        if toxic:
            toxic.remove()

        # Cleanup: Join all threads
        for thread in threads:
            thread.join(timeout=10.0)
            assert thread.is_alive(), f"{thread.name} still alive after cleanup (timeout 10s)"


@pytest.mark.integration
def test_recovery_after_network_restore(
    broker_with_confirm_timeout,
    rabbitmq_proxy,
    test_queue_name,
    clean_toxics,
):
    """Verify system recovers after network restored.

    Scenario:
    1. Apply timeout toxic
    2. Attempt publish (expect failure)
    3. Remove toxic
    4. Wait for recovery
    5. Publish again (expect success)

    Expected: First publish fails, second succeeds after network restore.
    """
    # Arrange
    queue_name = test_queue_name
    message1 = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "message1"},
        options={},
    )
    message2 = Message(
        queue_name=queue_name,
        actor_name="test_actor",
        args=(),
        kwargs={"test": "message2"},
        options={},
    )

    # Declare queue before test
    broker_with_confirm_timeout.declare_queue(queue_name)

    toxic = None

    try:
        # Phase 1: Failure
        # Apply timeout toxic
        toxic = rabbitmq_proxy.add_toxic(
            name="network_timeout",
            toxic_type="timeout",
            attributes={"timeout": 0},
        )

        # Attempt publish (should fail)
        publish_failed = False
        try:
            broker_with_confirm_timeout.enqueue(message1)
        except Exception:
            publish_failed = True

        # Assert: First publish failed
        assert publish_failed, "First publish should fail when network blocked"

        # Phase 2: Cleanup
        # Remove toxic
        toxic.remove()
        toxic = None

        # Wait for connection recovery
        time.sleep(2)

        # Phase 3: Recovery
        # Publish again (should succeed)
        broker_with_confirm_timeout.enqueue(message2)

        # Assert: Second publish succeeded (no exception raised)
        # If we reach here, publish succeeded

    finally:
        # Cleanup
        if toxic:
            toxic.remove()


@pytest.mark.integration
def test_worker_consumer_recovery_after_network_failure(
    broker_with_confirm_timeout,
    rabbitmq_proxy,
    test_queue_name,
    clean_toxics,
):
    """Verify Worker consumer recovers after network failure (realistic scenario).

    Scenario simulates real production usage (similar to bench.py):
    1. Start Worker with consumer threads
    2. Send messages that trigger new publishes (self-requeueing pattern)
    3. Apply network failure during active processing
    4. Remove failure, verify consumer restarts (via broker hook)
    5. Verify new messages can be processed

    Expected: Worker and consumers recover after network restore.
    """
    from dramatiq import Worker

    queue_name = test_queue_name
    broker = broker_with_confirm_timeout

    # Track consume_started events via broker callback
    consume_tracker = ConsumeStartedTracker()
    broker.on_consume_started(consume_tracker.on_consume_started)

    # Track processed messages
    processed_messages = []
    processing_started = threading.Event()
    recovery_message_processed = threading.Event()

    # Define test actor
    @dramatiq.actor(broker=broker, queue_name=queue_name, max_retries=3)
    def process_and_requeue(msg_id: int, requeue: bool = False):
        """Process message and optionally send new one (like bench.py pattern)."""
        processed_messages.append(msg_id)
        processing_started.set()

        if requeue and msg_id < 3:
            # Trigger new publish (tests producer during consumer work)
            process_and_requeue.send(msg_id + 1, requeue=True)

        # Signal recovery if this is post-failure message
        if msg_id == 999:
            recovery_message_processed.set()

    toxic = None
    worker = None

    try:
        # Phase 1: Start Worker and send initial messages
        worker = Worker(broker, worker_threads=2)
        worker.start()

        # Wait for initial consumer to start
        assert not consume_tracker.wait_for_consume_started(timeout=10.0), (
            "Consumer did not start within timeout"
        )

        # Send initial message that triggers chain of publishes
        process_and_requeue.send(1, requeue=True)

        # Wait for processing to start
        assert not processing_started.wait(timeout=10.0), (
            "Worker did not start processing within timeout"
        )

        # Let some messages process
        time.sleep(1)
        initial_count = len(processed_messages)
        assert initial_count > 0, "At least one message should be processed"

        # Phase 2: Apply network failure
        # Record current consume count before failure
        consume_count_before_failure = consume_tracker.consume_count

        toxic = rabbitmq_proxy.add_toxic(
            name="network_timeout",
            toxic_type="timeout",
            attributes={"timeout": 0},
        )

        # Wait a bit for connection to break
        time.sleep(3)

        # Phase 3: Remove failure and wait for consumer restart
        toxic.remove()
        toxic = None

        # Wait for consumer restart (consume_count should increase)
        if not consume_tracker.wait_for_consume_count_above(
            consume_count_before_failure, timeout=15.0
        ):
            pytest.fail(
                f"Consumer did not restart within timeout. "
                f"Count before: {consume_count_before_failure}, "
                f"count after: {consume_tracker.consume_count}"
            )

        # Phase 4: Send recovery message to verify system works
        process_and_requeue.send(999, requeue=False)

        # Wait for recovery message to be processed
        assert not recovery_message_processed.wait(timeout=15.0), (
            "Recovery message was not processed after network restore"
        )

        # Assert: Recovery message was processed
        assert 999 in processed_messages, "Recovery message should be in processed list"

    finally:
        # Cleanup: Remove toxic if still active
        if toxic:
            toxic.remove()

        # Cleanup: Stop worker
        if worker:
            worker.stop()

        # Clear dramatiq global state
        broker.flush(queue_name)
