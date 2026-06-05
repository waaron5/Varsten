"""Object storage for the batching data plane.

The proxy must never hold a multi-hundred-MB .jsonl in memory, so batch input and
output files live in object storage. The client uploads its input directly to
storage via a pre-signed URL; the backend streams it to OpenAI off the request
path. Two backends behind one interface:

- LocalStorage: a filesystem tree, for dev and CI. Its "pre-signed" URLs point at
  a Varsten passthrough upload/download route (real pre-signing needs a real
  object store).
- S3Storage: pre-signed PUT/GET straight against S3 in production. boto3 is
  imported lazily so the dependency is only needed when this backend is selected.

A key is always tenant-scoped (``<project_id>/...``) so one tenant can never read
another's staged content.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from app.core.config import settings


class Storage(Protocol):
    def presigned_put_url(self, key: str) -> str: ...
    def presigned_get_url(self, key: str) -> str: ...
    def write(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Filesystem-backed storage for dev/CI. Pre-signed URLs are Varsten routes
    that proxy the bytes, since a filesystem has no native pre-signing."""

    def __init__(self, base_dir: str | None = None) -> None:
        self.base = Path(base_dir or settings.batch_local_storage_dir)

    def _path(self, key: str) -> Path:
        # Guard against traversal: a key is a relative, slash-delimited path.
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"invalid storage key: {key!r}")
        return self.base / safe

    def presigned_put_url(self, key: str) -> str:
        return f"/v1/batches/local-storage/{key}"

    def presigned_get_url(self, key: str) -> str:
        return f"/v1/batches/local-storage/{key}"

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def reset(self) -> None:
        if self.base.exists():
            shutil.rmtree(self.base)


class S3Storage:
    """S3-backed storage for production. boto3 is imported lazily."""

    def __init__(self, bucket: str | None = None, region: str | None = None) -> None:
        self.bucket = bucket or settings.batch_s3_bucket
        self.region = region or settings.batch_s3_region
        if not self.bucket:
            raise RuntimeError("batch_s3_bucket must be set for the s3 storage backend")

    def _client(self):
        import boto3  # lazy: only prod needs it

        return boto3.client("s3", region_name=self.region or None)

    def presigned_put_url(self, key: str) -> str:
        return self._client().generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=settings.batch_presign_ttl_seconds,
        )

    def presigned_get_url(self, key: str) -> str:
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=settings.batch_presign_ttl_seconds,
        )

    def write(self, key: str, data: bytes) -> None:
        self._client().put_object(Bucket=self.bucket, Key=key, Body=data)

    def read(self, key: str) -> bytes:
        obj = self._client().get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def exists(self, key: str) -> bool:
        import botocore.exceptions

        try:
            self._client().head_object(Bucket=self.bucket, Key=key)
            return True
        except botocore.exceptions.ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client().delete_object(Bucket=self.bucket, Key=key)


def get_storage() -> Storage:
    """The configured storage backend. Local for dev/CI, S3 for production."""
    if settings.batch_storage_backend == "s3":
        return S3Storage()
    return LocalStorage()
