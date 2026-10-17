"""Keep the common construction source once per role-file version."""

from alembic import op

revision = "sii_0003"
down_revision = "sii_0002"
branch_labels = depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE sii.source_file ADD COLUMN line_source_file_id bigint REFERENCES sii.source_file(id)"
    )
    op.execute("""UPDATE sii.source_file s SET line_source_file_id=p.line_source
        FROM (SELECT source_file_id,max(line_source_file_id) AS line_source
              FROM sii.predio WHERE line_source_file_id IS NOT NULL GROUP BY source_file_id) p
        WHERE s.id=p.source_file_id""")
    op.execute("ALTER TABLE sii.predio DROP COLUMN line_source_file_id")


def downgrade():
    op.execute("ALTER TABLE sii.predio ADD COLUMN line_source_file_id bigint")
    op.execute("""UPDATE sii.predio p SET line_source_file_id=s.line_source_file_id
        FROM sii.source_file s WHERE p.source_file_id=s.id AND s.line_source_file_id IS NOT NULL""")
    op.execute("""ALTER TABLE sii.predio ADD CONSTRAINT predio_line_source_file_id_fkey
        FOREIGN KEY(line_source_file_id) REFERENCES sii.source_file(id) NOT VALID""")
    op.execute("ALTER TABLE sii.predio VALIDATE CONSTRAINT predio_line_source_file_id_fkey")
    op.execute("ALTER TABLE sii.source_file DROP COLUMN line_source_file_id")
