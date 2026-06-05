"""SSE progress streaming for report generation jobs.

Provides real-time progress updates via Server-Sent Events (SSE).
Clients connect to /report-builder/jobs/{id}/progress/stream and receive
events as the job progresses through stages.

Event format:
    event: progress
    data: {"stage": "binding", "pct": 25, "message": "Resolving entities..."}

    event: complete
    data: {"job_id": 1, "status": "done"}

    event: error
    data: {"message": "..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/report-builder", tags=["report-builder-sse"])


# ---------------------------------------------------------------------------
# In-memory progress bus (pub/sub for SSE clients)
# ---------------------------------------------------------------------------

@dataclass
class ProgressEvent:
    """A single progress event."""
    stage: str = ""
    pct: int = 0
    message: str = ""
    event_type: str = "progress"  # progress | complete | error
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        """Format as SSE text."""
        data = {
            "stage": self.stage,
            "pct": self.pct,
            "message": self.message,
            **(self.metadata or {}),
        }
        return f"event: {self.event_type}\ndata: {json.dumps(data)}\n\n"


class ProgressBus:
    """Pub/sub bus for job progress events.

    Publishers call `publish(job_id, event)`.
    Subscribers call `subscribe(job_id)` to get an async generator.
    """

    def __init__(self):
        self._subscribers: dict[int, list[asyncio.Queue]] = defaultdict(list)
        self._history: dict[int, list[ProgressEvent]] = defaultdict(list)
        self._max_history = 50

    def publish(self, job_id: int, event: ProgressEvent) -> None:
        """Publish a progress event to all subscribers of a job."""
        self._history[job_id].append(event)
        if len(self._history[job_id]) > self._max_history:
            self._history[job_id] = self._history[job_id][-self._max_history:]

        for queue in self._subscribers.get(job_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Drop if subscriber is too slow

    async def subscribe(self, job_id: int) -> AsyncGenerator[ProgressEvent, None]:
        """Subscribe to progress events for a job."""
        queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue(maxsize=100)
        self._subscribers[job_id].append(queue)

        # Replay recent history
        for event in self._history.get(job_id, []):
            yield event

        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event is None:
                    break
                yield event
                if event.event_type in ("complete", "error"):
                    break
        except asyncio.TimeoutError:
            # Send keepalive
            yield ProgressEvent(event_type="progress", message="keepalive", pct=-1)
        finally:
            if queue in self._subscribers.get(job_id, []):
                self._subscribers[job_id].remove(queue)

    def get_history(self, job_id: int) -> list[ProgressEvent]:
        """Get progress history for a job."""
        return list(self._history.get(job_id, []))

    def cleanup(self, job_id: int) -> None:
        """Remove all subscribers and history for a completed job."""
        self._subscribers.pop(job_id, None)
        # Keep history for a while (clients may reconnect)


# Global bus instance
_bus = ProgressBus()


def get_progress_bus() -> ProgressBus:
    """Get the global progress bus instance."""
    return _bus


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

def _get_db():
    from database.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/jobs/{job_id}/progress/stream")
async def stream_job_progress(
    job_id: int,
    request: Request,
    db: Session = Depends(_get_db),
):
    """SSE endpoint for real-time job progress.

    Returns a stream of Server-Sent Events with progress updates.
    """
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If job is already done, return final state immediately
    if job.status in ("done", "failed"):
        event_type = "complete" if job.status == "done" else "error"
        final = ProgressEvent(
            stage=job.stage or "done",
            pct=100 if job.status == "done" else -1,
            message=job.error_message or "Complete",
            event_type=event_type,
        )

        async def _static():
            yield final.to_sse()

        return StreamingResponse(
            _static(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def _event_generator():
        async for event in _bus.subscribe(job_id):
            if await request.is_disconnected():
                break
            yield event.to_sse()

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}/progress")
async def get_job_progress(
    job_id: int,
    db: Session = Depends(_get_db),
):
    """REST endpoint for current progress snapshot (non-streaming)."""
    from database.models import ReportJob
    job = db.query(ReportJob).filter(ReportJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    history = _bus.get_history(job_id)
    latest = history[-1] if history else None

    return {
        "job_id": job_id,
        "status": job.status,
        "stage": latest.stage if latest else job.stage,
        "pct": latest.pct if latest else 0,
        "message": latest.message if latest else "",
        "history_count": len(history),
    }
