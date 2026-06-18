# MBTA deploy — delete & redeploy, reproducibly

One shell script per service. IPs are **captured automatically** and propagated between
hosts, so deleting a Linode and redeploying "just works" — no hand-editing IPs.

## One-time setup
```bash
linode-cli configure                 # stores your Linode token (not kept in this repo)
cp deploy/config.env.example deploy/config.env
# edit deploy/config.env — fill in API keys + MONGODB_URI  (config.env is gitignored)
```

## Bring the whole stack up
```bash
bash deploy/up.sh
```
Runs in dependency order, writing each new IP into `deploy/state.env` so the next
service wires to it automatically:

```
registry → observability → agents → fares-nj → fares-frankfurt → exchange → register-agents
```

## One service at a time
```bash
bash deploy/up.sh agents        # (its upstreams must already be in state.env)
bash deploy/20-agents.sh        # same thing, directly
```

## Tear down
```bash
bash deploy/down.sh             # delete ALL MBTA Linodes (prompts), clears state.env
bash deploy/down.sh agents      # just one
FORCE=1 bash deploy/down.sh     # no prompt
```
Firewalls + SSH keys are kept and reused on the next `up.sh`.

## How it works
- **`config.env`** — your secrets + Linode region/plan + instance labels. Gitignored.
- **`state.env`** — generated; the captured public IPs (`REGISTRY_IP`, `AGENTS_IP`, …). Gitignored.
- **`_lib.sh`** — shared: idempotent `ensure_linode` (find-or-create **by label**, so
  re-running never duplicates), firewall/ssh-key helpers, `state_set` (capture IP),
  `render` (fills `${REGISTRY_IP}` etc. into supervisor templates via `envsubst`).
- **`templates/<svc>/*.conf`** — supervisor configs with `${...}` placeholders. **No secrets
  committed** — real values are substituted at deploy time and land only on the server.
- **`NN-<svc>.sh`** — per-service: create/reuse Linode → capture IP → package code →
  provision (venv/docker) → render+install supervisor configs → health check.

## Idempotency & redeploy
Everything keys off the Linode **label** (`LABEL_*` in `config.env`). Re-running a script
reuses the same instance; `down.sh` then `up.sh` gives a clean rebuild with fresh IPs that
propagate everywhere automatically.

## Services
| Script | Host | Ports | Needs |
|---|---|---|---|
| `10-registry.sh` | Northeastern registry | 6900 | MONGODB_URI |
| `40-observability.sh` | Jaeger/Grafana/ClickHouse/OTEL | 16686/3001/8123/4317 | — |
| `20-agents.sh` | alerts/planner/stopfinder + auth-ns | 8001-3 / 8300 | REGISTRY_IP |
| `50-fares-nj.sh` | fares (us-east) | 50054 | REGISTRY_IP |
| `60-fares-frankfurt.sh` | fares (eu-central) | 50054 | REGISTRY_IP |
| `30-exchange.sh` | exchange + frontend + resolver | 8100/3000/8200 | REGISTRY_IP, AGENTS_IP, OBS_IP |
| `register-agents.sh` | (no host) registers agents into registry | — | REGISTRY_IP, AGENTS_IP |

> Note: DANS naming server + prompt firewall live in the **separate `dans` repo**
> (`DataWorksAI-com/dans`, deployed via its own `scripts/deploy.sh`). This tooling covers
> the MBTA app side only.
