"""Photo attachment storage (MongoDB GridFS).

Why GridFS and not a PostgreSQL bytea column
-------------------------------------------
The project is built on a hybrid SQL-NoSQL design, and the split is principled
rather than arbitrary: PostgreSQL holds structured, transactional, integrity-
constrained data; MongoDB holds flexible, high-volume blobs. A 4 MB phone
photo is exactly the latter.

Concretely, GridFS is the right tool because:

* BSON documents are capped at 16 MB. GridFS splits an upload into 255 KB
  chunks, so there is no practical size limit tied to document size.
* Binary data never bloats the authoritative relational store. Backups and
  EXPLAIN plans stay unaffected by photo volume.
* The file metadata travels with the bytes, so `attachment.storage_ref` in
  PostgreSQL points at a file that carries its own name, content type and
  uploader.

PostgreSQL still owns the ATTACHMENT ROW: file name, size, content type, uploader
and timestamp are relational facts that must be queryable and constrained. The
split is therefore metadata in SQL, bytes in MongoDB, joined on complaint_id.

The images are NOT processed. No resizing, no EXIF stripping, no OCR. They are
stored and served back, which is the stated requirement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from gridfs import GridFS
from gridfs.errors import CorruptGridFile, FileExists, GridFSError, NoFile
from pymongo.errors import PyMongoError

from backend.core.config import get_settings
from backend.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

# --- limits -----------------------------------------------------------------
MAX_FILE_BYTES = 5 * 1024 * 1024      # 5 MB per photo
MAX_FILES_PER_COMPLAINT = 3

# Images only. HEIC is included because iPhones produce it by default and a
# campus complaint system that rejects iPhone photos is not usable on mobile.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/gif": ".gif",
}

# Magic-byte signatures. The browser-supplied Content-Type header is client
# controlled, so the actual bytes decide whether the upload is an image.
_MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


class AttachmentError(Exception):
    """Upload or retrieval failure carrying a user-facing message."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class StoredFile:
    """Result of a successful upload."""

    gridfs_id: str
    file_name: str
    content_type: str
    size: int

    @property
    def storage_ref(self) -> str:
        """Value stored in attachment.storage_ref."""
        return f"gridfs:{self.gridfs_id}"


def get_gridfs(db_name: str | None = None):
    """Return a GridFS handle bound to the configured database."""
    from backend.core.mongo import get_database

    return GridFS(get_database(db_name))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def sanitise_filename(name: str | None, fallback: str = "photo") -> str:
    """Reduce a client filename to a safe, ASCII, extension-preserving stem.

    Prevents path traversal ('../../etc/passwd') and strips control characters,
    while keeping the extension so the browser can render it inline.
    """
    if not name:
        return fallback

    # Strip any directory component the client may have sent.
    name = name.replace("\\", "/").split("/")[-1]

    # Normalise unicode (NFKD) then drop non-ASCII, so a filename typed on a
    # phone in any script becomes safe to store and echo in a header.
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()

    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:60] or fallback
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:8].lower()

    return f"{stem}.{ext}" if ext else stem


def sniff_content_type(data: bytes, declared: str | None) -> str | None:
    """Determine the content type from the file's actual magic bytes.

    Returns None when the bytes match no known image signature.

    SECURITY: this must never fall back to the client-supplied Content-Type
    header. That header is attacker-controlled, so trusting it lets a PDF (or
    any other file) be uploaded by renaming it to photo.png and declaring
    image/png. Every format this system accepts has a reliable signature, so an
    unrecognised signature is a rejection, not a licence to trust the header.
    """
    for signature, content_type in _MAGIC_SIGNATURES.items():
        if data.startswith(signature):
            return content_type

    # RIFF....WEBP
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"

    # ISO base media (HEIC/HEIF): 'ftyp' box at offset 4
    if data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"heif", b"mif1"):
            return "image/heic"

    return None


def validate_upload(data: bytes, declared_type: str | None, file_name: str | None) -> str:
    """Validate an upload and return its sanitised filename.

    Raises AttachmentError with a specific message so the UI can show the user
    something actionable instead of a generic failure.
    """
    if not data:
        raise AttachmentError("The uploaded file is empty", 422)

    if len(data) > MAX_FILE_BYTES:
        size_mb = len(data) / (1024 * 1024)
        raise AttachmentError(
            f"Image is {size_mb:.1f} MB; the limit is {MAX_FILE_BYTES // (1024 * 1024)} MB",
            413,
        )

    content_type = sniff_content_type(data, declared_type)

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise AttachmentError(
            "Only image files are allowed (JPEG, PNG, WebP, GIF or HEIC)",
            415,
        )

    safe_name = sanitise_filename(file_name, fallback="photo")
    # Ensure the stored extension reflects the real detected type.
    expected_ext = ALLOWED_CONTENT_TYPES[content_type]
    stem, dot, _ext = safe_name.rpartition(".")
    if not dot:
        safe_name = f"{safe_name}{expected_ext}"

    return safe_name


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def store_image(
    db_name: str | None,
    data: bytes,
    declared_type: str | None,
    file_name: str | None,
    *,
    complaint_id: int,
    uploaded_by: int,
    username: str,
) -> StoredFile:
    """Validate and write one image into GridFS.

    The uploader identity and complaint link are duplicated into GridFS metadata
    so a file remains self-describing even if the relational row is archived.
    """
    safe_name = validate_upload(data, declared_type, file_name)
    content_type = sniff_content_type(data, declared_type)

    try:
        fs = get_gridfs(db_name)
        gridfs_id = fs.put(
            data,
            filename=safe_name,
            contentType=content_type,
            metadata={
                "complaint_id": complaint_id,
                "uploaded_by": uploaded_by,
                "username": username,
                "uploaded_at": datetime.now(timezone.utc),
                "processed": False,  # explicitly: stored, never analysed
            },
        )
    except (PyMongoError, GridFSError, FileExists) as exc:
        logger.error("GridFS write failed: %s", exc)
        raise AttachmentError("Could not store the image. Please try again.", 503) from exc

    logger.info(
        "Stored attachment %s (%s, %d bytes) for complaint %s",
        gridfs_id, safe_name, len(data), complaint_id,
    )
    return StoredFile(
        gridfs_id=str(gridfs_id),
        file_name=safe_name,
        content_type=content_type,
        size=len(data),
    )


def load_image(db_name: str | None, gridfs_id: str) -> tuple[bytes, str]:
    """Read a stored image back. Returns (bytes, content_type)."""
    try:
        oid = ObjectId(gridfs_id)
    except (InvalidId, TypeError) as exc:
        raise AttachmentError("Malformed attachment reference", 400) from exc

    try:
        fs = get_gridfs(db_name)
        result = fs.get(oid)
    except NoFile as exc:
        raise AttachmentError("Attachment not found", 404) from exc
    except (CorruptGridFile, GridFSError, PyMongoError) as exc:
        logger.error("GridFS read failed for %s: %s", gridfs_id, exc)
        raise AttachmentError("Could not read the attachment", 503) from exc

    try:
        data = result.read()
    finally:
        result.close()

    return data, (result.content_type or "application/octet-stream")


def delete_image(db_name: str | None, gridfs_id: str) -> bool:
    """Remove a file from GridFS. Returns False when it was already absent."""
    try:
        oid = ObjectId(gridfs_id)
    except (InvalidId, TypeError):
        return False

    try:
        fs = get_gridfs(db_name)
    except (GridFSError, PyMongoError) as exc:
        logger.error("GridFS unavailable for delete: %s", exc)
        return False

    try:
        fs.delete(oid)
        return True
    except NoFile:
        return False
    except (GridFSError, PyMongoError) as exc:
        logger.error("GridFS delete failed for %s: %s", gridfs_id, exc)
        return False


def count_for_complaint(db_name: str | None, complaint_id: int) -> int:
    """How many files are stored for a complaint, enforced before upload."""
    try:
        fs = get_gridfs(db_name)
        return len(list(fs.find({"metadata.complaint_id": complaint_id})))
    except (GridFSError, PyMongoError) as exc:
        logger.warning("Could not count attachments: %s", exc)
        return 0