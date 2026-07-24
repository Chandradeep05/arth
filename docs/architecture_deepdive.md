# ARTH — AI Research & Trading Hub
## Systems Architecture & Engineering Deep-Dive
**Prepared by**: Antigravity, Principal Systems Architect
**Target Audience**: Backend Engineers, Quantitative Developers, and Systems Designers

---

## 1. Executive Platform Thesis

ARTH (AI Research & Trading Hub) is a production-grade, full-stack financial decision-support infrastructure. It is designed to deliver institutional-grade market intelligence, machine learning forecasting, and cited financial research reports on a zero-dollar infrastructure budget. 

The core challenge of building financial intelligence tools on public/free tiers is three-fold:
1. **IP Censorship & Throttling**: Yahoo Finance and other raw providers block cloud hosting IP addresses (AWS, Render, GCP) with HTTP 401/429 codes.
2. **Ephemeral Memory & Filesystem**: Free cloud tiers (such as Render) have ephemeral filesystems and strict 512MB RAM ceilings.
3. **LLM Hallucinations**: Standard LLMs cannot do math or recall historical metrics reliably, making them dangerous for financial analysis.

ARTH solves these issues through a decoupled, memory-conscious, async python backend (FastAPI) paired with a responsive, server-side rendered (SSR) Next.js 16 frontend. The system employs **deterministic prompt injection** to eliminate LLM hallucinations, **ephemeral in-memory vector databases** to bypass cloud disk limitations, and **on-demand XGBoost walk-forward models** optimized for low-memory constraints.

---

## 2. Core Platform Flowcharts & Lifecycles

### 2.1 Decoupled Platform Architecture

The diagram below details the structural layout of ARTH, showing the flow of REST API requests, Server-Sent Events (SSE), and data caching.

```mermaid
graph TD
    %% Frontend Layer
    subgraph Frontend [Next.js 16 Web Application]
        UI[User Interface - React components]
        State[State Manager / API Client]
        Proxy[Next.js API Proxy / Rewrites]
        UI --> State
        State --> Proxy
    end

    %% Routing Layer
    Proxy -->|REST / SSE / WebSockets| API[FastAPI Gateway - Port 8000]

    %% Backend Service Layer
    subgraph Backend [FastAPI Engine Core]
        API -->|Route Dispatch| Controllers[Endpoint Controllers]
        
        subgraph Engines [Intelligence Engines]
            MarketEng[Market Processing Engine]
            ResEng[Research Engine - Groq / Qwen]
            RiskEng[Sector-Aware Risk Engine]
            PredEng[XGBoost Forecasting Engine]
            RAGPipeline[RAG Pipeline]
        end
        
        Controllers --> MarketEng
        Controllers --> ResEng
        Controllers --> RiskEng
        Controllers --> PredEng
        Controllers --> RAGPipeline
    end

    %% Data Access Layer
    subgraph Adapters [Data Adapter Layer]
        Adapter[Base Data Adapter - Circuit Breaker + Retry]
        Yahoo[Yahoo Finance Adapter]
        TwelveData[Twelve Data US Stocks]
        
        Adapter --> Yahoo
        Adapter --> TwelveData
    end

    MarketEng --> Adapter
    ResEng --> RAGPipeline
    RiskEng --> Adapter
    PredEng --> Adapter

    %% Storage Layer
    subgraph Storage [Caching & Persistence Layer]
        Redis[(Redis Cache - TTL-based)]
        Timescale[(TimescaleDB - PostgreSQL)]
        Chroma[(ChromaDB - In-Memory Vector Store)]
    end

    Adapter -->|Read/Write Cache| Redis
    Adapter -->|Persist OHLCV| Timescale
    RAGPipeline -->|Embed & Query| Chroma
    PredEng -->|Read/Write Models| ModelDisk[/tmp/arth_models - JSON Cache]
```

---

### 2.2 Deep RAG Research Report Flow

The sequence diagram below represents the exact flow when a user requests an AI-generated deep research report. Note how the LLM is completely isolated from direct web fetching, preventing hallucinated numbers.

```mermaid
sequenceDiagram
    autoconf on
    actor User
    participant Frontend as Next.js 16 UI
    participant Backend as FastAPI Gateway
    participant RAG as RAG Pipeline
    participant yf as Yahoo Finance API
    participant Chroma as ChromaDB (In-Memory)
    participant LLM as Groq LLM (Qwen/Qwen3.6)

    User->>Frontend: Click "Generate Deep Report" (RELIANCE.NS)
    Frontend->>Backend: POST /api/v1/research/generate/RELIANCE.NS?depth=deep (SSE)
    
    rect rgb(20, 30, 40)
        Note over Backend, RAG: Step 1: Document Ingestion & Chunking
        Backend->>yf: Fetch Company Profile & news history (Throttled)
        yf-->>Backend: Return raw JSON metrics + 15 news articles
        Backend->>RAG: Pass raw data to DocumentProcessor
        RAG->>RAG: Parse description, metrics, news, sector context
        RAG->>RAG: Chunk text (500 words, 50 words overlap)
        RAG->>Chroma: ChromaClient.add_documents() (Index on the fly)
        Chroma-->>RAG: Index completed
    end

    rect rgb(30, 40, 50)
        Note over Backend, Chroma: Step 2: Semantic Retrieval & Calibration
        Backend->>RAG: retrieve_context("financial analysis report for RELIANCE")
        RAG->>Chroma: query(n_results=8)
        Chroma-->>RAG: Return raw chunks + L2 distances
        RAG->>RAG: Deduplicate chunks by title
        RAG->>RAG: Convert L2 distance to 0-1 relevance (1.0 - dist / 2.0)
        RAG->>RAG: Format chunks with [SOURCE N] markers
    end

    rect rgb(40, 50, 60)
        Note over Backend, LLM: Step 3: Cited Prompt Injections
        Backend->>Backend: Inject exact company metrics, technical indicators & RAG context
        Backend->>LLM: Stream request with DEEP_RESEARCH_SYSTEM_PROMPT
        loop Stream Token Generation
            LLM-->>Backend: Yield markdown tokens with [SOURCE N] references
            Backend-->>Frontend: SSE Stream chunk (data: token)
            Frontend->>User: Render text character-by-character
        end
    end
    
    Backend->>Chroma: delete_collection("RELIANCE") (Free memory)
```

---

### 2.3 XGBoost Forecasting & SHAP Explanation Loop

This flowchart displays the mathematical pipeline used to transform raw market ticks into a 5-day predictive forward return with feature importances.

```mermaid
graph TD
    %% Input
    Start([Request Forecast for Symbol]) --> Fetch[Fetch 2 Years of Daily OHLCV & Info]
    
    %% Feature Engineering
    subgraph FeatureEngineering [Feature Engineering Layer]
        Fetch --> CalcPrice[Price Features: returns 1d/5d/20d, volatility 20d, open gap]
        Fetch --> CalcTech[Technical Features: RSI 14, MACD signal value, BB position]
        Fetch --> CalcVol[Volume Features: Volume vs 20d SMA, volume trend]
        Fetch --> CalcFund[Fundamental Features: Log Market Cap, PE Ratio, PB Ratio]
        Fetch --> CalcCal[Calendar Features: Day of Week, Month]
    end
    
    %% Target Building
    CalcPrice --> Target[Build target_5d: Close.pct_change(5).shift(-5)]
    CalcTech --> Target
    CalcVol --> Target
    CalcFund --> Target
    CalcCal --> Target

    %% Pre-Processing
    Target --> Align[Align features & targets into DataFrame]
    Align --> Clean[Replace inf/-inf with NaN, dropna()]
    
    %% Train-Val Split
    Clean --> Split[Walk-Forward Split: Train on first 80%, Validate on last 20%]
    
    %% Training
    subgraph ModelTraining [XGBoost Training Engine]
        Split --> Fit[Fit XGBRegressor: n_estimators=100, max_depth=4, lr=0.05]
        Fit --> Eval[Evaluate validation set R2 & MAE]
    end

    %% Live Prediction
    Eval --> PredLive[Predict target using latest live features]
    
    %% Explanations
    subgraph Explainability [SHAP Explainability Layer]
        PredLive --> Explainer[Initialize SHAP TreeExplainer]
        Explainer --> Values[Calculate SHAP Values]
        Values --> CleanStrings[Sanitize bracket-wrapped strings & convert to float]
        CleanStrings --> MapHuman[Map keys to human-readable strings]
        MapHuman --> SortFactors[Sort by absolute value of SHAP importance]
    end

    %% Confidence
    SortFactors --> Conf[Compute Confidence: R2 factor + Signal magnitude + Sample size]
    
    %% Output
    Conf --> FormReturn[Format Output JSON]
    FormReturn --> Garbage[Call gc.collect() - Free Memory]
    Garbage --> End([Return Forecast Response])
```

---

## 3. Database & Infrastructure Choices (Why, When, How, Where)

A primary architectural decision is choosing the right datastore for the right work. Standard web applications default to a single database (like MongoDB or PostgreSQL). Because ARTH handles relational metrics, time-series prices, caching, and vector embedding, it uses a **polyglot persistence model**.

### 3.1 Architectural Selection Matrix

| Datastore | Option Evaluated | Decision | Rationale (Why, When, Where) |
|---|---|---|---|
| **Relational Database** | MySQL vs. **PostgreSQL** | **PostgreSQL** | Relational data integrity is vital for joining corporate profiles to exchange parameters. PostgreSQL provides superior JSON querying (via `JSONB`) and supports TimescaleDB extensions for time-series data. MySQL lacks robust time-series optimizations. |
| **Time-Series Store** | MongoDB vs. **TimescaleDB** | **TimescaleDB** | Store OHLCV price histories and technical indicators. MongoDB documents suffer from index bloat under large time-series queries. TimescaleDB uses **Hypertables** (automatic time-based chunking), allowing sub-millisecond range queries. |
| **Developer Database** | SQLite vs. **PostgreSQL** | **Both** | SQLite is utilized in local development for zero-dependency portability. In staging/production, the app upgrades to TimescaleDB (PostgreSQL) to handle simultaneous requests and async connection pools. |
| **Caching Layer** | Local Memory vs. **Redis** | **Redis** | Used to cache yfinance outputs to shield against rate limits. Local memory caching fails under multiple uvicorn worker processes (data inconsistency). Redis provides single-source-of-truth TTL caching. |
| **Vector Database** | Pinecone vs. **ChromaDB** | **ChromaDB** | Vector indexing for news and summaries. Pinecone requires API calls and external credentials. ChromaDB runs **in-memory** within the FastAPI container, requiring no external infrastructure setup. |

---

### 3.2 Database Setup & Installation Configurations

#### 3.2.1 TimescaleDB & Redis Docker Infrastructure
For local development and self-hosted environments, both datastores are run inside isolated Docker containers via the root [docker-compose.yml](file:///C:/Users/a4ama/.gemini/antigravity/scratch/afiip/docker-compose.yml):

```yaml
version: '3.8'

services:
  # TimescaleDB (Time-series Optimized PostgreSQL)
  timescaledb:
    image: timescale/timescaledb:latest-pg15
    container_name: arth-timescaledb
    restart: always
    environment:
      POSTGRES_DB: arth
      POSTGRES_USER: arth_user
      POSTGRES_PASSWORD: arth_dev_password
    ports:
      - "5432:5432"
    volumes:
      - timescaledb_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U arth_user -d arth"]
      interval: 10s
      timeout: 5s
      retries: 5

  # Redis (Data Caching & Rate-Limiting Store)
  redis:
    image: redis:7-alpine
    container_name: arth-redis
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --save 60 1 --loglevel warning
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  timescaledb_data:
  redis_data:
```

#### 3.2.2 TimescaleDB Hypertable Mechanics
SQLAlchemy defines the time-series model. However, creating a hypertable requires executing a raw SQL statement inside PostgreSQL. This is handled via Alembic migration scripts:

```python
# Alembic migration script: upgrading prices table to hypertable
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 1. Create standard relational table
    op.create_table(
        'prices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('open', sa.Float(), nullable=False),
        sa.Column('high', sa.Float(), nullable=False),
        sa.Column('low', sa.Float(), nullable=False),
        sa.Column('close', sa.Float(), nullable=False),
        sa.Column('volume', sa.BigInteger(), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.PrimaryKeyConstraint('id', 'timestamp')  # Timestamp must be part of primary key for hypertables
    )
    
    # 2. Execute TimescaleDB native hypertable conversion partitioned by 'timestamp'
    # Chunk interval set to 7 days for historical OHLCV data
    op.execute("SELECT create_hypertable('prices', 'timestamp', chunk_time_interval => INTERVAL '7 days');")
```

---

### 3.3 Production Deployment Topography
ARTH is deployed across a decoupled multi-host architecture to stay within budget constraints while maintaining separation of concerns:

```
[Client Web Browser]
         │
         ▼ (HTTPS)
┌───────────────────────────────────────┐
│        Vercel Edge Network            │
│   - Hosts Next.js 16 SSR Frontend     │
│   - Proxies /api/v1/* to Render       │
└──────────────────┬────────────────────┘
                   │
                   ▼ (HTTPS REST / SSE Stream)
┌───────────────────────────────────────┐
│        Render Web Service             │
│   - Hosts FastAPI Uvicorn Application │
│   - Performs async logic & ML fit     │
└──────┬───────────┬────────────┬───────┘
       │           │            │
       │ (REST)    │ (TCP)      │ (Redis Protocol)
       ▼           ▼            ▼
┌────────────┐ ┌──────────┐ ┌─────────────┐
│ Groq Cloud │ │Timescale │ │ Upstash     │
│ Qwen / LLaMA│ │ Cloud DB │ │ Redis Cache │
│ API Engine │ │ (Host)   │ │ (Host)      │
└────────────┘ └──────────┘ └─────────────┘
```

---

## 4. Async Concurrency & Task Offloading

A critical interview topic is understanding the async loop vs. CPU blockages. FastAPI runs a single-threaded asynchronous event loop (based on `uvloop`). Under heavy network I/O, this is extremely efficient, but CPU-intensive mathematical calculations will block the entire process, preventing other requests from resolving.

### 4.1 Event Loop and Thread Pool Decoupling
ARTH manages concurrency by categorizing operations into I/O (async/await) and CPU/Blocking I/O (offloaded to thread pools):

```
                                [FastAPI Async Event Loop]
                                            │
                ┌───────────────────────────┴───────────────────────────┐
                ▼ (Non-Blocking I/O)                                    ▼ (Blocking Work)
         [Await Redis Cache]                                   [ThreadPoolExecutor]
         [Await Async DB Query]                                         │
         [Await Groq HTTP Stream]                       ┌───────────────┴───────────────┐
                                                        ▼ (Synchronous I/O)             ▼ (CPU Intensive)
                                                [yfinance API Fetch]            [XGBoost Train/Fit]
                                                [twelvedata REST call]          [SHAP Tree Explanations]
```

### 4.2 Code-Level Offloading Implementation
Synchronous network libraries like `yfinance` block execution while waiting for socket responses. To prevent this, ARTH wraps yfinance calls inside a reusable async-offloading helper that executes them in a background thread pool:

```python
# From app/data/adapters/base.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2)

class BaseDataAdapter:
    async def _run_sync(self, func, *args, **kwargs):
        """Offload blocking sync functions to the module-level ThreadPoolExecutor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))
```

### 4.3 Worker Architecture: ASGI vs. WSGI
* **WSGI (Flask / Django)**: Allocates one OS thread per incoming request. If the client streams a long LLM report (SSE), that thread remains occupied for the duration, leading to thread exhaustion under low concurrency.
* **ASGI (FastAPI / Uvicorn)**: Asynchronous Server Gateway Interface. Uvicorn runs an async event loop that multiplexes thousands of active connections. When a response is waiting for the next LLM chunk, the loop yields execution to handle other incoming requests, allowing high concurrent streaming capabilities.

---

## 5. Code-Level Hallucination Mitigation Strategy

LLMs are creative generators, not databases. When prompted to analyze `AAPL` or `TCS.NS`, an LLM will confidently hallucinate P/E ratios, profit margins, and historical prices. ARTH solves this by enforcing **Data Sandbox Isolation** at the open-source engine level.

### 5.1 Strict Data Flow Isolation
Under no circumstances is the LLM allowed to query the internet, access its internal weights for statistics, or generate numerical metrics. The architecture follows a strict sandwich design:

$$\text{Fetch Real Data (yfinance)} \longrightarrow \text{Construct Concrete Context} \longrightarrow \text{Strict System Prompt Constraints}$$

### 5.2 System Prompt & Formatting Implementations
The prompt system defines exact boundaries. If data is missing (e.g., yfinance returns `None` for a metric), the prompt formatting helper maps it to `"N/A"`. The LLM system instructions explicitly dictate how to treat `"N/A"`.

```python
# Excerpt from app/engines/research/prompts.py
RESEARCH_SYSTEM_PROMPT = """You are ARTH's AI Financial Research Analyst. You generate institutional-grade company research reports.

STRICT RULES:
1. Use ONLY the financial data provided in the user message. NEVER use numbers from your training data.
2. If a metric is marked "N/A", you must state that the data was unavailable. You must NOT guess or assume its value.
3. Use probabilistic language: "suggests", "likely", "approximately", "based on available data".
4. NEVER say: "will go up", "guaranteed", "certain to", "buy signal", "sell signal".
5. Every numerical claim must reference the data source (e.g., "[yfinance]").
6. End with the mandatory risk disclaimer.
"""
```

Furthermore, user prompts are constructed programmatically using typed string conversion functions, wrapping every metric in deterministic formatters:

```python
def _fmt_large_num(val) -> str:
    """Deterministic conversion of numerical metrics to prevent prompt confusion."""
    if val is None:
        return "N/A"
    val = float(val)
    if val >= 1e12:
        return f"₹{val/1e12:.2f}T"
    if val >= 1e9:
        return f"₹{val/1e9:.2f}B"
    if val >= 1e7:
        return f"₹{val/1e7:.2f}Cr"
    return f"₹{val:,.0f}"
```

---

## 6. RAG Pipeline & Document Chunking (Practical Backend View)

ARTH’s RAG pipeline is built using ChromaDB, configured in **in-memory ephemeral client mode**. Since free-tier deployments (like Render) have ephemeral disk storage, saving a persistent vector database file is futile. Instead, ARTH builds, queries, and destroys collections on demand for specific research symbols.

### 5.1 Chromadb Initialization & Memory Optimization
The vector store initialization ensures ChromaDB runs without saving data to disk, avoiding file lock issues and keeping disk footprints at 0 MB:

```python
# Excerpt from app/engines/rag/vector_store.py
class VectorStore:
    def __init__(self) -> None:
        # In-memory settings override: no disk writing
        self._client = chromadb.Client()
        logger.info("vector_store_initialized", mode="in-memory")
```

### 5.2 Chunking Mechanics
The [document_processor.py](file:///C:/Users/a4ama/.gemini/antigravity/scratch/afiip/backend/app/engines/rag/document_processor.py) collects data from yfinance. It divides the information into four distinct document templates.

1. **Company Overview Doc**: Relational summary text.
2. **Financial Metrics Doc**: Markdown lists detailing trailing P/E, EPS, profit margin, ROE, debt-to-equity, etc.
3. **Sector Context Doc**: Sector and industry peer descriptions.
4. **News Articles**: Cap at 15 news summaries.

The text splitting uses a sliding window based on word length. This prevents sentences from getting cut in half and maintains context across chunks:

```python
def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into overlapping word-based chunks."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        # Shift start point backward by overlap size to keep context intact
        start = end - overlap

    return chunks
```

### 5.3 Semantic Search & Distance Calibration
ChromaDB’s default embedding model uses L2 squared distance (Euclidean). The raw distance value is not normalized (ranges from `0.0` to `2.0+` depending on vector similarity). To present a clean confidence value on the frontend, ARTH normalizes this distance into a `0.0` to `1.0` relevance score:

$$\text{Relevance} = \max\left(0.0,\, 1.0 - \frac{\text{L2 Distance}}{2.0}\right)$$

```python
# Excerpt from app/engines/rag/vector_store.py
for text, meta, dist in zip(docs, metas, dists):
    # L2 distance range is 0 to 2 for normalized embeddings.
    # Convert to 0-1 similarity value.
    relevance = max(0.0, 1.0 - dist / 2.0)
    output.append({
        "text": text,
        "metadata": meta,
        "relevance": round(relevance, 4),
    })
```

---

## 7. XGBoost Forecasting Engine

The [prediction_model.py](file:///C:/Users/a4ama/.gemini/antigravity/scratch/afiip/backend/app/engines/prediction/model.py) implements a machine learning system to forecast stock returns over a 5-day horizon.

### 7.1 Feature Engineering Matrix
The `FeatureEngineer` constructs 15 features across 5 categories:

| Feature Name | Category | Calculation / Formula |
|---|---|---|
| `return_1d` | Price | $\frac{\text{Close}_{t} - \text{Close}_{t-1}}{\text{Close}_{t-1}}$ |
| `return_5d` | Price | $\frac{\text{Close}_{t} - \text{Close}_{t-5}}{\text{Close}_{t-5}}$ |
| `return_20d` | Price | $\frac{\text{Close}_{t} - \text{Close}_{t-20}}{\text{Close}_{t-20}}$ |
| `volatility_20d`| Price | Standard Deviation of `return_1d` over a 20-day rolling window |
| `gap` | Price | $\frac{\text{Open}_{t} - \text{Close}_{t-1}}{\text{Close}_{t-1}}$ |
| `rsi_14` | Technical | Relative Strength Index (14-day window) |
| `macd_signal` | Technical | $\text{MACD Line (EMA12 - EMA26)} - \text{Signal Line (9 EMA of MACD)}$ |
| `bb_position` | Technical | $\frac{\text{Close} - \text{Lower BB}}{\text{Upper BB} - \text{Lower BB}}$ |
| `volume_ratio_20d`| Volume | $\frac{\text{Volume}_{t}}{\text{20-day rolling mean of Volume}}$ |
| `volume_trend_5d`| Volume | Percentage change of volume over 5 days |
| `pe_ratio` | Fundamental| Trailing Price-to-Earnings ratio (Static, broadcast) |
| `pb_ratio` | Fundamental| Price-to-Book ratio (Static, broadcast) |
| `market_cap_log`| Fundamental| $\log_{10}(\text{Market Cap})$ (Normalizes huge market cap scale differences) |
| `day_of_week` | Calendar | Integer representing trading day ($0 = \text{Monday}, 4 = \text{Friday}$) |
| `month` | Calendar | Integer representing trading day month ($1 = \text{January}, 12 = \text{December}$) |

### 7.2 Target Definition
The target variable `target_5d` represents the forward return over the next 5 trading days:

$$\text{Target}_t = \frac{\text{Close}_{t+5} - \text{Close}_{t}}{\text{Close}_{t}}$$

This is shifted backward by 5 steps so that features at index $t$ align with the future outcome at $t+5$. During training, rows containing the last 5 trading days are excluded because their future target value is still unknown.

### 7.3 XGBoost Regularization & Training Mechanics
XGBoost is prone to overfitting on volatile financial time-series data. To mitigate this, ARTH applies heavy L1 and L2 regularization:

```python
# Excerpt from app/engines/prediction/model.py
model = xgb.XGBRegressor(
    n_estimators=100,
    max_depth=4,            # Shallow tree depth prevents noise fitting
    learning_rate=0.05,
    subsample=0.8,          # Row subsampling adds bagging variance reduction
    colsample_bytree=0.8,   # Feature subsampling
    reg_alpha=0.1,          # L1 regularization (lasso) forces sparse weights
    reg_lambda=1.0,         # L2 regularization (ridge) prevents weight spikes
    random_state=42,
    n_jobs=1,               # Single threaded execution to prevent Render CPU throttling
    tree_method="hist",     # Memory efficient histogram division
)
```

We split the historical data chronologically using a **walk-forward split** (Train on first 80% of dates, Validate on last 20%). A standard cross-validation split (like K-Fold) is avoided because it would leak future data into the past.

---

### 7.4 Explaining Predictions with SHAP (TreeExplainer)
SHAP (SHapley Additive exPlanations) computes Shapley values from cooperative game theory. It determines how much each feature pushes the final prediction away from the baseline average prediction.

```python
# Excerpt from app/engines/prediction/model.py
explainer = shap.TreeExplainer(model)
raw = explainer.shap_values(live_df)
```

#### The Bracket-Wrapped String Compiling Bug
During deployment, the SHAP library sometimes clashes with specific combinations of NumPy and XGBoost compiled wheels. When calculating SHAP values, it might return bracket-wrapped scientific notation strings (e.g. `"[4.1156877E-3]"` ) instead of float numbers. This causes calculations to fail. 

ARTH handles this defensively by intercepting, sanitizing, and casting every value to a float:

```python
def _to_float(v) -> float:
    """Safely convert any SHAP value to float, handling numpy/string compilation quirks."""
    if isinstance(v, (int, float)):
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
        
    # Handle bracket-wrapped strings: '[4.1156877E-3]' → 4.1156877E-3
    s = str(v).strip().strip('[]').strip()
    try:
        f = float(s)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return 0.0
```

---

### 7.5 Market Regime Detection
To provide context for the prediction, the system analyzes the last 20 trading days of the feature matrix to classify the current market regime:

```python
@staticmethod
def _detect_regime(X: pd.DataFrame) -> Dict[str, Any]:
    recent = X.iloc[-20:]
    avg_return_20d = recent["return_20d"].mean()
    avg_volatility = recent["volatility_20d"].mean()
    avg_rsi = recent["rsi_14"].mean()

    # Trending: return exceeds volatility by a factor of 2
    if abs(avg_return_20d) > 0.05 and abs(avg_return_20d) / max(avg_volatility, 0.001) > 2:
        return {"current": "trending", "description": "Strong directional trend"}

    # Reverting: RSI is at extremes and volatility is elevated
    if (avg_rsi > 70 or avg_rsi < 30) and avg_volatility > 0.015:
        return {"current": "reverting", "description": "Mean-reverting, RSI extremes"}

    # Ranging: low return and low volatility
    return {"current": "ranging", "description": "Range-bound consolidation"}
```

---

## 8. System Observability & Analysis

ARTH maintains high uptime on free-tier servers through self-healing and defensive coding practices.

### 8.1 Circuit Breaker Pattern on Yahoo Finance
Yahoo Finance throttles cloud IPs aggressively. When a request fails, yfinance can return an empty dict, cause connection timeouts, or fail with HTTP 401. To mitigate this, ARTH wraps its API requests in a **circuit breaker with exponential backoff**:

```python
# Abstract flow inside app/data/adapters/base.py
class BaseDataAdapter:
    def __init__(self):
        self._circuit_open = False
        self._failure_count = 0
        self._max_failures = 3
        self._semaphore = asyncio.Semaphore(5)  # Limit concurrent requests to 5

    async def _throttled_run_sync(self, func, *args, **kwargs):
        if self._circuit_open:
            logger.warning("circuit_breaker_open", msg="Skipping external fetch")
            raise RuntimeError("Circuit breaker is open. Source is temporarily disabled.")

        async with self._semaphore:
            for attempt in range(1, 4):
                try:
                    # Run sync yfinance call in thread pool executor
                    return await self._run_sync(func, *args, **kwargs)
                except Exception as e:
                    self._failure_count += 1
                    wait_time = (2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
                    await asyncio.sleep(wait_time)
                    
            if self._failure_count >= self._max_failures:
                self._circuit_open = True
                # Start background task to reset the circuit breaker after 5 minutes
                asyncio.create_task(self._reset_circuit_after_delay())
```

---

### 8.2 Render 512MB RAM Optimization
XGBoost and SHAP use compiled C++ code that does not release memory back to Python immediately. If multiple users request forecasts simultaneously, Render will terminate the server for exceeding its 512MB RAM limit (OOM). 

ARTH handles this through three memory-saving techniques:
1. **Tree Method Pinning**: Using `tree_method="hist"` inside XGBoost reduces the memory footprint during tree split searches.
2. **Local Single-Thread Executions**: Restricting `n_jobs=1` prevents the system from spawning child CPU processes that duplicate memory overhead.
3. **Explicit Garbage Collection**: Forcing `gc.collect()` and deleting large DataFrames immediately after training:

```python
# Inside forecast loop
y_pred_val = model.predict(X_val)
...
# Cleanup references
del model, X_train, X_val, y_train, y_val
gc.collect()  # Force reclamation of memory back to OS
```

---

### 8.3 Security Controls & Vulnerability Defenses
Production systems must protect against injection vectors and denial of service. ARTH implements the following controls:
* **Strict Input Validation**: Endpoints use Pydantic models with constrained strings (`Pattern` validation). Ticker symbols are validated against regex `^[A-Z0-9\.\^\-]{1,16}$` to prevent sql/command injection.
* **CORS Settings**: The `allowed_origins` config is parsed explicitly and registered in FastAPI `CORSMiddleware`. Broad wildcards (`*`) are disallowed.
* **Prompt Injection Defense**: When injecting user data, the metrics are formatted into key-value sections separated by structural barriers. The system prompt instructs the model to ignore any instructions found in the data fields.
* **Token Rate Limiting**: Limiters trace client requests by IP.

---

### 8.4 Observability: Trace Correlation Schema
When debugging async processes across engines, standard logs become mixed. ARTH implements a **Trace Correlation ID** middleware. On entry, every request gets a unique UUID header:

`X-Correlation-ID: arth-1780515001350`

This ID is injected into Python's ThreadLocal context and structured logger. When a log is output, the schema format is:

```json
{
  "timestamp": "2026-07-11T14:43:20.124Z",
  "level": "INFO",
  "trace_id": "arth-1780515001350",
  "event": "prediction_training_success",
  "symbol": "RELIANCE.NS",
  "samples": 482,
  "r2_score": 0.0412,
  "latency_ms": 3850,
  "memory_rss_mb": 242.5
}
```

This lets developers trace a single query's lifecycle: from the REST route controller, through yfinance adapters, to ML training and output.

---

## 9. Complete System Loops & Sequence Walkthroughs

### 9.1 API Request-Response Lifecycle
The flowchart below maps the lifecycle of an incoming API request to the backend:

```
[Incoming Request] ──> (Middlewares: Log Trace ID & CORS)
                             │
                             ▼
                   [Route Controller]
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
      [Cache Hit]                        [Cache Miss]
     (Return Redis JSON)               (Adapter Call)
                                              │
                                              ▼
                                    (Acquire Semaphore)
                                              │
                                              ▼
                                     (Circuit Open?)
                                     ├─► Yes ──► [Fallback Local Data]
                                     └─► No ───► [Execute ThreadPool Executor]
                                                        │
                                                        ▼
                                                 (External API Fetch)
                                                        │
                                                        ▼
                                                 [Data Quality Check]
                                                 (Save to Cache & return)
```

### 9.2 Directory Organization & Tree Structure
The project structure keeps concerns separated, decoupling the API layer from calculations, data adapters, and database connections.

```
arth/
├── alembic/                       # Database schema migrations
│   ├── env.py                     # Configuration for alembic runs
│   └── versions/                  # Migration history
├── backend/                       # Python FastAPI codebase
│   ├── requirements.txt           # Packages
│   └── app/
│       ├── api/                   # Router definitions
│       │   └── v1/
│       │       ├── market.py      # Quotes and historical data endpoints
│       │       ├── research.py    # AI report and RAG endpoints
│       │       └── risk.py        # Sector-aware risk calculation
│       ├── core/                  # Core modules
│       │   ├── exceptions.py      # Custom errors
│       │   └── logging.py         # Structured logging configuration
│       ├── data/                  # Storage integration
│       │   ├── adapters/          # Integrations for Yahoo and TwelveData
│       │   └── cache.py           # Redis integration
│       ├── engines/               # Application logic
│       │   ├── prediction/        # XGBoost models & SHAP explanations
│       │   ├── rag/               # ChromaDB document loading and retrieval
│       │   ├── research/          # Prompts and LLM report templates
│       │   └── risk/              # Risk evaluation rules
│       ├── llm/                   # Client setups
│       │   ├── base.py            # Async LLM client interface
│       │   └── groq_client.py     # Groq API integration
│       └── main.py                # App entrypoint and startup tasks
└── frontend/                      # React Next.js 16 codebase
    ├── src/
    │   ├── app/                   # Next.js page components
    │   │   ├── page.tsx           # Dashboard view
    │   │   ├── markets/           # Charts and search
    │   │   └── research/          # RAG research dashboard
    │   ├── components/            # Shared UI components
    │   └── lib/                   # Utilities and API fetchers
```

---

## 10. Platform Limitations & Future Production Roadmap

### 10.1 Key System Limitations
1. **Third-Party Rate Limits**: Relying on unauthenticated yfinance requests is fragile; structural changes in Yahoo's web endpoints can break parsing.
2. **On-Demand ML Latency**: Re-training models on-demand adds 3–5 seconds of latency to `/markets/[symbol]` requests.
3. **ChromaDB Rebuilding Overhead**: Re-indexing document chunks on every RAG query consumes CPU cycles.
4. **Ephemerality**: Lack of persistent disk means models must retrain, and filings must re-index, after every server restart.

### 10.2 Future Production Improvements
To transition this design from a prototype to a high-scale production system, the following roadmap is planned:

* **Background Task Offloading (Celery + Redis)**: Move XGBoost model training and RAG indexing from FastAPI request threads to distributed Celery workers.
* **Message Broker (Apache Kafka)**: Shift from polling Yahoo Finance to consuming real-time market ticks via a Kafka queue.
* **Online Feature Store (Feast)**: Compute price features (like RSI, MACD, returns) asynchronously and store them in Redis for sub-millisecond retrieval.
* **Persistent Distributed Vector DB (Qdrant / Milvus)**: Deploy a persistent vector database to store pre-embedded filings and news, removing the need to index on-the-fly.
* **Model Version Registry (MLflow)**: Store and version trained models rather than caching them as JSON on ephemeral disk.
* **Telemetry and Monitoring (Prometheus + Grafana)**: Export metrics for API latencies, CPU/RAM utilization, cache hit ratios, and model error rates.

---

## 11. Interview Q&A Cheat Sheet

### Q1: Why TimescaleDB instead of PostgreSQL?
> "TimescaleDB is a PostgreSQL extension optimized for time-series data. It automatically partitions continuous stock price records into time-based tables called **hypertables**. This speeds up historical queries because index searches only scan the relevant time chunk, rather than the entire database."

### Q2: Why Redis?
> "Financial data requests have high temporal locality—users check the same symbols repeatedly. Redis acts as our caching layer with a TTL (Time-To-Live). This decreases response latency from seconds to milliseconds and shields our external APIs from rate limits."

### Q3: Why ChromaDB?
> "We don't need a persistent knowledge base for ARTH. Every research report is generated from fresh company data and news. So we build a temporary, in-memory ChromaDB collection, query it to retrieve relevant context, and delete it once the report is compiled."

### Q4: Why not Pinecone?
> "Pinecone is a cloud-hosted vector database, which is excellent for persistent enterprise-wide RAG. In ARTH, RAG is ephemeral and session-based. Making HTTP requests to an external vector cloud would only increase latency, setup complexity, and infrastructure costs."

### Q5: Why walk-forward validation?
> "Financial time-series data is chronological. Standard random train-test splits (like K-Fold) leak future information into past training periods, creating false accuracy metrics. Walk-forward validation splits data sequentially by date, keeping the chronological order intact."

### Q6: Why XGBoost?
> "Tabular financial features are modeled better with gradient-boosted trees than deep neural networks, which require massive datasets and struggle with tabular representation. XGBoost is faster to train, works on low-cost CPUs, and is interpretable through SHAP values."

### Q7: Why SHAP?
> "Quantitative traders will not trade based on black-box predictions. SHAP (SHapley Additive exPlanations) breaks down exactly how much each feature (e.g., 20d return, RSI) contributed to the final forecast return, improving trust and auditability."

### Q8: What is your API Rate-Limiting and Observability Strategy?
> "We use FastAPI client IP limiting to prevent DDoS. We also implement a Trace Correlation ID middleware that attaches a unique ID to every request. This ID is passed to our structured JSON logger, allowing us to trace a request's journey across adapters and ML training in production."
