import math
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .media import MAX_DURATION

ModelName = Literal["large-v3", "medium", "small", "base", "tiny"]
MODELS = ["large-v3", "medium", "small", "base", "tiny"]
ACTIVE = ("queued", "downloading", "loading_model", "transcribing")
Language = Annotated[str, Field(pattern=r"^(auto|[a-z]{2,3})$")]


class Settings(BaseModel):
    model: ModelName = "large-v3"
    language: Language = "auto"
    initial_prompt: str | None = Field(None, max_length=4000)


class URLJob(Settings):
    url: str = Field(min_length=1, max_length=4096)


class SegmentEdit(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    start: float = Field(ge=0, le=MAX_DURATION)
    end: float = Field(ge=0, le=MAX_DURATION)
    text: str = Field(max_length=20000)

    @model_validator(mode="after")
    def check_times(self):
        if not math.isfinite(self.start) or not math.isfinite(self.end) or self.end < self.start:
            raise ValueError("Invalid time range.")
        return self


class JobEdit(BaseModel):
    segments: list[SegmentEdit] = Field(max_length=20000)

    @field_validator("segments")
    @classmethod
    def check_ids_and_order(cls, segments):
        if len({segment.id for segment in segments}) != len(segments):
            raise ValueError("Segment IDs must be unique.")
        if any(previous.start > current.start for previous, current in zip(segments, segments[1:])):
            raise ValueError("Sort segments by start time.")
        return segments
