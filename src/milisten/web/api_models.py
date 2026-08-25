from __future__ import annotations

from pydantic import BaseModel, Field


class SourceModel(BaseModel):
    ref: str
    title: str
    kind: str
    area: str
    slug: str
    isLocal: bool


class AreaModel(BaseModel):
    name: str
    sources: list[SourceModel]
    recording: RecordingModel | None = None


class ChapterModel(BaseModel):
    title: str
    start: float
    end: float


class RecordingModel(BaseModel):
    area: str
    seconds: float
    bytes: int
    modified: float
    engine: str = ""
    voice: str = ""
    chapters: list[ChapterModel] = Field(default_factory=list)


class LibraryModel(BaseModel):
    areas: list[AreaModel]
    orphans: list[RecordingModel] = Field(default_factory=list)
    voices: list[str]
    audioDir: str


class AddSourceRequest(BaseModel):
    ref: str
    title: str | None = None
    area: str = "unfiled"


class RefRequest(BaseModel):
    ref: str


class PreviewRequest(BaseModel):
    ref: str
    layout: bool = False


class PreviewModel(BaseModel):
    title: str
    chars: int
    chunks: int
    minutes: float
    text: str


class BuildRequest(BaseModel):
    area: str
    engine: str = "kokoro"
    voice: str = "heart"
    speed: float = 1.0
    layout: bool = False
    keepWav: bool = False


class OkResponse(BaseModel):
    ok: bool = True


AreaModel.model_rebuild()
