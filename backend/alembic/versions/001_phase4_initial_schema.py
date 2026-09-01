"""
Phase 4 initial schema.

Revision: 001_phase4_initial
Created: Phase 4 implementation

Tables: profiles, invite_codes, watchlists, watchlist_items,
        conversations, messages, saved_research, alerts, notifications, background_jobs

Note: Assumes Supabase auth schema exists (auth.users).
FastAPI connects via service_role which bypasses RLS by design.
RLS is enabled as defense-in-depth against accidental direct client access.
"""
from alembic import op

revision = '001_phase4_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id UUID PRIMARY KEY,
            display_name TEXT,
            avatar_url TEXT,
            access_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (access_status IN ('pending', 'active', 'suspended')),
            role TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('user', 'admin')),
            preferences JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            created_by UUID REFERENCES profiles(id),
            used_by UUID REFERENCES profiles(id),
            used_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS watchlists (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            name TEXT NOT NULL DEFAULT 'My Watchlist',
            created_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_watchlists_user ON watchlists(user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            watchlist_id UUID NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            notes TEXT,
            added_at TIMESTAMPTZ DEFAULT now(),
            UNIQUE(watchlist_id, symbol)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_items_list ON watchlist_items(watchlist_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            title TEXT DEFAULT 'New Conversation',
            message_count INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at ASC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS saved_research (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            title TEXT,
            report_content JSONB NOT NULL,
            sources JSONB DEFAULT '[]',
            generated_at TIMESTAMPTZ,
            data_as_of TIMESTAMPTZ,
            engine_version TEXT,
            saved_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_saved_research_user ON saved_research(user_id, saved_at DESC)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL CHECK (alert_type IN ('price_above', 'price_below')),
            threshold NUMERIC NOT NULL,
            is_active BOOLEAN DEFAULT true,
            trigger_state TEXT DEFAULT 'armed' CHECK (trigger_state IN ('armed', 'triggered')),
            last_evaluated_value NUMERIC,
            last_triggered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(is_active, symbol) WHERE is_active = true")
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            alert_id UUID REFERENCES alerts(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            body TEXT,
            is_read BOOLEAN DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_unread ON notifications(user_id, created_at DESC) WHERE NOT is_read")
    op.execute("""
        CREATE TABLE IF NOT EXISTS background_jobs (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed')),
            payload JSONB,
            result JSONB,
            error_message TEXT,
            attempts INT DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user ON background_jobs(user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_running ON background_jobs(status, created_at) WHERE status IN ('pending', 'running')")
    for table in ['profiles', 'invite_codes', 'watchlists', 'watchlist_items',
                  'conversations', 'messages', 'saved_research', 'alerts',
                  'notifications', 'background_jobs']:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ['background_jobs', 'notifications', 'alerts', 'saved_research',
                  'messages', 'conversations', 'watchlist_items', 'watchlists',
                  'invite_codes', 'profiles']:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
