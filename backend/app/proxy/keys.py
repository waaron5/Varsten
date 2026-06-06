"""Resolve a project's upstream OpenAI key.

Phase 1 vaulting is deliberately minimal: keys come from PROXY_OPENAI_KEYS, a
JSON env map of project_id -> OpenAI key. A per-tenant KMS-backed vault replaces
this later. Keys are never returned to clients and never written to the ledger.
"""

import uuid

from app.core.config import settings


def openai_key_for_project(project_id: uuid.UUID) -> str | None:
    return settings.proxy_openai_keys.get(str(project_id))
