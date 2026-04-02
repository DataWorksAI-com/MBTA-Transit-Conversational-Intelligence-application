#!/usr/bin/env bash
# Register mbta-boston-weather-agent with the NANDA registry (local or cluster port-forward).
#
# agent_url must be reachable from the Exchange container. With Docker Compose, use the service name:
#   REGISTRY_URL=http://localhost:6900 WEATHER_AGENT_URL=http://weather-agent:8004 bash scripts/register_weather_agent.sh
#
# Health check uses WEATHER_AGENT_URL; use http://localhost:8004 when the weather port is published to the host.

set -eu

REGISTRY_URL="${REGISTRY_URL:-http://localhost:6900}"
REGISTRY_URL="${REGISTRY_URL%/}"
WEATHER_AGENT_URL="${WEATHER_AGENT_URL:-http://weather-agent:8004}"
WEATHER_HEALTH_URL="${WEATHER_HEALTH_URL:-http://localhost:8004}"
WEATHER_AGENT_URL="${WEATHER_AGENT_URL%/}"
WEATHER_HEALTH_URL="${WEATHER_HEALTH_URL%/}"

echo "Waiting for weather agent /health (ready=true) at ${WEATHER_HEALTH_URL}..."
attempt=1
max_attempts=24
while [ "$attempt" -le "$max_attempts" ]; do
  response="$(curl -fsS --max-time 5 "${WEATHER_HEALTH_URL}/health" 2>/dev/null || true)"
  if [ -n "$response" ] && echo "$response" | grep -Eq '"ready"[[:space:]]*:[[:space:]]*true'; then
    echo "Weather agent is ready."
    break
  fi
  echo "Not ready yet ($attempt/$max_attempts), sleeping 5s..."
  attempt=$((attempt + 1))
  sleep 5
done

if [ "$attempt" -gt "$max_attempts" ]; then
  echo "Timed out waiting for ${WEATHER_HEALTH_URL}/health" >&2
  exit 1
fi

echo "POST ${REGISTRY_URL}/register ..."
curl -fsS -X POST "${REGISTRY_URL}/register" \
  -H "Content-Type: application/json" \
  -d "{
    \"agent_id\": \"mbta-boston-weather-agent\",
    \"name\": \"MBTA Boston Weather Agent\",
    \"description\": \"Analyzes Boston-area weather impacts on MBTA transit (snow, ice, freezing rain, wind, flooding, heat, cold). Provides rider-facing commute risk guidance and operational risk context for subway, bus, commuter rail, and ferry.\",
    \"capabilities\": [\"weather\", \"commute_risk\", \"transit_weather\", \"boston_forecast\", \"service_risk\"],
    \"agent_url\": \"${WEATHER_AGENT_URL}\",
    \"protocol\": \"a2a\",
    \"transport\": \"http\"
  }"

echo ""
echo "PUT ${REGISTRY_URL}/agents/mbta-boston-weather-agent/status ..."
curl -fsS -X PUT "${REGISTRY_URL}/agents/mbta-boston-weather-agent/status" \
  -H "Content-Type: application/json" \
  -d '{
    "alive": true,
    "capabilities": ["weather", "commute_risk", "transit_weather", "boston_forecast", "service_risk"],
    "description": "Analyzes Boston-area weather impacts on MBTA transit (snow, ice, freezing rain, wind, flooding, heat, cold). Provides rider-facing commute risk guidance and operational risk context for subway, bus, commuter rail, and ferry."
  }'

echo ""
echo "Done."
