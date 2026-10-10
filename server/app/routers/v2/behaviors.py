"""API v2 Behaviors Router.

Implements the Behaviors system for developer-defined logic that runs during conversations:

1. Companion-level behavior management:
   - GET/POST /v2/companions/{id}/behaviors
   - GET/PATCH/DELETE /v2/companions/{id}/behaviors/{key}

2. Relationship-level behavior overrides:
   - GET/POST/PATCH/DELETE /v2/relationships/{id}/behaviors/{key}

Behaviors can:
- Run on triggers: ["always"], ["every:N"], ["turn:1,5,10"], ["keyword:X,Y"]
- Execute synchronously (priority=True) or asynchronously
- Inject prompt blocks into system prompt (priority behaviors)
- Update profile and session state via ctx.profile.set() and ctx.session.set()
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from ...auth import ProjectApiKeySubject, get_project_api_subject
from ...db import get_db
from ...models.v2.behavior import (
    BehaviorLinkCreate,
    BehaviorLinkResponse,
    BehaviorLinkSwitchRequest,
    BehaviorLinkUpdate,
    BehaviorResponse,
    BehaviorUpdate,
    CompanionBehaviorsResponse,
    IsolatedBehaviorDefinitionCreate,
    RelationshipBehaviorsResponse,
    TriggerBehaviorRequest,
    TriggerBehaviorResponse,
)
from ...repositories.behavior_repository import BehaviorRepository
from ...repositories.companion import CompanionRepository
from ...repositories.relationship_repository import RelationshipRepository

router = APIRouter(prefix="/v2", tags=["v2-behaviors"])
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _verify_companion_access(
    conn: asyncpg.Connection,
    companion_id: UUID,
    project_id: UUID,
) -> Any:
    """Verify the companion exists and belongs to the project."""
    companion = await CompanionRepository.get_companion_by_id_no_auth(conn, companion_id)
    if not companion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Companion {companion_id} not found",
        )
    if companion.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Companion does not belong to this project",
        )
    return companion


async def _verify_relationship_access(
    conn: asyncpg.Connection,
    relationship_id: UUID,
    project_id: UUID,
) -> Any:
    """Verify the relationship exists and belongs to the project."""
    relationship = await RelationshipRepository.get_by_id(conn, relationship_id)
    if not relationship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Relationship {relationship_id} not found",
        )

    # Check companion belongs to project
    companion = await CompanionRepository.get_companion_by_id_no_auth(
        conn, relationship.companion_id
    )
    if not companion or companion.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Relationship does not belong to this project",
        )
    return relationship, companion


def _to_link_response(behavior: Dict[str, Any], companion_id: UUID) -> BehaviorLinkResponse:
    """Convert repository dict to BehaviorLinkResponse."""
    return BehaviorLinkResponse(
        link_id=behavior["link_id"],
        companion_id=companion_id,
        relationship_id=behavior.get("relationship_id"),
        triggers=behavior.get("triggers", []),
        priority=behavior.get("priority", False),
        isolated=behavior.get("isolated", False),
        enabled=behavior.get("enabled", True),
        classifier_eligible=behavior.get("classifier_eligible", True),
        classifier_hint=behavior.get("classifier_hint"),
        webhook_url=behavior.get("webhook_url"),
        params=behavior.get("params", {}),
        behavior_id=behavior["id"],
        behavior_key=behavior["key"],
        behavior_name=behavior["name"],
        behavior_description=behavior.get("description"),
        has_source_code=bool(behavior.get("source_code")),
        version=behavior.get("version", 1),
    )


def _to_behavior_response(behavior: Dict[str, Any]) -> BehaviorResponse:
    """Convert repository dict to BehaviorResponse."""
    return BehaviorResponse(
        id=behavior["id"],
        key=behavior["key"],
        name=behavior["name"],
        description=behavior.get("description"),
        source_code=behavior.get("source_code"),
        dependencies=behavior.get("dependencies", []),
        timeout_seconds=behavior.get("timeout_seconds", 60),
        block_network=behavior.get("block_network", True),
        version=behavior.get("version", 1),
        created_at=behavior["created_at"],
        updated_at=behavior["updated_at"],
    )


# -----------------------------------------------------------------------------
# Companion-Level Behavior Endpoints
# -----------------------------------------------------------------------------


@router.post(
    "/companions/{companion_id}/behavior-definitions",
    response_model=BehaviorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fresh behavior definition",
    description="Create a new project-scoped definition; existing keys are never reused.",
)
async def create_isolated_behavior_definition(
    companion_id: UUID,
    body: IsolatedBehaviorDefinitionCreate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Create a fresh definition for a companion's later explicit link switch."""
    await _verify_companion_access(conn, companion_id, subject.project.id)
    existing = await BehaviorRepository.get_behavior_by_project_key(
        conn, project_id=subject.project.id, behavior_key=body.key
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Behavior key already exists; definition reuse is not allowed here",
        )
    try:
        async with conn.transaction():
            created = await BehaviorRepository.create_behavior(
                conn,
                behavior_id=uuid4(),
                project_id=subject.project.id,
                key=body.key,
                name=body.name,
                description=body.description,
                source_code=body.source_code,
                dependencies=body.dependencies,
                timeout_seconds=body.timeout_seconds,
                block_network=body.block_network,
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Behavior key already exists; definition reuse is not allowed here",
        ) from exc
    return _to_behavior_response(created)


@router.post(
    "/companions/{companion_id}/behaviors/{behavior_key}/switch",
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    summary="Switch behavior definition (disabled until runtime drain is supported)",
)
async def switch_companion_behavior_definition(
    companion_id: UUID,
    behavior_key: str,
    body: BehaviorLinkSwitchRequest,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Fail closed until distributed execution drain/cache invalidation exists."""
    await _verify_companion_access(conn, companion_id, subject.project.id)
    if body.behavior_key != behavior_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request behavior_key must match the URL",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Live behavior switching is disabled: the runtime cannot yet block new executions, "
            "confirm all in-flight jobs are drained, or invalidate caches across worker processes"
        ),
    )


@router.get(
    "/companions/{companion_id}/behaviors",
    response_model=CompanionBehaviorsResponse,
    summary="List companion behaviors",
    description="Get all behaviors linked to a companion (companion-level configs only, "
    "not relationship-specific overrides).",
)
async def list_companion_behaviors(
    companion_id: UUID,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """List all behaviors linked to a companion."""
    await _verify_companion_access(conn, companion_id, subject.project.id)

    behaviors = await BehaviorRepository.get_companion_behaviors_with_details(
        conn, companion_id, include_relationship_overrides=False
    )

    response_behaviors = [_to_link_response(b, companion_id) for b in behaviors]

    return CompanionBehaviorsResponse(
        companion_id=companion_id,
        behaviors=response_behaviors,
        total=len(response_behaviors),
    )


@router.post(
    "/companions/{companion_id}/behaviors",
    response_model=BehaviorLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Link behavior to companion",
    description="Create a new behavior and link it to the companion, or link an existing behavior.",
)
async def create_companion_behavior(
    companion_id: UUID,
    body: BehaviorLinkCreate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Create a behavior and link it to a companion.

    If a behavior with the same key already exists in the project, links to it.
    Otherwise, creates a new behavior (source_code can be added later via PATCH).
    """
    await _verify_companion_access(conn, companion_id, subject.project.id)

    # Check if behavior already exists in project
    existing_behavior = await BehaviorRepository.get_behavior_by_project_key(
        conn, project_id=subject.project.id, behavior_key=body.behavior_key
    )

    if existing_behavior:
        behavior_id = existing_behavior["id"]
    else:
        # Create new behavior (minimal - source code can be added via PATCH)
        behavior_id = uuid4()
        await BehaviorRepository.create_behavior(
            conn,
            behavior_id=behavior_id,
            project_id=subject.project.id,
            key=body.behavior_key,
            name=body.behavior_key,  # Use key as name initially
            source_code="",  # Empty source code - can be added later
        )

    # Check if link already exists
    existing_link = await BehaviorRepository.get_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=body.behavior_key
    )
    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Behavior '{body.behavior_key}' is already linked to this companion",
        )

    # Create link
    await BehaviorRepository.create_companion_behavior_link(
        conn,
        companion_id=companion_id,
        behavior_id=behavior_id,
        relationship_id=None,  # Companion-level
        triggers=body.triggers,
        priority=body.priority,
        isolated=body.isolated,
        classifier_eligible=body.classifier_eligible,
        classifier_hint=body.classifier_hint,
        params=body.params,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
        enabled=body.enabled,
    )

    if body.enabled:
        await CompanionRepository.ensure_actions_layer_state(
            conn,
            companion_id,
            enabled=True,
        )

    # Fetch and return the created link
    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=body.behavior_key
    )

    if not behavior_link:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create behavior link",
        )

    return BehaviorLinkResponse(
        link_id=behavior_link["link_id"],
        companion_id=companion_id,
        relationship_id=None,
        triggers=behavior_link.get("triggers", []),
        priority=behavior_link.get("priority", False),
        isolated=behavior_link.get("isolated", False),
        enabled=behavior_link.get("enabled", True),
        classifier_eligible=behavior_link.get("classifier_eligible", True),
        classifier_hint=behavior_link.get("classifier_hint"),
        webhook_url=behavior_link.get("webhook_url"),
        params=behavior_link.get("params", {}),
        behavior_id=behavior_id,
        behavior_key=body.behavior_key,
        behavior_name=behavior_link.get("behavior_name", body.behavior_key),
        behavior_description=behavior_link.get("behavior_description"),
        has_source_code=behavior_link.get("has_source_code", False),
        version=behavior_link.get("version", 1),
    )


@router.get(
    "/companions/{companion_id}/behaviors/{behavior_key}",
    response_model=BehaviorLinkResponse,
    summary="Get companion behavior",
    description="Get details of a specific behavior linked to a companion.",
)
async def get_companion_behavior(
    companion_id: UUID,
    behavior_key: str,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Get a specific behavior linked to a companion."""
    await _verify_companion_access(conn, companion_id, subject.project.id)

    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=behavior_key
    )

    if not behavior_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' not found for this companion",
        )

    return BehaviorLinkResponse(
        link_id=behavior_link["link_id"],
        companion_id=companion_id,
        relationship_id=behavior_link.get("relationship_id"),
        triggers=behavior_link.get("triggers", []),
        priority=behavior_link.get("priority", False),
        isolated=behavior_link.get("isolated", False),
        enabled=behavior_link.get("enabled", True),
        classifier_eligible=behavior_link.get("classifier_eligible", True),
        classifier_hint=behavior_link.get("classifier_hint"),
        webhook_url=behavior_link.get("webhook_url"),
        params=behavior_link.get("params", {}),
        behavior_id=behavior_link["behavior_id"],
        behavior_key=behavior_link["behavior_key"],
        behavior_name=behavior_link.get("behavior_name", behavior_key),
        behavior_description=behavior_link.get("behavior_description"),
        has_source_code=behavior_link.get("has_source_code", False),
        version=behavior_link.get("version", 1),
    )


@router.patch(
    "/companions/{companion_id}/behaviors/{behavior_key}",
    response_model=BehaviorLinkResponse,
    summary="Update companion behavior",
    description="Update the link configuration or behavior definition for a companion behavior.",
)
async def update_companion_behavior(
    companion_id: UUID,
    behavior_key: str,
    body: BehaviorLinkUpdate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Update a behavior link for a companion."""
    await _verify_companion_access(conn, companion_id, subject.project.id)

    # Get existing link
    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=behavior_key
    )

    if not behavior_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' not found for this companion",
        )

    # Update the link
    await BehaviorRepository.update_companion_behavior_link(
        conn,
        behavior_link["link_id"],
        triggers=body.triggers,
        priority=body.priority,
        isolated=body.isolated,
        classifier_eligible=body.classifier_eligible,
        classifier_hint=body.classifier_hint,
        params=body.params,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
        enabled=body.enabled,
    )

    if body.enabled is True:
        await CompanionRepository.ensure_actions_layer_state(
            conn,
            companion_id,
            enabled=True,
        )

    # Fetch and return updated link
    updated_link = await BehaviorRepository.get_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=behavior_key
    )

    return BehaviorLinkResponse(
        link_id=updated_link["link_id"],
        companion_id=companion_id,
        relationship_id=updated_link.get("relationship_id"),
        triggers=updated_link.get("triggers", []),
        priority=updated_link.get("priority", False),
        isolated=updated_link.get("isolated", False),
        enabled=updated_link.get("enabled", True),
        classifier_eligible=updated_link.get("classifier_eligible", True),
        classifier_hint=updated_link.get("classifier_hint"),
        webhook_url=updated_link.get("webhook_url"),
        params=updated_link.get("params", {}),
        behavior_id=updated_link["behavior_id"],
        behavior_key=updated_link["behavior_key"],
        behavior_name=updated_link.get("behavior_name", behavior_key),
        behavior_description=updated_link.get("behavior_description"),
        has_source_code=updated_link.get("has_source_code", False),
        version=updated_link.get("version", 1),
    )


@router.delete(
    "/companions/{companion_id}/behaviors/{behavior_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove behavior from companion",
    description="Remove the link between a behavior and companion. Does not delete the behavior itself.",
)
async def delete_companion_behavior(
    companion_id: UUID,
    behavior_key: str,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Remove a behavior link from a companion."""
    await _verify_companion_access(conn, companion_id, subject.project.id)

    deleted = await BehaviorRepository.delete_behavior_link_by_key(
        conn, companion_id=companion_id, behavior_key=behavior_key
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' not found for this companion",
        )


# -----------------------------------------------------------------------------
# Relationship-Level Behavior Override Endpoints
# -----------------------------------------------------------------------------


@router.get(
    "/relationships/{relationship_id}/behaviors",
    response_model=RelationshipBehaviorsResponse,
    summary="List relationship behavior overrides",
    description="Get all behavior overrides specific to a relationship.",
)
async def list_relationship_behaviors(
    relationship_id: UUID,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """List all behavior overrides for a relationship."""
    relationship, _companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    behaviors = await BehaviorRepository.get_relationship_behavior_overrides(conn, relationship_id)

    response_behaviors = []
    for b in behaviors:
        response_behaviors.append(
            BehaviorLinkResponse(
                link_id=b["link_id"],
                companion_id=b["companion_id"],
                relationship_id=relationship_id,
                triggers=b.get("triggers", []),
                priority=b.get("priority", False),
                isolated=b.get("isolated", False),
                enabled=b.get("enabled", True),
                classifier_eligible=b.get("classifier_eligible", True),
                classifier_hint=b.get("classifier_hint"),
                webhook_url=b.get("webhook_url"),
                params=b.get("params", {}),
                behavior_id=b["id"],
                behavior_key=b["key"],
                behavior_name=b["name"],
                behavior_description=b.get("description"),
                has_source_code=bool(b.get("source_code")),
                version=b.get("version", 1),
            )
        )

    return RelationshipBehaviorsResponse(
        relationship_id=relationship_id,
        companion_id=relationship.companion_id,
        behaviors=response_behaviors,
        total=len(response_behaviors),
    )


@router.post(
    "/relationships/{relationship_id}/behaviors",
    response_model=BehaviorLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create relationship behavior override",
    description="Create a relationship-specific behavior override. "
    "The behavior must already be linked to the companion.",
)
async def create_relationship_behavior(
    relationship_id: UUID,
    body: BehaviorLinkCreate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Create a relationship-specific behavior override.

    The behavior must already be linked to the companion at the companion level.
    This creates a relationship-specific override with custom triggers/config.
    """
    relationship, _companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    # Check if behavior exists and is linked to companion
    behavior = await BehaviorRepository.get_behavior_by_project_key(
        conn, project_id=subject.project.id, behavior_key=body.behavior_key
    )

    if not behavior:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{body.behavior_key}' not found in project",
        )

    # Check if relationship-level override already exists
    existing_link = await BehaviorRepository.get_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=body.behavior_key,
        relationship_id=relationship_id,
    )
    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Behavior override for '{body.behavior_key}' already exists for this relationship",
        )

    # Create relationship-level override
    await BehaviorRepository.create_companion_behavior_link(
        conn,
        companion_id=relationship.companion_id,
        behavior_id=behavior["id"],
        relationship_id=relationship_id,
        triggers=body.triggers,
        priority=body.priority,
        isolated=body.isolated,
        classifier_eligible=body.classifier_eligible,
        classifier_hint=body.classifier_hint,
        params=body.params,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
        enabled=body.enabled,
    )

    # Fetch and return the created override
    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=body.behavior_key,
        relationship_id=relationship_id,
    )

    return BehaviorLinkResponse(
        link_id=behavior_link["link_id"],
        companion_id=relationship.companion_id,
        relationship_id=relationship_id,
        triggers=behavior_link.get("triggers", []),
        priority=behavior_link.get("priority", False),
        isolated=behavior_link.get("isolated", False),
        enabled=behavior_link.get("enabled", True),
        classifier_eligible=behavior_link.get("classifier_eligible", True),
        classifier_hint=behavior_link.get("classifier_hint"),
        webhook_url=behavior_link.get("webhook_url"),
        params=behavior_link.get("params", {}),
        behavior_id=behavior["id"],
        behavior_key=body.behavior_key,
        behavior_name=behavior_link.get("behavior_name", body.behavior_key),
        behavior_description=behavior_link.get("behavior_description"),
        has_source_code=behavior_link.get("has_source_code", False),
        version=behavior_link.get("version", 1),
    )


@router.get(
    "/relationships/{relationship_id}/behaviors/{behavior_key}",
    response_model=BehaviorLinkResponse,
    summary="Get relationship behavior override",
    description="Get a specific behavior override for a relationship.",
)
async def get_relationship_behavior(
    relationship_id: UUID,
    behavior_key: str,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Get a relationship-specific behavior override."""
    relationship, _companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=behavior_key,
        relationship_id=relationship_id,
    )

    if not behavior_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior override for '{behavior_key}' not found for this relationship",
        )

    return BehaviorLinkResponse(
        link_id=behavior_link["link_id"],
        companion_id=relationship.companion_id,
        relationship_id=relationship_id,
        triggers=behavior_link.get("triggers", []),
        priority=behavior_link.get("priority", False),
        isolated=behavior_link.get("isolated", False),
        enabled=behavior_link.get("enabled", True),
        classifier_eligible=behavior_link.get("classifier_eligible", True),
        classifier_hint=behavior_link.get("classifier_hint"),
        webhook_url=behavior_link.get("webhook_url"),
        params=behavior_link.get("params", {}),
        behavior_id=behavior_link["behavior_id"],
        behavior_key=behavior_link["behavior_key"],
        behavior_name=behavior_link.get("behavior_name", behavior_key),
        behavior_description=behavior_link.get("behavior_description"),
        has_source_code=behavior_link.get("has_source_code", False),
        version=behavior_link.get("version", 1),
    )


@router.patch(
    "/relationships/{relationship_id}/behaviors/{behavior_key}",
    response_model=BehaviorLinkResponse,
    summary="Update relationship behavior override",
    description="Update a relationship-specific behavior override.",
)
async def update_relationship_behavior(
    relationship_id: UUID,
    behavior_key: str,
    body: BehaviorLinkUpdate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Update a relationship-specific behavior override."""
    relationship, _companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    behavior_link = await BehaviorRepository.get_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=behavior_key,
        relationship_id=relationship_id,
    )

    if not behavior_link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior override for '{behavior_key}' not found for this relationship",
        )

    # Update the link
    await BehaviorRepository.update_companion_behavior_link(
        conn,
        behavior_link["link_id"],
        triggers=body.triggers,
        priority=body.priority,
        isolated=body.isolated,
        classifier_eligible=body.classifier_eligible,
        classifier_hint=body.classifier_hint,
        params=body.params,
        webhook_url=body.webhook_url,
        webhook_secret=body.webhook_secret,
        enabled=body.enabled,
    )

    # Fetch and return updated link
    updated_link = await BehaviorRepository.get_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=behavior_key,
        relationship_id=relationship_id,
    )

    return BehaviorLinkResponse(
        link_id=updated_link["link_id"],
        companion_id=relationship.companion_id,
        relationship_id=relationship_id,
        triggers=updated_link.get("triggers", []),
        priority=updated_link.get("priority", False),
        isolated=updated_link.get("isolated", False),
        enabled=updated_link.get("enabled", True),
        classifier_eligible=updated_link.get("classifier_eligible", True),
        classifier_hint=updated_link.get("classifier_hint"),
        webhook_url=updated_link.get("webhook_url"),
        params=updated_link.get("params", {}),
        behavior_id=updated_link["behavior_id"],
        behavior_key=updated_link["behavior_key"],
        behavior_name=updated_link.get("behavior_name", behavior_key),
        behavior_description=updated_link.get("behavior_description"),
        has_source_code=updated_link.get("has_source_code", False),
        version=updated_link.get("version", 1),
    )


@router.delete(
    "/relationships/{relationship_id}/behaviors/{behavior_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete relationship behavior override",
    description="Delete a relationship-specific behavior override. "
    "The companion-level config will apply after this.",
)
async def delete_relationship_behavior(
    relationship_id: UUID,
    behavior_key: str,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Delete a relationship-specific behavior override."""
    relationship, _companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    deleted = await BehaviorRepository.delete_behavior_link_by_key(
        conn,
        companion_id=relationship.companion_id,
        behavior_key=behavior_key,
        relationship_id=relationship_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior override for '{behavior_key}' not found for this relationship",
        )


# -----------------------------------------------------------------------------
# Behavior Definition Endpoints (optional, for managing behavior source code)
# -----------------------------------------------------------------------------


@router.patch(
    "/companions/{companion_id}/behaviors/{behavior_key}/definition",
    response_model=BehaviorResponse,
    summary="Update behavior definition",
    description="Update the behavior source code and configuration. "
    "This updates the behavior itself, not the link configuration.",
)
async def update_behavior_definition(
    companion_id: UUID,
    behavior_key: str,
    body: BehaviorUpdate,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Update a behavior's definition (source code, dependencies, etc.)."""
    await _verify_companion_access(conn, companion_id, subject.project.id)

    # Get the behavior
    behavior = await BehaviorRepository.get_behavior_by_project_key(
        conn, project_id=subject.project.id, behavior_key=behavior_key
    )

    if not behavior:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' not found",
        )

    # Update the behavior definition
    updated = await BehaviorRepository.update_behavior(
        conn,
        behavior["id"],
        name=body.name,
        description=body.description,
        source_code=body.source_code,
        dependencies=body.dependencies,
        timeout_seconds=body.timeout_seconds,
        block_network=body.block_network,
    )

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update behavior",
        )

    return _to_behavior_response(updated)


# -----------------------------------------------------------------------------
# Behavior Trigger Endpoints (programmatic execution)
# -----------------------------------------------------------------------------


@router.post(
    "/relationships/{relationship_id}/behaviors/{behavior_key}/trigger",
    response_model=TriggerBehaviorResponse,
    summary="Trigger a behavior",
    description="Programmatically trigger a behavior to run for a relationship. "
    "Creates a job in the queue that will be processed by the behavior executor. "
    "Useful for triggering post-conversation synthesis or other async behaviors.",
)
async def trigger_behavior(
    relationship_id: UUID,
    behavior_key: str,
    body: TriggerBehaviorRequest = None,
    subject: ProjectApiKeySubject = Depends(get_project_api_subject),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Trigger a behavior to run for a relationship.

    This creates a job in the queue with higher priority (priority=10) that will
    be picked up by the Modal behavior executor on the next poll cycle.
    """
    # Verify relationship access
    relationship, companion = await _verify_relationship_access(
        conn, relationship_id, subject.project.id
    )

    # Verify behavior exists and is linked to this companion
    behavior = await BehaviorRepository.get_behavior_by_project_key(
        conn, project_id=subject.project.id, behavior_key=behavior_key
    )

    if not behavior:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' not found",
        )

    # Check if behavior is linked to this companion
    link = await conn.fetchrow(
        """
        SELECT cbl.id, cbl.enabled
        FROM companion_behavior_links cbl
        WHERE cbl.companion_id = $1
          AND cbl.behavior_id = $2
          AND (cbl.relationship_id IS NULL OR cbl.relationship_id = $3)
        ORDER BY cbl.relationship_id NULLS LAST
        LIMIT 1
        """,
        companion.id,
        behavior["id"],
        relationship_id,
    )

    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Behavior '{behavior_key}' is not linked to this companion",
        )

    if not link["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Behavior '{behavior_key}' is disabled",
        )

    # Create job with higher priority for API-triggered behaviors
    job_id = uuid4()
    await conn.execute(
        """
        INSERT INTO jobs (
            id, job_type, companion_id, external_user_id,
            params, status, priority, created_at
        ) VALUES ($1, 'behavior_execution', $2, $3, $4, 'pending', $5, NOW())
        """,
        job_id,
        companion.id,
        relationship.external_user_id,
        {
            "behavior_key": behavior_key,
            "relationship_id": str(relationship_id),
            "trigger_source": "api",
            "trigger_details": "api:manual",
            "extra_context": body.context if body and body.context else None,
            "turn_count": (relationship.message_count or 0) // 2 + 1,
        },
        10,  # Higher priority for API-triggered behaviors
    )

    logger.info(
        "Behavior triggered via API: relationship=%s, behavior=%s, job_id=%s",
        relationship_id,
        behavior_key,
        job_id,
    )

    return TriggerBehaviorResponse(
        job_id=job_id,
        status="queued",
        behavior_key=behavior_key,
    )
