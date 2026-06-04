"""proxy cache embedding (pgvector)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-03 21:00:00.000000

Adds the prompt embedding column for semantic-cache matching. Requires the
pgvector extension (CREATE EXTENSION here; in managed Postgres it may need to be
enabled by an admin/role first).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        f"ALTER TABLE proxy_cache_entries ADD COLUMN embedding vector({EMBEDDING_DIM})"
    )
    # HNSW index for fast cosine nearest-neighbor at scale (pgvector handles an
    # empty/small table fine; it just helps once the cache grows).
    op.execute(
        "CREATE INDEX ix_proxy_cache_embedding "
        "ON proxy_cache_entries USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_proxy_cache_embedding")
    op.execute("ALTER TABLE proxy_cache_entries DROP COLUMN embedding")
