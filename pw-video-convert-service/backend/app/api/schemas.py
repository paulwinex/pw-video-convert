from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class TaskCreate(BaseModel):
    input: str
    output: str | None = None
    quality: int = Field(default=5, ge=1, le=10)
    container: Literal["mkv", "mp4"] = "mkv"
    software: bool = False
    resolution: list[int] | None = Field(default=None, min_length=2, max_length=2)
    audio: list[int] | None = None
    remap_path: str = None

    @field_validator("resolution")
    @classmethod
    def _resolution_sizes_positive(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and not all(n > 0 for n in value):
            raise ValueError("resolution sizes must be positive")
        return value

    @field_validator("audio")
    @classmethod
    def _audio_tracks_positive(cls, value: list[int] | None) -> list[int] | None:
        if value is not None:
            if not value:
                raise ValueError("audio must list at least one track")
            if not all(n >= 1 for n in value):
                raise ValueError("audio track numbers start at 1")
            value = sorted(set(value))
        return value


class TaskReorder(BaseModel):
    uuids: list[str] = Field(min_length=1, description="Pending task uuids in the desired execution order")


class AudioTrack(BaseModel):
    track: int
    index: Optional[int] = None
    codec: str
    channels: int
    language: Optional[str] = None
    title: Optional[str] = None
    stream_bitrate: Optional[int] = None


class ProbeResponse(BaseModel):
    path: str
    audio: list[AudioTrack]


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: Optional[int] = None
    created: Optional[datetime] = None
    modified: Optional[datetime] = None


class ListResponse(BaseModel):
    path: str
    entries: list[FileEntry]
