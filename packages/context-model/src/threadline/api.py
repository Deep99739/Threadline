"""Read-only HTTP surface for the isolated synthetic product demo."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from threadline.demo import DEMO_TASK_ID, DEMO_TENANT_ID, DEMO_WORKSPACE_ID
from threadline.models import ContextSnapshot
from threadline.storage import ThreadlineStore

DEFAULT_API_DATABASE_URL = (
    "postgresql+psycopg://threadline:threadline_local@localhost:55432/threadline"
)


def _store(request: Request) -> ThreadlineStore:
    value: ThreadlineStore = request.app.state.store
    return value


def _active_context(store: ThreadlineStore) -> tuple[ContextSnapshot, dict[str, Any]]:
    snapshot = store.load_snapshot(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        task_id=DEMO_TASK_ID,
    )
    content = store.load_latest_handoff(
        tenant_id=DEMO_TENANT_ID,
        workspace_id=DEMO_WORKSPACE_ID,
        task_id=DEMO_TASK_ID,
    )
    return snapshot, content


def create_app(database_url: str | None = None) -> FastAPI:
    resolved_url = database_url or os.getenv("THREADLINE_DATABASE_URL") or DEFAULT_API_DATABASE_URL

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.store = ThreadlineStore(resolved_url)
        try:
            yield
        finally:
            app.state.store.close()

    app = FastAPI(
        title="Threadline Demo API",
        version="0.1.0",
        description="Read-only, exact-commit context for the isolated synthetic demo.",
        lifespan=lifespan,
    )
    allowed_origins = [
        item.strip()
        for item in os.getenv("THREADLINE_WEB_ORIGINS", "http://localhost:3000").split(",")
        if item.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic-read-only"}

    @app.get("/api/demo")
    def demo(request: Request) -> dict[str, Any]:
        try:
            snapshot, content = _active_context(_store(request))
        except LookupError as error:
            raise HTTPException(
                status_code=503, detail="Run the synthetic demo seed first."
            ) from error
        pack = content["context_pack"]
        return {
            "status": "partial" if content["unknowns"] or content["contradictions"] else "ok",
            "task": {
                "id": str(snapshot.task.id),
                "objective": snapshot.task.objective,
                "state": snapshot.task.status,
            },
            "repository": {
                "id": str(snapshot.repository_version.repository_id),
                "branch": snapshot.repository_version.branch,
                "commit": snapshot.repository_version.commit_sha,
            },
            "context_version": pack["context_version_id"],
            "request_id": pack["request_id"],
            "trace_id": pack["trace_id"],
            "next_action": content["next_action"],
            "constraints": content["constraints"],
            "verified_completed_work": content["verified_completed_work"],
            "unknowns": content["unknowns"],
            "conflicts": content["contradictions"],
            "items": pack["items"],
        }

    @app.get("/api/evidence/{evidence_id}")
    def evidence(evidence_id: UUID, request: Request) -> dict[str, Any]:
        snapshot, _ = _active_context(_store(request))
        item = next(
            (candidate for candidate in snapshot.evidence if candidate.id == evidence_id), None
        )
        if item is None:
            raise HTTPException(
                status_code=404, detail="Evidence is outside the demo task snapshot."
            )
        content = _store(request).load_evidence_content(
            tenant_id=DEMO_TENANT_ID,
            workspace_id=DEMO_WORKSPACE_ID,
            evidence_ids=[evidence_id],
        )
        return {
            "evidence_id": str(item.id),
            "locator": item.locator.model_dump(mode="json"),
            "content": content[evidence_id],
        }

    @app.get("/api/decisions/{decision_ref}")
    def decision(decision_ref: str, request: Request) -> dict[str, Any]:
        snapshot, _ = _active_context(_store(request))
        item = next(
            (
                candidate
                for candidate in snapshot.decisions
                if str(candidate.id) == decision_ref or candidate.decision_key == decision_ref
            ),
            None,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Decision was not found.")
        return {
            "decision_id": str(item.id),
            "decision_key": item.decision_key,
            "epistemic_state": "ASSERTED",
            "statement": item.statement,
            "rationale": item.rationale,
            "source_asserted_approver": str(item.approved_by) if item.approved_by else None,
            "evidence_ids": [str(value) for value in item.evidence_ids],
            "warning": "Repository metadata does not authenticate the asserted approver.",
        }

    return app


app = create_app()
