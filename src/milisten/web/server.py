"""FastAPI app over the milisten core.

Concurrency contract, same as prview: any route that touches the network or the
filesystem in a blocking way is a sync `def`, so FastAPI runs it in a threadpool
and never stalls the event loop. The build routes only poke the in-memory job
registry (the render itself already runs on its own daemon thread), so they stay
cheap regardless.

Errors map to structured {error, hint?} JSON. No stack traces reach the browser.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import library, manifest, package, tts
from ..chunk import chunk
from ..extract import ExtractionError, extract
from ..models import Source
from ..normalize import normalize
from . import ranges
from .api_models import (
    AddSourceRequest,
    AreaModel,
    BuildRequest,
    LibraryModel,
    OkResponse,
    PreviewModel,
    PreviewRequest,
    RecordingModel,
    RefRequest,
    SourceModel,
)
from .jobs import REGISTRY
from .security import SecurityMiddleware

STATIC = Path(__file__).parent / "static"
CHARS_PER_SECOND = 27.0

app = FastAPI(title="milisten")
app.add_middleware(SecurityMiddleware)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def set_session_token(token: str) -> None:
    app.state.session_token = token


def audio_dir() -> Path:
    return library.audio_path()


def _fail(status: int, error: str, hint: str = "") -> HTTPException:
    return HTTPException(status_code=status, detail={"error": error, **({"hint": hint} if hint else {})})


@app.exception_handler(HTTPException)
async def structured_errors(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    return JSONResponse(detail, status_code=exc.status_code)


def _source_model(source: Source) -> SourceModel:
    return SourceModel(
        ref=source.ref,
        title=source.title,
        kind=str(source.kind),
        area=source.area,
        slug=source.slug,
        isLocal=source.is_local,
    )


def _recording(area: str, path: Path) -> RecordingModel:
    stat = path.stat()
    meta = manifest.read(path)
    if meta is None:
        # Recorded before manifests existed: recover the spans from the file itself
        # and cache them, so the player has chapters without a second ffprobe.
        probed = package.probe_chapters(path)
        meta = manifest.to_dict(area, probed, "", "") if probed else {}
        if probed:
            manifest.write(path, meta)
    return RecordingModel(
        area=area,
        seconds=meta.get("seconds", 0.0),
        bytes=stat.st_size,
        modified=stat.st_mtime,
        engine=meta.get("engine", ""),
        voice=meta.get("voice", ""),
        chapters=meta.get("chapters", []),
    )


def _recordings() -> dict[str, RecordingModel]:
    root = audio_dir()
    if not root.is_dir():
        return {}
    return {p.stem: _recording(p.stem, p) for p in sorted(root.glob("*.m4b"))}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/library", response_model=LibraryModel)
def get_library() -> LibraryModel:
    sources = library.load()
    grouped = library.by_area(sources)
    found = _recordings()
    areas = [
        AreaModel(
            name=name,
            sources=[_source_model(s) for s in items],
            recording=found.get(name),
        )
        for name, items in grouped.items()
    ]
    orphans = [rec for name, rec in found.items() if name not in grouped]
    return LibraryModel(
        areas=areas,
        orphans=orphans,
        voices=list(tts.VOICES),
        audioDir=str(audio_dir()),
    )


@app.post("/api/sources", response_model=LibraryModel)
def add_source(body: AddSourceRequest) -> LibraryModel:
    ref = body.ref.strip()
    if not ref:
        raise _fail(422, "A URL or file path is required")
    resolved = ref if ref.startswith(("http://", "https://")) else str(Path(ref).expanduser())
    if not resolved.startswith("http") and not Path(resolved).exists():
        raise _fail(422, f"{resolved} does not exist", "check the path, or paste a URL instead")
    stem = Path(resolved.split("?")[0]).stem.replace("-", " ").replace("_", " ").strip()
    title = (body.title or "").strip() or stem or resolved
    library.save(library.add(library.load(), resolved, title, body.area.strip() or "unfiled"))
    return get_library()


@app.post("/api/sources/remove", response_model=LibraryModel)
def remove_source(body: RefRequest) -> LibraryModel:
    library.save(library.remove(library.load(), body.ref))
    return get_library()


@app.post("/api/preview", response_model=PreviewModel)
def preview(body: PreviewRequest) -> PreviewModel:
    match = next((s for s in library.load() if body.ref in (s.ref, s.slug)), None)
    if not match:
        raise _fail(404, "That source is not in the queue")
    try:
        text = normalize(extract(match, body.layout).body)
    except ExtractionError as exc:
        raise _fail(422, str(exc), "save the page or PDF locally, then add the file") from exc
    except OSError as exc:
        raise _fail(502, f"could not read {match.ref}: {exc}") from exc
    pieces = chunk(text)
    return PreviewModel(
        title=match.title,
        chars=len(text),
        chunks=len(pieces),
        minutes=round(len(text) / CHARS_PER_SECOND / 60, 1),
        text=text,
    )


@app.post("/api/build")
def start_build(body: BuildRequest) -> dict:
    grouped = library.by_area(library.load())
    if body.area not in grouped:
        raise _fail(404, f"unknown area {body.area!r}", f"have: {', '.join(grouped)}")
    if body.engine not in {"kokoro", "say"}:
        raise _fail(422, f"unknown engine {body.engine!r}")
    try:
        job = REGISTRY.start(
            body.area,
            grouped[body.area],
            audio_dir(),
            engine=body.engine,
            voice=body.voice,
            speed=body.speed,
            layout=body.layout,
            keep_wav=body.keepWav,
        )
    except RuntimeError as exc:
        raise _fail(409, str(exc), "wait for it to finish, or cancel it") from exc
    return job.snapshot()


@app.get("/api/build")
def build_status() -> dict:
    live = REGISTRY.live()
    return {
        "live": live.snapshot() if live and live.status == "running" else None,
        "recent": [j.snapshot() for j in REGISTRY.recent()],
    }


@app.get("/api/build/{job_id}")
def job_status(job_id: str) -> dict:
    job = REGISTRY.get(job_id)
    if not job:
        raise _fail(404, "no such build job")
    return job.snapshot()


@app.post("/api/build/{job_id}/cancel", response_model=OkResponse)
def cancel_build(job_id: str) -> OkResponse:
    if not REGISTRY.cancel(job_id):
        raise _fail(409, "that job is not running")
    return OkResponse()


@app.delete("/api/recordings/{area}", response_model=OkResponse)
def delete_recording(area: str) -> OkResponse:
    target = (audio_dir() / f"{area}.m4b").resolve()
    if target.parent != audio_dir().resolve() or not target.exists():
        raise _fail(404, f"no recording for {area!r}")
    target.unlink()
    manifest.path_for(target).unlink(missing_ok=True)
    return OkResponse()


@app.get("/audio/{area}.m4b")
def stream_audio(area: str, request: Request) -> Response:
    target = (audio_dir() / f"{area}.m4b").resolve()
    if target.parent != audio_dir().resolve() or not target.is_file():
        raise _fail(404, f"no recording for {area!r}")

    size = target.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
    window = ranges.parse(request.headers.get("range"), size)
    if window is None:
        return FileResponse(target, media_type="audio/mp4", headers=headers)

    start, end = window
    headers["Content-Range"] = ranges.content_range(start, end, size)
    headers["Content-Length"] = str(end - start + 1)

    def body():
        remaining = end - start + 1
        with target.open("rb") as handle:
            handle.seek(start)
            while remaining > 0:
                block = handle.read(min(ranges.CHUNK, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    return StreamingResponse(body(), status_code=206, media_type="audio/mp4", headers=headers)
