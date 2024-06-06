"""Test dramatiq-kombu-broker."""

import dramatiq_kombu_broker


def test_import() -> None:
    """Test that the package can be imported."""
    assert isinstance(dramatiq_kombu_broker.__name__, str)
