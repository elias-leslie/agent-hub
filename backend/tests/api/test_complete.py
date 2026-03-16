"""Tests for /complete endpoint JSON schema validation."""

from app.api.complete import validate_json_response


class TestJsonSchemaValidation:
    """Tests for JSON schema validation functionality."""

    def test_validate_json_response_valid(self):
        """Test validation passes for valid JSON matching schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        content = '{"name": "John", "age": 30}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is True
        assert error is None

    def test_validate_json_response_invalid_json(self):
        """Test validation fails for invalid JSON."""
        schema = {"type": "object"}
        content = "not valid json {"
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_validate_json_response_schema_mismatch(self):
        """Test validation fails when JSON doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        # Missing required field 'age'
        content = '{"name": "John"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error

    def test_validate_json_response_wrong_type(self):
        """Test validation fails when type doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        # 'count' is a string instead of integer
        content = '{"count": "five"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error
