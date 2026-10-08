from typing import Literal

from pydantic import BaseModel, Field, field_validator


class TaskCreate(BaseModel):
    input: str
    output: str | None = None
    quality: int = Field(default=5, ge=1, le=10)
    container: Literal["mkv", "mp4"] = "mkv"
    software: bool = False
    resolution: list[int] | None = Field(default=None, min_length=2, max_length=2)
    remap_path: str = None

    @field_validator("resolution")
    @classmethod
    def _resolution_sizes_positive(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and not all(n > 0 for n in value):
            raise ValueError("resolution sizes must be positive")
        return value
