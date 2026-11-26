"""Delivery tracking roll-ups, exports, and sample blueprints."""

import re
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse, Response

from app.api.deps import DB, CurrentUser
from app.models.enums import Role
from app.schemas.projects import BlueprintOut
from app.services import export, progress, samples
from app.services.access import authorize_blueprint, authorize_project

router = APIRouter(tags=["delivery"])


@router.get("/blueprints/{blueprint_id}/progress")
def get_progress(blueprint_id: uuid.UUID, db: DB, user: CurrentUser) -> dict[str, Any]:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    return progress.rollups(db, blueprint_id)


def _filename(title: str, ext: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "blueprint"
    return f"{slug[:60]}.{ext}"


@router.get(
    "/blueprints/{blueprint_id}/export",
    responses={
        200: {"content": {"text/markdown": {}, "application/json": {}, "application/pdf": {}}}
    },
)
def export_blueprint(
    blueprint_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    format: Literal["md", "json", "pdf"] = Query("md"),
) -> Response:
    bp = authorize_blueprint(db, user, blueprint_id, Role.viewer)
    sections, data = export.build_sections(db, bp)
    disposition = {"Content-Disposition": f'attachment; filename="{_filename(bp.title, format)}"'}
    if format == "json":
        return JSONResponse(data, headers=disposition)
    if format == "pdf":
        return Response(
            export.to_pdf(bp, sections), media_type="application/pdf", headers=disposition
        )
    return Response(
        export.to_markdown(bp, sections),
        media_type="text/markdown; charset=utf-8",
        headers=disposition,
    )


@router.get("/samples")
def list_samples() -> list[dict[str, Any]]:
    """Public: the curated sample blueprints (shown on the landing page)."""
    return samples.list_samples()


@router.post(
    "/projects/{project_id}/samples/{slug}",
    response_model=BlueprintOut,
    status_code=status.HTTP_201_CREATED,
)
def add_sample(project_id: uuid.UUID, slug: str, db: DB, user: CurrentUser) -> BlueprintOut:
    """Copy a sample into a project (e.g. after the sandbox was emptied)."""
    project = authorize_project(db, user, project_id, Role.editor)
    return BlueprintOut.model_validate(samples.create_from_sample(db, project, slug))
