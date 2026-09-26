"""
V4 Production Integration Tests.

Covers the critical fixes from the V4 production integration pass:
- DB middleware skip-list (public routes don't pin connections)
- Streaming persistence uses pool.acquire()
- Research NameError fix (redis_conn)
- Watchlist symbol validation
- Health score unavailable state
- Risk engine unavailable dimensions
- FMP Indian ticker guard
- XGBoost version pin
- Alert response shape compat
- Assistant prompt rules
"""

import re
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Resolve repo root regardless of CWD (tests/ -> backend/ -> repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── A1: research.py NameError fix ──────────────────────────────

def test_research_uses_redis_conn_parameter():
    """Verify research.py references redis_conn, not redis."""
    import ast
    from pathlib import Path

    src = (REPO_ROOT / "backend/app/api/v1/research.py").read_text("utf-8")
    tree = ast.parse(src)

    # Find function parameters named redis_conn
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            param_names = [a.arg for a in node.args.args]
            # The endpoint should have redis_conn as param
            if "redis_conn" in param_names:
                # Check that body doesn't use bare 'redis' as a Name
                for child in ast.walk(node):
                    if isinstance(child, ast.Name) and child.id == "redis":
                        # Allow 'redis_conn' references but not bare 'redis'
                        pytest.fail(
                            f"Function '{node.name}' uses bare 'redis' variable "
                            f"(line {child.lineno}) — should be 'redis_conn'"
                        )


# ── A2: DB middleware skip-list ────────────────────────────────

def test_no_db_prefixes_skip_list_exists():
    """Public routes (market, financials, risk) must NOT acquire a pooled connection."""
    src = open(str(REPO_ROOT / "backend/app/main.py"), "r", encoding="utf-8").read()
    assert "_NO_DB_PREFIXES" in src, "Skip-list tuple not found in main.py"
    assert '"/api/v1/market"' in src, "Market prefix missing from skip-list"
    assert '"/api/v1/risk"' in src, "Risk prefix missing from skip-list"
    assert '"/api/v1/financials"' in src, "Financials prefix missing from skip-list"


def test_middleware_uses_skip_list():
    """Middleware should check request.url.path.startswith(_NO_DB_PREFIXES)."""
    src = open(str(REPO_ROOT / "backend/app/main.py"), "r", encoding="utf-8").read()
    assert "startswith(_NO_DB_PREFIXES)" in src or "startswith( _NO_DB_PREFIXES)" in src


# ── A3: Streaming persistence uses pool.acquire ───────────────

def test_streaming_persist_uses_pool_acquire():
    """Both persist paths in assistant.py must use pool.acquire(), not request.state.db."""
    src = open(str(REPO_ROOT / "backend/app/api/v1/assistant.py"), "r", encoding="utf-8").read()
    assert "pool.acquire()" in src, "pool.acquire() not found in assistant.py"
    # Should appear at least twice (CancelledError path + normal completion)
    assert src.count("pool.acquire()") >= 2, (
        f"pool.acquire() found {src.count('pool.acquire()')} times, expected >= 2"
    )


# ── A4: Watchlist symbol validation ───────────────────────────

def test_watchlist_has_symbol_regex():
    """Watchlist add endpoint must validate symbol format with regex."""
    src = open(str(REPO_ROOT / "backend/app/api/v1/user_watchlists.py"), "r", encoding="utf-8").read()
    assert "_SYMBOL_RE" in src, "Symbol regex constant not found"
    assert "re.compile" in src, "re.compile not found"


# ── A6: Health score unavailable state ────────────────────────

def test_health_score_returns_unavailable_for_missing_data():
    """When all ratios are None, health score must return available=False."""
    src = open(str(REPO_ROOT / "backend/app/engines/research/statement_parser.py"), "r", encoding="utf-8").read()
    assert "'available': False" in src or '"available": False' in src, (
        "available: False not found in statement_parser.py"
    )
    assert "'available': True" in src or '"available": True' in src, (
        "available: True not found for normal case"
    )


# ── A7: FMP Indian ticker guard ───────────────────────────────

def test_fmp_rejects_indian_tickers():
    """FMP adapter must early-return None for .NS and .BO symbols."""
    src = open(str(REPO_ROOT / "backend/app/data/adapters/fmp.py"), "r", encoding="utf-8").read()
    assert ".NS" in src and ".BO" in src, "Indian ticker guard not found in fmp.py"
    assert "return None" in src


# ── A8: XGBoost version pin ───────────────────────────────────

def test_xgboost_version_pinned():
    """XGBoost must be pinned to <3.0.0 to prevent SHAP breakage."""
    src = open(str(REPO_ROOT / "backend/requirements.txt"), "r", encoding="utf-8").read()
    xgb_line = [l for l in src.splitlines() if l.startswith("xgboost")]
    assert xgb_line, "xgboost not found in requirements.txt"
    assert "<3.0.0" in xgb_line[0] or "<3" in xgb_line[0], (
        f"xgboost not pinned: {xgb_line[0]}"
    )


# ── A9: Lazy RAGRetriever import ──────────────────────────────

def test_rag_retriever_not_imported_at_module_level():
    """RAGRetriever must not be imported at module level (saves ~92MB boot RAM)."""
    src = open(str(REPO_ROOT / "backend/app/engines/research/engine.py"), "r", encoding="utf-8").read()
    # Check that the top-level imports don't include RAGRetriever
    lines = src.splitlines()
    for i, line in enumerate(lines[:50]):  # Only check first 50 lines (module-level)
        if "from app.engines.rag.retriever import RAGRetriever" in line:
            if not line.strip().startswith("#"):
                pytest.fail(
                    f"RAGRetriever imported at module level (line {i+1}). "
                    "Should be lazy-imported inside methods."
                )


# ── A10: Pool size reduced ────────────────────────────────────

def test_pool_size_reduced():
    """Connection pool should be max_size=5 (safe with skip-list)."""
    src = open(str(REPO_ROOT / "backend/app/main.py"), "r", encoding="utf-8").read()
    assert "max_size=5" in src, "max_size=5 not found in main.py"


# ── B2: Assistant prompt rules ────────────────────────────────

def test_assistant_prompt_forbids_fabricated_stats():
    """System prompt must forbid inventing statistics."""
    src = open(str(REPO_ROOT / "backend/app/engines/assistant/engine.py"), "r", encoding="utf-8").read()
    assert "NEVER fabricate" in src or "never fabricate" in src.lower(), (
        "Prompt rule about fabricated stats not found"
    )


def test_assistant_prompt_forbids_markdown_headings():
    """System prompt must forbid markdown headings and tables."""
    src = open(str(REPO_ROOT / "backend/app/engines/assistant/engine.py"), "r", encoding="utf-8").read()
    lower = src.lower()
    assert "no markdown heading" in lower or "no headings" in lower or "do not use markdown heading" in lower, (
        "Prompt rule about markdown headings not found"
    )


# ── C3: Risk engine unavailable dimensions ────────────────────

def test_risk_engine_marks_unavailable_dimensions():
    """Risk engine must return available=False for insufficient data."""
    src = open(str(REPO_ROOT / "backend/app/engines/risk/engine.py"), "r", encoding="utf-8").read()
    assert "available" in src, "available flag not found in risk engine"


# ── Frontend: accent-orange CSS variable ──────────────────────

def test_accent_orange_defined_in_css():
    """--accent-orange must be defined in globals.css."""
    src = open(str(REPO_ROOT / "frontend/src/app/globals.css"), "r", encoding="utf-8").read()
    assert "--accent-orange" in src, "--accent-orange not defined in globals.css"
    assert "#f97316" in src, "Orange color value not found"


# ── Dashboard honesty ─────────────────────────────────────────

def test_dashboard_no_hardcoded_market_session():
    """Dashboard must not have hardcoded 'Market Session: Open'."""
    src = open(str(REPO_ROOT / "frontend/src/app/page.tsx"), "r", encoding="utf-8").read()
    assert "Market Session: Open" not in src, (
        "Hardcoded 'Market Session: Open' still present"
    )


def test_dashboard_has_dynamic_session_label():
    """Dashboard must compute market session status dynamically."""
    src = open(str(REPO_ROOT / "frontend/src/app/page.tsx"), "r", encoding="utf-8").read()
    assert "getMarketSessionLabel" in src, "Dynamic session label function not found"


def test_dashboard_stock_list_fits_free_tier():
    """Dashboard stocks must fit in a single TwelveData batch (8 credits/min)."""
    src = open(str(REPO_ROOT / "frontend/src/app/page.tsx"), "r", encoding="utf-8").read()
    # Count unique ticker symbols in MARKET_STOCKS
    import re
    tickers = re.findall(r"'([A-Z]{1,5})'", src[:2000])  # First 2000 chars
    unique = set(tickers)
    assert len(unique) >= 6, f"Only {len(unique)} unique tickers found, expected >= 6"
    assert len(unique) <= 8, f"{len(unique)} tickers found — exceeds free tier batch limit of 8"


def test_dashboard_no_hardcoded_dollar_in_table():
    """MoversTable must use dynamic currency, not hardcoded $."""
    src = open(str(REPO_ROOT / "frontend/src/app/page.tsx"), "r", encoding="utf-8").read()
    # Check the movers table section doesn't have literal ${formatNumber
    assert "${formatNumber" not in src, (
        "Hardcoded $ in MoversTable price column — should use dynamic currency"
    )


# ── Auth fixes ────────────────────────────────────────────────

def test_auth_provider_awaits_profile():
    """AuthProvider must await fetchProfile before setLoading(false)."""
    src = open(str(REPO_ROOT / "frontend/src/lib/auth/AuthProvider.tsx"), "r", encoding="utf-8").read()
    assert "await fetchProfile" in src, "fetchProfile not awaited in AuthProvider"


def test_admin_page_uses_isAdmin():
    """Admin page must use isAdmin from useAuth(), not user?.role."""
    src = open(str(REPO_ROOT / "frontend/src/app/admin/page.tsx"), "r", encoding="utf-8").read()
    assert "isAdmin" in src, "isAdmin not used in admin page"
    # Should NOT check user?.role for admin
    assert "user?.role === 'admin'" not in src, (
        "admin page still checks user?.role instead of isAdmin"
    )


def test_callback_has_pkce_guard():
    """Auth callback must guard against double PKCE exchange."""
    src = open(str(REPO_ROOT / "frontend/src/app/auth/callback/page.tsx"), "r", encoding="utf-8").read()
    assert "exchangedRef" in src or "useRef" in src, (
        "PKCE double-exchange guard not found"
    )


# ── Secret scan ───────────────────────────────────────────────

def test_no_secrets_in_diff():
    """Ensure no API keys or secrets leaked in changed files."""
    import subprocess
    result = subprocess.run(
        ['C:\\Program Files\\Git\\cmd\\git.exe', '--no-optional-locks', 'diff', 'HEAD'],
        capture_output=True, text=True, cwd=".",
        encoding="utf-8", errors="replace",
    )
    diff = result.stdout
    secret_patterns = [
        r'sk-[a-zA-Z0-9]{20,}',           # OpenAI
        r'gsk_[a-zA-Z0-9]{20,}',          # Groq
        r'AIza[a-zA-Z0-9_-]{35}',          # Google
        r'ghp_[a-zA-Z0-9]{36}',            # GitHub PAT
        r'SUPABASE_SERVICE_ROLE_KEY\s*=',   # Supabase
        r'-----BEGIN (RSA |EC )?PRIVATE KEY', # Private keys
    ]
    for pattern in secret_patterns:
        matches = re.findall(pattern, diff)
        assert not matches, f"Potential secret leak: {pattern} matched {len(matches)} times"
