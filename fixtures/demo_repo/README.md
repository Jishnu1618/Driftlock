# User Service API Documentation

## Overview
The User Service provides REST API endpoints for user management.

## Endpoints

### Create User
**POST** `/v1/users`

Create a new user account.

**Request Body (`UserCreate`):**
```json
{
  "username": "alice",
  "email": "alice@example.com"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | str | Yes | Unique username (3-50 chars) |
| email | str | Yes | Valid email address |

**Response (`UserResponse`):**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "is_active": true
}
```

**Status Code:** `201 Created`

### Get User
**GET** `/v1/users/{user_id}`

Retrieve user details by ID.

**Response (`UserResponse`):**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@example.com",
  "is_active": true
}
```

**Status Code:** `200 OK`
