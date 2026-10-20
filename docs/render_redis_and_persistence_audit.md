# ARTH Architecture Audit: Redis & Persistence State Verification

**Document Version:** 1.0  
**Audit Date:** October 20, 2026  
**Scope:** Render Free/Starter Tier Persistence, `REDIS_URL` Fallback, and PostgreSQL Canon

---

## 1. Executive Summary

A critical architectural concern on Render (and cloud container platforms) is container restarts and ephemeral service instances. This audit verifies the separation of concerns between ephemeral caching and persistent state in ARTH:

1. **Redis is strictly an ephemeral, read-through cache.** No canonical application state is stored exclusively in Redis.
2. **In-memory fallback is fully functional.** When `REDIS_URL` is unset, invalid, or during Redis downtime, `app.data.cache.CacheManager` automatically falls back to an in-memory TTL cache (`_memory_cache`) bounded to 500 entries to prevent memory exhaustion on 512MB RAM containers.
3. **PostgreSQL (via asyncpg) is 100% canonical.** All user data, alert configurations, trigger histories, notifications, watchlists, invite codes, and prediction ledgers persist exclusively in PostgreSQL tables.

---

## 2. Persistence Model by Entity

| Entity | Primary Store | Caching Layer | Survives Redis Crash / Restart? |
|---|---|---|:---:|
| **User Profiles & Auth** | PostgreSQL (`profiles`) | None | **YES** |
| **Invite Codes** | PostgreSQL (`invite_codes`) | None | **YES** |
| **User Watchlists** | PostgreSQL (`watchlists`) | None | **YES** |
| **Price Alerts** | PostgreSQL (`alerts`) | In-memory evaluation | **YES** |
| **Notifications** | PostgreSQL (`notifications`) | None | **YES** |
| **Prediction Ledger** | PostgreSQL (`predictions`) | None | **YES** |
| **Stock Quotes** | Live Provider | Redis / `_memory_cache` (60s TTL) | **YES** (Refetched) |
| **OHLCV Candles** | Live Provider | Redis / `_memory_cache` (300s TTL) | **YES** (Refetched) |
| **Financial Statements** | Live Provider | Redis / `_memory_cache` (86400s TTL) | **YES** (Refetched) |
| **Distributed Job Locks** | Redis `SET NX` | In-process fallback | **YES** |

---

## 3. In-Memory Cache Verification

In `app/data/cache.py`:
- `_memory_cache: Dict[str, Tuple[dict, float]]` stores `(payload, monotonic_expiry)`.
- Bounded to `_MAX_ENTRIES = 500`.
- Automated cleanup every `_CLEANUP_INTERVAL = 60.0s`.
- When capacity is reached, 20% oldest entries are evicted.
- Thundering herd protection via `_FetchLock` ensures only one provider fetch occurs concurrently for the same cache key.
- Verified by unit test: `TestInMemoryCacheFallback::test_in_memory_quote_cache_roundtrip` (100% PASS).

---

## 4. Render Production Recommendation

- **If Redis Addon is provisioned:** Set `REDIS_URL=rediss://...`.
- **If Redis Addon is NOT provisioned / Free Tier:** Leave `REDIS_URL` empty or unset. ARTH will log `redis_disabled` and seamlessly activate bounded in-memory caching for quote acceleration without throwing errors or degrading persistent features.
