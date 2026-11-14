"""Remember whether an application belongs to the automatic or manual workflow."""
from alembic import op
import sqlalchemy as sa

revision = "b71f209ce831"
down_revision = "8c00b76f8366"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("applications", sa.Column("automation_mode", sa.String(16), nullable=False, server_default="manual"))
    op.execute("""UPDATE applications SET automation_mode = 'automatic'
                  WHERE EXISTS (SELECT 1 FROM events WHERE events.application_id = applications.id
                                AND events.type = 'autofill.queued')""")


def downgrade():
    with op.batch_alter_table("applications") as batch:
        batch.drop_column("automation_mode")
