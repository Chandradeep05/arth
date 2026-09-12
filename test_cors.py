"""
ARTH Phase 4 — CORS Regex Test

Tests the CORS allow_origin_regex pattern against known good and hostile URLs.
Finding #20 from external audit: don't rely on visual inspection.
"""
import re
import unittest

# This is the exact regex from main.py line 224
CORS_REGEX = r"https://arth(-[a-z0-9-]+)?\.vercel\.app"


class TestCORSRegex(unittest.TestCase):
    """Verify CORS regex matches only ARTH's own Vercel deployments."""

    def _matches(self, origin: str) -> bool:
        """Full-string match (how Starlette evaluates allow_origin_regex)."""
        return bool(re.fullmatch(CORS_REGEX, origin))

    # ── Should MATCH ──

    def test_primary_domain(self):
        self.assertTrue(self._matches("https://arth.vercel.app"))

    def test_five_slug(self):
        self.assertTrue(self._matches("https://arth-five.vercel.app"))

    def test_user_project_slug(self):
        self.assertTrue(self._matches("https://arth-chandradeep05s-projects.vercel.app"))

    def test_git_branch_slug(self):
        self.assertTrue(self._matches("https://arth-git-main-chandradeep05s-projects.vercel.app"))

    # ── Should NOT match ──

    def test_reject_evil_subdomain(self):
        """arth.vercel.app.evil.com should not match."""
        self.assertFalse(self._matches("https://arth.vercel.app.evil.com"))

    def test_reject_http(self):
        """HTTP (not HTTPS) should not match."""
        self.assertFalse(self._matches("http://arth.vercel.app"))

    def test_reject_unrelated_vercel(self):
        """Someone else's vercel.app should not match."""
        self.assertFalse(self._matches("https://evil.vercel.app"))

    def test_reject_prefix_spoof(self):
        """arth prefix but different project should not match (no hyphen)."""
        self.assertFalse(self._matches("https://arthevil.vercel.app"))

    def test_reject_trailing_path(self):
        """Origin with path should not match."""
        self.assertFalse(self._matches("https://arth.vercel.app/evil"))

    def test_reject_localhost(self):
        self.assertFalse(self._matches("http://localhost:3000"))

    def test_reject_empty(self):
        self.assertFalse(self._matches(""))

    def test_reject_none_string(self):
        self.assertFalse(self._matches("null"))


if __name__ == "__main__":
    unittest.main()
