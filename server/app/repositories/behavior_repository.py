"""Repository for v2 behavior management.

Provides data access for:
- behaviors table: Reusable behavior definitions (source code, config)
- companion_behavior_links table: Per-companion/relationship behavior configuration

All methods are static and require an asyncpg connection to be passed in.

Note: The table was renamed from 'actions' to 'behaviors' in migration 0049.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import asyncpg

from ..models.v2.behavior import (
    format_trigger_shorthand,
    parse_triggers,
)
from ..services.cache_manager import cache, ttl_from_env

logger = logging.getLogger(__name__)

# Cache TTL for behavior links (reduces repeated DB queries for same companion/relationship)
_BEHAVIOR_CACHE_TTL_S = ttl_from_env("BEHAVIOR_CACHE_TTL_S", 30.0)


def _parse_json_field(value: Any) -> Any:
    """Parse a JSON field that might be a string or already decoded."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _format_triggers_to_shorthand(triggers: Any) -> List[str]:
    """Convert stored triggers to shorthand strings for API response."""
    parsed = _parse_json_field(triggers) or []
    result = []
    for t in parsed:
        if isinstance(t, str):
            # Already in shorthand format
            result.append(t)
        elif isinstance(t, dict):
            result.append(format_trigger_shorthand(t))
    return result


class BehaviorRepository:
    """Data access helpers for behaviors and companion_behavior_links tables."""

    # -------------------------------------------------------------------------
    # Behavior CRUD Operations
    # -------------------------------------------------------------------------

    @staticmethod
    async def get_behavior_by_id(
        conn: asyncpg.Connection,
        behavior_id: UUID,
    ) -> Optional[Dict[str, Any]]:
        """Get a behavior by its ID."""
        row = await conn.fetchrow(
            """
            SELECT id, project_id, key, name, description, source_code,
                   dependencies, block_network, timeout_seconds, version,
                   created_at, updated_at
            FROM behaviors
            WHERE id = $1
            """,
            behavior_id,
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "source_code": row["source_code"],
            "dependencies": _parse_json_field(row["dependencies"]) or [],
            "block_network": row["block_network"],
            "timeout_seconds": row["timeout_seconds"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    async def get_behavior_by_project_key(
        conn: asyncpg.Connection,
        *,
        project_id: UUID,
        behavior_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Get a behavior by its project-scoped key.

        Behaviors are uniquely identified by (project_id, key).
        """
        row = await conn.fetchrow(
            """
            SELECT id, project_id, key, name, description, source_code,
                   dependencies, block_network, timeout_seconds, version,
                   created_at, updated_at
            FROM behaviors
            WHERE project_id = $1 AND key = $2
            """,
            project_id,
            behavior_key,
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "source_code": row["source_code"],
            "dependencies": _parse_json_field(row["dependencies"]) or [],
            "block_network": row["block_network"],
            "timeout_seconds": row["timeout_seconds"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    async def create_behavior(
        conn: asyncpg.Connection,
        *,
        behavior_id: UUID,
        project_id: UUID,
        key: str,
        name: str,
        description: Optional[str] = None,
        source_code: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        timeout_seconds: int = 60,
        block_network: bool = True,
    ) -> Dict[str, Any]:
        """Create a new behavior.

        Returns the created behavior dict.
        """
        row = await conn.fetchrow(
            """
            INSERT INTO behaviors (
                id, project_id, key, name, description, source_code,
                dependencies, timeout_seconds, block_network
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id, project_id, key, name, description, source_code,
                      dependencies, timeout_seconds, block_network, version,
                      created_at, updated_at
            """,
            behavior_id,
            project_id,
            key,
            name,
            description,
            source_code,
            dependencies or [],  # Don't json.dumps - asyncpg handles it
            timeout_seconds,
            block_network,
        )
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "source_code": row["source_code"],
            "dependencies": _parse_json_field(row["dependencies"]) or [],
            "block_network": row["block_network"],
            "timeout_seconds": row["timeout_seconds"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    async def update_behavior(
        conn: asyncpg.Connection,
        behavior_id: UUID,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        source_code: Optional[str] = None,
        dependencies: Optional[List[str]] = None,
        timeout_seconds: Optional[int] = None,
        block_network: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update an existing behavior.

        Only non-None fields are updated. Version is auto-incremented.
        Returns the updated behavior or None if not found.
        """
        updates = []
        params: List[Any] = []
        idx = 1

        if name is not None:
            params.append(name)
            updates.append(f"name = ${idx}")
            idx += 1
        if description is not None:
            params.append(description)
            updates.append(f"description = ${idx}")
            idx += 1
        if source_code is not None:
            params.append(source_code)
            updates.append(f"source_code = ${idx}")
            idx += 1
        if dependencies is not None:
            params.append(dependencies)  # Don't json.dumps - asyncpg handles it
            updates.append(f"dependencies = ${idx}")
            idx += 1
        if timeout_seconds is not None:
            params.append(timeout_seconds)
            updates.append(f"timeout_seconds = ${idx}")
            idx += 1
        if block_network is not None:
            params.append(block_network)
            updates.append(f"block_network = ${idx}")
            idx += 1

        if not updates:
            return await BehaviorRepository.get_behavior_by_id(conn, behavior_id)

        updates.append("updated_at = NOW()")

        params.append(behavior_id)
        sql = f"""
            UPDATE behaviors
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING id, project_id, key, name, description, source_code,
                      dependencies, timeout_seconds, block_network, version,
                      created_at, updated_at
        """
        row = await conn.fetchrow(sql, *params)
        if not row:
            return None
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "source_code": row["source_code"],
            "dependencies": _parse_json_field(row["dependencies"]) or [],
            "block_network": row["block_network"],
            "timeout_seconds": row["timeout_seconds"],
            "version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    async def delete_behavior(
        conn: asyncpg.Connection,
        behavior_id: UUID,
    ) -> bool:
        """Delete a behavior. Returns True if deleted."""
        result = await conn.execute(
            "DELETE FROM behaviors WHERE id = $1",
            behavior_id,
        )
        return result == "DELETE 1"

    @staticmethod
    async def get_behaviors_for_project(
        conn: asyncpg.Connection,
        project_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Get all behaviors for a project."""
        rows = await conn.fetch(
            """
            SELECT id, project_id, key, name, description, source_code,
                   dependencies, block_network, timeout_seconds, version,
                   created_at, updated_at
            FROM behaviors
            WHERE project_id = $1
            ORDER BY name
            """,
            project_id,
        )
        return [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "source_code": row["source_code"],
                "dependencies": _parse_json_field(row["dependencies"]) or [],
                "block_network": row["block_network"],
                "timeout_seconds": row["timeout_seconds"],
                "version": row["version"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # -------------------------------------------------------------------------
    # Companion Behavior Link Operations
    # -------------------------------------------------------------------------

    @staticmethod
    async def get_behavior_for_companion(
        conn: asyncpg.Connection,
        *,
        behavior_key: str,
        companion_id: UUID,
        relationship_id: Optional[UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a behavior with its companion/relationship-specific link config.

        If relationship_id is provided, looks for relationship-specific override first,
        then falls back to companion-level config.

        Returns None if the behavior is not linked to the companion or disabled.
        """
        # If relationship_id provided, try relationship-specific first
        if relationship_id:
            row = await conn.fetchrow(
                """
                SELECT
                    b.id, b.key, b.name, b.description, b.source_code,
                    b.dependencies, b.block_network, b.timeout_seconds, b.version,
                    cbl.id as link_id,
                    cbl.triggers, cbl.classifier_eligible, cbl.classifier_hint,
                    cbl.priority, cbl.isolated, cbl.webhook_url, cbl.webhook_secret,
                    cbl.params AS link_params, cbl.enabled,
                    cbl.relationship_id
                FROM behaviors b
                JOIN companion_behavior_links cbl ON cbl.behavior_id = b.id
                WHERE b.key = $1
                  AND cbl.companion_id = $2
                  AND cbl.relationship_id = $3
                  AND cbl.enabled = TRUE
                """,
                behavior_key,
                companion_id,
                relationship_id,
            )
            if row:
                return BehaviorRepository._row_to_behavior_link(row)

        # Fall back to companion-level config
        row = await conn.fetchrow(
            """
            SELECT
                b.id, b.key, b.name, b.description, b.source_code,
                b.dependencies, b.block_network, b.timeout_seconds, b.version,
                cbl.id as link_id,
                cbl.triggers, cbl.classifier_eligible, cbl.classifier_hint,
                cbl.priority, cbl.isolated, cbl.webhook_url, cbl.webhook_secret,
                cbl.params AS link_params, cbl.enabled,
                cbl.relationship_id
            FROM behaviors b
            JOIN companion_behavior_links cbl ON cbl.behavior_id = b.id
            WHERE b.key = $1
              AND cbl.companion_id = $2
              AND cbl.relationship_id IS NULL
              AND cbl.enabled = TRUE
            """,
            behavior_key,
            companion_id,
        )
        if not row:
            return None
        return BehaviorRepository._row_to_behavior_link(row)

    @staticmethod
    def _row_to_behavior_link(row: asyncpg.Record) -> Dict[str, Any]:
        """Convert a DB row to behavior link dict."""
        return {
            "id": row["id"],
            "key": row["key"],
            "name": row["name"],
            "description": row["description"],
            "source_code": row["source_code"],
            "dependencies": _parse_json_field(row["dependencies"]) or [],
            "block_network": row["block_network"],
            "timeout_seconds": row["timeout_seconds"],
            "version": row["version"],
            "link_id": row["link_id"],
            "triggers": _format_triggers_to_shorthand(row["triggers"]),
            "triggers_parsed": _parse_json_field(row["triggers"]) or [],
            "classifier_eligible": row["classifier_eligible"],
            "classifier_hint": row["classifier_hint"],
            "priority": row["priority"],
            "isolated": row["isolated"],
            "webhook_url": row["webhook_url"],
            "webhook_secret": row["webhook_secret"],
            "params": _parse_json_field(row["link_params"]) or {},
            "enabled": row["enabled"],
            "relationship_id": row["relationship_id"],
        }

    @staticmethod
    def _behavior_cache_key(
        companion_id: UUID,
        relationship_id: Optional[UUID] = None,
        classifier_eligible_only: bool = False,
    ) -> str:
        """Build cache key for behavior queries."""
        rel_part = str(relationship_id) if relationship_id else "none"
        filter_part = "ce" if classifier_eligible_only else "all"
        return f"{companion_id}:{rel_part}:{filter_part}"

    @staticmethod
    def invalidate_behavior_cache(
        companion_id: UUID,
        relationship_id: Optional[UUID] = None,
    ) -> None:
        """Invalidate cached behaviors for a companion/relationship.

        Call this when behaviors are added, removed, or modified.
        Clears both filtered and unfiltered cache entries.
        """
        # Clear all variations for this companion/relationship
        for ce_only in [True, False]:
            key = BehaviorRepository._behavior_cache_key(companion_id, relationship_id, ce_only)
            cache.delete("behaviors", key)

        # Also clear companion-level cache if relationship_id was provided
        # (since relationship changes might affect the merged view)
        if relationship_id:
            for ce_only in [True, False]:
                key = BehaviorRepository._behavior_cache_key(companion_id, None, ce_only)
                cache.delete("behaviors", key)

    @staticmethod
    async def get_active_behaviors_for_companion(
        conn: asyncpg.Connection,
        companion_id: UUID,
        *,
        relationship_id: Optional[UUID] = None,
        classifier_eligible_only: bool = False,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Get all enabled behaviors linked to a companion.

        If relationship_id is provided, includes relationship-specific overrides
        that take precedence over companion-level configs.

        Results are cached with TTL to reduce DB queries for repeated requests.

        Args:
            companion_id: The companion UUID
            relationship_id: Optional relationship UUID for relationship-specific overrides
            classifier_eligible_only: If True, only return classifier-eligible behaviors
            use_cache: Whether to use cached values (default True)

        Returns list of behavior dicts with their link config.
        """
        # Check cache first
        cache_key = BehaviorRepository._behavior_cache_key(
            companion_id, relationship_id, classifier_eligible_only
        )
        if use_cache:
            cached = cache.get("behaviors", cache_key)
            if cached is not None:
                logger.debug(f"[BehaviorRepository] Cache hit for behaviors: {cache_key}")
                return cached

        classifier_filter = "AND cbl.classifier_eligible = TRUE" if classifier_eligible_only else ""

        if relationship_id:
            # Get both companion-level and relationship-level configs
            # Relationship-level takes precedence (ordered first in UNION)
            rows = await conn.fetch(
                f"""
                WITH ranked_links AS (
                    SELECT
                        b.id, b.key, b.name, b.description, b.source_code,
                        b.dependencies, b.timeout_seconds, b.block_network, b.version,
                        cbl.id as link_id,
                        cbl.triggers, cbl.classifier_eligible, cbl.classifier_hint,
                        cbl.priority, cbl.isolated, cbl.webhook_url, cbl.webhook_secret,
                        cbl.params, cbl.enabled, cbl.relationship_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY b.key
                            ORDER BY CASE WHEN cbl.relationship_id IS NOT NULL THEN 0 ELSE 1 END
                        ) as rn
                    FROM behaviors b
                    JOIN companion_behavior_links cbl ON cbl.behavior_id = b.id
                    WHERE cbl.companion_id = $1
                      AND (cbl.relationship_id IS NULL OR cbl.relationship_id = $2)
                      AND cbl.enabled = TRUE
                      {classifier_filter}
                )
                SELECT * FROM ranked_links WHERE rn = 1
                ORDER BY name
                """,
                companion_id,
                relationship_id,
            )
        else:
            # Only get companion-level configs
            rows = await conn.fetch(
                f"""
                SELECT
                    b.id, b.key, b.name, b.description, b.source_code,
                    b.dependencies, b.timeout_seconds, b.block_network, b.version,
                    cbl.id as link_id,
                    cbl.triggers, cbl.classifier_eligible, cbl.classifier_hint,
                    cbl.priority, cbl.isolated, cbl.webhook_url, cbl.webhook_secret,
                    cbl.params, cbl.enabled, cbl.relationship_id
                FROM behaviors b
                JOIN companion_behavior_links cbl ON cbl.behavior_id = b.id
                WHERE cbl.companion_id = $1
                  AND cbl.relationship_id IS NULL
                  AND cbl.enabled = TRUE
                  {classifier_filter}
                ORDER BY b.name
                """,
                companion_id,
            )

        result = [
            {
                "id": row["id"],
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "source_code": row["source_code"],
                "dependencies": _parse_json_field(row["dependencies"]) or [],
                "timeout_seconds": row["timeout_seconds"],
                "block_network": row["block_network"],
                "version": row["version"],
                "link_id": row["link_id"],
                "triggers": _format_triggers_to_shorthand(row["triggers"]),
                "triggers_parsed": _parse_json_field(row["triggers"]) or [],
                "classifier_eligible": row["classifier_eligible"],
                "classifier_hint": row["classifier_hint"],
                "priority": row["priority"],
                "isolated": row["isolated"],
                "webhook_url": row["webhook_url"],
                "webhook_secret": row["webhook_secret"],
                "params": _parse_json_field(row["params"]) or {},
                "enabled": row["enabled"],
                "relationship_id": row.get("relationship_id"),
            }
            for row in rows
        ]

        # Cache the result
        if use_cache:
            cache.set("behaviors", cache_key, result, _BEHAVIOR_CACHE_TTL_S)
            logger.debug(f"[BehaviorRepository] Cached {len(result)} behaviors: {cache_key}")

        return result

    @staticmethod
    async def count_classifier_eligible(
        conn: asyncpg.Connection,
        companion_id: UUID,
    ) -> int:
        """Count classifier-eligible behaviors for a companion.

        This is a fast check to determine if classifier should run.
        Returns count of enabled behaviors with classifier_eligible = TRUE.

        Used by orchestrator to skip classifier when no behaviors are configured,
        saving ~100ms LLM call.
        """
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) as count
            FROM companion_behavior_links cbl
            WHERE cbl.companion_id = $1
              AND cbl.enabled = TRUE
              AND cbl.classifier_eligible = TRUE
              AND cbl.relationship_id IS NULL
            """,
            companion_id,
        )
        return row["count"] if row else 0

    @staticmethod
    async def get_classifier_eligible_behaviors(
        conn: asyncpg.Connection,
        companion_id: UUID,
        *,
        relationship_id: Optional[UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Get classifier-eligible behaviors for a companion.

        Returns only behaviors that have:
        - classifier_eligible = TRUE
        - A non-empty classifier_hint

        This is used by the orchestrator for classifier input.
        """
        return await BehaviorRepository.get_active_behaviors_for_companion(
            conn,
            companion_id,
            relationship_id=relationship_id,
            classifier_eligible_only=True,
        )

    @staticmethod
    async def get_companion_behaviors_with_details(
        conn: asyncpg.Connection,
        companion_id: UUID,
        *,
        include_relationship_overrides: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get all behaviors linked to a companion with full details.

        Used for the API listing endpoint. Includes disabled behaviors.
        """
        relationship_filter = (
            "" if include_relationship_overrides else "AND cbl.relationship_id IS NULL"
        )
        rows = await conn.fetch(
            f"""
            SELECT
                b.id, b.key, b.name, b.description, b.source_code,
                b.dependencies, b.timeout_seconds, b.block_network, b.version,
                cbl.id as link_id, cbl.triggers, cbl.priority,
                cbl.isolated, cbl.classifier_eligible, cbl.classifier_hint,
                cbl.enabled, cbl.webhook_url, cbl.params, cbl.relationship_id
            FROM behaviors b
            JOIN companion_behavior_links cbl ON b.id = cbl.behavior_id
            WHERE cbl.companion_id = $1
              {relationship_filter}
            ORDER BY b.name
            """,
            companion_id,
        )
        return [
            {
                "id": row["id"],
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "source_code": row["source_code"],
                "dependencies": _parse_json_field(row["dependencies"]) or [],
                "timeout_seconds": row["timeout_seconds"],
                "block_network": row["block_network"],
                "version": row["version"],
                "link_id": row["link_id"],
                "triggers": _format_triggers_to_shorthand(row["triggers"]),
                "triggers_parsed": _parse_json_field(row["triggers"]) or [],
                "priority": row["priority"],
                "isolated": row["isolated"],
                "classifier_eligible": row["classifier_eligible"],
                "classifier_hint": row["classifier_hint"],
                "enabled": row["enabled"],
                "webhook_url": row["webhook_url"],
                "params": _parse_json_field(row["params"]) or {},
                "relationship_id": row["relationship_id"],
            }
            for row in rows
        ]

    @staticmethod
    async def get_relationship_behavior_overrides(
        conn: asyncpg.Connection,
        relationship_id: UUID,
    ) -> List[Dict[str, Any]]:
        """Get behavior overrides specific to a relationship."""
        rows = await conn.fetch(
            """
            SELECT
                b.id, b.key, b.name, b.description, b.source_code,
                b.dependencies, b.timeout_seconds, b.block_network, b.version,
                cbl.id as link_id, cbl.companion_id, cbl.triggers, cbl.priority,
                cbl.isolated, cbl.classifier_eligible, cbl.classifier_hint,
                cbl.enabled, cbl.webhook_url, cbl.params, cbl.relationship_id
            FROM behaviors b
            JOIN companion_behavior_links cbl ON b.id = cbl.behavior_id
            WHERE cbl.relationship_id = $1
            ORDER BY b.name
            """,
            relationship_id,
        )
        return [
            {
                "id": row["id"],
                "key": row["key"],
                "name": row["name"],
                "description": row["description"],
                "source_code": row["source_code"],
                "dependencies": _parse_json_field(row["dependencies"]) or [],
                "timeout_seconds": row["timeout_seconds"],
                "block_network": row["block_network"],
                "version": row["version"],
                "link_id": row["link_id"],
                "companion_id": row["companion_id"],
                "triggers": _format_triggers_to_shorthand(row["triggers"]),
                "triggers_parsed": _parse_json_field(row["triggers"]) or [],
                "priority": row["priority"],
                "isolated": row["isolated"],
                "classifier_eligible": row["classifier_eligible"],
                "classifier_hint": row["classifier_hint"],
                "enabled": row["enabled"],
                "webhook_url": row["webhook_url"],
                "params": _parse_json_field(row["params"]) or {},
                "relationship_id": row["relationship_id"],
            }
            for row in rows
        ]

    @staticmethod
    async def create_companion_behavior_link(
        conn: asyncpg.Connection,
        *,
        companion_id: UUID,
        behavior_id: UUID,
        relationship_id: Optional[UUID] = None,
        triggers: Optional[List[str]] = None,
        priority: bool = False,
        isolated: bool = False,
        classifier_eligible: bool = True,
        classifier_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        enabled: bool = True,
    ) -> UUID:
        """Create a companion behavior link.

        Args:
            relationship_id: If None, creates companion-level config.
                           If set, creates relationship-specific override.
            triggers: List of trigger shorthand strings

        Returns the link ID.
        """
        # Parse trigger shorthand to structured format
        parsed_triggers = parse_triggers(triggers) if triggers else []

        row = await conn.fetchrow(
            """
            INSERT INTO companion_behavior_links
                (companion_id, behavior_id, relationship_id, triggers, priority,
                 isolated, classifier_eligible, classifier_hint, params,
                 webhook_url, webhook_secret, enabled)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING id
            """,
            companion_id,
            behavior_id,
            relationship_id,
            parsed_triggers,  # Don't json.dumps - asyncpg JSONB codec handles encoding
            priority,
            isolated,
            classifier_eligible,
            classifier_hint,
            params or {},  # Don't json.dumps - asyncpg JSONB codec handles encoding
            webhook_url,
            webhook_secret,
            enabled,
        )

        # Invalidate behavior cache for this companion/relationship
        BehaviorRepository.invalidate_behavior_cache(companion_id, relationship_id)

        return row["id"]

    @staticmethod
    async def update_companion_behavior_link(
        conn: asyncpg.Connection,
        link_id: UUID,
        *,
        triggers: Optional[List[str]] = None,
        priority: Optional[bool] = None,
        isolated: Optional[bool] = None,
        classifier_eligible: Optional[bool] = None,
        classifier_hint: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        webhook_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        """Update a companion behavior link.

        Only non-None fields are updated.
        Returns True if the link was found and updated.
        """
        updates = []
        update_params: List[Any] = []
        idx = 1

        if triggers is not None:
            parsed_triggers = parse_triggers(triggers)
            update_params.append(parsed_triggers)  # Don't json.dumps - asyncpg handles it
            updates.append(f"triggers = ${idx}")
            idx += 1
        if priority is not None:
            update_params.append(priority)
            updates.append(f"priority = ${idx}")
            idx += 1
        if isolated is not None:
            update_params.append(isolated)
            updates.append(f"isolated = ${idx}")
            idx += 1
        if classifier_eligible is not None:
            update_params.append(classifier_eligible)
            updates.append(f"classifier_eligible = ${idx}")
            idx += 1
        if classifier_hint is not None:
            update_params.append(classifier_hint)
            updates.append(f"classifier_hint = ${idx}")
            idx += 1
        if params is not None:
            update_params.append(params)  # Don't json.dumps - asyncpg handles it
            updates.append(f"params = ${idx}")
            idx += 1
        if webhook_url is not None:
            update_params.append(webhook_url)
            updates.append(f"webhook_url = ${idx}")
            idx += 1
        if webhook_secret is not None:
            update_params.append(webhook_secret)
            updates.append(f"webhook_secret = ${idx}")
            idx += 1
        if enabled is not None:
            update_params.append(enabled)
            updates.append(f"enabled = ${idx}")
            idx += 1

        if not updates:
            return True

        updates.append("updated_at = NOW()")

        update_params.append(link_id)
        sql = f"""
            UPDATE companion_behavior_links
            SET {", ".join(updates)}
            WHERE id = ${idx}
            RETURNING companion_id, relationship_id
        """
        row = await conn.fetchrow(sql, *update_params)
        if row:
            # Invalidate behavior cache
            BehaviorRepository.invalidate_behavior_cache(
                row["companion_id"], row["relationship_id"]
            )
            return True
        return False

    @staticmethod
    async def get_behavior_link_by_key(
        conn: asyncpg.Connection,
        *,
        companion_id: UUID,
        behavior_key: str,
        relationship_id: Optional[UUID] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get a behavior link by companion and behavior key.

        If relationship_id is provided, looks for relationship-specific override.
        Otherwise, looks for companion-level config.
        """
        if relationship_id:
            row = await conn.fetchrow(
                """
                SELECT
                    cbl.id as link_id, cbl.companion_id, cbl.behavior_id,
                    cbl.relationship_id, cbl.triggers, cbl.priority, cbl.isolated,
                    cbl.classifier_eligible, cbl.classifier_hint, cbl.params,
                    cbl.webhook_url, cbl.webhook_secret, cbl.enabled,
                    cbl.created_at, cbl.updated_at,
                    b.key, b.name, b.description, b.source_code, b.version
                FROM companion_behavior_links cbl
                JOIN behaviors b ON b.id = cbl.behavior_id
                WHERE cbl.companion_id = $1
                  AND b.key = $2
                  AND cbl.relationship_id = $3
                """,
                companion_id,
                behavior_key,
                relationship_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT
                    cbl.id as link_id, cbl.companion_id, cbl.behavior_id,
                    cbl.relationship_id, cbl.triggers, cbl.priority, cbl.isolated,
                    cbl.classifier_eligible, cbl.classifier_hint, cbl.params,
                    cbl.webhook_url, cbl.webhook_secret, cbl.enabled,
                    cbl.created_at, cbl.updated_at,
                    b.key, b.name, b.description, b.source_code, b.version
                FROM companion_behavior_links cbl
                JOIN behaviors b ON b.id = cbl.behavior_id
                WHERE cbl.companion_id = $1
                  AND b.key = $2
                  AND cbl.relationship_id IS NULL
                """,
                companion_id,
                behavior_key,
            )

        if not row:
            return None

        return {
            "link_id": row["link_id"],
            "companion_id": row["companion_id"],
            "behavior_id": row["behavior_id"],
            "relationship_id": row["relationship_id"],
            "triggers": _format_triggers_to_shorthand(row["triggers"]),
            "triggers_parsed": _parse_json_field(row["triggers"]) or [],
            "priority": row["priority"],
            "isolated": row["isolated"],
            "classifier_eligible": row["classifier_eligible"],
            "classifier_hint": row["classifier_hint"],
            "params": _parse_json_field(row["params"]) or {},
            "webhook_url": row["webhook_url"],
            "webhook_secret": row["webhook_secret"],
            "enabled": row["enabled"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "behavior_key": row["key"],
            "behavior_name": row["name"],
            "behavior_description": row["description"],
            "has_source_code": bool(row["source_code"]),
            "version": row["version"],
        }

    @staticmethod
    async def delete_companion_behavior_link(
        conn: asyncpg.Connection,
        link_id: UUID,
    ) -> bool:
        """Delete a companion behavior link.

        Returns True if a link was found and deleted.
        """
        # Get companion_id and relationship_id before delete for cache invalidation
        row = await conn.fetchrow(
            "DELETE FROM companion_behavior_links WHERE id = $1 RETURNING companion_id, relationship_id",
            link_id,
        )
        if row:
            BehaviorRepository.invalidate_behavior_cache(
                row["companion_id"], row["relationship_id"]
            )
            return True
        return False

    @staticmethod
    async def delete_behavior_link_by_key(
        conn: asyncpg.Connection,
        *,
        companion_id: UUID,
        behavior_key: str,
        relationship_id: Optional[UUID] = None,
    ) -> bool:
        """Delete a behavior link by companion and behavior key.

        Returns True if a link was found and deleted.
        """
        if relationship_id:
            result = await conn.execute(
                """
                DELETE FROM companion_behavior_links cbl
                USING behaviors b
                WHERE cbl.behavior_id = b.id
                  AND cbl.companion_id = $1
                  AND b.key = $2
                  AND cbl.relationship_id = $3
                """,
                companion_id,
                behavior_key,
                relationship_id,
            )
        else:
            result = await conn.execute(
                """
                DELETE FROM companion_behavior_links cbl
                USING behaviors b
                WHERE cbl.behavior_id = b.id
                  AND cbl.companion_id = $1
                  AND b.key = $2
                  AND cbl.relationship_id IS NULL
                """,
                companion_id,
                behavior_key,
            )
        rows_deleted = int(result.split()[-1]) if result else 0
        if rows_deleted > 0:
            # Invalidate behavior cache
            BehaviorRepository.invalidate_behavior_cache(companion_id, relationship_id)
        return rows_deleted > 0

    @staticmethod
    async def enable_behavior_link(
        conn: asyncpg.Connection,
        link_id: UUID,
    ) -> bool:
        """Enable a behavior link."""
        row = await conn.fetchrow(
            """UPDATE companion_behavior_links
               SET enabled = true, updated_at = NOW()
               WHERE id = $1
               RETURNING companion_id, relationship_id""",
            link_id,
        )
        if row:
            BehaviorRepository.invalidate_behavior_cache(
                row["companion_id"], row["relationship_id"]
            )
            return True
        return False

    @staticmethod
    async def disable_behavior_link(
        conn: asyncpg.Connection,
        link_id: UUID,
    ) -> bool:
        """Disable a behavior link (soft delete)."""
        row = await conn.fetchrow(
            """UPDATE companion_behavior_links
               SET enabled = false, updated_at = NOW()
               WHERE id = $1
               RETURNING companion_id, relationship_id""",
            link_id,
        )
        if row:
            BehaviorRepository.invalidate_behavior_cache(
                row["companion_id"], row["relationship_id"]
            )
            return True
        return False

    @staticmethod
    async def switch_companion_behavior_links(
        conn: asyncpg.Connection,
        *,
        companion_id: UUID,
        project_id: UUID,
        behavior_key: str,
        new_behavior_id: UUID,
        targets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Atomically compare-and-swap an exact companion behavior link set.

        This transaction does not drain runtime work or notify remote caches;
        callers must keep live switching disabled until those guarantees exist.
        """
        requested: dict[UUID, Dict[str, Any]] = {}
        for target in targets:
            link_id = target["link_id"]
            if link_id in requested:
                raise ValueError("duplicate target link_id")
            if target["expected_behavior_id"] == new_behavior_id:
                raise ValueError("expected behavior_id must differ from the new definition")
            requested[link_id] = target
        if not requested:
            raise ValueError("at least one target link is required")

        relationship_ids: set[UUID] = set()
        async with conn.transaction():
            # Existing API link writers take ROW EXCLUSIVE locks. Serialize the
            # inventory and swap with them so the override set cannot drift.
            await conn.execute(
                "LOCK TABLE companion_behavior_links IN SHARE ROW EXCLUSIVE MODE"
            )
            companion = await conn.fetchrow(
                "SELECT project_id FROM companions WHERE id = $1 FOR SHARE",
                companion_id,
            )
            if not companion or companion["project_id"] != project_id:
                raise ValueError("companion is missing or outside the project")

            new_definition = await conn.fetchrow(
                "SELECT id, project_id, key FROM behaviors WHERE id = $1 FOR SHARE",
                new_behavior_id,
            )
            if not new_definition or new_definition["project_id"] != project_id:
                raise ValueError("new behavior definition is missing or outside the project")
            if new_definition["key"] == behavior_key:
                raise ValueError("new definition must use a fresh behavior key")

            actual_rows = await conn.fetch(
                """
                SELECT cbl.id AS link_id, cbl.companion_id, cbl.relationship_id,
                       cbl.behavior_id, b.key AS behavior_key,
                       r.companion_id AS relationship_companion_id
                FROM companion_behavior_links cbl
                JOIN behaviors b ON b.id = cbl.behavior_id
                LEFT JOIN relationships r ON r.id = cbl.relationship_id
                WHERE cbl.companion_id = $1
                  AND b.key IN ($2, $3)
                ORDER BY cbl.id
                FOR UPDATE OF cbl
                """,
                companion_id,
                behavior_key,
                new_definition["key"],
            )
            actual_by_id = {row["link_id"]: row for row in actual_rows}
            if set(actual_by_id) != set(requested):
                raise ValueError("target link set is incomplete or contains non-target links")

            already_switched = True
            switched_link_ids = set()
            for link_id, target in requested.items():
                row = actual_by_id[link_id]
                if row["companion_id"] != companion_id:
                    raise ValueError("target link belongs to a different companion")
                if row["relationship_id"] != target["relationship_id"]:
                    raise ValueError("target relationship scope changed")
                if (
                    row["relationship_id"] is not None
                    and row["relationship_companion_id"] != companion_id
                ):
                    raise ValueError("relationship override belongs to another companion")
                if row["behavior_id"] != target["expected_behavior_id"]:
                    if row["behavior_id"] != new_behavior_id:
                        raise ValueError("expected behavior_id changed")
                    switched_link_ids.add(link_id)
                else:
                    already_switched = False
                if row["relationship_id"] is not None:
                    relationship_ids.add(row["relationship_id"])

            if switched_link_ids and not already_switched:
                raise ValueError("expected behavior_id changed")

            if not already_switched:
                active_jobs = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM jobs
                        WHERE companion_id = $1
                          AND behavior_key = $2
                          AND status IN ('pending', 'claimed', 'running')
                    )
                    """,
                    companion_id,
                    behavior_key,
                )
                if active_jobs:
                    raise ValueError("active behavior jobs must be drained before switching")

                for link_id, target in requested.items():
                    if actual_by_id[link_id]["behavior_id"] == new_behavior_id:
                        continue
                    changed = await conn.fetchval(
                        """
                        UPDATE companion_behavior_links
                        SET behavior_id = $1, updated_at = NOW()
                        WHERE id = $2 AND companion_id = $3 AND behavior_id = $4
                        RETURNING id
                        """,
                        new_behavior_id,
                        link_id,
                        companion_id,
                        target["expected_behavior_id"],
                    )
                    if changed is None:
                        raise ValueError("link compare-and-swap failed")

        # Cache invalidation is process-local. It is useful for local callers,
        # but not sufficient as a live cutover protocol across worker replicas.
        BehaviorRepository.invalidate_behavior_cache(companion_id)
        for relationship_id in relationship_ids:
            BehaviorRepository.invalidate_behavior_cache(companion_id, relationship_id)
        return {"switched": len(requested), "already_switched": already_switched}
