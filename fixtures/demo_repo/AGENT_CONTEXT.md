# Agent Context: User Service API

## Overview
This microservice manages user registration and retrieval.

## API Contracts

### POST /v1/users
Creates a new user. Expects a `UserCreate` payload:
- `username` (str, required): Unique username, 3-50 characters
- `email` (str, required): Valid email address

Returns a `UserResponse` with the created user data.

### GET /v1/users/{user_id}
Retrieves user details by ID. Returns a `UserResponse`.

## Schema Definitions

### UserCreate
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | str | Yes | Unique username |
| email | str | Yes | User email address |

### UserResponse
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | int | Yes | User ID |
| username | str | Yes | Username |
| email | str | Yes | Email address |
| is_active | bool | No | Active status (default: true) |

## Instructions for AI Agents
When modifying the User API:
1. Always validate that `UserCreate` payloads contain `username` and `email`.
2. Keep `UserResponse` in sync with `UserCreate` fields.
3. Run test_users.py after any schema changes.
