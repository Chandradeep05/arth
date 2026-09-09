"""
Add email and last_login columns to profiles.

Revision: 002_add_email_last_login
"""
from alembic import op

revision = '002_add_email_last_login'
down_revision = '001_phase4_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS email TEXT")
    op.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS last_login TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_profiles_email")
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS last_login")
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS email")
