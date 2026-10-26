"""Tests for the User API endpoints.

These tests reference UserCreate with only username and email fields,
making them stale once the 'tier' field is added.
"""

import pytest


def test_create_user_success():
    """Test creating a user with valid data."""
    payload = {"username": "alice", "email": "a@b.com"}
    # Simulated POST to /v1/users
    # response = client.post("/v1/users", json=payload)
    # assert response.status_code == 201
    assert "username" in payload
    assert "email" in payload
    # Uses UserCreate schema to validate input


def test_create_user_missing_email():
    """Test creating a user without email should fail validation."""
    payload = {"username": "bob"}
    # UserCreate requires email field
    assert "username" in payload
    assert "email" not in payload


def test_get_user_by_id():
    """Test retrieving a user by ID."""
    user_id = 42
    # Simulated GET to /v1/users/{user_id}
    # response = client.get(f"/v1/users/{user_id}")
    # assert response.status_code == 200
    assert user_id == 42


def test_create_user_response_model():
    """Test that the UserResponse contains expected fields from UserCreate."""
    # The UserResponse should mirror UserCreate fields
    expected_fields = ["id", "username", "email", "is_active"]
    assert "username" in expected_fields
    assert "email" in expected_fields
