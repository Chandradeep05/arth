# ARTH External Scheduler Configuration Guide

**Document Version:** 1.0  
**Effective Date:** October 20, 2026  
**Target:** Decoupling internal jobs from GitHub Actions cron jitter

---

## 1. Background & Why External Scheduling is Required

GitHub Actions scheduled workflows (`on: schedule: - cron: '*/5 * * * *'`) suffer from documented execution delays ranging from 20 minutes to 4 hours during peak GitHub compute load.

For high-confidence price alert notifications and data cache warming, ARTH provides hardened REST job endpoints protected by the `X-Internal-Secret` header that can be triggered reliably by external schedulers (e.g. Cron-Job.org, Cloudflare Workers, or AWS EventBridge).

---

## 2. Schedule Specification

| Endpoint | Method | Recommended Interval | Active Window | Header Required |
|---|:---:|:---:|:---:|---|
| `/api/v1/system/health` | `GET` | Every 5 min | 24x7 | None |
| `/api/v1/internal/jobs/evaluate-alerts` | `POST` | Every 5 min | Market Hours (09:00 - 21:30 UTC) | `X-Internal-Secret: <SECRET>` |
| `/api/v1/internal/jobs/warm-alert-symbols` | `POST` | Every 30 min | Market Hours | `X-Internal-Secret: <SECRET>` |
| `/api/v1/internal/jobs/evaluate-predictions` | `POST` | Every 6 hours | Market Days (Mon-Fri) | `X-Internal-Secret: <SECRET>` |

---

## 3. Setup Option A: Cron-Job.org (Recommended — Free & Reliable)

1. Create a free account at [cron-job.org](https://cron-job.org).
2. Create **Job 1 (Health Check)**:
   - **URL:** `https://your-app.onrender.com/api/v1/system/health`
   - **Schedule:** Every 5 minutes
3. Create **Job 2 (Alert Evaluator)**:
   - **URL:** `https://your-app.onrender.com/api/v1/internal/jobs/evaluate-alerts`
   - **Request Method:** `POST`
   - **Schedule:** Every 5 minutes
   - **Headers:**
     - Key: `X-Internal-Secret`
     - Value: `<YOUR_INTERNAL_JOB_SECRET>`
4. Create **Job 3 (Symbol Cache Warmup)**:
   - **URL:** `https://your-app.onrender.com/api/v1/internal/jobs/warm-alert-symbols`
   - **Request Method:** `POST`
   - **Schedule:** Every 30 minutes
   - **Headers:**
     - Key: `X-Internal-Secret`
     - Value: `<YOUR_INTERNAL_JOB_SECRET>`

---

## 4. Setup Option B: Cloudflare Worker (Zero Cost, Edge Trigger)

Deploy the following minimal worker script with Cron Triggers (`*/5 * * * *` and `*/30 * * * *`):

```javascript
export default {
  async scheduled(event, env, ctx) {
    const BASE_URL = env.ARTH_API_URL;
    const SECRET = env.INTERNAL_JOB_SECRET;

    const headers = {
      "X-Internal-Secret": SECRET,
      "Content-Type": "application/json",
    };

    if (event.cron === "*/5 * * * *") {
      // 5-minute alert evaluation
      await fetch(`${BASE_URL}/api/v1/internal/jobs/evaluate-alerts`, {
        method: "POST",
        headers,
      });
    }

    if (event.cron === "*/30 * * * *") {
      // 30-minute quote cache warmup
      await fetch(`${BASE_URL}/api/v1/internal/jobs/warm-alert-symbols`, {
        method: "POST",
        headers,
      });
    }
  },
};
```

---

## 5. Secondary Failover: GitHub Actions

The existing `.github/workflows/alert-evaluator.yml` remains in place as a secondary failover. If an external job run fails, GitHub Actions cron runs serve as backup evaluation cycles.
