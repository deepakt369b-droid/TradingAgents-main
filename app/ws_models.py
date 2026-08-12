"""Pydantic models for WebSocket message types between server and frontend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AnalysisRequest(BaseModel):
    """Parameters sent by the frontend to start an analysis run."""
    ticker: str
    date: str
    provider: str = "openai"
    deep_model: str = "gpt-5.5"
    quick_model: str = "gpt-5.4-mini"
    analysts: list[str] = ["market", "social", "news", "fundamentals"]
    depth: int = 1
    language: str = "English"
    api_key: str | None = None
    thinking_config: str | None = None
    cli_options: dict[str, str | bool] = {}


class WSMessage(BaseModel):
    """Base WebSocket message envelope."""
    type: str


class AgentStatusMessage(WSMessage):
    """Sent when an agent's status changes."""
    type: str = "agent_status"
    agent: str
    status: str  # pending | in_progress | completed | error
    team: str | None = None


class ReportUpdateMessage(WSMessage):
    """Sent when a report section is updated."""
    type: str = "report_update"
    section: str
    content: str
    is_final: bool = False


class MessageEvent(WSMessage):
    """Sent for agent/tool messages."""
    type: str = "message"
    msg_type: str  # Agent | User | Data | System | Control
    content: str


class ToolCallEvent(WSMessage):
    """Sent when an agent invokes a tool."""
    type: str = "tool_call"
    name: str
    args: dict[str, Any] = {}


class StatsMessage(WSMessage):
    """Periodic stats update."""
    type: str = "stats"
    llm_calls: int = 0
    tool_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed: float = 0.0


class CompleteMessage(WSMessage):
    """Sent when analysis finishes successfully."""
    type: str = "complete"
    final_state: dict[str, Any] = {}


class ErrorMessage(WSMessage):
    """Sent on fatal errors."""
    type: str = "error"
    detail: str = "Unknown error"


class UpdateCheckResponse(BaseModel):
    """Response for /api/update-check."""
    current_version: str
    latest_version: str
    download_url: str = ""
    update_available: bool = False
    release_notes: str = ""


class KeyValidationRequest(BaseModel):
    """Request for /api/validate-key."""
    provider: str
    key: str


class KeyValidationResponse(BaseModel):
    """Response for /api/validate-key."""
    valid: bool
    message: str = ""
