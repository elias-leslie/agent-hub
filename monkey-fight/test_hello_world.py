"""
Test file for the hello_world function.
"""

import unittest
from hello_world import hello_world


class TestHelloWorld(unittest.TestCase):
    """Test cases for the hello_world function."""

    def test_hello_world_returns_string(self):
        """Test that hello_world returns a string."""
        result = hello_world()
        self.assertIsInstance(result, str)

    def test_hello_world_returns_correct_message(self):
        """Test that hello_world returns the correct message."""
        result = hello_world()
        self.assertEqual(result, "Hello, World!")


if __name__ == "__main__":
    unittest.main()
