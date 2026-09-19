# ARTH — AI Research & Trading Hub

<p align="center">
  <strong>Institutional-Grade Equity Intelligence, Probabilistic Forecasting & Grounded AI Research Platform</strong>
</p>

<p align="center">
  <a href="https://arth-five.vercel.app/"><img src="https://img.shields.io/badge/Live_Demo-arth--five.vercel.app-10b981?style=for-the-badge&logo=vercel&logoColor=white" alt="Live Demo"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11"/>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/Next.js-16.2-black?style=flat-square&logo=next.js&logoColor=white" alt="Next.js 16"/>
  <img src="https://img.shields.io/badge/React-19-61dafb?style=flat-square&logo=react&logoColor=black" alt="React 19"/>
  <img src="https://img.shields.io/badge/TypeScript-5.x-3178c6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript"/>
  <img src="https://img.shields.io/badge/TailwindCSS-v4.0-38bdf8?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind CSS v4"/>
  <img src="https://img.shields.io/badge/PostgreSQL-16_(Supabase)-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL 16"/>
  <img src="https://img.shields.io/badge/Redis-7_(Upstash)-dc382d?style=flat-square&logo=redis&logoColor=white" alt="Redis Cache"/>
  <img src="https://img.shields.io/badge/Tests-306_Passing-success?style=flat-square&logo=pytest&logoColor=white" alt="306 Tests Passing"/>
  <img src="https://img.shields.io/badge/Security-Zero_Secrets-success?style=flat-square" alt="Zero Secrets"/>
  <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="MIT License"/>
</p>

---

## Executive Summary

**ARTH** (**A**I **R**esearch & **T**rading **H**ub) is a full-stack financial intelligence and equity analytics platform designed to deliver institutional-grade research, probabilistic return forecasting, and real-time market data across global exchanges (US: NYSE, NASDAQ) and domestic Indian markets (NSE, BSE).

Unlike consumer market portals that rely on siloed data or ungrounded Large Language Models that hallucinate financial figures, ARTH bridges **deterministic quantitative finance**, **explainable machine learning (XGBoost + SHAP)**, and **in-memory Retrieval-Augmented Generation (ChromaDB + ONNX)** into a high-density, obsidian-glass terminal interface.

---

## Core Capabilities

### 1. Multi-Exchange Live Market Terminal
* **Cross-Market Coverage**: Seamlessly ingest, normalize, and monitor equities across US markets (NYSE, NASDAQ) and Indian exchanges (NSE, BSE) using standardized OHLCV data contracts.
* **TradingView-Grade Interactive Visualizations**: High-performance Canvas candlestick and volume charting powered by `lightweight-charts` v5.2, featuring dynamic timeframe resolution (`1D`, `1W`, `1M`, `3M`, `1Y`, `5Y`).
* **Quantitative Indicator Suite**: Deterministic computation of Wilder's RSI (14-period), MACD (12/26 EMA with 9-period signal line), Bollinger Bands (20-period SMA &plusmn; 2&sigma;), Average True Range (ATR-14), and VWAP.
* **Market Breadth & Movement**: Real-time sector heatmaps, top gainers, top losers, and index benchmarks (NIFTY 50, SENSEX, S&P 500, NASDAQ Composite).

### 2. Explainable ML Return Forecasting
* **Supervised Walk-Forward Modeling**: Walk-forward validated gradient-boosted regression (`XGBoost` with histogram optimization) predicting 5-day forward price directional momentum across 14 engineered technical and fundamental features.
* **SHAP Interpretability**: Local feature-attribution scoring via `shap.TreeExplainer` exposing the exact mathematical drivers behind every prediction (e.g., RSI divergence, momentum decay, volatility spikes).
* **Market Regime Classification**: Algorithmic identification of macro price regimes (`Trending`, `Mean-Reverting`, `High-Volatility Range`) with calibrated confidence ratings.

### 3. Grounded Equity Research Lab (RAG)
* **In-Memory Semantic Indexing**: Lightweight, zero-dependency ChromaDB vector store running embedded ONNX transformers (`all-MiniLM-L6-v2`, 384 dimensions) indexing corporate disclosures, press releases, and financial filings on demand.
* **Citation-Enforced Synthesis**: Multi-stage prompt orchestration synthesizing structured equity research reports (Executive Summary, Catalysts, Valuation Ratios, Financial Health, and Bear Thesis) paired with verifiable source footnote citations.
* **Personalized Research Dossiers**: One-click immutable snapshot archiving allowing authenticated users to bookmark and retrieve historical research reports with full provenance tracking.

### 4. Algorithmic Risk Intelligence
* **Multi-Factor Risk Decomposition**: Normalized 0–100 composite risk scoring combining 30-day and 90-day annualized historical volatility, bid/ask liquidity spread, debt-to-equity leverage, and beta sensitivity.
* **Corporate Governance Auditing**: Automated detection of insider transactions, board independence metrics, and shareholder concentration signals.
* **Sector-Aware Normalization**: Adaptive accounting thresholds dynamically adjusting leverage benchmarks across asset classes (e.g., adjusting debt tolerance for capital-heavy utilities vs. asset-light technology firms).

### 5. Context-Aware Conversational Assistant
* **Financial Ticker Extraction**: In-flight regex entity resolution extracting mentioned equity tickers while filtering out common natural language terms (e.g., `VS`, `GOING`, `FOR`).
* **Automated Data Tool Augmentation**: Dynamically injects live quote pricing, moving averages, 52-week extremes, and momentum metrics directly into prompt system contexts before LLM inference.
* **Token-Efficient Streaming**: Low-latency Server-Sent Events (SSE) streaming with automated `<think>` reasoning block elimination to prevent vendor token leakage and ensure concise outputs.

### 6. User Workspace & Automated Price Alerts
* **Multi-List Watchlists**: Create, reorder, and manage custom equity baskets with real-time price change hydration and batch quote retrieval.
* **Distributed Price Alert Engine**: Set high-precision conditional price triggers (`price_above` or `price_below`) evaluated asynchronously against cached Redis quotes every 5 minutes with zero outbound API credit consumption.
* **In-App Notification Center**: Unread badge counts, instant state transition notifications, and cursor-based historical alert review.
* **Role-Gated Administration**: Access-controlled admin panel for invite-code provisioning, user role management (`user` / `admin`), and real-time status transitions (`pending`, `active`, `suspended`).

---

## System Architecture

```
+---------------------------------------------------------------------------------------+
|                                  CLIENT LAYER (Vercel)                                |
|  Next.js 16.2 (App Router) | React 19 | Tailwind CSS v4 | Lightweight-Charts | Supabase |
+-------------------------------------------+-------------------------------------------+
                                            | HTTPS / REST / SSE
                                            v
+---------------------------------------------------------------------------------------+
|                              APPLICATION LAYER (FastAPI / Render)                     |
|                                                                                       |
|   [Middleware: CORS (Strict Vercel Regex) -> RateLimiter -> TraceID -> Metrics -> DB]  |
|                                                                                       |
|   +-------------------+  +-------------------+  +-------------------+  +------------+ |
|   |  Market Provider  |  |  Research Engine  |  | Prediction Engine |  | User/Auth  | |
|   |  Capability Matrix|  |  (ChromaDB RAG)   |  | (XGBoost + SHAP)  |  | Workspace  | |
|   +---------+---------+  +---------+---------+  +---------+---------+  +-----+------+ |
|             |                      |                      |                  |        |
+-------------|----------------------|----------------------|------------------|--------+
              |                      |                      |                  |
              +----------------------+----------------------+                  |
              |                                                                |
              v                                                                v
+-----------------------------+                                  +----------------------+
|    REDIS IN-MEMORY CACHE    |                                  | POSTGRESQL (Supabase)|
|  - Quote TTL: 300s          |                                  |  - Profiles & Roles  |
|  - Indicators TTL: 600s     |                                  |  - Watchlists/Items  |
|  - Fundamentals TTL: 24h    |                                  |  - Alerts & Notices  |
|  - Lua Sliding Quotas       |                                  |  - Saved Research    |
|  - Mutex Locks for Workers  |                                  |  - Chat Messages     |
+-----------------------------+                                  +----------------------+
              |                                                                ^
              v                                                                |
+-----------------------------+                                                |
|   EXTERNAL PROVIDER LAYER   |                                                |
|  - Twelve Data (US Quotes)  |                                                |
|  - Finnhub (News / Profiles)|                                                |
|  - FMP (Statements / Ratios)|                                                |
|  - NSE India (Live Quotes)  |                                                |
+-----------------------------+                                                |
              |                                                                |
              v                                                                |
+-----------------------------+         +----------------------------+         |
|   LLM INFERENCE & DEVOPS    |         |    DISTRIBUTED CRON WORKER |         |
|  - Groq Cloud API (Qwen)    |         |    (GitHub Actions)        |         |
|  - Fallback: GPT-OSS Chain  |         |  - Alert Evaluator (5 min) |---------+
|  - Ollama (Local Dev)       |         |  - Symbol Warmup (30 min)  |
|  - Keepalive Self-Ping Loop |         |  - Keep-Alive Ping (14 min)|
+-----------------------------+         +----------------------------+
```

---

## Data Ingestion & Capability Routing

No single public market data provider offers comprehensive, unmetered access to both global and domestic Indian equities across quotes, fundamentals, and news. ARTH implements a **Capability Matrix Router** that inspects ticker symbols, queries cached states, and dispatches requests to specialized adapters:

| Market / Exchange | Data Type | Primary Provider | Fallback Provider | Normalization Contract |
|---|---|---|---|---|
| **US Equities** (`AAPL`, `NVDA`) | Real-Time Quotes | **Twelve Data** | **Finnhub** | `NormalizedQuote` |
| **US Equities** | Historical OHLCV | **Twelve Data** | — | `NormalizedOHLCV` (DataFrame) |
| **US Equities** | Company News & Profiles | **Finnhub** | — | `ArticleList` / `CompanyProfile` |
| **US Equities** | Financial Statements | **Financial Modeling Prep (FMP)** | — | `FinancialStatements` |
| **Indian Equities** (`.NS`, `.BO`) | Real-Time Quotes | **NSE India Web Adapter** | — | `NormalizedQuote` |
| **Indian Equities** | Historical OHLCV | **NSE India Web Adapter** | — | `NormalizedOHLCV` (DataFrame) |

### Resiliency Patterns
* **Three-State Circuit Breakers**: The NSE India adapter features an automated circuit breaker (`CLOSED` &rarr; `OPEN` &rarr; `HALF_OPEN`). After 3 consecutive network failures, calls immediately fail fast for 300 seconds, preventing connection pool starvation.
* **Tiered Multi-Model LLM Failover**: Groq client calls execute across a priority fallback chain:
  `qwen/qwen3.6-27b` &rarr; `openai/gpt-oss-120b` &rarr; `openai/gpt-oss-20b`.
  If a model encounters an upstream rate limit (HTTP 429) or vendor decommissioning, the query seamlessly executes on the next tier without propagating errors to the user.
* **Multi-Tier TTL Caching**: Redis preserves quotes for 300 seconds, technical indicators for 600 seconds, and corporate fundamentals for 24 hours (86,400 seconds), maintaining sub-5ms response times on hot paths.

---

## Defensive Security & API Protection

* **Cryptographic JWT Validation**: Validates Supabase JWTs with dynamic key algorithm detection. Supports both legacy HS256 tokens and modern ES256 tokens verified against an in-memory cached JWKS public key client (`PyJWKClient`).
* **Zero-Trust Database Status Verification**: While JWTs establish client identity (`sub`), the user's operational status (`pending`, `active`, `suspended`) and role (`user`, `admin`) are re-queried from PostgreSQL on every request. Revoked or suspended accounts are barred instantly (HTTP 403) without waiting for token expiry.
* **Network-Level Sliding-Window Throttling**: In-memory IP rate limiter protecting against brute-force volumetric attacks:
  * Public Global: `60 req/min`
  * XGBoost Predictions: `10 req/min`
  * AI Chat Invocations: `10 req/min`
  * RAG Report Generation: `5 req/min`
* **Atomic Redis Lua User Quotas**: Authenticated feature consumption is strictly metered via atomic Redis Lua scripts (`ZREMRANGEBYSCORE` &rarr; `ZCARD` &rarr; `ZADD`):
  * Assistant Messages: `30 requests / hour`
  * Predictive Forecasts: `20 requests / day`
  * Deep Research Reports: `10 requests / day`
* **Strict CORS Origin Filtering**: Production origin checking enforces a strict regular expression (`r"^https://arth(-[a-z0-9-]+)?\.vercel\.app$"`), rejecting unvetted origins, null origins, newline injection, and malicious subdomain collisions.
* **Idempotent Data Mutation**: Critical database writes (message dispatch, alert creation) employ unique constraints (`uq_alerts_active`, `uq_messages_idempotency`) and `ON CONFLICT DO NOTHING` patterns to neutralize network retries and duplicate insertion races.

---

## Verified Test Suite & Code Quality

ARTH maintains an extensive, verified automated test suite covering unit contracts, data schemas, security perimeters, and runtime stability:

```
================================================================================
ARTH AUTOMATED TEST EXECUTION SUMMARY
================================================================================
Suite Name                  Scope / Coverage                    Cases     Status
--------------------------------------------------------------------------------
test_adversarial_auth.py    JWT bounds, CORS, Lua quotas, UUID   29       PASSED
test_cors.py                Vercel preview & production origins  12       PASSED
test_phase3.py              Data contracts, rate limits, ML      91       PASSED
test_integration.py         Multi-provider schema integration    86       PASSED
test_stabilization.py       Reasoning strip, OHLCV, NSE circuit  88       PASSED
--------------------------------------------------------------------------------
TOTAL VERIFIED TESTS        100% Passing Coverage               306       PASSED
================================================================================
```

* **Secret Leakage Prevention**: Automated regex scan across all 200 tracked files verifying zero committed private keys, JWT secrets, database credentials, or provider access tokens.
* **Turbopack Build Cleanliness**: 16/16 Next.js frontend routes verified to statically compile and prerender cleanly without syntax errors or unhandled hydration discrepancies.

---

## Technology Stack

```
Frontend:
  - Next.js 16.2.6 (App Router, Turbopack)
  - React 19.2.4 / React DOM 19.2.4
  - TypeScript 5.x (Strict Type Checking)
  - Tailwind CSS v4.0 (Native PostCSS Integration)
  - TradingView Lightweight-Charts v5.2.0
  - Recharts v3.8.1 (Financial Statement Breakdown)
  - Framer Motion v12.40.0 (Atmospheric Transitions)
  - Lucide React (Financial & Terminal Iconography)

Backend:
  - Python 3.11
  - FastAPI 0.115.12 / Uvicorn 0.34.3 (ASGI)
  - Pydantic v2.11.3 / Pydantic-Settings v2.9.1
  - orjson 3.10.18 (High-Throughput C-Serialization)
  - asyncpg 0.30.0 (Asynchronous PostgreSQL Pool)
  - SQLAlchemy 2.0.41 / Alembic 1.15.2 (Schema Migrations)
  - redis-py 6.2.0 (with hiredis C-Parser)
  - structlog 25.4.0 (Structured JSON Observability)

AI, Machine Learning & Quantitative Analytics:
  - Groq Cloud SDK 0.25.0 (Qwen 3.6 27B / GPT-OSS Models)
  - ChromaDB v0.4.x (In-Memory Ephemeral Vector Store)
  - ONNX Runtime (all-MiniLM-L6-v2 Embeddings)
  - XGBoost >= 2.0.0 (XGBRegressor Histogram Boosting)
  - SHAP >= 0.43.0 (TreeExplainer Attribution)
  - NumPy 1.26.4 / Pandas 2.2.3 / Scikit-Learn 1.4.0

Infrastructure & DevOps:
  - Vercel (Frontend Serverless Edge Hosting)
  - Render (Backend Web Service, Python 3.11 Runtime)
  - Supabase (PostgreSQL 16 Database with Row-Level Security)
  - Upstash (Serverless Distributed Redis Caching)
  - GitHub Actions (Scheduled Evaluation & Keep-Alive Workflows)
  - Docker & Docker Compose (TimescaleDB / Redis Local Environments)
```

---

## API Catalog Summary

The backend exposes **71 total HTTP endpoints** versioned under `/api/v1` alongside foundational health probes:

| Category | Route Prefix | Sample Endpoints | Description |
|---|---|---|---|
| **Market Data** | `/api/v1/market/*` | `GET /quote/{sym}`<br/>`GET /ohlcv/{sym}`<br/>`POST /batch-quotes` | Real-time prices, historical bars, technical indicators, and multi-asset hydration. |
| **Forecasting** | `/api/v1/prediction/*` | `POST /{sym}/forecast`<br/>`GET /{sym}/regime` | XGBoost 5-day return predictions, SHAP attributions, and market regime detection. |
| **Research** | `/api/v1/research/*` | `POST /generate/{sym}`<br/>`POST /index/{sym}` | In-memory ChromaDB vector indexing and cited equity research report generation. |
| **Financials** | `/api/v1/financials/*` | `GET /{sym}/statements`<br/>`GET /{sym}/ratios` | Standardized Balance Sheet, Income Statement, Cash Flow, and financial health scoring. |
| **Risk** | `/api/v1/risk/*` | `GET /{sym}`<br/>`GET /governance/{sym}` | Composite risk factor breakdowns (volatility, liquidity, leverage, governance). |
| **Assistant** | `/api/v1/user/conversations/*` | `POST /{id}/messages`<br/>`GET /` | Multi-turn AI chat with automated financial tool execution and token streaming. |
| **Workspace** | `/api/v1/user/*` | `GET /watchlists`<br/>`POST /alerts`<br/>`GET /research/saved` | Custom watchlist management, price threshold alert rules, and saved dossiers. |
| **Admin** | `/api/v1/admin/*` | `GET /users`<br/>`POST /invite-codes` | Closed-beta invite code generation, user role updates, and system usage audit. |
| **Internal** | `/api/v1/internal/*` | `POST /jobs/evaluate-alerts`<br/>`POST /jobs/warm-alert-symbols`| Machine-to-machine cron jobs for price alert evaluation and Redis pre-warming. |
| **System** | `/api/v1/system/*` | `GET /health`<br/>`GET /metrics` | Deep subsystem health verification (DB, Redis) and latency percentiles. |

---

## Getting Started

### Prerequisites
* **Python**: `3.11+`
* **Node.js**: `18+` (Node 20+ recommended)
* **Package Managers**: `pip`, `npm`
* **PostgreSQL & Redis**: Optional locally (Docker Compose provided) or cloud instances (Supabase & Upstash)

### 1. Clone the Repository
```bash
git clone https://github.com/Chandradeep05/arth.git
cd arth
```

### 2. Backend Installation & Setup
```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows PowerShell

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp ../.env.example .env
# Open .env and configure your API keys (see Configuration Reference below)

# Run database migrations
alembic upgrade head

# Launch development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Backend Swagger API documentation will be available at `http://localhost:8000/docs`.

### 3. Frontend Installation & Setup
```bash
cd ../frontend

# Install dependencies
npm install

# Run development server
npm run dev
```
Open `http://localhost:3000` in your browser to access the ARTH terminal.

### 4. Running with Docker Compose (Local Services)
To spin up local TimescaleDB and Redis containers automatically:
```bash
docker compose up -d
```

---

## Configuration Reference

Configure the following environment variables in `backend/.env` and `frontend/.env.local`:

### Backend Environment Variables (`backend/.env`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_NAME` | string | `ARTH` | Platform application name. |
| `APP_ENV` | enum | `development` | Runtime environment (`development`, `staging`, `production`). |
| `DATABASE_URL` | string | `postgresql+asyncpg://...` | PostgreSQL connection DSN (with `asyncpg` driver). |
| `REDIS_URL` | string | `redis://localhost:6379/0` | Primary Redis connection URL. |
| `UPSTASH_REDIS_URL` | string | `""` | Optional serverless Upstash Redis REST URL. |
| `UPSTASH_REDIS_TOKEN` | string | `""` | Optional serverless Upstash Redis token. |
| `GROQ_API_KEY` | string | `""` | Groq Cloud API key for high-speed LLM inference. |
| `GROQ_MODEL` | string | `qwen/qwen3.6-27b` | Primary LLM model identifier. |
| `GROQ_FALLBACK_MODELS` | string | `openai/gpt-oss-120b,...` | Comma-separated model failover priority list. |
| `GROQ_MAX_TOKENS` | integer | `1000` | Maximum token ceiling per inference pass. |
| `TWELVEDATA_API_KEY` | string | `""` | Twelve Data API key for real-time US equity pricing. |
| `FINNHUB_API_KEY` | string | `""` | Finnhub API key for news feeds and company profiles. |
| `FMP_API_KEY` | string | `""` | Financial Modeling Prep API key for financial statements. |
| `SUPABASE_URL` | string | `""` | Supabase project URL (used for JWKS endpoint validation). |
| `SUPABASE_JWT_SECRET` | string | `""` | Supabase shared JWT secret (used for legacy HS256 validation). |
| `INTERNAL_JOB_SECRET` | string | `""` | Shared machine-to-machine secret for `/api/v1/internal/*` cron jobs. |

### Frontend Environment Variables (`frontend/.env.local`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | string | `http://localhost:8000` | Backend API base URL (or production Render endpoint). |
| `NEXT_PUBLIC_SUPABASE_URL` | string | `""` | Supabase project URL for client authentication. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | string | `""` | Supabase public anonymous API key. |

---

## Deployment Topology

ARTH operates in a dual-cloud serverless configuration:

* **Frontend**: Hosted on **Vercel**, leveraging Edge Network routing, automatic SSL, and Next.js Turbopack optimized bundle outputs.
* **Backend**: Hosted on **Render** as a high-performance Python 3.11 ASGI web service with an automated keep-alive self-ping background loop preventing free-tier cold sleep cycles.
* **Database & Auth**: Hosted on **Supabase** (PostgreSQL 16 with Row-Level Security) paired with **Upstash** serverless distributed Redis.
* **Automation**: Scheduled **GitHub Actions** cron runners executing automated alert condition evaluations every 5 minutes and pre-warming volatile tickers every 30 minutes.

---

## Legal & Compliance Disclaimer

> **IMPORTANT**: ARTH is an artificial intelligence-augmented financial intelligence and research platform developed for informational, analytical, and educational purposes only.
> 
> * **Not Financial Advice**: Nothing contained within this software, its quantitative models, its predictive forecasts, or its AI-synthesized research dossiers constitutes financial, investment, legal, or tax advice.
> * **Data Latency**: Real-time market quotes may be delayed by approximately 15 seconds or subject to upstream exchange provider dissemination schedules.
> * **No Execution Warranty**: Forward-looking probabilistic return forecasts generated via machine learning (XGBoost) represent statistical estimates of historical technical price action and do not guarantee future performance.
> 
> Always conduct independent research and consult a licensed financial advisor before allocating capital to publicly traded securities.

---

## License

This project is open-source software licensed under the [MIT License](LICENSE).
