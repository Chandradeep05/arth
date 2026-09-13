"""phase5 alert unique and messages idempotency

Revision ID: 003
Revises: 002
Create Date: 2026-09-13 12:11:44.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_active ON alerts(user_id, symbol, alert_type, threshold) WHERE is_active = true")
    
    op.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS idempotency_key TEXT;")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_idempotency ON messages(conversation_id, idempotency_key) WHERE idempotency_key IS NOT NULL;")

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_messages_idempotency")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP INDEX IF EXISTS uq_alerts_active")
