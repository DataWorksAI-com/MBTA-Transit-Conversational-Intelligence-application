# MBTA Agntcy — Full Handoff Document

**Owner:** Manikandan Meenakshisundaram (meenakshisundaram.m@northeastern.edu)  
**Last updated:** 2026-05-27  
**Status:** Production — all systems live, tested, and security-hardened

---

## 1. What Was Built

A production **multi-agent transit assistant** for MBTA. Users ask natural-language questions; the system routes them through specialized AI agents secured by a prompt firewall.

Three layers:
1. **DANS + Prompt Firewall** — naming service + security middleware (agent registry)
2. **Exchange Server** — entry point, intent classification, A2A routing with Protocol Intelligence
3. **Agents** — Planner, Fares, StopFinder, Alerts

### Recent major additions (2026-05-27)
- **Protocol Intelligence — MBTA wired up** — Exchange server now fully reads DANS-negotiated protocol on every agent call. Fixed `call_stopfinder_for_location` to use `config.resolved_protocol` instead of global flag. Added `protocol_used` per-agent in `/chat` response metadata. Fixed `ANS_RESOLVER_URL` in supervisor config — was missing, causing ANS to fall back silently. Verified E2E: `transport=dans_negotiated`, `negotiated_by=intersection` for all MBTA agents.
- **Protocol Intelligence** (2026-05-26) — DANS negotiates best protocol on `/resolve`. MBTA agents registered with `protocols` + `protocol_metadata`.
- **Security Hardening** (2026-05-26) — 12 security vulnerabilities fixed. 22/22 live verification tests passing.

---

## 2. Servers & Access

### SSH Keys (all at `C:\Users\Manikandan\Desktop\mbta\`)

| Key file | Server | User |
|---|---|---|
| `Northeastern-registry-v3-key` | 97.107.132.213 (DANS/Registry) | root |
| `mbta-exchange-key` | 50.116.53.133 (Exchange) | root |
| `mbta-agents-key` | 96.126.111.107 (Agents) | root |

**SSH command pattern:**
```powershell
$key = "C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key"
ssh -i $key -o StrictHostKeyChecking=no root@97.107.132.213
```

### Server Map

| Server IP | Role | Key services |
|---|---|---|
| **97.107.132.213** | DANS + Registry + Firewall | Docker: agentns(:8200), registry(:6900). Nginx on :80 |
| **50.116.53.133** | Exchange Server + Chat UI | Supervisord: mbta-exchange(:8100), chat-server(:8000) |
| **96.126.111.107** | Agents + SLIM | Supervisord: planner(:50052), alerts(:8001), stopfinder(:8003), fares(:50054), SLIM(:46357) |
| **50.116.57.161** | Fares agent (EU replica) | fares(:50054) |
| **85.90.246.180** | Fares agent (EU replica 2) | fares(:50054) |

### Public URLs

| URL | What it is |
|---|---|
| `http://50.116.53.133:8000` | MBTA Chat UI (browser) |
| `http://50.116.53.133:8100` | Exchange Server API |
| `http://50.116.53.133:8100/chat` | Chat endpoint (POST) |
| `http://97.107.132.213/dans/` | DANS landing page |
| `http://97.107.132.213/dans/health` | DANS health + all registered agents |
| `http://97.107.132.213/dans/firewall/rules` | Live firewall rules (JSON) |
| `http://97.107.132.213/dans/firewall/stats` | Firewall hit/block counts |
| `http://97.107.132.213/dans/docs` | DANS Swagger API docs |

---

## 3. Repos

| Repo | Local path | GitHub |
|---|---|---|
| **agent-registry** (DANS + Firewall) | `C:\Users\Manikandan\Desktop\agent-registry` | `https://github.com/DataWorksAI-com/dans` |
| **mbta** (Exchange + Agents) | `C:\Users\Manikandan\Desktop\mbta` | No remote configured (local only) |

### agent-registry recent commits
```
65aa7d9  security: harden DANS against ReDoS, SSRF, XSS, and injection vectors
583b2c0  feat: add Protocol Intelligence section to DANS landing page
381ae6d  fix: bump version strings to 3.1.0; add E2E verification script
f1829f4  feat: Protocol Intelligence — DANS negotiates protocol on resolve
efc416e  Add MIT License
0dd864c  fix(landing): use relative links and request.url base for all hrefs
```

### Current DANS version: **3.1.0**

---

## 4. Key Files

### On the DANS server (97.107.132.213)

| Remote path | What it is | Source (local) |
|---|---|---|
| `/opt/agent-registry/src/agentns_server.py` | DANS FastAPI app (volume-mounted) | `agent-registry/agentns/server.py` |
| `/opt/agent-registry/src/agentns_firewall.py` | Firewall engine (volume-mounted) | `agent-registry/agentns/firewall.py` |
| `/opt/agent-registry/src/tenant.py` | Tenant/auth logic (volume-mounted) | `agent-registry/agentns/tenant.py` |
| `/opt/agent-registry/src/docker-compose.atlas.yml` | Docker Compose (runs on server) | Edit directly on server |

**Deploy DANS changes (from agent-registry folder):**
```powershell
$key = "C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key"
scp -i $key agentns/server.py   root@97.107.132.213:/opt/agent-registry/src/agentns_server.py
scp -i $key agentns/firewall.py root@97.107.132.213:/opt/agent-registry/src/agentns_firewall.py
ssh -i $key root@97.107.132.213 "cd /opt/agent-registry/src && docker compose -f docker-compose.atlas.yml restart agentns"
```

> **Note:** `server_selection.py` and `__init__.py` are baked into the Docker image (not volume-mounted). If you change those files, you must `docker cp` them into the running container too, then restart:
> ```powershell
> scp -i $key agentns/server_selection.py root@97.107.132.213:/tmp/server_selection.py
> ssh -i $key root@97.107.132.213 "CNAME=\$(docker ps --filter name=agentns --format '{{.Names}}' | head -1) && docker cp /tmp/server_selection.py \$CNAME:/app/agentns/server_selection.py"
> ```

### On the Exchange server (50.116.53.133)

| Remote path | What it is |
|---|---|
| `/opt/mbta-agentcy/src/exchange_agent/exchange_server.py` | Exchange FastAPI app |
| `/opt/mbta-agentcy/src/exchange_agent/stategraph_orchestrator.py` | LangGraph A2A orchestrator |
| `/opt/mbta-agentcy/src/exchange_agent/resolver_client.py` | DANS resolve client (Protocol Intelligence) |
| `/opt/mbta-agentcy/src/exchange_agent/slim_client.py` | SLIM transport client |
| `/opt/mbta-agentcy/src/exchange_agent/mcp_client.py` | MCP tool client |
| `/etc/supervisor/conf.d/mbta-exchange.conf` | Supervisord config |
| `/var/log/mbta-exchange.out.log` | Exchange server logs |

**Deploy exchange changes:**
```powershell
$key = "C:\Users\Manikandan\Desktop\mbta\mbta-exchange-key"
scp -i $key src/exchange_agent/stategraph_orchestrator.py root@50.116.53.133:/opt/mbta-agentcy/src/exchange_agent/stategraph_orchestrator.py
scp -i $key src/exchange_agent/resolver_client.py root@50.116.53.133:/opt/mbta-agentcy/src/exchange_agent/resolver_client.py
ssh -i $key root@50.116.53.133 "sudo supervisorctl restart mbta-exchange"
```

### Local important files

| Local path | What it is |
|---|---|
| `agent-registry/agentns/server.py` | DANS server (v3.1.0, security-hardened) |
| `agent-registry/agentns/firewall.py` | Firewall engine (ReDoS-safe, TTL-capped) |
| `agent-registry/agentns/server_selection.py` | Protocol negotiation logic |
| `agent-registry/agentns/__init__.py` | SUPPORTED_PROTOCOLS constant |
| `agent-registry/tests/test_api.py` | **54 unit tests** (all passing) |
| `agent-registry/verify_protocol_intelligence.py` | E2E Protocol Intelligence verification |
| `agent-registry/verify_security.py` | Live security verification (22/22 tests) |
| `agent-registry/check_resolve.py` | Quick protocol negotiation check |
| `agent-registry/DANS.md` | DANS API reference |
| `mbta/src/exchange_agent/resolver_client.py` | DANS resolve client + Protocol Intelligence |
| `mbta/src/exchange_agent/stategraph_orchestrator.py` | A2A orchestrator |
| `mbta/register_with_protocols.py` | Re-register MBTA agents with protocol metadata |
| `mbta/e2e_protocol_test.py` | E2E test: send chat query, verify protocol metadata in response |
| `mbta/TECHNICAL_DOC.md` | Full engineering reference |
| `mbta/PRESENTATION_SCRIPT.md` | Demo + presentation script |

---

## 5. Protocol Intelligence (DANS v3.1.0)

DANS now decides which protocol to use on every `/resolve` call — callers don't need to know what protocol each agent speaks.

### How it works

**Register an agent with protocols:**
```json
POST /dans/register
{
  "label": "planner",
  "endpoint": "http://96.126.111.107:50052",
  "protocols": ["a2a", "slim", "http"],
  "protocol_metadata": {
    "a2a":  {"version": "0.2.1", "path": "/a2a/message"},
    "slim": {"identity": "mbta-transit-ci/planner"}
  }
}
```

**Resolve with caller preference:**
```json
POST /dans/resolve
{
  "agent_name": "planner",
  "requester_context": {"protocols": ["slim", "a2a", "http"]}
}
```

**Response includes negotiated protocol:**
```json
{
  "protocol": "slim",
  "negotiated_by": "intersection",
  "fallback_protocol": "a2a",
  "protocol_metadata": {"identity": "mbta-transit-ci/planner"}
}
```

**Negotiation paths:**
| `negotiated_by` | Meaning |
|---|---|
| `intersection` | Caller and agent both support this protocol (best match) |
| `agent_default` | Caller sent no preference — agent's first protocol used |
| `fallback` | No overlap — returns `http` + `warning: no_protocol_match` |

### Supported protocols
`a2a`, `mcp`, `slim`, `grpc`, `http`, `sse`, `acp`

### Current MBTA agent protocol registrations
| Agent | Protocols | Notes |
|---|---|---|
| alerts | a2a, slim, http | SLIM identity: mbta-transit-ci/alerts |
| planner | a2a, slim, http | SLIM identity: mbta-transit-ci/planner |
| stopfinder | a2a, slim, http | SLIM identity: mbta-transit-ci/stopfinder |
| fares | a2a, http | No SLIM (different host) |

**Re-register agents (if needed):**
```powershell
cd C:\Users\Manikandan\Desktop\mbta
python register_with_protocols.py
```

---

## 6. Environment Variables

### DANS container (docker-compose.atlas.yml on 97.107.132.213)

| Variable | Value |
|---|---|
| `AGENTNS_TLD` | `agents.dataworksai.com` |
| `AGENTNS_NAMESPACE` | `public` |
| `MONGODB_URI` | `mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/` |
| `MONGODB_DB` | `agentns_registry` |
| `DANS_AUTH` | `off` |
| `A2A_PROXY_ENDPOINTS` | `http://97.107.132.213/dans` |
| `AGENTNS_PROXY_MODE` | `dans` |
| `AGENTNS_WORKERS` | `1` ← **CRITICAL: must stay 1** (firewall state is in-memory) |

### Exchange server (supervisor conf on 50.116.53.133)

| Variable | Value |
|---|---|
| `AGENTNS_URL` | `http://97.107.132.213/dans` |
| `ANS_ENABLED` | `true` |
| `ANS_RESOLVER_URL` | `http://97.107.132.213/dans` |
| `ANS_TLD` | `agents.dataworksai.com` |
| `ANS_APP` | `mbta-transit-ci` |
| `USE_SLIM` | `true` |
| `SLIM_ENDPOINT` | `http://96.126.111.107:46357` |
| `SLIM_ORG` | `mbta` |
| `SLIM_NS` | `transit-ci` |
| `OPENAI_API_KEY` | In `.env` file on server |
| `MBTA_API_KEY` | In `.env` file on server |

---

## 7. MongoDB

**Connection string:** `mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/`  
**Database:** `agentns_registry`  
**Collections:**
- `registrations` — registered agent endpoints + protocol metadata
- `firewall` — active firewall rules (10 canonical rules)
- `federations` — connected remote registries

**View/manage rules live:**
```
http://97.107.132.213/dans/firewall/rules
```

---

## 8. Active Firewall Rules (10 canonical rules)

```bash
curl http://97.107.132.213/dans/firewall/rules | python3 -m json.tool
```

| Priority | Action | Match type | Match value |
|---|---|---|---|
| 10 | block_response | contains | `system prompt` |
| 11 | block_response | contains | `my instructions are` |
| 20 | redact → `[API-KEY-REDACTED]` | regex | `sk-[A-Za-z0-9]{20,}` |
| 21 | redact → `[SSN-REDACTED]` | regex | `\d{3}-\d{2}-\d{4}` |
| 22 | redact → `[INTERNAL-IP-REDACTED]` | regex | `10\.\d+\.\d+\.\d+\|192\.168\.\d+\.\d+` |
| 100 | block | contains | `ignore previous instructions` |
| 100 | block | contains | `reveal your system prompt` |
| 100 | block | contains | `jailbreak` |
| 101 | block | regex | `(?i)(ignore\|forget\|disregard).{0,20}?(previous\|above\|prior\|all).{0,20}?(instructions\|prompt\|rules\|context)` |
| 102 | block | regex | `(?i)(act as\|pretend (you are\|to be)\|you are now).{0,30}?(unrestricted\|jailbreak\|DAN\|evil\|unfiltered)` |

---

## 9. Security Hardening (2026-05-26) — commit 65aa7d9

12 security vulnerabilities found (as a 5-year Akamai security engineer would review) and fixed. All verified live with 22/22 tests passing.

| # | Vulnerability | Fix |
|---|---|---|
| 1 | **ReDoS** — user-supplied regex patterns could hang the server | Two-layer defence: static nested-quantifier heuristic (0ms) + subprocess test with OS kill (immune to GIL) |
| 2 | **SSRF** — switchboard could register internal IPs as remote registries | `_validate_remote_url()` blocks 10.x, 192.168.x, 127.x, 169.254.x, non-http schemes |
| 3 | **XSS** — landing page rendered `request.url` raw into HTML | `html.escape()` applied to all URL template insertions |
| 4 | **Endpoint scheme injection** — `file://`, `javascript:`, `ftp://` endpoints accepted | Scheme validation at `/register` (http/https only) |
| 5 | **Label/endpoint length** — unbounded inputs could flood memory | Max 128 chars (label), 512 chars (endpoint) |
| 6 | **Host header injection** — proxy forwarded `X-Forwarded-Host` etc. | Strip `X-Forwarded-Host`, `X-Original-Host`, `X-Host`, `X-Real-IP`, `X-Forwarded-Server` |
| 7 | **Proxy size DoS** — malicious agent could return 10GB response | Content-Length pre-check + post-read check, hard limit 10MB |
| 8 | **Cache TTL poisoning** — `ttl: 999999999` could create permanent cache entries | TTL capped at 3600s (1 hour) in both `cache_set()` and `get_cache_ttl_for()` |
| 9 | **Log injection** — raw match_value in logs enabled ANSI/newline injection | `repr(rule.match_value[:80])` used in all log lines |
| 10 | **Health check DoS** — 1000 registered agents → 1000 concurrent outbound probes from one request | `asyncio.Semaphore(10)` limits concurrent health checks |
| 11 | **A2A method type confusion** — non-string `method` field could bypass firewall checks | Type check + 128-char cap on extracted A2A method |
| 12 | **Error leakage** — federation errors exposed internal IPs and stack details | Full error logged server-side; generic message returned to caller |

**Run live security verification:**
```powershell
cd C:\Users\Manikandan\Desktop\agent-registry
$env:PYTHONIOENCODING="utf-8"
python verify_security.py
# Expected: 22/22 passed ALL GOOD
```

---

## 10. Docker on DANS Server

```bash
# Check running containers
docker ps

# Check DANS worker count (must say --workers 1)
docker inspect src-agentns-1 --format '{{json .Config.Cmd}}'

# Restart DANS
cd /opt/agent-registry/src
docker compose -f docker-compose.atlas.yml restart agentns

# Force recreate (if image-baked files need updating)
docker compose -f docker-compose.atlas.yml up -d --force-recreate agentns

# View logs
docker logs src-agentns-1 -f --tail=50
```

> **Critical:** `--workers 1` must stay. Two workers = split in-memory firewall state = rules only enforced 50% of requests.

---

## 11. Supervisord on Exchange Server

```bash
sudo supervisorctl status
sudo supervisorctl restart mbta-exchange
tail -f /var/log/mbta-exchange.out.log
tail -f /var/log/mbta-exchange.err.log
```

---

## 12. Running Tests

### Unit tests — agent-registry (54 tests)
```powershell
Set-Location C:\Users\Manikandan\Desktop\agent-registry
python -m pytest tests/test_api.py -v
# Expected: 54 passed (47 core + 7 security)
```

### Protocol Intelligence E2E verification (live server)
```powershell
cd C:\Users\Manikandan\Desktop\agent-registry
$env:PYTHONIOENCODING="utf-8"
python verify_protocol_intelligence.py http://97.107.132.213/dans
# Expected: All checks passed
```

### Security verification (live server, 22 tests)
```powershell
cd C:\Users\Manikandan\Desktop\agent-registry
$env:PYTHONIOENCODING="utf-8"
python verify_security.py
# Expected: 22/22 passed ALL GOOD
```

### Quick protocol check (which protocol DANS picks per agent)
```powershell
cd C:\Users\Manikandan\Desktop\agent-registry
python check_resolve.py http://97.107.132.213/dans
# Expected: alerts/stopfinder → slim, planner/fares → a2a  (intersection negotiation)
```

### E2E Protocol Intelligence test (exchange → DANS → agents)
```powershell
cd C:\Users\Manikandan\Desktop\mbta
$env:PYTHONIOENCODING="utf-8"
python e2e_protocol_test.py
# Expected: transport=dans_negotiated, ans_enabled=True, ans_traces with negotiated_by=intersection
```

---

## 13. Common Operations

### Add a new firewall rule
```bash
curl -X POST http://97.107.132.213/dans/firewall/rules \
  -H "Content-Type: application/json" \
  -d '{"label":"*","action":"block","match_type":"contains","match_value":"YOUR_PATTERN","priority":100}'
```

### Delete a firewall rule
```bash
curl -X DELETE http://97.107.132.213/dans/firewall/rules/RULE_ID
```

### Test a message against firewall (dry-run)
```bash
curl -X POST http://97.107.132.213/dans/firewall/test \
  -H "Content-Type: application/json" \
  -d '{"label":"*","body":{"message":"YOUR MESSAGE HERE"}}'
```

### Check DANS health + registered agents
```bash
curl http://97.107.132.213/dans/health | python3 -m json.tool
```

### Call exchange API directly
```bash
curl -X POST http://50.116.53.133:8100/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"get me from north station to back bay"}'
```

### Resolve an agent (see what protocol DANS picks)
```bash
curl -X POST http://97.107.132.213/dans/resolve \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"planner","requester_context":{"protocols":["slim","a2a","http"]}}'
```

---

## 14. Architecture — Quick Reference

```
User
 │
 ▼
Chat UI (50.116.53.133:8000)
 │
 ▼
Exchange Server (50.116.53.133:8100)
 │
 ├─ Gate-zero firewall check → POST /dans/firewall/test
 │     blocked? → return immediately (25ms)
 │     pass?    → continue
 │
 ├─ Intent classification (GPT-4)
 │
 └─ A2A path → StateGraph (stategraph_orchestrator.py)
       │
       ├─ firewall_node
       ├─ discovery_node (which agents to call)
       ├─ execute_agents_node
       │     ↓
       │   POST /dans/resolve   ← DANS returns negotiated protocol
       │     ↓
       │   Use resolved protocol (slim/a2a/http) to call agent
       └─ synthesize_node (GPT-4 synthesis)
              │
              ▼
       POST /dans/proxy/{label}  (97.107.132.213)
              │
       DANS Firewall evaluates request
              │
       Target agent (96.126.111.107)
              │
       DANS Firewall evaluates response (redact/block_response)
              │
       Response returned to user
```

---

## 15. Known Issues & Notes

| Issue | Status | Notes |
|---|---|---|
| SLIM transport | Configured and working | alerts/planner/stopfinder use SLIM (protocol negotiated by DANS). HTTP fallback works if SLIM controller down. |
| `--workers 1` | Enforced via docker-compose | If you see `--workers 2` in docker inspect, force recreate immediately |
| MongoDB rules deduplication | Resolved | 10 canonical rules in MongoDB |
| GitHub deployment failures | Resolved | No active CI/CD pipeline — deploy manually via SCP + restart |
| `server_selection.py` + `__init__.py` | Baked into Docker image | If changed, must `docker cp` into container manually (see Key Files section) |

---

## 16. What To Tell the Next Session

Paste this into the new chat:

> I have a production multi-agent MBTA transit assistant with security hardening. The system has:
>
> - **DANS v3.1.0** (Dynamic Agent Naming Service + Prompt Firewall + Protocol Intelligence) on 97.107.132.213, Docker container src-agentns-1, code at `C:\Users\Manikandan\Desktop\agent-registry` (GitHub: DataWorksAI-com/dans, latest commit: 65aa7d9)
> - **Exchange Server** on 50.116.53.133:8100, supervisord process mbta-exchange, code at `C:\Users\Manikandan\Desktop\mbta\src\exchange_agent\`
> - **Agents** (planner, fares, alerts, stopfinder) on 96.126.111.107
> - SSH key for DANS server: `C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key`
> - SSH key for exchange server: `C:\Users\Manikandan\Desktop\mbta\mbta-exchange-key`
> - MongoDB Atlas: `mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/` DB: agentns_registry
> - 10 active firewall rules in MongoDB
> - Protocol Intelligence: DANS negotiates slim/a2a/http per agent on every /resolve call
> - 12 security fixes deployed and verified (22/22 live tests passing)
> - Unit tests: 54 passing (`agent-registry/tests/test_api.py`)
> - Security verify script: `agent-registry/verify_security.py`
> - Full handoff doc: `C:\Users\Manikandan\Desktop\mbta\HANDOFF.md`
