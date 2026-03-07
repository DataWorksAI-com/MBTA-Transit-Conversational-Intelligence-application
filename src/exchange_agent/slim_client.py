"""
SLIM Client for Exchange Agent
Calls agents via SLIM transport using a2a-sdk client
"""

import logging
import os
from typing import Any, Dict
from uuid import uuid4

import httpx
from a2a.client import A2AClient
from a2a.types import Message, MessageSendParams, SendMessageRequest, TextPart

logger = logging.getLogger(__name__)


class SlimAgentClient:
    """Client for calling agents via SLIM transport"""

    def __init__(self):
        self.clients: Dict[str, Any] = {}
        self._httpx_client: httpx.AsyncClient | None = None
        self._initialized = False
        self.alerts_agent_url = os.getenv("ALERTS_AGENT_URL", "http://alerts-agent:50051").rstrip("/") + "/"
        self.planner_agent_url = os.getenv("PLANNER_AGENT_URL", "http://planner-agent:50052").rstrip("/") + "/"
        self.stopfinder_agent_url = os.getenv("STOPFINDER_AGENT_URL", "http://stopfinder-agent:50053").rstrip("/") + "/"

    async def initialize(self):
        """Initialize SLIM clients for all agents"""
        if self._initialized:
            return

        try:
            logger.info("Initializing SLIM agent clients (a2a-sdk)...")
            self._httpx_client = httpx.AsyncClient(timeout=20.0)

            self.clients["alerts"] = A2AClient(self._httpx_client, url=self.alerts_agent_url)
            logger.info("Alerts SLIM client ready")

            self.clients["planner"] = A2AClient(self._httpx_client, url=self.planner_agent_url)
            logger.info("Planner SLIM client ready")

            self.clients["stopfinder"] = A2AClient(self._httpx_client, url=self.stopfinder_agent_url)
            logger.info("StopFinder SLIM client ready")

            self._initialized = True
            logger.info("All SLIM clients initialized")

        except Exception as e:
            logger.error(f"SLIM client initialization failed: {e}", exc_info=True)
            raise

    async def call_agent(self, agent_name: str, message: str) -> Dict[str, Any]:
        """Call agent via SLIM transport"""
        if not self._initialized:
            await self.initialize()

        client = self.clients.get(agent_name)
        if not client:
            raise ValueError(f"Unknown agent: {agent_name}")

        try:
            logger.info(f"Calling {agent_name} via SLIM...")

            msg = Message(
                message_id=str(uuid4()),
                parts=[TextPart(text=message)],
                role="user",
            )
            request = SendMessageRequest(
                id=str(uuid4()),
                params=MessageSendParams(message=msg),
            )

            response = await client.send_message(request)
            response_text = self._extract_response_text(response)

            logger.info(f"SLIM success for {agent_name}: {len(response_text)} chars")
            return {
                "response": response_text,
                "metadata": {"transport": "slim", "agent": agent_name},
            }

        except Exception as e:
            logger.error(f"SLIM call to {agent_name} failed: {e}", exc_info=True)
            raise

    def _extract_response_text(self, response: Any) -> str:
        """Extract text payload from varying a2a response object shapes."""
        root = getattr(response, "root", None)
        if root is not None:
            result = getattr(root, "result", None)
            if result is not None:
                parts = getattr(result, "parts", None) or []
                for part in parts:
                    part_root = getattr(part, "root", None)
                    if part_root is not None and hasattr(part_root, "text"):
                        return part_root.text
                    if hasattr(part, "text"):
                        return part.text
        return str(response)

    async def cleanup(self):
        """Close all SLIM client connections"""
        logger.info("Closing SLIM clients...")

        if self._httpx_client is not None:
            try:
                await self._httpx_client.aclose()
            except Exception as e:
                logger.warning(f"Error closing SLIM httpx client: {e}")
            self._httpx_client = None

        self.clients.clear()
        self._initialized = False
        logger.info("All SLIM clients closed")
