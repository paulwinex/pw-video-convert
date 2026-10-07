from typing import Literal

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    input: str
    output: str | None = None
    quality: int = Field(default=5, ge=1, le=10)
    container: Literal["mkv", "mp4"] = "mkv"
    software: bool = False
    remap_path: str = None
