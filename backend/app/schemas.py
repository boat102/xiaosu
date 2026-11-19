from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    user_id: str = "demo-user"
    conversation_id: str = "default"
    channel: str = "web"


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    citations: list[dict] = []
    tools_used: list[str] = []
    usage: dict = {}


class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    chunk_count: int
    content_type: str


class HealthOut(BaseModel):
    status: str
    model: str
