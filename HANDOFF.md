# MBTA Agntcy — Full Handoff Document

**Owner:** Manikandan Meenakshisundaram (meenakshisundaram.m@northeastern.edu)  
**Last updated:** 2026-05-24  
**Status:** Production — all systems live and tested

---

## 1. What Was Built

A production **multi-agent transit assistant** for MBTA. Users ask natural-language questions; the system routes them through specialized AI agents secured by a prompt firewall.

Three layers:
1. **DANS + Prompt Firewall** — naming service + security middleware (agent registry)
2. **Exchange Server** — entry point, intent classification, MCP/A2A routing
3. **Agents** — Planner, Fares, StopFinder, Alerts

---

## 2. Servers & Access

### SSH Keys (all at `C:\Users\Manikandan\Desktop\mbta\`)

| Key file | Server | User |
|---|---|---|
| `Northeastern-registry-v3-key` | 97.107.132.213 (DANS/Registry) | root |
| `mbta-exchange-key` | 50.116.53.133 (Exchange) | root |
| `mbta-agents-key` | 96.126.111.107 (Agents) | root |

**SSH command pattern:**
```bash
ssh -i C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key -o StrictHostKeyChecking=no root@97.107.132.213
```

### Server Map

| Server IP | Role | Key services |
|---|---|---|
| **97.107.132.213** | DANS + Registry + Firewall | Docker: agentns(:8200), registry(:6900). Nginx on :80 |
| **50.116.53.133** | Exchange Server + Chat UI | Supervisord: mbta-exchange(:8100), chat-server(:8000) |
| **96.126.111.107** | Agents + SLIM | Supervisord: planner(:50052), alerts(:8001), stopfinder(:8003), fares(:50054), SLIM(:46357) |

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
efc416e  Add MIT License
0dd864c  fix(landing): use relative links and request.url base for all hrefs
92dbf85  feat(landing): add Prompt Firewall to DANS landing page and DANS.md
8c7f50a  docs(readme): add Prompt Firewall section, API routes, updated repo structure
eb40c81  test(firewall): add response filtering tests
5254c59  feat(firewall): add response filtering — block_response and redact actions
```

### mbta recent commits
```
c4ecb0e  docs: add presentation and demo script
a850387  docs: add TECHNICAL_DOC.md
fbb1efc  docs: add README
d3bcbfb  feat: MBTA Agntcy - A2A multi-agent exchange with DANS Firewall integration
```

---

## 4. Key Files

### On the DANS server (97.107.132.213)

| Remote path | What it is | Source (local) |
|---|---|---|
| `/opt/agent-registry/src/agentns_server.py` | DANS FastAPI app (volume-mounted) | `agent-registry/agentns/server.py` |
| `/opt/agent-registry/src/agentns_firewall.py` | Firewall engine (volume-mounted) | `agent-registry/agentns/firewall.py` |
| `/opt/agent-registry/src/docker-compose.atlas.yml` | Docker Compose (runs on server) | Edit directly on server |

**Deploy DANS changes:**
```powershell
$key = "C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key"
scp -i $key agentns/server.py   root@97.107.132.213:/opt/agent-registry/src/agentns_server.py
scp -i $key agentns/firewall.py root@97.107.132.213:/opt/agent-registry/src/agentns_firewall.py
ssh -i $key root@97.107.132.213 "cd /opt/agent-registry/src && docker compose -f docker-compose.atlas.yml restart agentns"
```

### On the Exchange server (50.116.53.133)

| Remote path | What it is |
|---|---|
| `/opt/mbta-agentcy/src/exchange_agent/exchange_server.py` | Exchange FastAPI app |
| `/opt/mbta-agentcy/src/exchange_agent/stategraph_orchestrator.py` | LangGraph A2A orchestrator |
| `/opt/mbta-agentcy/src/exchange_agent/slim_client.py` | SLIM transport client |
| `/opt/mbta-agentcy/src/exchange_agent/mcp_client.py` | MCP tool client |
| `/etc/supervisor/conf.d/mbta-exchange.conf` | Supervisord config |
| `/var/log/mbta-exchange.out.log` | Exchange server logs |

**Deploy exchange changes:**
```powershell
$key = "C:\Users\Manikandan\Desktop\mbta\mbta-exchange-key"
scp -i $key src/exchange_agent/exchange_server.py root@50.116.53.133:/opt/mbta-agentcy/src/exchange_agent/exchange_server.py
scp -i $key src/exchange_agent/stategraph_orchestrator.py root@50.116.53.133:/opt/mbta-agentcy/src/exchange_agent/stategraph_orchestrator.py
ssh -i $key root@50.116.53.133 "sudo supervisorctl restart mbta-exchange"
```

### Local important files

| Local path | What it is |
|---|---|
| `mbta/src/exchange_agent/exchange_server.py` | Exchange server |
| `mbta/src/exchange_agent/stategraph_orchestrator.py` | A2A orchestrator |
| `mbta/src/exchange_agent/slim_client.py` | SLIM client |
| `mbta/src/exchange_agent/mcp_client.py` | MCP client |
| `mbta/deploy/supervisor/exchange-server/mbta-exchange.conf` | Supervisor config (source of truth) |
| `mbta/README.md` | Project README |
| `mbta/TECHNICAL_DOC.md` | Full engineering reference |
| `mbta/PRESENTATION_SCRIPT.md` | Demo + presentation script |
| `agent-registry/agentns/firewall.py` | Firewall engine |
| `agent-registry/agentns/server.py` | DANS server |
| `agent-registry/tests/test_api.py` | 38 unit tests |
| `agent-registry/DANS.md` | DANS API reference |

---

## 5. Environment Variables

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
| `AGENTNS_WORKERS` | `1` ← CRITICAL: must stay 1 (firewall state is in-memory) |

### Exchange server (supervisor conf on 50.116.53.133)

| Variable | Value |
|---|---|
| `AGENTNS_URL` | `http://97.107.132.213/dans` |
| `ANS_ENABLED` | `true` |
| `ANS_RESOLVER_URL` | `http://50.116.53.133:8200` |
| `ANS_TLD` | `agents.dataworksai.com` |
| `ANS_APP` | `mbta-transit-ci` |
| `USE_SLIM` | `true` |
| `SLIM_ENDPOINT` | `http://96.126.111.107:46357` |
| `SLIM_ORG` | `mbta` |
| `SLIM_NS` | `transit-ci` |
| `OPENAI_API_KEY` | In `.env` file on server |
| `MBTA_API_KEY` | In `.env` file on server |

---

## 6. MongoDB

**Connection string:** `mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/`  
**Database:** `agentns_registry`  
**Collections:**
- `registrations` — registered agent endpoints
- `firewall` — active firewall rules (10 canonical rules)
- `federations` — connected remote registries

**View/manage rules live:**
```
http://97.107.132.213/dans/firewall/rules
```

---

## 7. Active Firewall Rules (10 canonical rules)

Run this to see live state:
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

**If rules are lost (e.g. after clearing MongoDB), re-add them:**
```powershell
# On server — run the canonical rule setup script
$key = "C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key"
scp -i $key C:\Users\Manikandan\AppData\Local\Temp\add_fw_rules.py root@97.107.132.213:/tmp/add_fw_rules.py
ssh -i $key root@97.107.132.213 "docker cp /tmp/add_fw_rules.py src-agentns-1:/tmp/ && docker exec src-agentns-1 python3 /tmp/add_fw_rules.py"
```

---

## 8. Docker on DANS Server

```bash
# Check running containers
docker ps

# Check DANS worker count (must say --workers 1)
docker inspect src-agentns-1 --format '{{json .Config.Cmd}}'

# Restart DANS
cd /opt/agent-registry/src
docker compose -f docker-compose.atlas.yml restart agentns

# Force recreate (if CMD didn't update after restart)
docker compose -f docker-compose.atlas.yml up -d --force-recreate agentns

# View logs
docker logs src-agentns-1 -f --tail=50
```

**Critical:** If you ever see `--workers 2` in the CMD output, force recreate immediately. Two workers = split in-memory firewall state = rules only enforced 50% of the time.

---

## 9. Supervisord on Exchange Server

```bash
# Status
sudo supervisorctl status

# Restart exchange server
sudo supervisorctl restart mbta-exchange

# View logs
tail -f /var/log/mbta-exchange.out.log
tail -f /var/log/mbta-exchange.err.log
```

---

## 10. Running Tests

### Unit tests (agent-registry)
```powershell
Set-Location C:\Users\Manikandan\Desktop\agent-registry
python -m pytest tests/test_api.py -v
# Expected: 38 passed
```

### Live functional tests (against prod DANS)
```powershell
# Upload and run inside the container
$key = "C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key"
scp -i $key C:\Users\MANIKA~1\AppData\Local\Temp\fw_verify.py root@97.107.132.213:/tmp/fw_verify.py
ssh -i $key root@97.107.132.213 "docker cp /tmp/fw_verify.py src-agentns-1:/tmp/ && docker exec src-agentns-1 python3 /tmp/fw_verify.py"
# Expected: 13/13 passed
```

### E2E tests (against prod exchange server)
```powershell
python C:\Users\MANIKA~1\AppData\Local\Temp\e2e_test.py
# Expected: 6/6 passed
```

---

## 11. Common Operations

### Add a new firewall rule
```bash
curl -X POST http://97.107.132.213/dans/firewall/rules \
  -H "Content-Type: application/json" \
  -d '{"label":"*","action":"block","match_type":"contains","match_value":"YOUR_PATTERN","priority":100}'
```

### Delete a firewall rule
```bash
# First get the rule_id from /firewall/rules
curl -X DELETE http://97.107.132.213/dans/firewall/rules/RULE_ID
```

### Test a message against the firewall (dry-run)
```bash
curl -X POST http://97.107.132.213/dans/firewall/test \
  -H "Content-Type: application/json" \
  -d '{"label":"*","body":{"message":"YOUR MESSAGE HERE"}}'
```

### Test response redaction
```bash
curl -X POST http://97.107.132.213/dans/firewall/test \
  -H "Content-Type: application/json" \
  -d '{"label":"*","body":{},"response_body":{"text":"Text with sk-abc123xyz456def789ghi012 inside"}}'
```

### Call the exchange API directly
```bash
curl -X POST http://50.116.53.133:8100/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"get me from north station to back bay","force_protocol":"auto"}'
```

### Check DANS health + registered agents
```bash
curl http://97.107.132.213/dans/health | python3 -m json.tool
```

---

## 12. Architecture — Quick Reference

```
User
 │
 ▼
Chat UI (50.116.53.133:8000)
 │
 ▼
Exchange Server (50.116.53.133:8100)  ← exchange_server.py
 │
 ├─ Gate-zero firewall check → POST /dans/firewall/test
 │     blocked? → return immediately (25ms, no agents called)
 │     pass?    → continue
 │
 ├─ Intent classification (GPT-4)
 │
 ├─ MCP path → direct tool calls to agent MCP endpoints
 │
 └─ A2A path → StateGraph (stategraph_orchestrator.py)
       │
       ├─ firewall_node (gate-zero again)
       ├─ discovery_node (which agents to call)
       ├─ execute_agents_node (parallel A2A calls via DANS proxy)
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

## 13. Known Issues & Notes

| Issue | Status | Notes |
|---|---|---|
| SLIM transport | Configured but may fall back to HTTP | Check logs for "SLIM ready" vs "SLIM failed". HTTP fallback works fine. |
| `--workers 1` | Enforced via docker-compose command override | If you see `--workers 2` in docker inspect, force recreate the container |
| MongoDB rules deduplication | Resolved | Previous sessions had duplicates — cleared and reloaded canonical 10 rules |
| GitHub deployment failures | Resolved | Deleted all 8 failed deployments from GitHub UI. No active CI/CD pipeline configured. |
| Footer links on DANS landing page | Fixed | Were using absolute paths (`/firewall/stats`), now relative (`firewall/stats`) |

---

## 14. What To Tell the Next Session

Paste this into the new chat:

> I have a production multi-agent MBTA transit assistant. The system has:
> - **DANS** (Dynamic Agent Naming Service + Prompt Firewall) running on 97.107.132.213, Docker container src-agentns-1, code at `C:\Users\Manikandan\Desktop\agent-registry` (GitHub: DataWorksAI-com/dans)
> - **Exchange Server** running on 50.116.53.133:8100, supervisord process mbta-exchange, code at `C:\Users\Manikandan\Desktop\mbta\src\exchange_agent\`
> - **Agents** (planner, fares, alerts, stopfinder) on 96.126.111.107
> - SSH key for DANS server: `C:\Users\Manikandan\Desktop\mbta\Northeastern-registry-v3-key`
> - SSH key for exchange server: `C:\Users\Manikandan\Desktop\mbta\mbta-exchange-key`
> - MongoDB Atlas: `mongodb+srv://nanda_admin:nanda_pass@cluster0.auzlobs.mongodb.net/` DB: agentns_registry
> - 10 active firewall rules in MongoDB (5 request-blocking, 5 response-filtering)
> - All tests passing: 38 unit tests, 13 firewall functional tests, 6 E2E tests
> - Full technical doc at `C:\Users\Manikandan\Desktop\mbta\TECHNICAL_DOC.md`
> - Full handoff doc at `C:\Users\Manikandan\Desktop\mbta\HANDOFF.md`
