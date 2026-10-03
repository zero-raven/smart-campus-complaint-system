"""Photo attachment endpoints.

The images are stored and served; they are deliberately NOT processed. No
resizing, no EXIF extraction, no OCR, no classification from image content.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.deps import get_current_user, get_user_context
from backend.core.mongo import get_database
from backend.core.permissions import Action, UserContext, can_view_complaint
from backend.models.people import AppUser
from backend.services import attachment_service
from backend.services import complaint_service as svc

router = APIRouter(prefix="/complaints", tags=["attachments"])

_settings = get_settings()


def _mongo_name() -> str | None:
    """Database name for GridFS, or None to use the configured default."""
    return _settings.mongo_db


def _authorise_complaint(context: UserContext, db: Session, complaint_id: int):
    """Load a complaint the caller is allowed to see, or raise 404."""
    complaint = svc.get_complaint_or_404(db, complaint_id)
    if not can_view_complaint(context, complaint.reported_by, complaint.dept_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found"
        )
    return complaint


@router.get("/{complaint_id}/attachments")
def list_attachments(
    complaint_id: int,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_user_context),
):
    """Attachment metadata for a complaint. Bytes are fetched separately."""
    _authorise_complaint(context, db, complaint_id)
    return {"items": svc.list_attachments(db, complaint_id)}


@router.post(
    "/{complaint_id}/attachments",
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    complaint_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: AppUser = Depends(get_current_user),
    context: UserContext = Depends(get_user_context),
):
    """Attach one photo to a complaint.

    Access mirrors commenting: anyone who can see the complaint may attach to
    it. Bytes go to MongoDB GridFS, metadata to PostgreSQL.
    """
    _authorise_complaint(context, db, complaint_id)

    # Reject an oversized upload BEFORE reading it into memory, so a malicious
    # 500 MB request cannot exhaust the server.
    declared_length = file.size or 0
    if declared_length > attachment_service.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Image is larger than "
                f"{attachment_service.MAX_FILE_BYTES // (1024 * 1024)} MB"
            ),
        )

    data = await file.read()

    try:
        row = svc.add_attachment(
            db,
            complaint_id,
            data=data,
            declared_type=file.content_type,
            file_name=file.filename,
            uploader=user,
            mongo_db=_mongo(),
            mongo_db_name=_mongo_name(),
        )
    except attachment_service.AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "attachment_id": row.attachment_id,
        "file_name": row.file_name,
        "content_type": row.content_type,
        "file_size": row.file_size,
        "url": f"/api/v1/complaints/{complaint_id}/attachments/{row.attachment_id}/content",
        "processed": False,
    }


@router.get("/{complaint_id}/attachments/{attachment_id}/content")
def download_attachment(
    complaint_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_user_context),
):
    """Stream the stored image back from GridFS."""
    _authorise_complaint(context, db, complaint_id)

    try:
        row = svc.get_attachment(db, complaint_id, attachment_id)
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if not row.storage_ref or not row.storage_ref.startswith("gridfs:"):
        raise HTTPException(status_code=404, detail="Attachment content is unavailable")

    try:
        data, content_type = attachment_service.load_image(
            _mongo_name(), row.storage_ref.split(":", 1)[1]
        )
    except attachment_service.AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # inline so the browser renders it in an <img>; nosniff prevents a stored
    # file from ever being executed as script in the user's browser.
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{row.file_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{complaint_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_attachment(
    complaint_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    context: UserContext = Depends(get_user_context),
):
    """Delete an attachment.

    Only the complaint's reporter or an administrator may delete, so a staff
    member who attached evidence cannot erase it from the record.
    """
    complaint = _authorise_complaint(context, db, complaint_id)

    is_reporter = complaint.reported_by == context.user_id
    if not (is_reporter or context.role == "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the reporter or an administrator may delete an attachment",
        )

    try:
        svc.delete_attachment(
            db,
            complaint_id,
            attachment_id,
            context,
            mongo_db=_mongo(),
            mongo_db_name=_mongo_name(),
        )
    except svc.ComplaintError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _mongo():
    """Best-effort Mongo handle for the activity stream."""
    from backend.core.mongo import get_database

    try:
        return get_database()
    except Exception:  # pragma: no cover
        return None