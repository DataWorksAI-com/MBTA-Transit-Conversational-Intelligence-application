from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import asyncio
import httpx
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

app = FastAPI(title="MBTA Chat UI")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
EXCHANGE_AGENT_URL = "http://localhost:8100"

# Mount static files for images
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/js/visualization_3d.js")
async def serve_viz_js():
    """Serve visualization JS with no-cache headers so updates always reflect immediately."""
    js_path = Path(__file__).parent / "static" / "visualization_3d.js"
    return FileResponse(
        str(js_path),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket connection. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
    
    async def send_message(self, message: Dict, websocket: WebSocket):
        await websocket.send_json(message)

manager = ConnectionManager()

@app.get("/")
async def get_ui():
    """Serve the enhanced chat UI with real time weather effects and protocol override"""
    # ANS infrastructure display values — read from env at request time, no hardcoded IPs
    import os as _os
    _ans_resolver_url = _os.getenv("ANS_RESOLVER_URL", "http://localhost:8200")
    _ans_registry_url = _os.getenv("REGISTRY_URL", "http://localhost:6900")
    _ans_agent_host = _os.getenv("AGENT_HOST", "localhost")
    _ans_resolver_display = _ans_resolver_url.replace("http://", "").replace("https://", "")
    _ans_registry_display = _ans_registry_url.replace("http://", "").replace("https://", "")
    _ans_authns_display = _ans_agent_host + ":8300"
    _ans_dans_url = _os.getenv("AGENTNS_URL", _os.getenv("ANS_RESOLVER_URL", "http://97.107.132.213/dans"))
    _ans_dans_display = _ans_dans_url.replace("http://", "").replace("https://", "")
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MBTA Agntcy Transit Intelligence</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-image: url('/static/bgbg.jpg');
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
            background-repeat: no-repeat;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
            position: relative;
            overflow: hidden;
        }
        
        /* Subtle overlay for better contrast */
        body::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: radial-gradient(circle at top, rgba(102,126,234,0.1) 0%, rgba(118,75,162,0.2) 100%);
            pointer-events: none;
            z-index: 0;
        }

        /* Weather Canvas */
        #weatherCanvas {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            z-index: 1;
        }

        .container {
            width: 100%;
            max-width: 1400px;
            height: 90vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 0;
            overflow: hidden;
            position: relative;
            z-index: 2;
        }


        /* ========================================================== */
        /* CHAT PANEL (MIDDLE) */
        /* ========================================================== */

        /* Left Panel Chat */
        .chat-panel {
            display: grid;
            grid-template-rows: auto 1fr auto auto;
            height: 100%;
            border-right: 1px solid #e0e0e0;
            min-height: 0;
        }

        .chat-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 30px;
            font-size: 24px;
            font-weight: bold;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: 15px;
        }

        .weather-indicator {
            font-size: 28px;
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }

        .connection-status {
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 12px;
            background: rgba(255,255,255,0.2);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ff4444;
        }

        .status-dot.connected {
            background: #00ff88;
        }

        .messages-container {
            overflow-y: auto;
            overflow-x: hidden;
            padding: 20px 30px;
            background: #f8f9fa;
            min-height: 0;
        }

        .message {
            margin-bottom: 20px;
            animation: slideIn 0.3s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .message.user {
            text-align: right;
        }

        .message-content {
            display: inline-block;
            max-width: 85%;
            padding: 12px 18px;
            border-radius: 18px;
            word-wrap: break-word;
        }

        .message.user .message-content {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-bottom-right-radius: 4px;
        }

        .message.assistant .message-content {
            background: white;
            color: #333;
            border: 1px solid #e0e0e0;
            border-bottom-left-radius: 4px;
            text-align: left;
        }

        .message.system {
            text-align: center;
        }

        .message.system .message-content {
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffeaa7;
            font-size: 13px;
            padding: 8px 14px;
        }

        /* Protocol Override Controls */
        .protocol-controls {
            padding: 15px 30px;
            background: rgba(255, 255, 255, 0.95);
            border-top: 1px solid #e0e0e0;
            display: flex;
            align-items: center;
            gap: 10px;
            backdrop-filter: blur(10px);
            flex-shrink: 0;
        }

        .protocol-label {
            font-size: 13px;
            font-weight: 600;
            color: #333;
        }

        .protocol-button {
            padding: 8px 16px;
            border: 2px solid #d0d0d0;
            background: white;
            border-radius: 8px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .protocol-button:hover {
            background: #f8f9fa;
            border-color: #667eea;
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(102, 126, 234, 0.2);
        }

        .protocol-button.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-color: #667eea;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        .protocol-button.active:hover {
            background: linear-gradient(135deg, #5568d3 0%, #653a8b 100%);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.5);
        }

        .protocol-icon {
            font-size: 14px;
        }

        /* Input Area */
        .input-area {
            padding: 20px 30px;
            background: white;
            border-top: 1px solid #e0e0e0;
            flex-shrink: 0;
        }

        .input-container {
            display: flex;
            gap: 10px;
        }

        #messageInput {
            flex: 1;
            padding: 14px 18px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.3s;
        }

        #messageInput:focus {
            border-color: #667eea;
        }

        #sendButton {
            padding: 14px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }

        #sendButton:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }

        #sendButton:active {
            transform: translateY(0);
        }

        #sendButton:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        /* ========================================================== */
        /* RIGHT PANEL: SYSTEM INTERNALS */
        /* ========================================================== */

        /* Right Panel System Internals */
        .internals-panel {
            background: #1a1a2e;
            color: #eee;
            display: grid;
            grid-template-rows: auto 1fr;
            height: 100%;
            min-height: 0;
        }

        .internals-header {
            padding: 20px;
            background: #16213e;
            border-bottom: 1px solid #2a2a4e;
            flex-shrink: 0;
        }

        .internals-title {
            font-size: 18px;
            font-weight: bold;
            color: #fff;
            margin-bottom: 8px;
        }

        .internals-subtitle {
            font-size: 12px;
            color: #888;
        }

        .weather-info {
            margin-top: 10px;
            padding: 10px 14px;
            background: rgba(78, 205, 196, 0.15);
            border-left: 3px solid #4ecdc4;
            border-radius: 6px;
            font-size: 12px;
            backdrop-filter: blur(8px);
        }

        .weather-info-title {
            font-weight: 600;
            color: #4ecdc4;
            margin-bottom: 6px;
            font-size: 13px;
        }

        .weather-info-detail {
            color: #d0d0d0;
            font-size: 11px;
            line-height: 1.4;
        }

        .internals-content {
            overflow-y: auto;
            overflow-x: hidden;
            padding: 20px;
            min-height: 0;
        }

        .info-block {
            background: #16213e;
            border: 1px solid #2a2a4e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }

        .info-label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }

        .info-value {
            font-size: 14px;
            color: #fff;
            font-weight: 500;
        }

        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            margin-right: 6px;
            margin-bottom: 6px;
        }

        .badge.mcp {
            background: #4ecdc4;
            color: #1a1a2e;
        }

        .badge.a2a {
            background: #ff6b6b;
            color: white;
        }

        .badge.shortcut {
            background: #95e1d3;
            color: #1a1a2e;
        }

        .badge.fallback {
            background: #ffa07a;
            color: #1a1a2e;
        }

        .badge.firewall {
            background: #e74c3c;
            color: white;
            animation: pulseBadge 1.5s infinite;
        }

        .badge.override {
            background: #ffd93d;
            color: #1a1a2e;
            animation: pulseBadge 1.5s infinite;
        }

        @keyframes pulseBadge {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .latency-bar {
            height: 6px;
            background: #2a2a4e;
            border-radius: 3px;
            margin-top: 8px;
            overflow: hidden;
        }

        .latency-fill {
            height: 100%;
            background: linear-gradient(90deg, #4ecdc4, #667eea);
            border-radius: 3px;
            transition: width 0.5s ease;
        }

        .agent-list {
            list-style: none;
        }

        .agent-item {
            padding: 8px 0;
            border-bottom: 1px solid #2a2a4e;
            font-size: 13px;
        }

        .agent-item:last-child {
            border-bottom: none;
        }

        /* ANS Resolution Trace */
        .ans-block {
            background: linear-gradient(135deg, #0d1b2e 0%, #0a2240 100%);
            border: 1px solid #1a4a7a;
            border-radius: 10px;
            padding: 14px;
            margin-bottom: 15px;
        }
        .ans-title {
            font-size: 11px;
            font-weight: 700;
            color: #4ecdc4;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .ans-agent-section {
            margin-bottom: 12px;
        }
        .ans-agent-section:last-child { margin-bottom: 0; }
        .ans-urn {
            font-family: 'Courier New', monospace;
            font-size: 9.5px;
            color: #a0c8f0;
            margin-bottom: 8px;
            word-break: break-all;
            opacity: 0.85;
        }
        .ans-hop {
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 5px 0;
            font-size: 11px;
            border-left: 2px solid #1a4a7a;
            padding-left: 10px;
            margin-left: 6px;
            position: relative;
        }
        .ans-hop::before {
            content: '↓';
            position: absolute;
            left: -8px;
            color: #4ecdc4;
            font-size: 12px;
            line-height: 1;
        }
        .ans-hop-label {
            color: #aaa;
            flex-shrink: 0;
            min-width: 90px;
        }
        .ans-hop-addr {
            color: #e0e0ff;
            font-family: 'Courier New', monospace;
            font-size: 10px;
        }
        .ans-hop-final {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 7px 10px;
            background: rgba(78,205,196,0.12);
            border: 1px solid rgba(78,205,196,0.3);
            border-radius: 6px;
            margin-top: 4px;
            margin-left: 6px;
            font-size: 11px;
        }
        .ans-hop-final .endpoint { color: #4ecdc4; font-family: monospace; font-size: 10.5px; }
        .ans-badge {
            font-size: 9px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 8px;
            text-transform: uppercase;
        }
        .ans-badge.cached  { background: #1a4a1a; color: #4ecdc4; border: 1px solid #4ecdc4; }
        .ans-badge.live    { background: #3a1a1a; color: #ff9f43; border: 1px solid #ff9f43; }
        .ans-badge.foreign { background: #3a1a3a; color: #a29bfe; border: 1px solid #a29bfe;
                             animation: pulseBadge 2s infinite; }
        .ans-latency { color: #888; font-size: 10px; margin-left: auto; }
        @keyframes ansSlideIn {
            from { opacity: 0; transform: translateY(-6px); }
            to   { opacity: 1; transform: translateY(0); }
        }
        .ans-agent-section { animation: ansSlideIn 0.3s ease; }

        /* Cross-region foreign agent panel */
        .foreign-agent-block {
            background: linear-gradient(135deg, #1a0a2e 0%, #2a0a4a 100%);
            border: 1px solid #6c3fc4;
            border-radius: 10px;
            padding: 14px;
            margin-bottom: 15px;
            animation: ansSlideIn 0.4s ease;
        }
        .foreign-title {
            font-size: 11px;
            font-weight: 700;
            color: #a29bfe;
            text-transform: uppercase;
            letter-spacing: 1.2px;
            margin-bottom: 12px;
        }
        .geo-route {
            display: flex;
            align-items: stretch;
            gap: 0;
            margin: 10px 0;
            font-size: 12px;
        }
        .geo-node {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 3px;
            flex: 1;
        }
        .geo-flag { font-size: 20px; line-height: 1; }
        .geo-city {
            font-size: 10px;
            font-weight: 700;
            color: #e0e0ff;
            text-align: center;
        }
        .geo-role {
            font-size: 9px;
            color: #888;
            text-align: center;
        }
        .geo-arrow {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 0 6px;
            flex-shrink: 0;
        }
        .geo-arrow-line {
            width: 40px;
            height: 2px;
            background: linear-gradient(90deg, #4ecdc4, #a29bfe);
            position: relative;
        }
        .geo-arrow-line::after {
            content: '';
            position: absolute;
            right: -4px;
            top: -4px;
            border: 4px solid transparent;
            border-left-color: #a29bfe;
        }
        .geo-km { font-size: 9px; color: #a29bfe; margin-top: 3px; }
        .foreign-endpoint {
            background: rgba(162,155,254,0.1);
            border: 1px solid rgba(162,155,254,0.35);
            border-radius: 6px;
            padding: 7px 10px;
            margin-top: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 11px;
        }
        .foreign-endpoint .ep-url {
            color: #a29bfe;
            font-family: monospace;
            font-size: 10px;
            flex: 1;
        }
        .foreign-urn {
            font-family: 'Courier New', monospace;
            font-size: 9px;
            color: #8080c0;
            margin-bottom: 8px;
            word-break: break-all;
        }
        .foreign-reason {
            font-size: 10px;
            color: #9090c0;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid rgba(162,155,254,0.2);
            line-height: 1.5;
        }
        .candidates-block {
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(162,155,254,0.2);
            border-radius: 6px;
            padding: 8px 10px;
            font-family: 'Courier New', monospace;
            font-size: 9.5px;
            line-height: 1.8;
        }
        .candidate-row { word-break: break-all; }

        /* Route Cards */
        .route-cards {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-top: 4px;
        }

        .route-card {
            background: #fff;
            border: 1px solid #e0e0e0;
            border-radius: 12px;
            padding: 14px 16px;
            border-left: 4px solid #667eea;
        }

        .route-card-header {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }

        .route-option-number {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 12px;
            font-weight: 700;
            padding: 3px 10px;
            border-radius: 10px;
        }

        .route-line-name {
            font-weight: 600;
            font-size: 14px;
            color: #333;
        }

        .route-stats {
            display: flex;
            gap: 16px;
            margin-bottom: 10px;
        }

        .route-stat {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .route-stat-label {
            font-size: 10px;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .route-stat-value {
            font-size: 13px;
            font-weight: 600;
            color: #444;
        }

        .route-divider {
            border: none;
            border-top: 1px solid #f0f0f0;
            margin: 8px 0;
        }

        .route-directions {
            font-size: 13px;
            color: #555;
            line-height: 1.5;
        }

        .route-intro {
            font-size: 14px;
            color: #333;
            margin-bottom: 10px;
        }

        /* Scrollbar styling */
        ::-webkit-scrollbar {
            width: 8px;
        }

        ::-webkit-scrollbar-track {
            background: #f1f1f1;
        }

        ::-webkit-scrollbar-thumb {
            background: #667eea;
            border-radius: 4px;
        }

        .internals-panel ::-webkit-scrollbar-track {
            background: #1a1a2e;
        }

        .internals-panel ::-webkit-scrollbar-thumb {
            background: #4ecdc4;
        }

        /* Little moving train at the bottom */
        .train-layer {
            position: fixed;
            bottom: 8px;
            left: 0;
            width: 100%;
            pointer-events: none;
            z-index: 3;
        }

        .train-track {
            position: relative;
            width: 100%;
            height: 40px;
        }

        .train-rail {
            position: absolute;
            bottom: 6px;
            left: 0;
            width: 100%;
            height: 4px;
            background: repeating-linear-gradient(
                to right,
                rgba(15, 23, 42, 0.7) 0,
                rgba(15, 23, 42, 0.7) 20px,
                transparent 20px,
                transparent 40px
            );
            opacity: 0.9;
        }

        .train {
            position: absolute;
            bottom: 14px;
            width: 80px;
            height: 26px;
            margin-left: -100px;
            background: #111827;
            border-radius: 8px;
            box-shadow: 0 4px 0 rgba(15, 23, 42, 0.8), 0 0 20px rgba(253, 224, 71, 0.3);
            animation: trainRide 15s linear infinite;
            border: 1px solid rgba(255, 255, 255, 0.2);
        }

        .train::before {
            content: "";
            position: absolute;
            left: 8px;
            top: 6px;
            width: 22px;
            height: 12px;
            background: #fde047;
            border-radius: 4px;
            box-shadow: 0 0 12px rgba(253, 224, 71, 0.8), 0 0 24px rgba(253, 224, 71, 0.4);
        }

        .train::after {
            content: "";
            position: absolute;
            bottom: -5px;
            left: 10px;
            width: 60px;
            height: 5px;
            background: repeating-linear-gradient(
                to right,
                #4b5563 0,
                #4b5563 6px,
                transparent 6px,
                transparent 12px
            );
        }

        @keyframes trainRide {
            0%   { transform: translateX(0); }
            100% { transform: translateX(110vw); }
        }

        @keyframes tpulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.25;transform:scale(0.7)} }
    </style>
</head>
<body>
    <canvas id="weatherCanvas"></canvas>

    <div class="container">
        

        
        <!-- MIDDLE PANEL: CHAT -->
        <div class="chat-panel">
            <div class="chat-header">
                <div class="header-left">
                    <span>🚇 MBTA Agntcy</span>
                    <span class="weather-indicator" id="weatherIcon">☁️</span>
                </div>
                <div class="connection-status">
                    <span class="status-dot" id="statusDot"></span>
                    <span id="statusText">Connecting...</span>
                </div>
            </div>

            <div class="messages-container" id="messagesContainer">
                <div class="message system">
                    <div class="message-content">
                        Welcome to MBTA Agntcy! Ask about transit alerts, routes, or stations.
                    </div>
                </div>
            </div>

            <div class="protocol-controls">
                <span class="protocol-label">Routing Mode:</span>
                <button class="protocol-button active" data-protocol="auto" onclick="selectProtocol('auto')">
                    <span class="protocol-icon">🤖</span>
                    <span>Auto</span>
                </button>
                <button class="protocol-button" data-protocol="mcp" onclick="selectProtocol('mcp')">
                    <span class="protocol-icon">⚡</span>
                    <span>MCP</span>
                </button>
                <button class="protocol-button" data-protocol="a2a" onclick="selectProtocol('a2a')">
                    <span class="protocol-icon">🔄</span>
                    <span>A2A</span>
                </button>
            </div>

            <div class="input-area">
                <div class="input-container">
                    <input 
                        type="text" 
                        id="messageInput" 
                        placeholder="Ask about MBTA alerts, routes, or stations..."
                        onkeypress="handleKeyPress(event)"
                    >
                    <button id="sendButton" onclick="sendMessage()">Send</button>
                </div>
            </div>
        </div>

        <!-- RIGHT PANEL: SYSTEM INTERNALS -->
        <div class="internals-panel">
            <div class="internals-header">
                <div class="internals-title">System Internals</div>
                <div class="internals-subtitle">Real time routing & execution metrics</div>
                <div class="weather-info" id="weatherInfo">
                    <div class="weather-info-title">Loading weather...</div>
                    <div class="weather-info-detail">Fetching Boston conditions...</div>
                </div>
            </div>

            <div class="internals-content" id="internalsContent">
                <div class="info-block">
                    <div class="info-label">Waiting for query...</div>
                    <div class="info-value" style="color: #888;">Send a message to see routing details</div>
                </div>
            </div>
        </div>
    </div>

        <!-- Floating Viz Button -->
    <button onclick="openVizFullscreen()" style="
        position: fixed;
        bottom: 80px;
        right: 30px;
        width: 70px;
        height: 70px;
        border-radius: 50%;
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        font-size: 36px;
        border: 3px solid rgba(255,255,255,0.3);
        cursor: pointer;
        box-shadow: 0 10px 30px rgba(102,126,234,0.6);
        z-index: 1000;
        transition: all 0.3s;
        display: flex;
        align-items: center;
        justify-content: center;
    " onmouseover="this.style.transform='scale(1.2) rotate(15deg)'" 
       onmouseout="this.style.transform='scale(1)'">
        🏢
    </button>
 
    <!-- Full-Screen 3D Office Overlay -->
    <div id="viz-fullscreen" style="
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: #1a1a2e;
        z-index: 9999;
        flex-direction: column;
    ">
        <!-- Header -->
        <div style="
            padding: 20px 30px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        ">
            <span style="font-size: 24px; font-weight: 600; color: white;">
                🏢 Live Agent Office - 3D Visualization
            </span>
            <button onclick="closeVizFullscreen()" style="
                padding: 12px 24px;
                border-radius: 8px;
                background: rgba(255,255,255,0.2);
                color: white;
                font-size: 16px;
                font-weight: 600;
                border: none;
                cursor: pointer;
                transition: all 0.2s;
            " onmouseover="this.style.background='rgba(255,255,255,0.3)'" 
               onmouseout="this.style.background='rgba(255,255,255,0.2)'">
                ✕ Close
            </button>
        </div>
        
        <!-- Canvas Container -->
        <div style="flex: 1; position: relative;">
            <canvas id="viz-fullscreen-canvas"></canvas>
            
            <!-- Status Display -->
            <div id="viz-fullscreen-status" style="
                position: absolute;
                top: 30px;
                left: 30px;
                background: rgba(30,30,46,0.95);
                border: 2px solid rgba(102,126,234,0.6);
                border-radius: 12px;
                padding: 20px 26px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.4);
                color: #667eea;
                font-size: 18px;
                font-weight: 600;
                max-width: 550px;
                text-shadow: 0 0 10px rgba(102,126,234,0.8);
            ">
                Ready - Robots will animate when you send queries
            </div>

            <!-- Thinking Panel -->
            <div id="viz-think-panel" style="display:none;position:absolute;bottom:110px;left:30px;width:340px;max-height:290px;background:rgba(8,11,24,0.93);border:1px solid #2a3560;border-radius:11px;overflow:hidden;z-index:10002;box-shadow:0 4px 24px rgba(0,0,0,0.5);">
                <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:rgba(15,20,50,0.95);border-bottom:1px solid #2a3560;">
                    <div id="viz-think-dot" style="width:7px;height:7px;border-radius:50%;background:#a371f7;"></div>
                    <span style="font-size:10.5px;font-weight:800;color:#a371f7;letter-spacing:0.6px;text-transform:uppercase;">Exchange Reasoning</span>
                    <span id="viz-think-badge" style="display:none;margin-left:auto;font-size:9px;font-weight:800;padding:2px 8px;border-radius:99px;"></span>
                </div>
                <div id="viz-think-body" style="padding:10px 12px;font-size:11px;line-height:1.7;color:#b0bac8;font-family:'Consolas','Courier New',monospace;white-space:pre-wrap;word-break:break-word;overflow-y:auto;max-height:238px;"></div>
            </div>

            <!-- Agent Legend -->
            <div style="
                position: absolute;
                top: 30px;
                right: 30px;
                background: rgba(30,30,46,0.95);
                border: 2px solid rgba(102,126,234,0.6);
                border-radius: 12px;
                padding: 20px 24px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.4);
            ">
                <div style="color: #667eea; font-weight: 600; font-size: 15px; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 1px;">
                    Agents in Office
                </div>
                <div style="color: #a8b2d1; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 16px; height: 16px; border-radius: 50%; background: #3498DB; box-shadow: 0 0 8px #3498DB;"></span>
                    User
                </div>
                <div style="color: #a8b2d1; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 16px; height: 16px; border-radius: 50%; background: #9B59B6; box-shadow: 0 0 8px #9B59B6;"></span>
                    Exchange
                </div>
                <div style="color: #a8b2d1; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 16px; height: 16px; border-radius: 50%; background: #E74C3C; box-shadow: 0 0 8px #E74C3C;"></span>
                    Alerts
                </div>
                <div style="color: #a8b2d1; font-size: 14px; margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 16px; height: 16px; border-radius: 50%; background: #27AE60; box-shadow: 0 0 8px #27AE60;"></span>
                    Planner
                </div>
                <div style="color: #a8b2d1; font-size: 14px; display: flex; align-items: center; gap: 10px;">
                    <span style="width: 16px; height: 16px; border-radius: 50%; background: #F39C12; box-shadow: 0 0 8px #F39C12;"></span>
                    StopFinder
                </div>
            </div>
        </div>
    </div>

    <!-- Little moving train layer -->
    <div class="train-layer">
        <div class="train-track">
            <div class="train-rail"></div>
            <div class="train"></div>
        </div>
    </div>

    <script>
        /*__ANS_VARS_PLACEHOLDER__*/
        let ws = null;
        let currentProtocol = 'auto';
        let currentWeather = null;


                // Full-screen visualization controls
        function openVizFullscreen() {
            document.getElementById('viz-fullscreen').style.display = 'flex';
            
            if (!window.agentVizInitialized) {
                setTimeout(() => {
                    if (typeof initializeVisualization === 'function') {
                        initializeVisualization();
                        window.agentVizInitialized = true;
                    }
                }, 300);
            }
        }
        
        function closeVizFullscreen() {
            document.getElementById('viz-fullscreen').style.display = 'none';
        }

        // ============================================================
        // AGENT VISUALIZATION TOGGLE
        // ============================================================
        
        function toggleAgentViz() {
            const content = document.getElementById('viz-content');
            const icon = document.getElementById('viz-collapse-icon');
            content.classList.toggle('open');
            icon.classList.toggle('open');
            
            if (content.classList.contains('open') && !window.agentVizInitialized) {
                // Wait a bit for CSS transition, then initialize
                setTimeout(() => {
                    if (typeof initializeVisualization === 'function') {
                        initializeVisualization();
                        window.agentVizInitialized = true;
                    }
                }, 100);
            }
        }

        // ============================================================
        // WEATHER EFFECTS SYSTEM
        // ============================================================

        const canvas = document.getElementById('weatherCanvas');
        const ctx = canvas.getContext('2d');

        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;

        window.addEventListener('resize', () => {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        });

        let particles = [];

        class Particle {
            constructor(type) {
                this.type = type;
                this.x = Math.random() * canvas.width;
                this.y = Math.random() * canvas.height - canvas.height;
                this.reset();
            }

            reset() {
                if (this.type === 'snow') {
                    this.speed = Math.random() * 1 + 0.5;
                    this.radius = Math.random() * 3 + 1;
                    this.wind = Math.random() * 0.5 - 0.25;
                    this.opacity = Math.random() * 0.6 + 0.4;
                } else if (this.type === 'rain') {
                    this.speed = Math.random() * 5 + 10;
                    this.length = Math.random() * 20 + 10;
                    this.opacity = Math.random() * 0.4 + 0.3;
                    this.wind = Math.random() * 2 - 1;
                } else if (this.type === 'cloud') {
                    this.speed = Math.random() * 0.3 + 0.1;
                    this.radius = Math.random() * 30 + 20;
                    this.opacity = Math.random() * 0.3 + 0.2;
                    this.y = Math.random() * canvas.height * 0.3;
                }
            }

            update() {
                if (this.type === 'snow') {
                    this.y += this.speed;
                    this.x += this.wind;

                    if (this.y > canvas.height) {
                        this.y = -10;
                        this.x = Math.random() * canvas.width;
                    }
                } else if (this.type === 'rain') {
                    this.y += this.speed;
                    this.x += this.wind;

                    if (this.y > canvas.height) {
                        this.y = -this.length;
                        this.x = Math.random() * canvas.width;
                    }
                } else if (this.type === 'cloud') {
                    this.x += this.speed;

                    if (this.x > canvas.width + this.radius) {
                        this.x = -this.radius;
                    }
                }
            }

            draw() {
                ctx.save();
                ctx.globalAlpha = this.opacity;

                if (this.type === 'snow') {
                    ctx.fillStyle = 'white';
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                    ctx.fill();
                } else if (this.type === 'rain') {
                    ctx.strokeStyle = '#a0c4ff';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(this.x, this.y);
                    ctx.lineTo(this.x + this.wind * 2, this.y + this.length);
                    ctx.stroke();
                } else if (this.type === 'cloud') {
                    ctx.fillStyle = 'white';
                    ctx.beginPath();
                    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                    ctx.arc(this.x + this.radius * 0.5, this.y - this.radius * 0.3, this.radius * 0.7, 0, Math.PI * 2);
                    ctx.arc(this.x + this.radius, this.y, this.radius * 0.8, 0, Math.PI * 2);
                    ctx.fill();
                }

                ctx.restore();
            }
        }

        function setWeatherEffect(weatherCondition) {
            particles = [];
            
            const weatherMap = {
                'Clear': 'clear',
                'ClearNight': 'clear',
                'Clouds': 'cloudy',
                'Rain': 'rain',
                'Drizzle': 'rain',
                'Thunderstorm': 'rain',
                'Snow': 'snow',
                'Mist': 'cloudy',
                'Fog': 'cloudy',
                'Haze': 'cloudy'
            };

            const effect = weatherMap[weatherCondition] || 'clear';

            if (effect === 'snow') {
                for (let i = 0; i < 150; i++) {
                    particles.push(new Particle('snow'));
                }
            } else if (effect === 'rain') {
                for (let i = 0; i < 200; i++) {
                    particles.push(new Particle('rain'));
                }
            } else if (effect === 'cloudy') {
                for (let i = 0; i < 5; i++) {
                    particles.push(new Particle('cloud'));
                }
            }
        }

        function animateWeather() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            particles.forEach(particle => {
                particle.update();
                particle.draw();
            });
            requestAnimationFrame(animateWeather);
        }

        animateWeather();

        // ============================================================
        // FETCH REAL WEATHER
        // ============================================================

        async function fetchWeather() {
            try {
                const response = await fetch('/weather');
                const data = await response.json();
                
                const weatherData = data.data || data;
                
                if (data.error || !weatherData.current_condition || !weatherData.current_condition[0]) {
                    throw new Error('Invalid weather data format');
                }
                
                const current = weatherData.current_condition[0];
                const weatherDesc = current.weatherDesc[0].value;
                const temp = current.temp_F;
                const feelsLike = current.FeelsLikeF;
                
                const astronomy = weatherData.weather[0].astronomy[0];
                const sunrise = astronomy.sunrise;
                const sunset = astronomy.sunset;
                
                const isNight = isCurrentlyNight(sunrise, sunset);
                
                let condition = 'Clear';
                if (weatherDesc.toLowerCase().includes('snow')) {
                    condition = 'Snow';
                } else if (weatherDesc.toLowerCase().includes('rain')) {
                    condition = 'Rain';
                } else if (weatherDesc.toLowerCase().includes('cloud')) {
                    condition = 'Clouds';
                } else if (weatherDesc.toLowerCase().includes('clear') || weatherDesc.toLowerCase().includes('sunny')) {
                    condition = isNight ? 'ClearNight' : 'Clear';
                }
                
                currentWeather = {
                    condition: condition,
                    description: weatherDesc,
                    temp: temp,
                    feelsLike: feelsLike,
                    location: 'Boston, MA',
                    isNight: isNight,
                    sunrise: sunrise,
                    sunset: sunset
                };
                
                updateWeatherDisplay();
                setWeatherEffect(condition);
                
            } catch (error) {
                console.error('Weather fetch failed:', error);
                currentWeather = {
                    condition: 'Clear',
                    description: 'Weather unavailable',
                    temp: '--',
                    feelsLike: '--',
                    location: 'Boston, MA',
                    isNight: false
                };
                updateWeatherDisplay();
            }
        }
        
        function isCurrentlyNight(sunrise, sunset) {
            try {
                const now = new Date();
                const currentMinutes = now.getHours() * 60 + now.getMinutes();
                
                const sunriseMatch = sunrise.match(/(\d+):(\d+)\s*(AM|PM)/i);
                let sunriseMinutes = 0;
                if (sunriseMatch) {
                    let hours = parseInt(sunriseMatch[1]);
                    const minutes = parseInt(sunriseMatch[2]);
                    const period = sunriseMatch[3].toUpperCase();
                    
                    if (period === 'PM' && hours !== 12) hours += 12;
                    if (period === 'AM' && hours === 12) hours = 0;
                    
                    sunriseMinutes = hours * 60 + minutes;
                }
                
                const sunsetMatch = sunset.match(/(\d+):(\d+)\s*(AM|PM)/i);
                let sunsetMinutes = 0;
                if (sunsetMatch) {
                    let hours = parseInt(sunsetMatch[1]);
                    const minutes = parseInt(sunsetMatch[2]);
                    const period = sunsetMatch[3].toUpperCase();
                    
                    if (period === 'PM' && hours !== 12) hours += 12;
                    if (period === 'AM' && hours === 12) hours = 0;
                    
                    sunsetMinutes = hours * 60 + minutes;
                }
                
                const isNight = currentMinutes < sunriseMinutes || currentMinutes >= sunsetMinutes;
                
                console.log(`Time check: ${now.getHours()}:${now.getMinutes()} | Sunrise: ${sunrise} (${sunriseMinutes}min) | Sunset: ${sunset} (${sunsetMinutes}min) | Night: ${isNight}`);
                
                return isNight;
                
            } catch (error) {
                console.error('Day/night detection failed:', error);
                return false;
            }
        }

        function updateWeatherDisplay() {
            if (!currentWeather) return;

            const iconMap = {
                'Clear': '☀️',
                'ClearNight': '🌙',
                'Clouds': '☁️',
                'Rain': '🌧️',
                'Drizzle': '🌦️',
                'Thunderstorm': '⛈️',
                'Snow': '❄️',
                'Mist': '🌫️',
                'Fog': '🌫️',
                'Haze': '🌫️'
            };

            const icon = iconMap[currentWeather.condition] || '☁️';
            document.getElementById('weatherIcon').textContent = icon;

            let timeInfo = '';
            if (currentWeather.sunrise && currentWeather.sunset) {
                if (currentWeather.isNight) {
                    timeInfo = ` • 🌙 Night (sunrise at ${currentWeather.sunrise})`;
                } else {
                    timeInfo = ` • ☀️ Day (sunset at ${currentWeather.sunset})`;
                }
            }

            const weatherInfo = document.getElementById('weatherInfo');
            weatherInfo.innerHTML = `
                <div class="weather-info-title">${icon} ${currentWeather.description}</div>
                <div class="weather-info-detail">
                    ${currentWeather.location} • ${currentWeather.temp}°F (feels like ${currentWeather.feelsLike}°F)${timeInfo}
                </div>
            `;
        }

        fetchWeather();
        setInterval(fetchWeather, 600000);

        // ============================================================
        // PROTOCOL SELECTION
        // ============================================================

        function selectProtocol(protocol) {
            currentProtocol = protocol;
            
            document.querySelectorAll('.protocol-button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-protocol="${protocol}"]`).classList.add('active');
            
            const mode = protocol === 'auto' ? 'Intelligent Auto Routing' : 
                        protocol === 'mcp' ? 'MCP Fast Path (forced)' : 
                        'A2A Multi Agent (forced)';
            
            addSystemMessage(`Routing mode: ${mode}`);
        }

        // ============================================================
        // WEBSOCKET CONNECTION
        // ============================================================

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.hostname}:${window.location.port}/ws`;
            
            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                console.log('WebSocket connected');
                document.getElementById('statusDot').classList.add('connected');
                document.getElementById('statusText').textContent = 'Connected';
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                console.log('Received:', data);

                if (data.type === 'response') {
                    addMessage('assistant', data.response);
                    updateInternals(data.metadata, data.path);

                    // ✨ TRIGGER AGENT VISUALIZATION
                    if (window.triggerAgentAnimation && data.metadata) {
                        const unified = data.metadata.unified_decision || {};
                        window.triggerAgentAnimation({
                            path: data.path || unified.path || data.metadata.path || 'a2a',
                            agents_called: data.metadata.agents_called || [],
                            latency_ms: data.metadata.latency_ms || 0
                        });
                    }
                } else if (data.type === 'thinking_start') {
                    const p = document.getElementById('viz-think-panel');
                    const b = document.getElementById('viz-think-body');
                    const d = document.getElementById('viz-think-dot');
                    const badge = document.getElementById('viz-think-badge');
                    if (p) { p.style.display='block'; b.innerHTML=''; badge.style.display='none'; d.style.animation='tpulse 0.9s ease-in-out infinite'; }
                } else if (data.type === 'thinking') {
                    const b = document.getElementById('viz-think-body');
                    if (b) {
                        b.innerHTML = (b.innerHTML + data.chunk)
                            .replace(/DECISION: USE_MCP/g, '<span style="color:#4ade80;font-weight:700;">DECISION: USE_MCP</span>')
                            .replace(/DECISION: USE_A2A/g, '<span style="color:#a371f7;font-weight:700;">DECISION: USE_A2A</span>');
                        b.scrollTop = b.scrollHeight;
                    }
                } else if (data.type === 'thinking_done') {
                    const d = document.getElementById('viz-think-dot');
                    const badge = document.getElementById('viz-think-badge');
                    if (d) d.style.animation = '';
                    if (badge) {
                        const p = data.path || '';
                        if (p === 'firewall_block') {
                            badge.textContent = '🛡️ BLOCKED';
                            badge.style.background = '#e74c3c';
                        } else if (p === 'mcp') {
                            badge.textContent = 'MCP';
                            badge.style.background = '#1a7f37';
                        } else if (p === 'shortcut') {
                            badge.textContent = 'SHORTCUT';
                            badge.style.background = '#95e1d3';
                        } else {
                            badge.textContent = p.toUpperCase() || 'A2A';
                            badge.style.background = '#6e40c9';
                        }
                        badge.style.display = 'inline';
                        badge.style.color = '#fff';
                    }
                } else if (data.type === 'error') {
                    addMessage('system', `Error: ${data.message}`);
                }

                document.getElementById('sendButton').disabled = false;
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                document.getElementById('statusDot').classList.remove('connected');
                document.getElementById('statusText').textContent = 'Error';
            };

            ws.onclose = () => {
                console.log('WebSocket disconnected');
                document.getElementById('statusDot').classList.remove('connected');
                document.getElementById('statusText').textContent = 'Disconnected';
                
                setTimeout(connectWebSocket, 3000);
            };
        }

        function sendMessage() {
            const input = document.getElementById('messageInput');
            const message = input.value.trim();

            if (!message || !ws || ws.readyState !== WebSocket.OPEN) {
                return;
            }

            addMessage('user', message);

            ws.send(JSON.stringify({
                message: message,
                force_protocol: currentProtocol
            }));

            input.value = '';
            document.getElementById('sendButton').disabled = true;

            updateInternals({
                path: 'processing',
                intent: 'analyzing...',
                confidence: 0
            });
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendMessage();
            }
        }

        function parseRouteCards(text) {
            // Handles both formats:
            // 1. Inline: **Option 1:** - Lines: X - Transfers: Y - Stops: N, Time: T - directions
            // 2. Multi-line: Option 1 - Lines / key: val / ...
            const inlineRegex = /\*\*Option\s+(\d+):\*\*\s*([\s\S]*?)(?=\*\*Option\s+\d+:\*\*|$)/gi;
            const multilineRegex = /Option\s+(\d+)\s*[-]+\s*([^\\n]+)([\s\S]*?)(?=Option\s+\d+\s*[-]|$)/gi;

            let matches = [...text.matchAll(inlineRegex)];
            const isInline = matches.length >= 1;
            if (!isInline) {
                matches = [...text.matchAll(multilineRegex)];
            }
            if (matches.length < 1) return null;

            // Intro: everything before first Option match
            const firstIdx = text.search(isInline ? /\*\*Option\s+1:\*\*/i : /Option\s+1\s*[-]/i);
            const rawIntro = firstIdx > 0 ? text.slice(0, firstIdx).replace(/\*\*/g, '').trim() : '';

            // Outro: everything after last option block ends
            const lastMatch = matches[matches.length - 1];
            const lastEnd = lastMatch.index + lastMatch[0].length;
            const rawOutro = text.slice(lastEnd).replace(/\*\*/g, '').trim();

            let cardsHtml = rawIntro ? `<div class="route-intro">${rawIntro}</div>` : '';
            cardsHtml += '<div class="route-cards">';

            for (const match of matches) {
                const num = match[1];
                let lines = '', transfers = '', stops = '', time = '', directions = '';

                if (isInline) {
                    // Inline format: body is everything after "**Option N:**"
                    const body = match[2].trim();
                    // Split on " - " separators
                    const parts = body.split(/\s+-\s+/);
                    const dirParts = [];
                    for (const part of parts) {
                        if (/^Lines?:/i.test(part)) {
                            lines = part.replace(/^Lines?:\s*/i, '').replace(/\*\*/g, '').trim();
                        } else if (/^Transfers?:/i.test(part)) {
                            transfers = part.replace(/^Transfers?:\s*/i, '').replace(/\*\*/g, '').trim();
                        } else if (/^Stops?:/i.test(part)) {
                            const stopsM = part.match(/Stops?:\s*(\S+)/i);
                            const timeM = part.match(/Time:\s*([^,\-]+)/i);
                            if (stopsM) stops = stopsM[1];
                            if (timeM) time = timeM[1].trim();
                        } else if (/^Time:/i.test(part)) {
                            time = part.replace(/^Time:\s*/i, '').trim();
                        } else if (part.trim()) {
                            dirParts.push(part.trim());
                        }
                    }
                    directions = dirParts.join(' ');
                    // Use Lines value as the card title if present
                    if (!lines) lines = '';
                } else {
                    // Multi-line format
                    lines = match[2].trim();
                    const body = match[3].trim();
                    const dirParts = [];
                    for (const rawLine of body.split('\\n')) {
                        const l = rawLine.replace(/^[-•]\s*/, '').trim();
                        if (!l) continue;
                        if (/^Transfer at:/i.test(l)) transfers = l.replace(/^Transfer at:\s*/i, '');
                        else if (/^Stops:/i.test(l)) stops = l.replace(/^Stops:\s*/i, '');
                        else if (/^Time:/i.test(l)) time = l.replace(/^Time:\s*/i, '');
                        else dirParts.push(l);
                    }
                    directions = dirParts.join(' ');
                }

                const transferHtml = transfers ? `
                    <div class="route-stat">
                        <span class="route-stat-label">Transfer at</span>
                        <span class="route-stat-value">${transfers}</span>
                    </div>` : '';
                const stopsHtml = stops ? `
                    <div class="route-stat">
                        <span class="route-stat-label">Stops</span>
                        <span class="route-stat-value">${stops}</span>
                    </div>` : '';
                const timeHtml = time ? `
                    <div class="route-stat">
                        <span class="route-stat-label">Time</span>
                        <span class="route-stat-value">${time}</span>
                    </div>` : '';
                const directionsHtml = directions
                    ? `<hr class="route-divider"><div class="route-directions">${directions}</div>`
                    : '';

                cardsHtml += `
                    <div class="route-card">
                        <div class="route-card-header">
                            <span class="route-option-number">Option ${num}</span>
                            <span class="route-line-name">${lines}</span>
                        </div>
                        <div class="route-stats">
                            ${transferHtml}${stopsHtml}${timeHtml}
                        </div>
                        ${directionsHtml}
                    </div>`;
            }

            cardsHtml += '</div>';
            if (rawOutro) cardsHtml += `<div class="route-intro" style="margin-top:10px;">${rawOutro}</div>`;
            return cardsHtml;
        }

        function addMessage(role, content) {
            const container = document.getElementById('messagesContainer');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${role}`;

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';

            if (role === 'assistant') {
                const routeHtml = parseRouteCards(content);
                if (routeHtml) {
                    contentDiv.innerHTML = routeHtml;
                } else {
                    contentDiv.textContent = content;
                }
            } else {
                contentDiv.textContent = content;
            }

            messageDiv.appendChild(contentDiv);
            container.appendChild(messageDiv);

            container.scrollTop = container.scrollHeight;
        }

        function addSystemMessage(content) {
            addMessage('system', content);
        }

        function updateInternals(metadata, topLevelPath) {
            const internalsContent = document.getElementById('internalsContent');

            if ((topLevelPath || metadata.path) === 'processing') {
                internalsContent.innerHTML = `
                    <div class="info-block">
                        <div class="info-label">Status</div>
                        <div class="info-value">⏳ Processing query...</div>
                    </div>
                `;
                return;
            }

            const unified = metadata.unified_decision || {};
            const path = topLevelPath || metadata.path || unified.path || 'unknown';
            const intent = unified.intent || (path === 'firewall_block' ? 'blocked' : 'unknown');
            const confidence = unified.confidence || (path === 'firewall_block' ? 1 : 0);
            const latency = metadata.latency_ms || 0;
            const reasoning = unified.reasoning || (path === 'firewall_block' ? '🛡️ Blocked by DANS Firewall' : 'No reasoning provided');
            const agents = metadata.agents_called || [];
            const manualOverride = unified.manual_override || false;
            const forceProtocol = unified.force_protocol || 'auto';
            const ansTraces = metadata.ans_traces || [];

            let badgeClass = 'mcp';
            let badgeText = 'MCP';
            if (path === 'a2a' || path === 'a2a_fallback') {
                badgeClass = 'a2a';
                badgeText = 'A2A';
            } else if (path === 'shortcut') {
                badgeClass = 'shortcut';
                badgeText = 'SHORTCUT';
            } else if (path === 'firewall_block') {
                badgeClass = 'firewall';
                badgeText = '🛡️ BLOCKED';
            }

            const latencyPercent = Math.min((latency / 3000) * 100, 100);

            internalsContent.innerHTML = `
                <div class="info-block">
                    <div class="info-label">Routing Path</div>
                    <div class="info-value">
                        <span class="badge ${badgeClass}">${badgeText}</span>
                        ${manualOverride ? '<span class="badge override">🔧 MANUAL OVERRIDE</span>' : ''}
                    </div>
                </div>

                ${manualOverride ? `
                <div class="info-block">
                    <div class="info-label">Override Mode</div>
                    <div class="info-value" style="color: #ffd93d;">
                        User selected: ${forceProtocol.toUpperCase()}
                    </div>
                </div>
                ` : ''}

                <div class="info-block">
                    <div class="info-label">Intent Classification</div>
                    <div class="info-value">${intent} (${(confidence * 100).toFixed(0)}%)</div>
                </div>

                <div class="info-block">
                    <div class="info-label">Response Time</div>
                    <div class="info-value">${latency}ms</div>
                    <div class="latency-bar">
                        <div class="latency-fill" style="width: ${latencyPercent}%"></div>
                    </div>
                </div>

                <div class="info-block">
                    <div class="info-label">Routing Logic</div>
                    <div class="info-value" style="font-size: 12px; line-height: 1.6;">${reasoning}</div>
                </div>

                ${agents.length > 0 ? `
                <div class="info-block">
                    <div class="info-label">Agents Called (${agents.length})</div>
                    <ul class="agent-list">
                        ${agents.map(agent => `<li class="agent-item">→ ${agent}</li>`).join('')}
                    </ul>
                </div>
                ` : ''}

                ${(() => {
                    if (!ansTraces.length) return '';
                    // Use server-side is_foreign flag exclusively — no hardcoded IP lists in the UI
                    const localTraces   = ansTraces.filter(t => t.is_foreign !== true);
                    const foreignTraces = ansTraces.filter(t => t.is_foreign === true);

                    const localBlock = localTraces.length ? `
                    <div class="ans-block">
                        <div class="ans-title">🔍 ANS Dynamic Resolution</div>
                        ${localTraces.map(trace => {
                            const cachedBadge = trace.cached
                                ? '<span class="ans-badge cached">⚡ CACHED</span>'
                                : '<span class="ans-badge live">🔴 LIVE</span>';
                            const latencyStr = trace.latency_ms > 0 ? trace.latency_ms + 'ms' : '';
                            return `
                            <div class="ans-agent-section">
                                <div class="ans-urn">${trace.urn}</div>
                                <div class="ans-hop">
                                    <span class="ans-hop-label">DANS</span>
                                    <span class="ans-hop-addr">${window.ANS_DANS_DISPLAY}</span>
                                    ${trace.selected_by ? `<span class="ans-badge" style="background:#1a4a7a;color:#7ec8f7;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:6px">${trace.selected_by}</span>` : ''}
                                    ${trace.region ? `<span style="color:#888;font-size:9px;margin-left:4px">${trace.flag || ''} ${trace.region}</span>` : ''}
                                </div>
                                <div class="ans-hop-final">
                                    <span>✅</span>
                                    <span class="endpoint">${trace.endpoint}</span>
                                    ${cachedBadge}
                                    ${latencyStr ? '<span class="ans-latency">' + latencyStr + '</span>' : ''}
                                </div>
                            </div>`;
                        }).join('<hr style="border-color:#1a4a7a;margin:10px 0">')}
                    </div>` : '';

                    const foreignBlock = foreignTraces.map(trace => {
                        const flag        = trace.flag        || '🌍';
                        const regionLabel = trace.region_label || 'Remote';
                        const reason      = trace.reason       || 'Geo-distributed foreign agent node';
                        const isTrulyForeign = trace.is_foreign === true;
                        const title = isTrulyForeign ? '🌐 Cross-Region Agent Call' : '🌐 Geo-Distributed Agent Call';
                        const selectedBy = trace.selected_by || 'ans';
                        const selectionNote = selectedBy === 'lowest_latency'
                            ? '⚡ Selected by ANS: lowest latency'
                            : selectedBy === 'only_available' ? '📍 Only available endpoint'
                            : '🔍 ANS resolved';
                        // Candidate comparison rows
                        const candidates = trace.candidates || [];
                        const candidateRows = candidates.length > 0 ? candidates.map(c => {
                            const isSelected = c.endpoint === trace.endpoint;
                            const healthIcon = c.healthy ? '✅' : '❌';
                            const latStr = c.latency_ms === Infinity ? '∞' : c.latency_ms + 'ms';
                            const selMark = isSelected ? ' ◀ SELECTED' : '';
                            const rowColor = isSelected ? '#4ecdc4' : '#888';
                            const regionStr = c.region ? ` (${c.region})` : '';
                            return `<div class="candidate-row" style="color:${rowColor}">
                                ${healthIcon} ${c.endpoint}${regionStr} — ${latStr}${selMark}
                            </div>`;
                        }).join('') : '';
                        return `
                        <div class="foreign-agent-block">
                            <div class="foreign-title">${title}</div>
                            <div class="foreign-urn">${trace.urn}</div>
                            ${candidates.length > 1 ? `
                            <div style="margin:8px 0 6px;font-size:10px;color:#a29bfe;font-weight:700;text-transform:uppercase;letter-spacing:.8px">
                                ANS Candidate Selection
                            </div>
                            <div class="candidates-block">${candidateRows}</div>
                            <div style="font-size:10px;color:#4ecdc4;margin:6px 0">${selectionNote}</div>
                            ` : ''}
                            <div class="geo-route">
                                <div class="geo-node">
                                    <div class="geo-flag">🇺🇸</div>
                                    <div class="geo-city">Boston, MA</div>
                                    <div class="geo-role">Exchange Server</div>
                                </div>
                                <div class="geo-arrow">
                                    <div class="geo-arrow-line"></div>
                                    <div class="geo-km">${isTrulyForeign ? '~6,200 km' : 'same region'}</div>
                                </div>
                                <div class="geo-node">
                                    <div class="geo-flag">${flag}</div>
                                    <div class="geo-city">${regionLabel}</div>
                                    <div class="geo-role">Fares Agent</div>
                                </div>
                            </div>
                            <div class="foreign-endpoint">
                                <span>✅</span>
                                <span class="ep-url">${trace.endpoint}</span>
                                ${isTrulyForeign ? '<span class="ans-badge foreign">🌍 FOREIGN</span>' : '<span class="ans-badge" style="background:#1a3a1a;color:#4ecdc4;border:1px solid #4ecdc4">🇺🇸 LOCAL</span>'}
                                <span class="ans-badge live">🔴 LIVE</span>
                            </div>
                            ${reason ? `<div class="foreign-reason">💡 ${reason}</div>` : ''}
                        </div>`;
                    }).join('');

                    return localBlock + foreignBlock;
                })()}
            `;
        }

        // Initialize
        connectWebSocket();
    </script>
    
    <!-- Three.js Library -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    
    <!-- 3D Agent Visualization -->
    <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    <script src="/js/visualization_3d.js"></script>

</body>
</html>
    """
    # Inject ANS display values from env vars into HTML
    _ans_js = (
        "        window.ANS_RESOLVER_DISPLAY = '" + _ans_resolver_display + "';" + chr(10) +
        "        window.ANS_REGISTRY_DISPLAY = '" + _ans_registry_display + "';" + chr(10) +
        "        window.ANS_AUTHNS_DISPLAY = '" + _ans_authns_display + "';" + chr(10) +
        "        window.ANS_DANS_DISPLAY = '" + _ans_dans_display + "';"
    )
    html_content = html_content.replace('        /*__ANS_VARS_PLACEHOLDER__*/', _ans_js)
    return HTMLResponse(
        content=html_content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_json()
            message = data.get('message', '')
            conversation_id = data.get('conversation_id')
            force_protocol = data.get('force_protocol', 'auto')
            
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        f"{EXCHANGE_AGENT_URL}/chat",
                        json={
                            'query': message,
                            'conversation_id': conversation_id,
                            'force_protocol': force_protocol
                        },
                        timeout=30.0
                    )
                    response.raise_for_status()
                    result = response.json()

                    confidence_value = result.get('confidence', 0.0)
                    logger.info(f"Query: '{message}' | Confidence: {confidence_value} | Intent: {result.get('intent')} | Path: {result.get('path')} | Override: {force_protocol}")

                    # Stream thinking text word by word before the response
                    thinking_text = result.get('metadata', {}).get('thinking_text', '')
                    if thinking_text:
                        await manager.send_message({'type': 'thinking_start'}, websocket)
                        words = thinking_text.split(' ')
                        chunk = ''
                        for i, word in enumerate(words):
                            chunk += word + ' '
                            if (i + 1) % 4 == 0 or i == len(words) - 1:
                                await manager.send_message({'type': 'thinking', 'chunk': chunk}, websocket)
                                chunk = ''
                                await asyncio.sleep(0.04)
                        path_taken = result.get('path', result.get('metadata', {}).get('path', 'mcp'))
                        await manager.send_message({'type': 'thinking_done', 'path': path_taken}, websocket)

                    await manager.send_message({
                        'type': 'response',
                        'response': result['response'],
                        'conversation_id': conversation_id,
                        'path': result.get('path', 'unknown'),
                        'metadata': result.get('metadata', {})
                    }, websocket)
                    
                except httpx.HTTPError as e:
                    logger.error(f"Error calling exchange agent: {e}")
                    await manager.send_message({
                        'type': 'error',
                        'message': 'Failed to process message. Please try again.'
                    }, websocket)
                    
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@app.get("/weather")
async def get_weather():
    """Proxy endpoint for weather to avoid CORS issues"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://wttr.in/Boston?format=j1")
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        return {
            "error": str(e),
            "current_condition": [{
                "weatherDesc": [{"value": "Unknown"}],
                "temp_F": "--",
                "FeelsLikeF": "--"
            }],
            "weather": [{
                "astronomy": [{
                    "sunrise": "07:00 AM",
                    "sunset": "05:00 PM"
                }]
            }]
        }

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "frontend"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)