/**
 * MongoDB script: add agent_name (ANS URN) to existing agent documents.
 *
 * Run on the registry server (97.107.132.213):
 *   mongosh "mongodb://localhost:27017/nanda_private_registry" deploy/mongodb_update_urns.js
 *
 * Or with auth:
 *   mongosh "$MONGODB_URI" deploy/mongodb_update_urns.js
 */

const TLD = "agents.dataworksai.com";
const APP = "mbta-transit-ci";

const updates = [
    { agent_id: "mbta-alerts",     agent_name: `urn:${TLD}:${APP}:alerts`     },
    { agent_id: "mbta-planner",    agent_name: `urn:${TLD}:${APP}:planner`    },
    { agent_id: "mbta-stopfinder", agent_name: `urn:${TLD}:${APP}:stopfinder` },
];

print("Updating agent documents with ANS URNs...");

for (const { agent_id, agent_name } of updates) {
    const result = db.agents.updateOne(
        { agent_id },
        { $set: { agent_name } }
    );
    if (result.matchedCount === 0) {
        print(`  ⚠️  Not found: ${agent_id}`);
    } else {
        print(`  ✅ Updated: ${agent_id} → ${agent_name}`);
    }
}

// Verify
print("\nVerification:");
db.agents.find(
    { agent_id: { $in: updates.map(u => u.agent_id) } },
    { agent_id: 1, agent_name: 1, _id: 0 }
).forEach(doc => print(`  ${doc.agent_id}: ${doc.agent_name || "(missing)"}`));
