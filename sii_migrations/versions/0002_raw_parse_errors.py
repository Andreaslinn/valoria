"""Preserve invalid public dates without guessing a replacement."""

from alembic import op

revision = "sii_0002"
down_revision = "sii_0001"
branch_labels = depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE sii.transferencia_raw ADD COLUMN errores_parseo text[] NOT NULL DEFAULT '{}'"
    )


def downgrade():
    op.execute("ALTER TABLE sii.transferencia_raw DROP COLUMN errores_parseo")
