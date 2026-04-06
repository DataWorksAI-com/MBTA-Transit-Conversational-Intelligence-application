"""
Northeastern Registry v4.0 - Semantic Agent Discovery
Production ready registry side filtering for scalable agent discovery
"""

from flask import Flask, request, jsonify
import os
from datetime import datetime
from flask_cors import CORS
from typing import Any, Dict, List, Tuple
import re

TEST_MODE = os.getenv("TEST_MODE") == "1"

if not TEST_MODE:
    from pymongo import MongoClient

app = Flask(__name__)
CORS(app)

DEFAULT_PORT = 6900

MONGO_URI = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
MONGO_DBNAME = os.getenv("MONGODB_DB", "nanda_private_registry")

if not TEST_MODE:
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        mongo_db = mongo_client[MONGO_DBNAME]
        agent_registry_col = mongo_db.get_collection("agents")
        client_registry_col = mongo_db.get_collection("client_registry")
        users_col = mongo_db.get_collection("users")
        mcp_registry_col = mongo_db.get_collection("mcp_registry")
        messages_col = mongo_db.get_collection("messages")
        USE_MONGO = True
        print("✅ MongoDB connected")
    except Exception as e:
        USE_MONGO = False
        agent_registry_col = None
        client_registry_col = None
        users_col = None
        mcp_registry_col = None
        messages_col = None
        print(f"⚠️  MongoDB unavailable: {e}")
else:
    USE_MONGO = False
    agent_registry_col = None
    client_registry_col = None
    users_col = None
    mcp_registry_col = None
    messages_col = None

registry = {"agent_status": {}}
client_registry = {"agent_map": {}}

# Load from MongoDB
if not TEST_MODE and USE_MONGO and agent_registry_col is not None:
    try:
        for doc in agent_registry_col.find():
            agent_id = doc.get("agent_id")
            if not agent_id:
                continue
            registry[agent_id] = doc.get("agent_url")
            registry["agent_status"][agent_id] = {
                "alive": doc.get("alive", False),
                "assigned_to": doc.get("assigned_to"),
                "last_update": doc.get("last_update"),
                "api_url": doc.get("api_url"),
                "description": doc.get("description", ""),
                "capabilities": doc.get("capabilities", []),
                "tags": doc.get("tags", [])
            }
        print(f"📚 Loaded {len(registry) - 1} agents")
    except Exception as e:
        print(f"⚠️  Error loading agents: {e}")

if not TEST_MODE and USE_MONGO and client_registry_col is not None:
    try:
        for doc in client_registry_col.find():
            client_name = doc.get("client_name")
            if not client_name:
                continue
            client_registry[client_name] = doc.get("api_url")
            client_registry["agent_map"][client_name] = doc.get("agent_id")
        print(f"👥 Loaded {len(client_registry) - 1} clients")
    except Exception as e:
        print(f"⚠️  Error loading clients: {e}")


def save_client_registry():
    if TEST_MODE or not USE_MONGO or client_registry_col is None:
        return
    try:
        for client_name, api_url in client_registry.items():
            if client_name == 'agent_map':
                continue
            agent_id = client_registry.get('agent_map', {}).get(client_name)
            client_registry_col.update_one(
                {"client_name": client_name},
                {"$set": {"api_url": api_url, "agent_id": agent_id}},
                upsert=True,
            )
    except Exception as e:
        print(f"⚠️  Error saving clients: {e}")


def save_registry():
    if TEST_MODE or not USE_MONGO or agent_registry_col is None:
        return
    try:
        for agent_id, agent_url in registry.items():
            if agent_id == 'agent_status':
                continue
            status = registry.get('agent_status', {}).get(agent_id, {})
            mongo_doc = {
                "agent_id": agent_id,
                "agent_url": agent_url,
                **status
            }
            agent_registry_col.update_one(
                {"agent_id": agent_id},
                {"$set": mongo_doc},
                upsert=True,
            )
    except Exception as e:
        print(f"⚠️  Error saving registry: {e}")


# ============================================================================
# SEMANTIC SEARCH - KEYWORD MATCHING + RELEVANCE SCORING
# ============================================================================

def normalize_text(text: str) -> str:
    """Normalize text for matching"""
    return re.sub(r'[^a-z0-9\s]', ' ', text.lower()).strip()


def extract_keywords(query: str) -> List[str]:
    """Extract meaningful keywords from query"""
    text = normalize_text(query)
    
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'i', 'you', 'he', 'she', 'it', 'we',
        'they', 'this', 'that', 'these', 'those', 'what', 'which', 'who',
        'when', 'where', 'why', 'how', 'my', 'your', 'get', 'find', 'need',
        'want', 'tell', 'me', 'about'
    }
    
    words = [w for w in text.split() if w not in stopwords and len(w) > 2]
    return words


def calculate_relevance_score(
    query: str,
    agent_id: str,
    description: str,
    capabilities: List[str],
    tags: List[str]
) -> Tuple[float, str]:
    """
    Calculate relevance score for agent based on query
    Returns: (score, reason)
    """
    query_keywords = extract_keywords(query)
    if not query_keywords:
        return 0.0, "no_keywords"
    
    score = 0.0
    match_details = []
    
    # Agent ID matching (weight: 2.0)
    agent_id_norm = normalize_text(agent_id)
    for keyword in query_keywords:
        if keyword in agent_id_norm:
            score += 2.0
            match_details.append(f"id:{keyword}")
    
    # Description matching (weight: 1.5)
    if description:
        desc_norm = normalize_text(description)
        for keyword in query_keywords:
            if keyword in desc_norm:
                score += 1.5
                match_details.append(f"desc:{keyword}")
    
    # Capabilities matching (weight: 3.0 highest priority)
    if capabilities:
        for cap in capabilities:
            cap_norm = normalize_text(cap)
            for keyword in query_keywords:
                if keyword in cap_norm:
                    score += 3.0
                    match_details.append(f"cap:{keyword}")
    
    # Tags matching (weight: 1.0)
    if tags:
        for tag in tags:
            tag_norm = normalize_text(tag)
            for keyword in query_keywords:
                if keyword in tag_norm:
                    score += 1.0
                    match_details.append(f"tag:{keyword}")
    
    # Exact phrase matching bonus
    query_norm = normalize_text(query)
    if description and query_norm in normalize_text(description):
        score += 5.0
        match_details.append("exact_phrase")
    
    reason = ",".join(match_details) if match_details else "no_match"
    return score, reason


def _build_agent_payload(agent_id: str) -> Dict[str, Any]:
    agent_url = registry.get(agent_id)
    status_obj = registry.get('agent_status', {}).get(agent_id, {})
    return {
        'agent_id': agent_id,
        'agent_url': agent_url,
        'api_url': status_obj.get('api_url'),
        'alive': status_obj.get('alive', False),
        'assigned_to': status_obj.get('assigned_to'),
        'last_update': status_obj.get('last_update'),
        'capabilities': status_obj.get('capabilities', []),
        'tags': status_obj.get('tags', []),
        'description': status_obj.get('description', '')
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "version": "4.0.0",
        "mongo": USE_MONGO and not TEST_MODE,
        "semantic_search": True,
        "timestamp": datetime.now().isoformat()
    })


@app.route('/stats', methods=['GET'])
def stats():
    agents = [a for a in registry.keys() if a != 'agent_status']
    total_agents = len(agents)
    alive_agents = 0
    if 'agent_status' in registry:
        alive_agents = sum(1 for a in agents if registry['agent_status'].get(a, {}).get('alive'))
    total_clients = len([c for c in client_registry.keys() if c != 'agent_map'])
    return jsonify({
        'version': '4.0.0',
        'total_agents': total_agents,
        'alive_agents': alive_agents,
        'total_clients': total_clients,
        'mongodb_enabled': USE_MONGO and not TEST_MODE,
        'semantic_search_enabled': True
    })


@app.route('/search/semantic', methods=['POST'])
def semantic_search():
    """
    PRODUCTION SEMANTIC SEARCH
    
    POST /search/semantic
    {
        "query": "find transit planning agents",
        "max_results": 5,
        "alive_only": true
    }
    
    Returns top N agents ranked by relevance
    """
    data = request.json or {}
    query = data.get('query', '').strip()
    max_results = int(data.get('max_results', 5))
    alive_only = data.get('alive_only', True)
    
    if not query:
        return jsonify({"error": "query parameter required"}), 400
    
    if max_results < 1 or max_results > 20:
        return jsonify({"error": "max_results must be between 1 and 20"}), 400
    
    agent_ids = [a for a in registry.keys() if a != 'agent_status']
    
    if alive_only:
        agent_ids = [
            a for a in agent_ids 
            if registry.get('agent_status', {}).get(a, {}).get('alive', False)
        ]
    
    scored_agents: List[Tuple[str, float, str]] = []
    
    for agent_id in agent_ids:
        status = registry.get('agent_status', {}).get(agent_id, {})
        description = status.get('description', '')
        capabilities = status.get('capabilities', [])
        tags = status.get('tags', [])
        
        score, reason = calculate_relevance_score(
            query, agent_id, description, capabilities, tags
        )
        
        scored_agents.append((agent_id, score, reason))
    
    scored_agents.sort(key=lambda x: x[1], reverse=True)
    
    top_agents = [(aid, score, reason) for aid, score, reason in scored_agents if score > 0][:max_results]
    
    results = []
    for agent_id, score, reason in top_agents:
        payload = _build_agent_payload(agent_id)
        payload['relevance_score'] = score
        payload['match_reason'] = reason
        results.append(payload)
    
    return jsonify({
        'query': query,
        'total_candidates': len(agent_ids),
        'filtered_count': len(scored_agents),
        'returned_count': len(results),
        'results': results
    })


@app.route('/search', methods=['GET'])
def search_agents():
    """Legacy simple search endpoint"""
    query = request.args.get('q', '').strip().lower()
    capabilities_filter = request.args.get('capabilities')
    tags_filter = request.args.get('tags')
    
    capabilities_list = [c.strip() for c in capabilities_filter.split(',')] if capabilities_filter else []
    tags_list = [t.strip() for t in tags_filter.split(',')] if tags_filter else []

    results: List[Dict[str, Any]] = []
    for agent_id in registry.keys():
        if agent_id == 'agent_status':
            continue
        if query and query not in agent_id.lower():
            continue
        
        payload = _build_agent_payload(agent_id)
        
        if capabilities_list:
            agent_caps = payload.get('capabilities', []) or []
            if not any(c in agent_caps for c in capabilities_list):
                continue
        
        if tags_list:
            agent_tags = payload.get('tags', []) or []
            if not any(t in agent_tags for t in tags_list):
                continue
        
        results.append(payload)
    
    return jsonify(results)


@app.route('/agents/<agent_id>', methods=['GET'])
def get_agent(agent_id):
    if agent_id not in registry or agent_id == 'agent_status':
        return jsonify({'error': 'Agent not found'}), 404
    return jsonify(_build_agent_payload(agent_id))


@app.route('/agents/<agent_id>', methods=['DELETE'])
def delete_agent(agent_id):
    if agent_id not in registry or agent_id == 'agent_status':
        return jsonify({'error': 'Agent not found'}), 404
    
    registry.pop(agent_id, None)
    if 'agent_status' in registry:
        registry['agent_status'].pop(agent_id, None)
    
    to_remove = []
    for client_name, mapped_agent in client_registry.get('agent_map', {}).items():
        if mapped_agent == agent_id:
            to_remove.append(client_name)
    
    for client_name in to_remove:
        client_registry.pop(client_name, None)
        client_registry.get('agent_map', {}).pop(client_name, None)
    
    save_registry()
    save_client_registry()
    
    return jsonify({'status': 'deleted', 'agent_id': agent_id})


@app.route('/agents/<agent_id>/status', methods=['PUT'])
def update_agent_status(agent_id):
    if agent_id not in registry or agent_id == 'agent_status':
        return jsonify({'error': 'Agent not found'}), 404
    
    data = request.json or {}
    status_obj = registry.get('agent_status', {}).get(agent_id, {})
    
    if 'alive' in data:
        status_obj['alive'] = bool(data['alive'])
    if 'assigned_to' in data:
        status_obj['assigned_to'] = data['assigned_to']
    
    status_obj['last_update'] = datetime.now().isoformat()
    
    if 'capabilities' in data and isinstance(data['capabilities'], list):
        status_obj['capabilities'] = data['capabilities']
    if 'tags' in data and isinstance(data['tags'], list):
        status_obj['tags'] = data['tags']
    if 'description' in data and isinstance(data['description'], str):
        status_obj['description'] = data['description']
    
    registry['agent_status'][agent_id] = status_obj
    save_registry()
    
    return jsonify({'status': 'updated', 'agent': _build_agent_payload(agent_id)})


@app.route('/register', methods=['POST'])
def register():
    data = request.json
    if not data or 'agent_id' not in data or 'agent_url' not in data:
        return jsonify({"error": "Missing agent_id or agent_url"}), 400

    agent_id = data['agent_id']
    agent_url = data['agent_url']
    api_url = data.get('api_url')
    description = data.get('description', '')
    capabilities = data.get('capabilities', [])
    tags = data.get('tags', [])

    registry[agent_id] = agent_url

    if 'agent_status' not in registry:
        registry['agent_status'] = {}

    registry['agent_status'][agent_id] = {
        'alive': False,
        'assigned_to': None,
        'api_url': api_url,
        'description': description,
        'capabilities': capabilities,
        'tags': tags,
        'last_update': datetime.now().isoformat()
    }

    save_registry()
    print(f"✅ Registered: {agent_id}")

    return jsonify({"status": "success", "message": f"Agent {agent_id} registered"})


@app.route('/lookup/<id>', methods=['GET'])
def lookup(id):
    if id in registry and id != 'agent_status':
        agent_url = registry[id]
        status_obj = registry['agent_status'].get(id, {})
        api_url = status_obj.get('api_url')
        description = status_obj.get('description', '')
        return jsonify({
            "agent_id": id,
            "agent_url": agent_url,
            "api_url": api_url,
            "description": description
        })

    if id in client_registry:
        agent_id = client_registry["agent_map"][id]
        agent_url = registry[agent_id]
        api_url = client_registry[id]
        status_obj = registry['agent_status'].get(agent_id, {})
        description = status_obj.get('description', '')
        return jsonify({
            "agent_id": agent_id,
            "agent_url": agent_url,
            "api_url": api_url,
            "description": description
        })

    return jsonify({"error": f"ID '{id}' not found"}), 404


@app.route('/list', methods=['GET'])
def list_agents():
    result = {k: v for k, v in registry.items() if k != 'agent_status'}
    return jsonify(result)


@app.route('/clients', methods=['GET'])
def list_clients():
    result = {k: 'alive' for k, v in client_registry.items() if k != 'agent_map'}
    return jsonify(result)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', DEFAULT_PORT))
    print(f"🚀 Northeastern Registry v4.0 (Semantic Discovery) on port {port}")
    app.run(host='0.0.0.0', port=port)