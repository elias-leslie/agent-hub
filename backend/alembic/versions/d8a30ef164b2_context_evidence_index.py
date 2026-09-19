"""Index source evidence and normalize observed legacy agent scope encoding.

Revision ID: d8a30ef164b2
Revises: c7e92a160a31
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d8a30ef164b2"
down_revision = "c7e92a160a31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("context_records", sa.Column("source_keys", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.execute("UPDATE context_records SET source_keys=jsonb_path_query_array(payload::jsonb, '$.**.source_id')")
    op.create_index("ix_context_records_sources", "context_records", ["source_keys"], postgresql_using="gin")
    op.execute("""UPDATE memories SET scope_id=COALESCE(NULLIF(scope_id,''), split_part(scope,':',2)),
                  scope=split_part(scope,':',1), version=version+1, updated_at=now()
                  WHERE scope LIKE 'agent:%' OR scope LIKE 'project:%'""")


def downgrade() -> None:
    op.drop_index("ix_context_records_sources", table_name="context_records")
    op.drop_column("context_records", "source_keys")
