# Pass/Fail Vs Expected Path/Agent

Generated: 2026-03-07T02:16:52.358053

Total checks: 189  
Overall pass: 175/189

## AUTO
- Pass: 49/63
- Path failures: 10
- Agent-rule failures: 13

## MCP
- Pass: 63/63
- Path failures: 0
- Agent-rule failures: 0

## A2A
- Pass: 63/63
- Path failures: 0
- Agent-rule failures: 0

## Auto Mode Failures (Expected Categories)
- Query: `What are all the alerts on Red Line?` | expected path `a2a` got `mcp` | expected agents `mbta-alerts` (exact) got ``
- Query: `Show me all current MBTA service disruptions` | expected path `a2a` got `mcp` | expected agents `mbta-alerts` (exact) got ``
- Query: `Are there any Green Line delays right now?` | expected path `a2a` got `mcp` | expected agents `mbta-alerts` (exact) got ``
- Query: `Check Orange and Blue Line status` | expected path `a2a` got `mcp` | expected agents `mbta-alerts` (exact) got ``
- Query: `Where is Copley station?` | expected path `a2a` got `mcp` | expected agents `mbta-stopfinder` (exact) got ``
- Query: `Show me all Orange Line stops` | expected path `a2a` got `mcp` | expected agents `mbta-stopfinder` (exact) got ``
- Query: `What station is closest to Northeastern University?` | expected path `a2a` got `mcp` | expected agents `mbta-stopfinder` (exact) got ``
- Query: `List all Green Line stations` | expected path `a2a` got `mcp` | expected agents `mbta-stopfinder` (exact) got ``
- Query: `Is it worth waiting for Red Line to resume or should I take Orange?` | expected path `a2a` got `a2a` | expected agents `mbta-alerts` (exact) got `mbta-alerts,mbta-planner`
- Query: `What are the Red Line alerts?` | expected path `a2a` got `mcp` | expected agents `mbta-alerts` (exact) got ``
- Query: `Route from Park to Kendall` | expected path `a2a` got `a2a` | expected agents `mbta-alerts,mbta-planner` (exact) got `mbta-stopfinder,mbta-alerts,mbta-planner`
- Query: `Hello!` | expected path `shortcut` got `a2a` | expected agents `` (n/a) got ``
- Query: `Route from Park to Harvard` | expected path `a2a` got `a2a` | expected agents `mbta-alerts,mbta-planner` (exact) got `mbta-stopfinder,mbta-alerts,mbta-planner`
- Query: `Fenway Park to South Station` | expected path `a2a` got `a2a` | expected agents `mbta-stopfinder,mbta-alerts,mbta-planner` (contains_all) got `mbta-alerts,mbta-planner`
