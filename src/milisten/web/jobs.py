"""Build-job registry: one render at a time, progress polled over HTTP.

Rendering is CPU-bound, so running two areas at once only thrashes; the registry
refuses a second job while one is live. Cancellation is cooperative and lands
between chapters, because a single chapter's synthesis is one blocking call.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..build import render_area
from ..models import Source

MAX_EVENTS = 400


@dataclass
class Job:
    id: str
    area: str
    status: str = "running"
    message: str = ""
    chapters_done: int = 0
    chapters_total: int = 0
    seconds: float = 0.0
    started: float = field(default_factory=time.time)
    finished: float | None = None
    path: str | None = None
    events: list[dict] = field(default_factory=list)
    cancel: threading.Event = field(default_factory=threading.Event)

    def snapshot(self) -> dict:
        elapsed = (self.finished or time.time()) - self.started
        return {
            "id": self.id,
            "area": self.area,
            "status": self.status,
            "message": self.message,
            "chaptersDone": self.chapters_done,
            "chaptersTotal": self.chapters_total,
            "seconds": round(self.seconds, 1),
            "elapsed": round(elapsed, 1),
            "path": self.path,
            "events": list(self.events),
        }


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._live: str | None = None

    def live(self) -> Job | None:
        with self._lock:
            return self._jobs.get(self._live) if self._live else None

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self, limit: int = 8) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)[:limit]

    def start(self, area: str, sources: Sequence[Source], destination: Path, **options) -> Job:
        with self._lock:
            live = self._jobs.get(self._live) if self._live else None
            if live and live.status == "running":
                raise RuntimeError(f"a build of {live.area!r} is already running")
            job = Job(id=uuid.uuid4().hex[:12], area=area, chapters_total=len(sources))
            self._jobs[job.id] = job
            self._live = job.id

        thread = threading.Thread(
            target=self._run,
            args=(job, area, sources, destination, options),
            name=f"milisten-build-{area}",
            daemon=True,
        )
        thread.start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status != "running":
            return False
        job.cancel.set()
        job.message = "cancelling after the current chapter"
        return True

    def _run(self, job: Job, area, sources, destination, options) -> None:
        def note(kind: str, text: str) -> None:
            job.events.append({"t": round(time.time() - job.started, 1), "kind": kind, "text": text})
            del job.events[:-MAX_EVENTS]

        try:
            for event in render_area(area, sources, destination, **options):
                if job.cancel.is_set():
                    job.status = "cancelled"
                    note("cancelled", "stopped between chapters")
                    break
                if event.kind == "chapter-start":
                    job.message = f"[{event.index}/{event.total}] {event.title}"
                elif event.kind == "chapter-done":
                    job.chapters_done += 1
                    job.seconds += event.seconds
                    note("done", f"{event.title} — {event.seconds / 60:.1f} min")
                elif event.kind == "skipped":
                    note("skipped", f"{event.title} — {event.detail}")
                elif event.kind in {"loading", "packaging"}:
                    job.message = event.detail
                elif event.kind == "failed":
                    job.status = "failed"
                    job.message = event.detail
                    note("failed", event.detail)
                elif event.kind == "done":
                    job.status = "done"
                    job.seconds = event.seconds
                    job.path = str(event.path)
                    job.message = f"{event.index} chapters, {event.seconds / 60:.0f} min"
                    note("packaged", job.message)
        except Exception as exc:  # noqa: BLE001 - a build thread must never die silently
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
            note("failed", job.message)
        finally:
            if job.status == "running":
                job.status = "done" if job.chapters_done else "failed"
            job.finished = time.time()


REGISTRY = Registry()
