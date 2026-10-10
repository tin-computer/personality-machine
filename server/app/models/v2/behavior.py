"""API v2 Behavior Models.

Behaviors are developer-defined logic that runs during conversations for state
management and context orchestration.

Key concepts:
- Behaviors table: Project-level behavior definitions
- companion_behavior_links: Links behaviors to companions/relationships
- Triggers: ["always"], ["every:N"], ["turn:1,5,10"], ["keyword:X,Y"], ["cron:..."]
- Priority: sync (execute before LLM) vs async (execute after turn)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Trigger Parsing (shorthand strings -> structured dicts)
# -----------------------------------------------------------------------------


def parse_trigger_shorthand(trigger: str) -> Dict[str, Any]:
    """Parse shorthand trigger string into trigger definition.

    Supported formats:
    - "always" -> {"type": "always"}
    - "every:3" -> {"type": "every_n", "n": 3}
    - "turn:1,5,10" -> {"type": "turn_count", "turns": [1, 5, 10]}
    - "keyword:anxious,stressed" -> {"type": "keyword", "keywords": ["anxious", "stressed"]}
    - "cron:0 9 * * *" -> {"type": "cron", "expression": "0 9 * * *"}
    """
    trigger = trigger.strip()

    if trigger == "always":
        return {"type": "always"}

    if trigger.startswith("every:"):
        n_str = trigger[6:].strip()
        try:
            n = int(n_str)
            if n > 0:
                return {"type": "every_n", "n": n}
        except ValueError:
            pass
        raise ValueError(f"Invalid every trigger: {trigger}")

    if trigger.startswith("turn:"):
        turns_str = trigger[5:].strip()
        try:
            turns = [int(t.strip()) for t in turns_str.split(",") if t.strip()]
            if turns:
                return {"type": "turn_count", "turns": turns}
        except ValueError:
            pass
        raise ValueError(f"Invalid turn trigger: {trigger}")

    if trigger.startswith("keyword:"):
        keywords_str = trigger[8:].strip()
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
        if keywords:
            return {"type": "keyword", "keywords": keywords}
        raise ValueError(f"Invalid keyword trigger: {trigger}")

    if trigger.startswith("cron:"):
        expression = trigger[5:].strip()
        if expression:
            return {"type": "cron", "expression": expression}
        raise ValueError(f"Invalid cron trigger: {trigger}")

    if trigger.startswith("idle:"):
        minutes_str = trigger[5:].strip()
        try:
            minutes = int(minutes_str)
            if minutes > 0:
                return {"type": "idle", "minutes": minutes}
        except ValueError:
            pass
        raise ValueError(f"Invalid idle trigger: {trigger}")

    raise ValueError(f"Unknown trigger format: {trigger}")


def parse_triggers(triggers: List[str]) -> List[Dict[str, Any]]:
    """Parse a list of shorthand trigger strings into trigger definitions."""
    return [parse_trigger_shorthand(t) for t in triggers]


def format_trigger_shorthand(trigger: Dict[str, Any]) -> str:
    """Format a trigger definition back to shorthand string."""
    trigger_type = trigger.get("type", "")

    if trigger_type == "always":
        return "always"
    elif trigger_type == "every_n":
        return f"every:{trigger.get('n', 0)}"
    elif trigger_type == "turn_count":
        turns = trigger.get("turns", [])
        return f"turn:{','.join(str(t) for t in turns)}"
    elif trigger_type == "keyword":
        keywords = trigger.get("keywords", [])
        return f"keyword:{','.join(keywords)}"
    elif trigger_type == "cron":
        return f"cron:{trigger.get('expression', '')}"
    elif trigger_type == "idle":
        return f"idle:{trigger.get('minutes', 0)}"
    else:
        return str(trigger)


# -----------------------------------------------------------------------------
# Behavior Models
# -----------------------------------------------------------------------------


class BehaviorBase(BaseModel):
    """Base behavior definition (project-level)."""

    key: str = Field(..., description="Unique key within project")
    name: str = Field(..., description="Human-readable name")
    description: str | None = Field(None, description="Description of what this behavior does")
    source_code: str | None = Field(
        None,
        description="Python source code for the behavior function",
    )
    dependencies: List[str] | None = Field(
        default_factory=list,
        description="Python packages required by this behavior",
    )
    timeout_seconds: int = Field(60, description="Execution timeout in seconds")
    block_network: bool = Field(True, description="Block network access during execution")


class BehaviorCreate(BehaviorBase):
    """Request model for creating a behavior."""

    pass


class BehaviorUpdate(BaseModel):
    """Request model for updating a behavior."""

    name: str | None = None
    description: str | None = None
    source_code: str | None = None
    dependencies: List[str] | None = None
    timeout_seconds: int | None = None
    block_network: bool | None = None


class Behavior(BehaviorBase):
    """Full behavior model with metadata."""

    id: UUID
    project_id: UUID
    version: int = Field(1, description="Auto-incremented on code changes")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BehaviorResponse(BaseModel):
    """API response for a single behavior."""

    id: UUID
    key: str
    name: str
    description: str | None = None
    source_code: str | None = None
    dependencies: List[str] = Field(default_factory=list)
    timeout_seconds: int = 60
    block_network: bool = True
    version: int = 1
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------------------------------
# Behavior Link Models (Companion/Relationship Level)
# -----------------------------------------------------------------------------


class BehaviorLinkBase(BaseModel):
    """Base behavior link configuration."""

    triggers: List[str] = Field(
        default_factory=list,
        description="Trigger shorthand strings: ['always'], ['every:3'], etc.",
    )
    priority: bool = Field(
        False,
        description="If True, executes synchronously before LLM and can inject prompt blocks",
    )
    isolated: bool = Field(False, description="Run in isolated container (slower, more secure)")
    enabled: bool = Field(True, description="Whether this behavior is enabled")
    classifier_eligible: bool = Field(
        True,
        description="Whether the intent classifier can select this behavior",
    )
    classifier_hint: str | None = Field(
        None,
        description="Hint for classifier about when to trigger this behavior",
    )
    webhook_url: str | None = Field(
        None,
        description="URL to call after behavior completes",
    )
    webhook_secret: str | None = Field(
        None,
        description="HMAC secret for webhook signature verification",
    )
    params: Dict[str, Any] | None = Field(
        default_factory=dict,
        description="Custom parameters passed to the behavior",
    )


class BehaviorLinkCreate(BehaviorLinkBase):
    """Request model for linking a behavior to a companion."""

    behavior_key: str = Field(..., description="Key of the behavior to link")


class BehaviorLinkUpdate(BaseModel):
    """Request model for updating a behavior link."""

    triggers: List[str] | None = None
    priority: bool | None = None
    isolated: bool | None = None
    enabled: bool | None = None
    classifier_eligible: bool | None = None
    classifier_hint: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    params: Dict[str, Any] | None = None


class BehaviorLinkSwitchTarget(BaseModel):
    """One explicitly scoped default or relationship override link."""

    link_id: UUID
    relationship_id: UUID | None = None
    expected_behavior_id: UUID


class IsolatedBehaviorDefinitionCreate(BaseModel):
    """Create a fresh project definition without reusing an existing key."""

    key: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str | None = None
    source_code: str = ""
    dependencies: List[str] = Field(default_factory=list)
    timeout_seconds: int = Field(60, ge=1, le=600)
    block_network: bool = True


class BehaviorLinkSwitchRequest(BaseModel):
    """Compare-and-swap request for a companion behavior link.

    Relationship override links must be named explicitly. The server rejects
    incomplete or stale scopes instead of guessing which overrides to move.
    """

    behavior_key: str = Field(..., min_length=1)
    new_behavior_id: UUID
    links: List[BehaviorLinkSwitchTarget] = Field(..., min_length=1)


class BehaviorLink(BehaviorLinkBase):
    """Full behavior link model."""

    id: UUID
    companion_id: UUID
    behavior_id: UUID
    relationship_id: UUID | None = Field(
        None,
        description="NULL = companion-level default, set = relationship-specific override",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BehaviorLinkResponse(BaseModel):
    """API response for a behavior link with behavior details."""

    # Link fields
    link_id: UUID
    companion_id: UUID
    relationship_id: UUID | None = None
    triggers: List[str] = Field(default_factory=list)
    priority: bool = False
    isolated: bool = False
    enabled: bool = True
    classifier_eligible: bool = True
    classifier_hint: str | None = None
    webhook_url: str | None = None
    params: Dict[str, Any] = Field(default_factory=dict)

    # Behavior fields
    behavior_id: UUID
    behavior_key: str
    behavior_name: str
    behavior_description: str | None = None
    has_source_code: bool = False
    version: int = 1


class CompanionBehaviorsResponse(BaseModel):
    """API response for listing companion behaviors."""

    companion_id: UUID
    behaviors: List[BehaviorLinkResponse]
    total: int


class RelationshipBehaviorsResponse(BaseModel):
    """API response for listing relationship-level behavior overrides."""

    relationship_id: UUID
    companion_id: UUID
    behaviors: List[BehaviorLinkResponse]
    total: int


# -----------------------------------------------------------------------------
# Behavior Execution Models
# -----------------------------------------------------------------------------


class BehaviorExecutionContext(BaseModel):
    """Context passed to behavior during execution."""

    message: str = Field(..., description="User message that triggered this behavior")
    companion_id: str
    relationship_id: str | None = None
    external_user_id: str | None = None
    turn_count: int = 0
    trigger_source: str = Field(..., description="What triggered this: always, keyword, etc.")
    trigger_details: str | None = None

    # State snapshots (read-only for behavior)
    profile: Dict[str, Any] = Field(default_factory=dict)
    session_state: Dict[str, Any] = Field(default_factory=dict)

    # Action params from link config
    params: Dict[str, Any] = Field(default_factory=dict)


class BehaviorEffect(BaseModel):
    """An effect produced by behavior execution."""

    type: str = Field(..., description="Effect type: state_patch, memory_write, webhook, etc.")
    payload: Dict[str, Any] = Field(default_factory=dict)


class BehaviorExecutionResult(BaseModel):
    """Result from behavior execution."""

    success: bool = True
    prompt_block: str | None = Field(
        None,
        description="String to inject into system prompt (priority behaviors only)",
    )
    effects: List[BehaviorEffect] = Field(
        default_factory=list,
        description="State changes to apply after turn",
    )
    error: str | None = None
    duration_ms: int | None = None


# -----------------------------------------------------------------------------
# API Trigger Models
# -----------------------------------------------------------------------------


class TriggerBehaviorRequest(BaseModel):
    """Request to manually trigger a behavior via API."""

    context: Dict[str, Any] | None = Field(
        None,
        description="Optional additional context passed to the behavior",
    )


class TriggerBehaviorResponse(BaseModel):
    """Response from triggering a behavior."""

    job_id: UUID = Field(..., description="Job ID for tracking the behavior execution")
    status: str = Field(default="queued", description="Job status")
    behavior_key: str = Field(..., description="The behavior that was triggered")
