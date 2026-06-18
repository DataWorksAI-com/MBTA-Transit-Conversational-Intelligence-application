# agentns — Technical Reference

**Version:** 1.0.0  
**Organization:** DataWorksAI  
**License:** MIT

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Startup Sequence](#3-startup-sequence)
4. [End-to-End Flows](#4-end-to-end-flows)
   - 4.1 [Agent Registration Flow](#41-agent-registration-flow)
   - 4.2 [Resolution Flow (Cache Hit)](#42-resolution-flow-cache-hit)
   - 4.3 [Resolution Flow (Cache Miss)](#43-resolution-flow-cache-miss)
   - 4.4 [Background Health Sweep](#44-background-health-sweep)
   - 4.5 [Deregistration Flow](#45-deregistration-flow)
5. [Module Reference](#5-module-reference)
   - 5.1 [server.py](#51-serverpy--main-application)
   - 5.2 [health_checker.py](#52-health_checkerpy--health-probing)
   - 5.3 [server_selection.py](#53-server_selectionpy--ranking-engine)
   - 5.4 [cache.py](#54-cachepy--resolution-cache)
   - 5.5 [urn_parser.py](#55-urn_parserpy--urn-parsing)
   - 5.6 [client.py](#56-clientpy--python-client-sdk)
6. [Data Models](#6-data-models)
7. [Server Selection Algorithm](#7-server-selection-algorithm)
8. [Concurrency Model](#8-concurrency-model)
9. [Persistence Layer](#9-persistence-layer)
10. [Configuration Reference](#10-configuration-reference)
11. [API Reference](#11-api-reference)
12. [Error Handling](#12-error-handling)
13. [Performance Characteristics](#13-performance-characteristics)

---

## 1. System Overview

agentns is a **service discovery sidecar** for multi-agent AI systems. It solves the same problem that DNS solves for the internet — but for AI agents instead of web servers.

### The Core Problem

In a multi-agent system, orchestrators need to find and call other agents by name. Without a discovery layer, agent URLs are hardcoded. This breaks when:
- Agents scale horizontally (multiple replicas)
- Agents move between hosts or clouds
- An agent goes down and a replica must take over
- Geographic routing is needed (nearest healthy replica)

### What agentns Does

agentns runs as a **sidecar process** alongside your orchestrator. Agents register themselves with the sidecar on startup. Orchestrators ask the sidecar "where is the emailer agent?" and receive back the best available endpoint — selected by health, geographic distance, protocol compatibility, and measured latency.

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Zero hardcoded values** | Every IP, URL, and name comes from environment variables |
| **Language-agnostic** | Plain HTTP API — Python, Go, Node.js, Java, curl all work |
| **Graceful degradation** | Never crashes the caller — returns emergency fallback if all replicas unhealthy |
| **No single point of failure** | In-memory mode works without MongoDB; MongoDB mode survives restarts |
| **Self-healing** | Background health loop continuously re-evaluates endpoints, auto-recovers when agents come back |

---

## 2. Architecture

### Component Map

```
┌──────────────────────────────────────────────────────────────┐
│                      agentns Process                          │
│                                                              │
│  ┌──────────────┐    ┌─────────────────────────────────┐    │
│  │  FastAPI app  │    │         Global State             │    │
│  │  (server.py) │    │                                  │    │
│  │              │    │  _registry: Dict[label, [ep,...]]│    │
│  │  POST /resolve│    │  _health_cache: Dict[url, dict] │    │
│  │  POST /register│   │  _cache: ResolutionCache        │    │
│  │  DELETE /...  │    │  _mongo_col: Collection | None  │    │
│  │  GET /health  │    └─────────────────────────────────┘    │
│  │  GET /agents  │                                           │
│  └──────┬───────┘                                           │
│         │ calls                                              │
│  ┌──────▼───────────────────────────────────────────────┐   │
│  │              Core Modules                             │   │
│  │                                                       │   │
│  │  urn_parser.py      → parse / build URNs              │   │
│  │  health_checker.py  → async HTTP health probes        │   │
│  │  server_selection.py→ rank endpoints by 5-key sort    │   │
│  │  cache.py           → TTL resolution cache            │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │           Background asyncio Task                     │   │
│  │   _health_loop() — runs every HEALTH_INTERVAL seconds │   │
│  │   → _check_all() → parallel health probes            │   │
│  │   → _cache.purge_expired()                           │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐   │
│  │           MongoDB (optional)                          │   │
│  │   Collection: agentns.agents                         │   │
│  │   Indexes: label, (label + endpoint) unique          │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
         ▲                          ▲
         │ POST /register           │ POST /resolve
         │                          │
   ┌─────┴──────┐            ┌──────┴──────┐
   │   Agent    │            │ Orchestrator │
   │ (any lang) │            │  (any lang)  │
   └────────────┘            └─────────────┘
```

### Module Dependency Graph

```
server.py
   ├── urn_parser.py       (parse_urn, build_urn, extract_label)
   ├── health_checker.py   (check_agent_health, probe_endpoint)
   ├── server_selection.py (rank_servers, select_protocol, calculate_ttl)
   └── cache.py            (ResolutionCache)

client.py                  (standalone — calls server.py via HTTP only)
```

### What "Single Binary" Means

Traditional ANS architectures use three separate networked hops:

```
Traditional:  Orchestrator → Recursive Resolver → Registry NS → Auth NS
agentns:      Orchestrator → agentns (all three hops in one process)
```

agentns collapses all three into one in-process function call chain, eliminating the network overhead of the middle hops while keeping the same logical resolution model.

---

## 3. Startup Sequence

When agentns starts (`agentns-server` or `docker run`), the following steps execute in strict order before any HTTP request is accepted:

```
Process starts
     │
     ▼
main() in server.py
  └─ parse CLI args (--port, --host, --namespace, --log-level)
  └─ uvicorn.run("agentns.server:app", ...)
         │
         ▼
     FastAPI lifespan() begins (asynccontextmanager)
         │
         ├─ Step 1: _init_mongo()
         │     If MONGODB_URI is set:
         │       - Create AsyncIOMotorClient with 6s selection timeout
         │       - Get database[MONGODB_DB]
         │       - Get collection "agents"
         │       - Create index on "label"
         │       - Create unique compound index on (label, endpoint)
         │       - Ping MongoDB to verify connection
         │       - Set _mongo_col = collection handle
         │     If MONGODB_URI is empty:
         │       - Log warning, leave _mongo_col = None
         │       - Continue in in-memory mode
         │
         ├─ Step 2: _load_from_mongo()
         │     If _mongo_col is not None:
         │       - Stream all documents from the collection
         │       - For each doc: extract label + endpoint fields
         │       - Append to _registry if endpoint not already present
         │       - (Prevents duplicates if same endpoint registered twice)
         │
         ├─ Step 3: _check_all()  ← initial health sweep
         │     - Build set of unique (endpoint_url, health_check_url) pairs
         │       from all entries in _registry
         │     - asyncio.gather() all health probes in parallel
         │     - Write results into _health_cache
         │     - This ensures the FIRST /resolve call has real health data
         │       and does not return "unknown" for every endpoint
         │
         ├─ Step 4: asyncio.create_task(_health_loop())
         │     - Spawns the background health sweep coroutine
         │     - Does not block startup — runs concurrently
         │
         ├─ Log: "agentns ready — N endpoint(s) across M label(s) | port P"
         │
         └─ yield  ← server begins accepting HTTP requests
```

**Shutdown** (Ctrl+C or SIGTERM):
```
lifespan resumes after yield
  └─ task.cancel()           ← signals _health_loop to stop
  └─ await task              ← waits for clean cancellation
  └─ except CancelledError   ← expected, suppressed
```

---

## 4. End-to-End Flows

### 4.1 Agent Registration Flow

An agent calls `POST /register` on startup. Here is what happens step by step:

```
Agent process                agentns server
─────────────                ─────────────
POST /register
{
  "label": "emailer",
  "endpoint": "http://ny-host:9001",
  "region": "us-east",
  "location": {"city": "New York"},
  "protocols": ["http", "A2A"],
  "health_check_url": "http://ny-host:9001/health"
}
                         ─────────────────────────►

                              1. Validate input
                                 - label and endpoint required
                                 - HTTP 400 if missing

                              2. Normalize location
                                 - city "New York" looked up in CITY_COORDS
                                 - lat/lon (40.7128, -74.0060) injected
                                 - Enables geo-routing without caller knowing coords

                              3. Build URN
                                 build_urn(DEFAULT_TLD, namespace, label)
                                 → "urn:agentns.local:agents.local:emailer"

                              4. Build entry dict
                                 {endpoint, health_check_url, namespace,
                                  protocols, region, region_label, flag,
                                  location, agent_name}

                              5. Check _registry[label]
                                 If endpoint already exists → update in place
                                 If endpoint is new → append to list
                                 (multiple endpoints = replica pool)

                              6. _save_to_mongo(label, entry)
                                 MongoDB upsert:
                                   filter: {label, endpoint}
                                   $set: all fields + last_seen = now
                                   $setOnInsert: registered_at = now
                                 (no-op if MongoDB not configured)

                              7. asyncio.create_task(_check_single(...))
                                 Fires a non-blocking background health check
                                 Result written to _health_cache immediately
                                 Next /resolve call will have fresh data

                         ◄─────────────────────────
                              {
                                "status": "registered",
                                "label": "emailer",
                                "endpoint": "http://ny-host:9001",
                                "agent_name": "urn:agentns.local:agents.local:emailer",
                                "total_endpoints": 1
                              }
```

**Key behavior:** If the same `(label, endpoint)` pair is registered again, the existing entry is **updated** (not duplicated). If a new `endpoint` is registered under the same `label`, it is **appended** to the pool — creating a replica group. This is how multi-region failover is achieved.

---

### 4.2 Resolution Flow (Cache Hit)

The fast path — a repeat resolution within the TTL window:

```
Orchestrator                 agentns server
────────────                 ─────────────
POST /resolve
{
  "agent_name": "urn:agentns.local:agents.local:emailer",
  "requester_context": {
    "location": {"city": "Boston"},
    "protocols": ["A2A", "http"]
  }
}
                         ─────────────────────────►

                              1. Parse identifier
                                 parse_urn("urn:agentns.local:agents.local:emailer")
                                 → ParsedURN(tld=..., namespace=..., label="emailer")

                              2. Build cache key
                                 MD5("emailer" | ["A2A","http"] | {"city":"Boston"})
                                 → "a3f2c1..." (deterministic hex digest)

                              3. _cache.get(key)
                                 → entry found AND monotonic() < expiry
                                 → hits counter incremented
                                 → cached payload returned

                              4. Inject resolution_time_ms
                                 Set cached=True on payload

                         ◄─────────────────────────
                              {
                                "endpoint": "http://ny-host:9001",
                                "protocol": "A2A",
                                "ttl": 60,
                                "cached": true,
                                "resolution_time_ms": 0.3,
                                ...
                              }
```

Cache hit round-trip: **< 1 ms** (in-process dict lookup + MD5).

---

### 4.3 Resolution Flow (Cache Miss)

The full resolution path — first call or after TTL expiry:

```
Orchestrator                 agentns server
────────────                 ─────────────
POST /resolve
{
  "agent_name": "urn:...:emailer",
  "requester_context": {
    "location": {"city": "Paris"},
    "protocols": ["A2A"]
  }
}
                         ─────────────────────────►

                              1. Parse URN → label = "emailer"

                              2. Cache miss (key not found or expired)

                              3. Registry lookup
                                 endpoints = _registry["emailer"]
                                 → [nyc_entry, london_entry]
                                 HTTP 404 if label not registered

                              4. Build servers list
                                 For each endpoint entry, create server dict
                                 with server_id, protocols, region, location

                              5. Read health from _health_cache
                                 health_map = {
                                   "http://ny-host:9001": {status:"healthy", latency:45ms},
                                   "http://lon-host:9001": {status:"healthy", latency:210ms}
                                 }

                              6. Live-check unchecked endpoints
                                 Any server where status == "unknown" (not yet in cache):
                                 → parallel check_agent_health() calls
                                 → updates _health_cache and health_map in place

                              7. rank_servers(servers, health_map, requester_context)
                                 For each server, compute sort key:
                                   (health_score, protocol_score, geo_km, latency_ms, load)
                                 
                                 Requester is in Paris (48.8566°N, 2.3522°E)
                                 
                                 NYC:    geo = haversine(Paris, NYC) = 5837 km
                                 London: geo = haversine(Paris, London) = 341 km
                                 
                                 Sort keys:
                                   NYC:    (0, 0, 5837, 45.0,  30.0)
                                   London: (0, 0,  341, 210.0, 20.0)
                                 
                                 London wins (lower geo distance)
                                 ranked = [(london_server, london_health), (nyc_server, nyc_health)]

                              8. Determine selected_by
                                 len(ranked) > 1 AND location provided
                                 → selected_by = "geo_nearest"

                              9. select_protocol(["http","A2A"], ["A2A"])
                                 → "A2A" (first preferred that server supports)

                              10. calculate_ttl({status:"healthy"})
                                  → 60 seconds

                              11. Build result dict
                                  + tag with _cache_key_agent = "emailer"

                              12. _cache.set(key, result, ttl=60)
                                  Store in cache with 60s expiry

                              13. Pop _cache_key_agent from result

                              14. Log:
                                  "Resolved 'emailer': http://lon-host:9001
                                   (210ms, ttl=60s, by=geo_nearest)"

                         ◄─────────────────────────
                              {
                                "endpoint": "http://lon-host:9001",
                                "protocol": "A2A",
                                "ttl": 60,
                                "region": "London, UK",
                                "flag": "🇬🇧",
                                "cached": false,
                                "selected_by": "geo_nearest",
                                "resolution_time_ms": 3.7,
                                "metadata": {
                                  "label": "emailer",
                                  "latency_ms": 210.0,
                                  "total_candidates": 2,
                                  "all_candidates": [
                                    {"endpoint":"http://lon-host:9001","status":"healthy","latency_ms":210},
                                    {"endpoint":"http://ny-host:9001","status":"healthy","latency_ms":45}
                                  ]
                                }
                              }
```

---

### 4.4 Background Health Sweep

This loop runs concurrently with all HTTP requests. It is the core of automatic failover and recovery:

```
asyncio event loop
      │
      ├─ (HTTP requests served here)
      │
      └─ _health_loop() [background task]
              │
              ├─ loop forever:
              │
              │   _check_all()
              │     │
              │     ├─ Build deduped map of {endpoint_url → health_check_url}
              │     │   from all entries in _registry
              │     │   (dedup because same endpoint may appear under multiple labels)
              │     │
              │     ├─ asyncio.gather(*[_check_one(url, hc_url) for each])
              │     │     └─ Each _check_one():
              │     │           check_agent_health(hc_url)  ← HTTP GET
              │     │           async with _health_lock:
              │     │             _health_cache[endpoint_url] = result
              │     │
              │     │   All probes run in parallel (asyncio, not threads)
              │     │   gather(return_exceptions=True) so one failure
              │     │   doesn't cancel the rest
              │     │
              │     └─ debug log: "Health sweep: N endpoint(s) checked"
              │
              │   _cache.purge_expired()
              │     └─ Remove entries where monotonic() > expiry
              │         (prevents unbounded cache growth)
              │
              └─ asyncio.sleep(HEALTH_INTERVAL)  ← default 30s
```

**Failover scenario:**
1. `emailer-nyc` endpoint goes down between sweeps
2. At next sweep (~30s): `check_agent_health` returns `{status: "unhealthy"}`
3. `_health_cache["http://nyc:9001"] = {status: "unhealthy", ...}`
4. Next `/resolve` call: `rank_servers()` sees nyc=unhealthy, excludes it
5. London endpoint selected automatically — no configuration change

**Recovery scenario:**
1. `emailer-nyc` comes back up
2. At next sweep: `check_agent_health` returns `{status: "healthy", latency: 45ms}`
3. `_health_cache` updated
4. Next `/resolve` call: both endpoints healthy, NYC wins on latency (45ms vs 210ms)

---

### 4.5 Deregistration Flow

```
Agent shutting down          agentns server
───────────────              ─────────────
DELETE /register/emailer
{"endpoint": "http://ny-host:9001"}
                         ─────────────────────────►

                              1. Check label in _registry
                                 HTTP 404 if not found

                              2. endpoint provided → remove specific entry
                                 _registry["emailer"] filtered to exclude nyc
                                 If list becomes empty → delete key entirely

                                 No endpoint → remove all endpoints for label
                                 _registry.pop("emailer")

                              3. MongoDB cleanup
                                 delete_one({label, endpoint})  ← specific
                                 delete_many({label})           ← all

                         ◄─────────────────────────
                              {
                                "status": "deregistered",
                                "label": "emailer",
                                "removed": 1
                              }
```

---

## 5. Module Reference

### 5.1 `server.py` — Main Application

**File:** `agentns/server.py`  
**Purpose:** FastAPI application. Owns all HTTP endpoints, global state, startup/shutdown, MongoDB integration, and the background health loop.

#### Global State

```python
_registry: Dict[str, List[Dict]]
```
The primary data structure. Maps every registered `label` to a list of endpoint dicts. One label can have many endpoints (replica pool). Updated by `register()` and `deregister()`. Read by `resolve()`.

```python
_health_cache: Dict[str, Dict]
```
Maps every `http_endpoint` URL to its most recent health result dict. Written exclusively by `_check_all()`, `_check_single()`, and the live-check block inside `resolve()`. Protected by `_health_lock`. Read by `_cached_health()`.

```python
_health_lock: asyncio.Lock
```
Prevents concurrent writes to `_health_cache` from the background loop and from on-demand checks inside `resolve()`.

```python
_cache: ResolutionCache
```
Singleton instance of the TTL resolution cache. Holds fully-resolved response payloads keyed by MD5 of (label + protocols + location).

```python
_mongo_col: Optional[AsyncIOMotorCollection]
```
Handle to the MongoDB `agents` collection. `None` if MongoDB is not configured or the connection failed. All MongoDB operations are guarded by `if _mongo_col is None: return`.

---

#### `_init_mongo() → None` (async)

**Called by:** `lifespan()` at startup  
**Purpose:** Establishes MongoDB connection and creates indexes.

Procedure:
1. Checks `MONGODB_URI` env var. Returns immediately if empty.
2. Creates `AsyncIOMotorClient` with a 6-second server selection timeout (prevents hanging startup if MongoDB is unreachable).
3. Gets the database and `agents` collection.
4. Creates two indexes:
   - Single-field index on `label` — fast lookups by agent name
   - Unique compound index on `(label, endpoint)` — prevents duplicate registrations, enables upsert semantics
5. Pings the admin endpoint to verify connectivity.
6. Sets `_mongo_col` globally.

On any exception: logs the error and sets `_mongo_col = None`. The server continues in in-memory mode — MongoDB failure never prevents startup.

---

#### `_load_from_mongo() → None` (async)

**Called by:** `lifespan()` at startup, after `_init_mongo()`  
**Purpose:** Restores the `_registry` from MongoDB so that dynamically registered agents (registered in a previous process run) survive restarts.

Procedure:
1. If `_mongo_col is None`, returns immediately.
2. Streams all documents from the collection with `find({})`.
3. For each document, extracts `label` and removes MongoDB internal fields (`_id`).
4. Checks whether the endpoint already exists in `_registry[label]` (guarded to prevent duplicates if static agents and MongoDB have overlapping entries).
5. Appends new entries.

**Why this matters:** Without this function, every restart loses all dynamically registered agents (e.g. geo-replica agents registered by remote processes). With it, the registry is restored to its pre-restart state within the first seconds of startup.

---

#### `_save_to_mongo(label, entry) → None` (async)

**Called by:** `register()` after every successful registration  
**Purpose:** Persists a single endpoint entry to MongoDB.

Procedure:
1. Copies the `entry` dict (avoids mutating the in-memory copy).
2. Adds `label` field to the MongoDB document.
3. Performs an **upsert** using `update_one()`:
   - Filter: `{label, endpoint}` — the unique identity of this registration
   - `$set`: all fields + `last_seen = now` (updated on every re-registration)
   - `$setOnInsert`: `registered_at = now` (only set when a new document is created)
4. The upsert ensures idempotency — re-registering the same endpoint updates metadata without creating duplicates.

---

#### `_check_all() → None` (async)

**Called by:** `lifespan()` (once at startup), `_health_loop()` (every N seconds)  
**Purpose:** Parallel health probe of every unique registered endpoint.

Procedure:
1. Iterates `_registry` to build a deduped dict `{endpoint_url: health_check_url}`.
   - Deduplication is important: if "emailer-nyc" and "invoicer-nyc" share the same host, only one probe is sent.
2. If the dict is empty (no registered agents), returns early.
3. Defines inner coroutine `_check_one(endpoint_url, hc_url)`:
   - If `hc_url` is set: calls `check_agent_health(hc_url)`
   - If empty: calls `probe_endpoint(endpoint_url)` (auto-discovery)
   - Acquires `_health_lock` and writes result to `_health_cache`
4. Runs all `_check_one` coroutines concurrently via `asyncio.gather(..., return_exceptions=True)`.
   - `return_exceptions=True` is critical: a timeout or connection error in one probe does not cancel the rest.

---

#### `_health_loop() → None` (async)

**Called by:** `lifespan()` via `asyncio.create_task()`  
**Purpose:** Infinite loop that periodically checks all endpoints and purges the resolution cache.

```
while True:
    _check_all()          ← probe every endpoint
    _cache.purge_expired() ← evict stale cache entries
    asyncio.sleep(HEALTH_INTERVAL)
```

The loop is wrapped in `try/except` so a single loop iteration error (e.g. a transient network error during gather) logs a warning but does not terminate the loop.

The loop is cancelled cleanly during shutdown via `task.cancel()` + `await task` in `lifespan()`.

---

#### `_cached_health(endpoint_url) → Dict`

**Called by:** `resolve()`, `health()`, `list_agents()`  
**Purpose:** Safe read from `_health_cache` with a default sentinel.

Returns the stored health dict if present, or a default dict with `status="unknown"` if the endpoint has never been probed. This prevents KeyError and ensures `rank_servers()` always receives a valid health dict.

The "unknown" default causes `rank_servers()` to assign `health_score=2` (between degraded and unhealthy), which means never-probed endpoints are ranked lower than healthy endpoints but higher than unhealthy ones.

---

#### `_check_single(endpoint_url, hc_url) → None` (async)

**Called by:** `register()` via `asyncio.create_task()`  
**Purpose:** One-shot health probe for a freshly registered endpoint.

Immediately probes the newly registered endpoint so that the first `/resolve` call after registration has real health data rather than the "unknown" sentinel. This is non-blocking (fired as a background task) so the `/register` response is not delayed.

---

#### `lifespan(application) → AsyncContextManager`

**FastAPI lifespan context manager.**  
Everything before `yield` runs at startup; everything after runs at shutdown.

```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    await _init_mongo()          # Step 1: connect to MongoDB
    await _load_from_mongo()     # Step 2: restore registry
    await _check_all()           # Step 3: initial health sweep
    task = asyncio.create_task(_health_loop())  # Step 4: start background loop
    yield                        # ← server is running
    task.cancel()                # Step 5: cancel loop
    await task                   # Step 6: wait for clean exit
```

---

#### `POST /resolve` — `resolve(body)`

The primary API endpoint. Full logic:

1. **Identifier parsing** — Accepts `agent_name` (URN), `urn`, `agent`, or `label` fields. Priority: URN fields first, plain label second. URN is parsed by `parse_urn()` to extract the `label`.
2. **Cache key** — `_cache.make_key(label, requester_context)` → MD5 hex string.
3. **Cache check** — `await _cache.get(key)`. If hit: inject `resolution_time_ms`, set `cached=True`, return immediately.
4. **Registry lookup** — `_registry.get(label)`. HTTP 404 if label unknown.
5. **Server list construction** — Flatten endpoint dicts into a normalized `servers` list with consistent keys (`server_id`, `endpoint`, `health_check_url`, `protocols`, `region`, `region_label`, `flag`, `location`).
6. **Health map population** — `_cached_health()` for each server. Identifies any server with `status="unknown"` (never probed).
7. **Live check for unchecked** — If any server is "unknown", runs `check_agent_health()` (with explicit URL) or `probe_endpoint()` (auto-discover) inline. Parallel via `asyncio.gather()`. Updates both `_health_cache` and the local `health_map`.
8. **Ranking** — `rank_servers(servers, health_map, requester_context)`. Returns sorted list, unhealthy excluded.
9. **Emergency fallback** — If `ranked` is empty (all endpoints unhealthy): returns first server with TTL=5, `selected_by="emergency_fallback"`. Never raises a 503.
10. **Winner extraction** — `ranked[0]` is `(best_server, best_health)`.
11. **Protocol selection** — `select_protocol(best_server["protocols"], preferred_protocols)`.
12. **TTL calculation** — `calculate_ttl(best_health)`.
13. **`selected_by` determination** — `"only_available"` if one healthy server, `"geo_nearest"` if location provided, `"lowest_latency"` otherwise.
14. **Cache store** — `_cache.set(key, result, ttl)`.
15. **Return** — Full result dict.

---

#### `POST /register` — `register(body)`

1. Validates `label` and `endpoint` (HTTP 400 if missing).
2. Applies defaults: `namespace=DEFAULT_NS`, `protocols=["http"]`.
3. **City normalization**: if `location.city` is provided without coordinates, looks up `CITY_COORDS[city]` and injects `latitude`/`longitude`. Enables geo-routing without the caller knowing exact coordinates.
4. Builds `entry` dict including the constructed `agent_name` URN.
5. Checks for existing entry in `_registry[label]`:
   - If found: updates in place (all fields overwritten)
   - If new: appends (creating a new replica in the pool)
6. Calls `_save_to_mongo()` to persist.
7. Fires `_check_single()` as a background task.
8. Returns `{status, label, endpoint, agent_name, total_endpoints}`.

---

#### `DELETE /register/{label}` — `deregister(label, body)`

1. HTTP 404 if label not in `_registry`.
2. If `body.endpoint` provided: removes that specific endpoint from the list. If list becomes empty, deletes the label key entirely.
3. If no `endpoint`: removes all endpoints for the label (`_registry.pop`).
4. Calls `delete_one` or `delete_many` on MongoDB accordingly.
5. Returns `{status, label, removed}`.

---

#### `GET /health` — `health()`

Reads `_registry` and `_health_cache` (via `_cached_health`) to build a per-agent, per-endpoint status report. Determines overall status: `"ok"` if no endpoint is unhealthy, `"degraded"` otherwise. Returns service metadata (version, MongoDB connection status, uptime, total counts).

---

#### `GET /agents` — `list_agents()`

Returns the full registry with current health status for every endpoint. Includes `agent_name` (URN), `namespace`, `protocols`, and `last_check` timestamp. Designed for UI dashboards and debugging.

---

#### `GET /namespaces` — `namespaces()`

Groups all labels by their registered namespace. Returns `{tld, namespaces: {namespace: [label, ...]}}`. Useful for namespace-level browsing.

---

#### `GET /cache/stats` — `cache_stats()`

Delegates to `_cache.stats()`. Returns hit/miss counts, hit rate, active vs expired entries.

---

#### `POST /cache/clear` — `cache_clear()`

Delegates to `_cache.clear()`. Flushes all cached resolutions. Useful after a bulk re-registration event.

---

#### `main() → None`

CLI entry point invoked by `agentns-server` command or `python -m agentns`.

1. Parses CLI arguments: `--port`, `--host`, `--log-level`, `--namespace`.
2. If `--namespace` differs from default, sets the env var so the FastAPI app picks it up.
3. Prints startup banner with config summary.
4. Calls `uvicorn.run("agentns.server:app", ...)`.

---

### 5.2 `health_checker.py` — Health Probing

**File:** `agentns/health_checker.py`  
**Purpose:** Async HTTP health checking. Probes agent endpoints and returns a normalized health dict.

#### Module-Level Constants

```python
CONNECT_TIMEOUT = 5.0   # seconds to establish TCP connection
READ_TIMEOUT    = 5.0   # seconds to read response body
SLOW_MS         = 2000  # milliseconds above which status → "degraded"
```

---

#### `_get_client() → httpx.AsyncClient`

Returns a shared singleton `httpx.AsyncClient`. Lazily created on first call. Recreated if the client has been closed.

The client is configured with:
- **Connection pool**: up to 100 concurrent connections, 20 keepalive
- **Redirects**: followed automatically
- **Timeouts**: separate connect, read, write, and pool timeouts

Using a singleton client (rather than creating a new one per check) is important for performance — it allows connection reuse and avoids the overhead of creating a new TLS session for every probe.

---

#### `_now_iso() → str`

Returns the current UTC time as an ISO-8601 string. Used to populate `last_check` in every health result.

---

#### `_unhealthy(reason="") → Dict`

Factory function that returns a standardized "unhealthy" result dict:
```python
{
    "status":           "unhealthy",
    "load":             100.0,    # max load — worst case for ranking
    "response_time_ms": 0.0,
    "last_check":       "<now>",
    "reason":           "<reason string>"
}
```
`load=100.0` ensures unhealthy servers sort to the end even on the load tiebreaker.

---

#### `check_agent_health(health_url) → Dict` (async)

The primary health probe function. Given a full URL:

1. Gets the shared httpx client.
2. Records `t0 = time.perf_counter()`.
3. Issues `GET health_url`.
4. Calculates `elapsed = (perf_counter() - t0) * 1000` (milliseconds).
5. If response status >= 400 → returns `_unhealthy(f"HTTP {status_code}")`.
6. Attempts to parse JSON body and extract `load_percent` or `load` field.
   - If JSON parsing fails (e.g. HTML response) → silently defaults to `load=50.0`
7. Determines status:
   - `load >= 90` OR `elapsed > SLOW_MS` → `"degraded"`
   - Otherwise → `"healthy"`
8. Returns `{status, load, response_time_ms, last_check}`.

Exception handling:
- `httpx.ConnectError` → `_unhealthy("connection refused")`
- `httpx.TimeoutException` → `_unhealthy("timeout")`
- Any other exception → `_unhealthy(str(exc)[:80])` (truncated to prevent huge log messages)

---

#### `probe_endpoint(endpoint) → Dict` (async)

Auto-discovery function. Tries three standard health URLs in order:
1. `{endpoint}/.well-known/agent.json` — A2A AgentCard standard
2. `{endpoint}/health` — REST convention
3. `{endpoint}/healthz` — Kubernetes convention

Returns the first non-unhealthy result. If all three fail, returns `_unhealthy("all probe URLs failed")`.

This function is called when an endpoint was registered without a `health_check_url`, or when a never-seen endpoint needs immediate checking during resolution.

---

### 5.3 `server_selection.py` — Ranking Engine

**File:** `agentns/server_selection.py`  
**Purpose:** Pure functions for ranking a pool of endpoints. No I/O, no state. Deterministic given the same inputs.

#### `CITY_COORDS: Dict[str, Tuple[float, float]]`

A lookup table mapping lowercase city name strings to `(latitude, longitude)` tuples. Covers 60+ cities across North America, Europe, Asia-Pacific, and South America.

Used by:
- `_resolve_location()` — to convert a requester's city name to coordinates
- `register()` in server.py — to inject coordinates when an agent registers with just a city name

---

#### `_haversine(lat1, lon1, lat2, lon2) → float`

Computes the great-circle distance in kilometres between two lat/lon points.

Formula:
```
a = sin²(Δlat/2) + cos(lat1) · cos(lat2) · sin²(Δlon/2)
distance = 2 · R · arcsin(√a)
```
Where `R = 6371.0 km` (Earth's mean radius).

This is the standard Haversine formula — accurate for distances up to 20,000 km, with error < 0.5%.

Example outputs:
- Boston → New York: ~306 km
- Boston → London: ~5,263 km
- Paris → Frankfurt: ~448 km

---

#### `_resolve_location(ctx) → Optional[Tuple[float, float]]`

Extracts a `(latitude, longitude)` pair from the `requester_context` dict.

Accepts three input forms:
```python
{"location": {"latitude": 48.8, "longitude": 2.35}}   # explicit coords
{"location": {"city": "Paris"}}                        # city lookup
{"city": "Paris"}                                      # flat form
```

Also accepts field aliases: `lat`/`lon`/`lng` in addition to `latitude`/`longitude`.

Returns `None` if no location can be extracted (triggers `math.inf` geo distance in ranking, falling through to latency-based selection).

---

#### `_health_score(status) → int`

Maps health status string to a numeric sort score:

| Status | Score |
|--------|-------|
| `"healthy"` | 0 |
| `"degraded"` | 1 |
| `"unknown"` | 2 |
| `"unhealthy"` | 3 |

Any unrecognized status defaults to 2 (unknown). Lower is better in the sort.

---

#### `_geo_distance(server, requester_latlon) → float`

Computes the haversine distance between a server's `location` dict and the requester's `(lat, lon)` tuple.

Returns `math.inf` if:
- `requester_latlon` is `None` (no location provided)
- The server's `location` dict has no coordinates

`math.inf` causes geo distance to not be a deciding factor — the sort falls through to `response_time_ms`.

---

#### `rank_servers(servers, health_map, requester_context, include_unhealthy=False) → List[Tuple]`

The core ranking function. Returns `[(server_dict, health_dict), ...]` sorted best-first.

**Algorithm for each server:**

```python
sort_key = (
    _health_score(status),          # 0=healthy → 3=unhealthy
    proto_score,                    # 0=preferred protocol available, 1=not
    _geo_distance(server, latlon),  # km, inf if no location
    health.get("response_time_ms"), # ms, 9999 if unknown
    health.get("load"),             # 0–100%
)
```

- If `status == "unhealthy"` and `include_unhealthy=False` (default): skip this server entirely. It won't appear in the result.
- All remaining servers are appended to `scored` list with their key tuple.
- `scored.sort(key=lambda x: x[0])` — Python's tuple comparison is lexicographic: the first differing element decides. Only when health scores are equal does protocol matter; only when protocol scores are equal does geo matter; and so on.

Returns `[(server, health)]` pairs stripped of the sort key.

---

#### `select_protocol(server_protocols, preferred) → str`

Iterates through `preferred` in order, returns the first one that exists in `server_protocols` (case-insensitive comparison via `.upper()`).

Falls back to `server_protocols[0]` if no preferred protocol is available. Falls back to `"http"` if `server_protocols` is empty.

---

#### `calculate_ttl(health) → int`

Returns a TTL in seconds based on health status. The logic is conservative:

| Status | TTL | Rationale |
|--------|-----|-----------|
| `healthy` | 60s | Stable — no need to recheck frequently |
| `degraded` | 15s | Unstable — recheck soon in case it recovers |
| `unknown` | 10s | No data — recheck quickly |
| `unhealthy` | 5s | Last resort — recheck almost immediately |

A TTL of 60s means the orchestrator can call the same agent label 60 times per minute and get sub-millisecond responses (all from cache). At second 61, the cache expires and a fresh resolution runs.

---

### 5.4 `cache.py` — Resolution Cache

**File:** `agentns/cache.py`  
**Purpose:** Thread-safe (asyncio-safe), TTL-based in-memory cache for resolved agent responses.

#### `ResolutionCache` class

Internal state:
```python
_store: Dict[str, Tuple[Any, float]]  # key → (payload, expiry_monotonic)
_lock:  asyncio.Lock                  # serializes all mutations
_hits:  int                           # hit counter (for stats)
_misses: int                          # miss counter
```

---

#### `make_key(agent_name, requester_context) → str`

Generates a deterministic cache key as an MD5 hex digest.

Key inputs:
1. `agent_name` (label string)
2. `sorted(protocols)` — sorted to ensure `["A2A", "http"]` and `["http", "A2A"]` produce the same key
3. `json.dumps(location, sort_keys=True)` — sorted JSON to ensure `{"city":"Boston"}` is always the same string

Raw input example:
```
"emailer|['A2A', 'http']|{"city": "Boston"}"
```
Digest: `MD5(raw).hexdigest()` → `"a3f2c1d8..."`

MD5 is used here for speed (not security). The key space is collision-resistant enough for this use case.

---

#### `get(key) → Optional[Any]` (async)

1. Acquires `_lock`.
2. Looks up `key` in `_store`.
3. If not found: increments `_misses`, returns `None`.
4. If found: checks `time.monotonic() > expiry`.
   - If expired: deletes entry, increments `_misses`, returns `None`.
   - If valid: increments `_hits`, returns `payload`.

`time.monotonic()` is used (not `time.time()`) because it is guaranteed to never go backwards — wall clock changes (NTP, DST) cannot cause cache entries to appear unexpired or prematurely expired.

---

#### `set(key, payload, ttl) → None` (async)

1. Acquires `_lock`.
2. Stores `(payload, time.monotonic() + ttl)` at `key`.

Overwrites any existing entry for the same key. No max-size limit — the `purge_expired()` call in `_health_loop()` is the only eviction mechanism. This is acceptable because the number of distinct (label + context) combinations in a typical system is bounded.

---

#### `invalidate(agent_name) → int` (async)

Removes cache entries tagged with `_cache_key_agent == agent_name`. Used when an agent is deregistered to ensure stale resolutions are not served.

Note: because cache keys are MD5 hashes, they cannot be reverse-looked-up. The `_cache_key_agent` tag (added transiently to the payload before storage) enables reverse lookup.

---

#### `clear() → int` (async)

Wipes the entire store, resets hit/miss counters, returns the number of entries removed.

---

#### `stats() → Dict` (async)

Reads `_store`, `_hits`, `_misses` under lock. Computes:
- `active_entries` — entries where `monotonic() < expiry`
- `expired_entries` — entries past their TTL that haven't been purged yet
- `hit_rate_pct` — `hits / (hits + misses) * 100`

---

#### `purge_expired() → int` (async)

Scans the store for expired entries and deletes them. Called by `_health_loop()` every `HEALTH_INTERVAL` seconds to prevent unbounded memory growth. Returns count of entries removed.

---

### 5.5 `urn_parser.py` — URN Parsing

**File:** `agentns/urn_parser.py`  
**Purpose:** Parse, build, and validate Agent URNs. No I/O, no dependencies beyond the standard library.

#### URN Format

```
urn : <tld> : <namespace> : <label>

urn:acme.com:sales:emailer
 │       │       │       └── label     — agent role
 │       │       └────────── namespace — application/org grouping
 │       └────────────────── tld       — top-level domain (like DNS)
 └────────────────────────── literal scheme prefix
```

#### `ParsedURN` dataclass

Fields: `tld`, `namespace`, `label`, `raw`

Properties:
- `full` — reconstructs the canonical URN string from parts, omitting empty segments
- `matches_namespace(tld, namespace)` — boolean check used by namespace routing

---

#### `parse_urn(value) → ParsedURN`

Never raises. Handles all input forms:

| Input | tld | namespace | label |
|-------|-----|-----------|-------|
| `"urn:acme.com:sales:emailer"` | `acme.com` | `sales` | `emailer` |
| `"urn:agentns.local:emailer"` | `agentns.local` | `""` | `emailer` |
| `"sales:emailer"` | `sales` | `""` | `emailer` |
| `"emailer"` | `""` | `""` | `emailer` |

Algorithm:
1. Strip whitespace.
2. Strip leading `"urn:"` prefix (case-insensitive).
3. Split on `":"`.
4. If 3+ parts: `tld=parts[0]`, `namespace=parts[1]`, `label=":".join(parts[2:])` (handles colons in label).
5. If 2 parts: `tld=parts[0]`, `namespace=""`, `label=parts[1]`.
6. If 1 part: all empty except `label=parts[0]`.

---

#### `build_urn(tld, namespace, label) → str`

Simple f-string: `f"urn:{tld}:{namespace}:{label}"`. Used to construct the `agent_name` field stored in the registry.

---

#### `extract_label(value) → str`

Convenience function. Calls `parse_urn()` and returns `.label`. If label is empty (malformed URN), returns the original string. Used in edge cases where the input might already be a plain label.

---

### 5.6 `client.py` — Python Client SDK

**File:** `agentns/client.py`  
**Purpose:** Type-safe Python client for calling the agentns sidecar. Two classes: async (`AgentNSClient`) and sync wrapper (`AgentNSClientSync`).

#### `ResolvedAgent` dataclass

The typed return value from `client.resolve()`.

| Field | Type | Description |
|-------|------|-------------|
| `endpoint` | str | Full URL of the selected agent |
| `protocol` | str | Selected protocol (e.g. "A2A", "http") |
| `ttl` | int | Seconds until resolution should be refreshed |
| `region` | str | Human-readable region name |
| `cached` | bool | True if served from cache |
| `selected_by` | str | Selection reason |
| `resolution_time_ms` | float | Total round-trip time in ms |
| `metadata` | dict | Candidate list, latency, total_candidates |
| `flag` | str | Emoji flag |
| `endpoint_url` | property | Alias for `endpoint` (backward compatibility) |

---

#### `AgentNSClient` (async)

Initialized with `url` (defaults to `AGENTNS_URL` env var) and `timeout` (default 5s). Creates a persistent `httpx.AsyncClient` with JSON headers pre-set.

**`resolve(agent_name, *, requester_context, cache_enabled) → Optional[ResolvedAgent]`**

- Never raises. On any error (network, 4xx, 5xx, JSON decode): returns `None`.
- Caller is expected to implement fallback logic when `None` is returned.
- Wraps the response JSON into a typed `ResolvedAgent` dataclass.

**`register(label, endpoint, **kwargs) → Dict`**

- Raises `httpx.HTTPStatusError` (via `raise_for_status()`) on server errors.
- Caller should catch on startup and retry or abort.

**`deregister(label, endpoint="") → Dict`**

- Empty `endpoint` deregisters all replicas for the label.
- Raises on HTTP error.

**`health() → Dict`**  
**`agents() → Dict`**

- Direct passthrough to `/health` and `/agents` endpoints.

**Context manager protocol** (`async with AgentNSClient(...) as c:`):
- `__aenter__` returns `self`.
- `__aexit__` calls `self._client.aclose()` — important for connection cleanup.
- Can also call `await client.close()` manually.

---

#### `AgentNSClientSync`

A synchronous convenience wrapper. Each method call wraps the async equivalent in `asyncio.run()`:

```python
def resolve(self, agent_name, **kwargs):
    async def _go():
        async with AgentNSClient(self._url, self._timeout) as c:
            return await c.resolve(agent_name, **kwargs)
    return asyncio.run(_go())
```

Creates and destroys an event loop per call. Fine for scripts, agent startup/shutdown code, and testing. Not suitable for high-throughput production paths — use `AgentNSClient` with `await` in those cases.

---

## 6. Data Models

### Endpoint Entry (in `_registry`)

```python
{
    "endpoint":         "http://ny-host:9001",           # required
    "health_check_url": "http://ny-host:9001/health",    # optional, empty if auto-discover
    "namespace":        "agents.local",                   # URN namespace
    "protocols":        ["http", "A2A"],                  # supported protocols
    "region":           "us-east",                        # region code
    "region_label":     "New York, NY",                   # human-readable
    "flag":             "🇺🇸",                             # emoji flag
    "location": {
        "city":         "New York",
        "latitude":     40.7128,
        "longitude":    -74.0060
    },
    "agent_name":       "urn:agentns.local:agents.local:emailer"
}
```

### Health Dict (in `_health_cache`)

```python
{
    "status":           "healthy",      # "healthy" | "degraded" | "unhealthy" | "unknown"
    "load":             42.5,           # 0–100, defaults to 50 if not reported
    "response_time_ms": 87.3,           # round-trip to health URL in ms
    "last_check":       "2025-04-17T14:23:01.456789+00:00",
    "reason":           ""              # populated only on unhealthy
}
```

### Resolution Response (from `POST /resolve`)

```python
{
    "endpoint":             "http://lon-host:9001",
    "protocol":             "A2A",
    "ttl":                  60,
    "region":               "London, UK",
    "flag":                 "🇬🇧",
    "cached":               False,
    "selected_by":          "geo_nearest",
    "resolution_time_ms":   3.7,
    "metadata": {
        "label":            "emailer",
        "latency_ms":       210.0,
        "total_candidates": 2,
        "all_candidates": [
            {
                "endpoint":   "http://lon-host:9001",
                "region":     "London, UK",
                "flag":       "🇬🇧",
                "status":     "healthy",
                "latency_ms": 210.0,
                "load":       20.0
            },
            {
                "endpoint":   "http://ny-host:9001",
                "region":     "New York, NY",
                "flag":       "🇺🇸",
                "status":     "healthy",
                "latency_ms": 45.0,
                "load":       30.0
            }
        ]
    }
}
```

### MongoDB Document Schema

```javascript
{
    "_id":          ObjectId("..."),          // MongoDB internal
    "label":        "emailer",                // indexed
    "endpoint":     "http://ny-host:9001",    // part of unique compound index
    "health_check_url": "http://ny-host:9001/health",
    "namespace":    "agents.local",
    "protocols":    ["http", "A2A"],
    "region":       "us-east",
    "region_label": "New York, NY",
    "flag":         "🇺🇸",
    "location":     {"city": "New York", "latitude": 40.7128, "longitude": -74.006},
    "agent_name":   "urn:agentns.local:agents.local:emailer",
    "registered_at": ISODate("2025-04-17T10:00:00Z"),  // $setOnInsert — never changes
    "last_seen":     ISODate("2025-04-17T14:23:01Z")   // updated on every re-registration
}
```

---

## 7. Server Selection Algorithm

The ranking algorithm is the intellectual core of agentns. It answers: *"Given N endpoints registered for label X, and a request from location L wanting protocol P, which endpoint should answer?"*

### Sort Key

```python
(health_score, protocol_score, geo_distance_km, response_time_ms, load_percent)
```

Each position is only consulted when all positions to its left are tied. This creates a strict priority hierarchy.

### Priority 1: Health Status

```
healthy (0) >> degraded (1) >> unknown (2) >> unhealthy (3, excluded)
```

A degraded endpoint (slow but alive) is always preferred over an unknown one (not yet probed). Unhealthy endpoints are completely removed from the candidate list before sorting.

### Priority 2: Protocol Compatibility

```
preferred protocol available (0) >> not available (1)
```

If the caller wants A2A but an endpoint only supports HTTP, it scores 1. An endpoint supporting A2A scores 0. Among equally healthy endpoints, protocol-compatible ones always win.

### Priority 3: Geographic Distance

```python
distance_km = haversine(requester_lat, requester_lon, server_lat, server_lon)
# Returns math.inf if either party has no known location
```

A Boston requester calling `resolve()` gets New York (306 km) over Frankfurt (6,200 km) — even if Frankfurt has lower latency at that moment. Geographic proximity is the stronger signal because:
- It correlates with compliance (data sovereignty)
- Network latency and geo distance are strongly correlated at global scale
- Geo stability is more predictable than momentary latency measurements

If no location is provided (or no server has location data), all geo distances are `math.inf` and the sort falls through to latency.

### Priority 4: Response Time

```python
health.get("response_time_ms", 9999.0)
```

Measured round-trip in milliseconds from the most recent health sweep. Within the same geo zone (or when no location provided), the fastest endpoint wins. 9999ms default for unknown-latency endpoints pushes them below measured ones.

### Priority 5: CPU Load

```python
health.get("load", 50.0)
```

Load percent (0–100) from the agent's health endpoint JSON. Final tiebreaker when everything else is equal. 50% default for endpoints that don't report load.

### Worked Example

Two replicas for `emailer`, requester in Boston:

```
               NYC               London
health_score:   0 (healthy)       0 (healthy)
proto_score:    0 (A2A ✓)         0 (A2A ✓)
geo_km:         306 km            5,263 km
latency_ms:     45 ms             210 ms
load:           30%               20%

NYC sort key:    (0, 0,  306, 45,  30)
London sort key: (0, 0, 5263, 210, 20)

NYC wins at position 3 (geo_km 306 < 5263)
selected_by = "geo_nearest"
```

Same example, no location provided:

```
NYC sort key:    (0, 0, inf, 45,  30)
London sort key: (0, 0, inf, 210, 20)

NYC wins at position 4 (latency_ms 45 < 210)
selected_by = "lowest_latency"
```

---

## 8. Concurrency Model

agentns uses **cooperative multitasking** via Python's asyncio. There are no threads.

### Event Loop Tasks

At runtime, the asyncio event loop runs multiple coroutines concurrently:

```
asyncio event loop
    ├── uvicorn ASGI server          (handles HTTP connections)
    │     ├── resolve() coroutine     (per incoming request)
    │     ├── register() coroutine    (per incoming request)
    │     └── health() coroutine      (per incoming request)
    │
    └── _health_loop() task          (background, started in lifespan)
          └── _check_all()           (every HEALTH_INTERVAL seconds)
                └── asyncio.gather() (all endpoint probes in parallel)
```

### Shared State and Locking

Only `_health_cache` requires a lock because it is written by both:
1. `_check_all()` (background loop)
2. The live-check block inside `resolve()` (request handlers)

The `asyncio.Lock` (`_health_lock`) ensures that concurrent writes do not corrupt the dict. Because asyncio is single-threaded, lock contention is only possible at `await` yield points — lock acquisition is almost always instant.

`_registry` does **not** have a lock. Modifications only happen in `register()` and `deregister()` which are regular (non-concurrent) HTTP handlers. In asyncio, dict mutations between yield points are atomic.

`_cache` has its own internal `asyncio.Lock` within `ResolutionCache`.

### Health Probe Parallelism

```python
await asyncio.gather(*[_check_one(u, h) for u, h in seen.items()], return_exceptions=True)
```

All health probes execute concurrently. For 10 endpoints, the sweep takes as long as the slowest individual probe (5s timeout), not 50s. `return_exceptions=True` ensures one timed-out probe does not cancel the others.

---

## 9. Persistence Layer

### In-Memory Mode (default)

When `MONGODB_URI` is not set:
- `_registry` lives only in process memory
- On restart: all dynamically registered agents are lost
- Static agents (hardcoded in code) survive restarts
- Suitable for: local development, single-process deployments, ephemeral environments

### MongoDB Mode

When `MONGODB_URI` is set:
- Every `POST /register` call upserts to MongoDB
- On startup: `_load_from_mongo()` restores the registry before the first health sweep
- The full startup sequence including MongoDB load and initial health sweep completes before the first HTTP request is accepted
- Suitable for: production deployments, multi-instance deployments, any environment where agents do not re-register on every startup

### MongoDB Upsert Semantics

```python
await _mongo_col.update_one(
    {"label": label, "endpoint": entry["endpoint"]},   # filter = unique identity
    {
        "$set":         {**doc, "last_seen": now},      # always update
        "$setOnInsert": {"registered_at": now},          # only on first insert
    },
    upsert=True,
)
```

This is idempotent: calling `POST /register` with the same `(label, endpoint)` 100 times produces exactly one MongoDB document, with `registered_at` set on the first call and `last_seen` updated on every subsequent call.

---

## 10. Configuration Reference

All configuration is via environment variables. No config files. No hardcoded values.

| Variable | Default | Type | Description |
|----------|---------|------|-------------|
| `AGENTNS_PORT` | `8200` | int | HTTP port the server listens on |
| `AGENTNS_NAMESPACE` | `agents.local` | str | Default URN namespace for newly registered agents |
| `AGENTNS_TLD` | `agentns.local` | str | URN TLD used in `agent_name` construction |
| `AGENTNS_HEALTH_INTERVAL` | `30` | int | Seconds between background health sweeps |
| `MONGODB_URI` | `""` | str | MongoDB connection string. Empty = in-memory mode |
| `MONGODB_DB` | `agentns` | str | MongoDB database name |
| `AGENTNS_URL` | `http://localhost:8200` | str | Used by `AgentNSClient()` with no arguments |

---

## 11. API Reference

### `POST /register`

Register or update an agent endpoint.

**Request:**
```json
{
  "label":           "emailer",
  "endpoint":        "http://host:9001",
  "namespace":       "acme.sales",
  "region":          "us-east",
  "region_label":    "New York, NY",
  "location":        {"city": "New York"},
  "protocols":       ["http", "A2A"],
  "health_check_url":"http://host:9001/health",
  "flag":            "🇺🇸"
}
```

**Response 200:**
```json
{
  "status":          "registered",
  "label":           "emailer",
  "endpoint":        "http://host:9001",
  "agent_name":      "urn:agentns.local:acme.sales:emailer",
  "total_endpoints": 1
}
```

**Response 400:** `label` or `endpoint` missing.

---

### `POST /resolve`

Resolve an agent to its best available endpoint.

**Request:**
```json
{
  "agent_name": "urn:agentns.local:acme.sales:emailer",
  "requester_context": {
    "location":  {"city": "Boston"},
    "protocols": ["A2A", "http"]
  },
  "cache_enabled": true
}
```

**Response 200:**
```json
{
  "endpoint":           "http://host:9001",
  "protocol":           "A2A",
  "ttl":                60,
  "region":             "New York, NY",
  "flag":               "🇺🇸",
  "cached":             false,
  "selected_by":        "geo_nearest",
  "resolution_time_ms": 3.7,
  "metadata": {
    "label":            "emailer",
    "latency_ms":       45.0,
    "total_candidates": 2,
    "all_candidates":   [...]
  }
}
```

**Response 400:** No `agent_name` or `label` provided.  
**Response 404:** Label not registered.

---

### `DELETE /register/{label}`

Remove one or all endpoints for a label.

**Request body (optional):**
```json
{"endpoint": "http://host:9001"}
```
Omit body or set endpoint to `""` to remove all endpoints for the label.

**Response 200:**
```json
{"status": "deregistered", "label": "emailer", "removed": 1}
```

---

### `GET /health`

Full service health report. HTTP 200 always (even when agents are unhealthy — the sidecar itself is up).

### `GET /agents`

All registered labels with per-endpoint health status.

### `GET /namespaces`

All namespaces and the labels registered under each.

### `GET /cache/stats`

Cache hit rate and entry counts.

### `POST /cache/clear`

Flush the resolution cache. Does not affect `_registry` or `_health_cache`.

---

## 12. Error Handling

### Principle: Never Crash the Caller

Every code path in agentns is designed to return a response rather than propagate an unhandled exception.

| Scenario | Behavior |
|----------|----------|
| MongoDB unreachable at startup | Logs error, continues in-memory mode |
| MongoDB write fails during register | Logs error, registration still succeeds in-memory |
| MongoDB load fails at startup | Logs error, starts with empty registry |
| Health probe times out | Returns `_unhealthy("timeout")`, endpoint marked unhealthy |
| Health probe connection refused | Returns `_unhealthy("connection refused")` |
| All endpoints unhealthy during resolve | Returns `emergency_fallback` with first endpoint, TTL=5 |
| One probe in gather() throws | `return_exceptions=True` — other probes continue |
| Background health loop iteration fails | Logs warning, sleeps, retries next iteration |
| `AgentNSClient.resolve()` throws | Catches all exceptions, returns `None` |
| Unknown status in `_health_score()` | Defaults to `2` (unknown) |
| City name not in `CITY_COORDS` | Returns `None` from `_resolve_location()`, disables geo |

### HTTP Error Codes

| Code | When |
|------|------|
| 400 | Missing required fields (`label`, `endpoint`, `agent_name`) |
| 404 | Label not registered when resolving or deregistering |
| 200 | All success cases, including `emergency_fallback` |

The 200 for emergency fallback is intentional — returning 503 would cause orchestrators to fail hard. Returning 200 with a low TTL (5s) allows the orchestrator to call the unhealthy endpoint (which may still be partially functional) and retry resolution quickly.

---

## 13. Performance Characteristics

### Resolution Latency

| Path | Typical latency |
|------|----------------|
| Cache hit | < 1 ms |
| Cache miss, all endpoints in health cache | 1–5 ms |
| Cache miss, one endpoint unchecked (live probe) | 50–500 ms (network dependent) |

### Health Sweep Throughput

Health sweeps run with `asyncio.gather()` — all probes are concurrent. For N endpoints:
- Sequential: `N × avg_probe_latency`
- With gather: `≈ max_probe_latency` (bounded by slowest single probe)

For 50 endpoints with 100ms average probe latency: ~100ms sweep time vs ~5000ms sequential.

### Memory Usage

The `_registry` dict is tiny — a few KB per registered endpoint. `_health_cache` is similar. `ResolutionCache._store` holds fully serialized JSON payloads, typically 1–5 KB each.

For a system with 100 agents and 500 distinct (label + context) resolution combinations: total in-memory state < 5 MB.

### Scalability Limits

agentns is a sidecar — one instance per orchestrator host. It is not designed for horizontal scaling of the discovery service itself. For very large systems (thousands of agents), MongoDB becomes the scaling lever: multiple agentns instances share the same MongoDB backend, each with a local in-memory cache.

---

*Technical Reference — agentns v1.0.0 — DataWorksAI — MIT License*
