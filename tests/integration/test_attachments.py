"""Photo attachment tests.

Covers the whole path: validation, GridFS storage, the relational metadata row,
retrieval, the per-complaint limit, and RBAC.

The stated requirement is that photos are STORED but NOT PROCESSED, so one test
asserts the round-trip is byte-identical - any future resizing or transcoding
would break it and that is exactly the point.
"""

from __future__ import annotations

import io

import pytest

# A real 1x1 PNG. Magic bytes matter: the service sniffs the actual content
# rather than trusting the client's Content-Type header.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63fcffff3f0300050001a5f645bf0000"
    "000049454e44ae426082"
)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"

NOT_AN_IMAGE = b"%PDF-1.4\n%not a real image at all\n" * 20


@pytest.fixture()
def complaint(client, auth_headers):
    """A complaint owned by the test student."""
    created = client.post(
        "/api/v1/complaints",
        headers=auth_headers["STUDENT"],
        json={
            "subject": "Broken window in the second floor corridor",
            "description": "The window pane near the stairs is shattered and needs replacement.",
        },
    ).json()
    return created["complaint"]


def upload(client, headers, complaint_id, data=PNG_BYTES, name="window.png", mime="image/png"):
    return client.post(
        f"/api/v1/complaints/{complaint_id}/attachments",
        headers=headers,
        files={"file": (name, io.BytesIO(data), mime)},
    )


class TestValidation:
    """Rejections happen before anything is written."""

    def test_empty_file_rejected(self, client, auth_headers, complaint):
        response = upload(client, auth_headers["STUDENT"], complaint["complaint_id"], b"")
        assert response.status_code == 422
        assert "empty" in response.json()["detail"].lower()

    def test_non_image_rejected(self, client, auth_headers, complaint):
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"],
            NOT_AN_IMAGE, "payload.pdf", "application/pdf",
        )
        assert response.status_code == 415
        assert "image" in response.json()["detail"].lower()

    def test_oversized_file_rejected(self, client, auth_headers, complaint):
        big = PNG_BYTES + b"\x00" * (6 * 1024 * 1024)
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"], big, "huge.png", "image/png"
        )
        assert response.status_code in (413, 415)

    def test_spoofed_content_type_still_rejected(self, client, auth_headers, complaint):
        """A .png declared as image/png but containing PDF bytes must fail.

        The client controls the Content-Type header, so validation must come
        from the file's magic bytes. This is the test that proves it does.
        """
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"],
            NOT_AN_IMAGE, "innocent.png", "image/png",
        )
        assert response.status_code == 415

    def test_jpeg_signature_accepted(self, client, auth_headers, complaint):
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"],
            JPEG_BYTES, "photo.jpg", "image/jpeg",
        )
        assert response.status_code == 201, response.text

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("../../etc/passwd", "passwd"),
            ("C:\\Windows\\System32\\evil.exe", "evil"),
            ("photo with spaces.png", "photo"),
        ],
    )
    def test_filename_sanitised(self, client, auth_headers, complaint, name, expected):
        """Path traversal and control characters must not survive."""
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"],
            PNG_BYTES, name, "image/png",
        )
        assert response.status_code == 201, response.text
        stored = response.json()["file_name"]
        assert "/" not in stored and "\\" not in stored
        assert expected in stored


class TestUploadAndRetrieval:
    def test_upload_returns_201(self, client, auth_headers, complaint):
        response = upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["file_size"] == len(PNG_BYTES)
        assert body["processed"] is False, "photos must be stored, not analysed"

    def test_metadata_row_is_created(self, client, auth_headers, complaint, db):
        """The attachment must exist relationally, with a gridfs storage ref."""
        from sqlalchemy import text

        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        row = db.execute(
            text(
                "SELECT file_name, content_type, file_size, storage_ref "
                "FROM attachment WHERE complaint_id = :cid"
            ),
            {"cid": complaint["complaint_id"]},
        ).one()

        assert row.file_name.endswith(".png")
        assert row.content_type == "image/png"
        assert row.file_size == len(PNG_BYTES)
        assert row.storage_ref.startswith("gridfs:")

    def test_listing_returns_metadata(self, client, auth_headers, complaint):
        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        response = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        )
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1

    def test_empty_listing_when_no_photos(self, client, auth_headers, complaint):
        response = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        )
        assert response.json()["items"] == []

    def test_content_roundtrips_byte_for_byte(self, client, auth_headers, complaint):
        """Requirement: stored, NOT processed. Any transform breaks this."""
        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        listing = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        ).json()

        response = client.get(
            listing["items"][0]["url"], headers=auth_headers["STUDENT"]
        )
        assert response.status_code == 200
        assert response.content == PNG_BYTES, "image bytes were altered in storage"
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_gridfs_really_holds_the_bytes(self, client, auth_headers, complaint, mongo_db):
        """The blob must live in GridFS, not in PostgreSQL."""
        from gridfs import GridFS

        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        fs = GridFS(mongo_db)
        files = list(fs.find({"metadata.complaint_id": complaint["complaint_id"]}))
        assert len(files) == 1
        assert files[0].read() == PNG_BYTES
        assert files[0].metadata["processed"] is False

    def test_upload_recorded_in_activity_stream(self, client, auth_headers, complaint):
        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        timeline = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/timeline",
            headers=auth_headers["STUDENT"],
        ).json()
        assert any(e["event_type"] == "ATTACHMENT_ADDED" for e in timeline["events"])

    def test_multiple_photos_up_to_limit(self, client, auth_headers, complaint):
        for i in range(3):
            response = upload(
                client, auth_headers["STUDENT"], complaint["complaint_id"],
                PNG_BYTES, f"photo{i}.png", "image/png",
            )
            assert response.status_code == 201, response.text

    def test_fourth_photo_rejected(self, client, auth_headers, complaint):
        for i in range(3):
            upload(
                client, auth_headers["STUDENT"], complaint["complaint_id"],
                PNG_BYTES, f"p{i}.png", "image/png",
            )
        response = upload(
            client, auth_headers["STUDENT"], complaint["complaint_id"],
            PNG_BYTES, "p3.png", "image/png",
        )
        assert response.status_code == 422
        assert "at most" in response.json()["detail"].lower()

    def test_limit_is_per_complaint(self, client, auth_headers, complaint):
        for i in range(3):
            upload(
                client, auth_headers["STUDENT"], complaint["complaint_id"],
                PNG_BYTES, f"a{i}.png", "image/png",
            )
        second = client.post(
            "/api/v1/complaints",
            headers=auth_headers["STUDENT"],
            json={
                "subject": "Another complaint with its own photo budget",
                "description": "This complaint should still accept three photos of its own.",
            },
        ).json()

        response = upload(
            client, auth_headers["STUDENT"], second["complaint"]["complaint_id"]
        )
        assert response.status_code == 201, response.text


class TestAttachmentRBAC:
    def test_anonymous_cannot_upload(self, client, complaint):
        response = upload(client, {}, complaint["complaint_id"])
        assert response.status_code == 401

    def test_anonymous_cannot_read(self, client, auth_headers, complaint):
        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        listing = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        ).json()
        response = client.get(listing["items"][0]["url"])
        assert response.status_code == 401

    def test_stranger_cannot_upload_to_others_complaint(
        self, client, auth_headers, complaint, users
    ):
        """A different student must get 404, not 403 - existence must not leak."""
        from backend.core.security import hash_password
        from backend.models.people import AppUser
        from backend.core.database import SessionLocal

        session = SessionLocal()
        try:
            stranger = AppUser(
                username="stranger_student",
                email="stranger@rvce.edu.in",
                password_hash=hash_password("Test@1234"),
                full_name="Unrelated Student",
                role="STUDENT",
            )
            session.add(stranger)
            session.commit()
            stranger_id = stranger.user_id
        finally:
            session.close()

        stranger_headers = {
            "Authorization": f"Bearer {auth_headers['STUDENT']['Authorization'].split()[1]}"
        }
        # Log in as the stranger with their own account.
        from fastapi.testclient import TestClient

        login = client.post(
            "/api/v1/auth/login",
            json={"username": "stranger_student", "password": "Test@1234"},
        )
        assert login.status_code == 200, login.text
        stranger_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        response = upload(client, stranger_headers, complaint["complaint_id"])
        assert response.status_code == 404

    def test_staff_can_read_photos_of_visible_complaints(
        self, client, auth_headers, complaint
    ):
        upload(client, auth_headers["STUDENT"], complaint["complaint_id"])
        response = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["ADMIN"],
        )
        assert response.status_code == 200

    def test_reporter_can_delete_own_photo(self, client, auth_headers, complaint):
        created = upload(client, auth_headers["STUDENT"], complaint["complaint_id"]).json()
        response = client.delete(
            f"/api/v1/complaints/{complaint['complaint_id']}"
            f"/attachments/{created['attachment_id']}",
            headers=auth_headers["STUDENT"],
        )
        assert response.status_code == 204

        listing = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        ).json()
        assert listing["items"] == []

    def test_staff_cannot_delete_evidence(self, client, auth_headers, complaint, db):
        """Evidence must not be erasable by a resolver who attached it.

        test_staff belongs to the CIVIL department. The complaint is routed by
        the triage rules, which may or may not be CIVIL, so the response is
        either 403 (visible to them, delete forbidden) or 404 (not visible at
        all). Both are acceptable refusals; what must never happen is 204.
        """
        created = upload(client, auth_headers["STUDENT"], complaint["complaint_id"]).json()
        response = client.delete(
            f"/api/v1/complaints/{complaint['complaint_id']}"
            f"/attachments/{created['attachment_id']}",
            headers=auth_headers["STAFF"],
        )
        assert response.status_code in (403, 404), (
            f"staff must not delete an attachment, got {response.status_code}"
        )
        assert response.status_code != 204

        # The photo must still be attached.
        listing = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments",
            headers=auth_headers["STUDENT"],
        ).json()
        assert len(listing["items"]) == 1

    def test_admin_can_delete(self, client, auth_headers, complaint):
        created = upload(client, auth_headers["STUDENT"], complaint["complaint_id"]).json()
        response = client.delete(
            f"/api/v1/complaints/{complaint['complaint_id']}"
            f"/attachments/{created['attachment_id']}",
            headers=auth_headers["ADMIN"],
        )
        assert response.status_code == 204

    def test_missing_attachment_is_404(self, client, auth_headers, complaint):
        response = client.get(
            f"/api/v1/complaints/{complaint['complaint_id']}/attachments/999999/content",
            headers=auth_headers["STUDENT"],
        )
        assert response.status_code == 404