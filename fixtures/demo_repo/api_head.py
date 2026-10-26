"""Head API contract: UserCreate now adds tier (required) and organization_id (optional)."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="User Service", version="1.1.0")


class UserCreate(BaseModel):
    """Payload to create a new user."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: str = Field(..., description="User email address")
    tier: str = Field(..., description="Subscription tier (free, pro, enterprise)")
    organization_id: int = Field(default=1, description="Organization identifier")


class UserResponse(BaseModel):
    """Response model for user endpoints."""
    id: int
    username: str
    email: str
    tier: str
    organization_id: int
    is_active: bool = True


@app.post("/v1/users", response_model=UserResponse, status_code=201)
async def create_user(payload: UserCreate) -> UserResponse:
    """Create a new user in the system."""
    pass


@app.get("/v1/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int) -> UserResponse:
    """Retrieve user details by ID."""
    pass
