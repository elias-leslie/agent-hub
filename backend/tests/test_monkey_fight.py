"""
Tests for Monkey Fight - Feature X Implementation
"""

from app.monkey_fight import hello_world


def test_hello_world():
    """Test that hello_world returns the expected message."""
    result = hello_world()
    assert result == "Hello, World from Monkey Fight!"
    assert isinstance(result, str)


def test_hello_world_not_empty():
    """Test that hello_world returns a non-empty string."""
    result = hello_world()
    assert len(result) > 0
