from pydantic import BaseModel,Field
from llm_client import DEFAULT_MODEL
from decimal import Decimal

class RegisterIn(BaseModel):
    username: str = Field(min_length=3,max_length=20)
    password: str = Field(min_length=8,max_length=72)

class UserOut(BaseModel):
    id: int
    username: str

class LoginIn(BaseModel):
    username: str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TodoIn(BaseModel):
    title: str = Field(min_length=1,max_length=200)

class TodoUpdate(BaseModel):
    title :str | None = Field(default=None,min_length=1,max_length=200)
    done: bool | None = None

class TodoOut(BaseModel):
    id :int
    title :str
    done :bool
    model_config = {"from_attributes": True}

class ChatIn(BaseModel):
    prompt: str = Field(min_length=1,max_length=2000)
    model: str = DEFAULT_MODEL
    temperature: float = Field(default=0.0, ge = 0, le=2)

class ChatOut(BaseModel):
    reply: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: Decimal

class UsageOut(BaseModel):
    today_success: int
    today_failed: int
    month_success: int
    month_failed: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost: Decimal
