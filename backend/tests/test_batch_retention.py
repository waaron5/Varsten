"""Batch content retention: staged .jsonl objects are deleted from storage once
their TTL lapses, while the BatchJob metadata row is kept. The batch file is a
documented content store (like the cache), so it must be retention-bounded.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.models import BatchJob, Project
from app.proxy import batch as batch_service
from app.storage import get_storage


def _stage(db, project, *, expires_at):
    job = batch_service.stage_input_job(db, project, None, endpoint="/v1/chat/completions", completion_window="24h")
    job.expires_at = expires_at
    db.commit()
    return job


def test_purge_deletes_expired_content_keeps_row(tmp_path, client, db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "batch_storage_backend", "local")
    monkeypatch.setattr(settings, "batch_local_storage_dir", str(tmp_path / "b"))
    ws = provision(sub="auth0|batchret", email="batchret@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    storage = get_storage()

    now = datetime.now(UTC)
    expired = _stage(db_session, project, expires_at=now - timedelta(hours=1))
    fresh = _stage(db_session, project, expires_at=now + timedelta(hours=1))
    # The client uploads content to the staged keys; simulate that here.
    storage.write(expired.input_storage_key, b'{"x":1}\n')
    storage.write(fresh.input_storage_key, b'{"y":2}\n')

    # Global sweep (other rows may exist in a dev DB); assert on our two jobs.
    assert batch_service.purge_expired_objects(db_session, now=now) >= 1

    # Expired content is gone; the row remains, marked purged.
    assert storage.exists(expired.input_storage_key) is False
    db_session.refresh(expired)
    assert expired.objects_purged_at is not None
    assert db_session.get(BatchJob, expired.id) is not None  # row kept

    # Fresh content untouched.
    assert storage.exists(fresh.input_storage_key) is True
    db_session.refresh(fresh)
    assert fresh.objects_purged_at is None


def test_purge_is_idempotent(tmp_path, client, db_session, provision, monkeypatch):
    monkeypatch.setattr(settings, "batch_storage_backend", "local")
    monkeypatch.setattr(settings, "batch_local_storage_dir", str(tmp_path / "b"))
    ws = provision(sub="auth0|batchret2", email="batchret2@example.com")
    project = db_session.get(Project, uuid.UUID(ws["project_id"]))
    storage = get_storage()

    now = datetime.now(UTC)
    job = _stage(db_session, project, expires_at=now - timedelta(hours=1))
    storage.write(job.input_storage_key, b'{"x":1}\n')

    assert batch_service.purge_expired_objects(db_session, now=now) >= 1
    db_session.refresh(job)
    assert job.objects_purged_at is not None
    # A second sweep finds nothing new (objects_purged_at filters every row out).
    assert batch_service.purge_expired_objects(db_session, now=now) == 0
