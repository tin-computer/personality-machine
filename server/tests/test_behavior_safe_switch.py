"""Synthetic database contract tests for behavior link compare-and-swap."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from app.repositories.behavior_repository import BehaviorRepository


@pytest.fixture
async def synthetic_conn():
    """Use an explicitly designated disposable database, never a dev/live DSN."""
    dsn = os.getenv("PM_SAFE_SWITCH_TEST_DSN")
    if not dsn:
        pytest.skip("PM_SAFE_SWITCH_TEST_DSN is not configured")
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


def _id(value: int) -> UUID:
    return UUID(int=value)


async def _seed(conn, *, temporary_tables: bool = True):
    project_id = _id(1)
    companion_ids = [_id(i) for i in range(10, 14)]
    old_behavior_id = _id(20)
    new_behavior_id = _id(21)
    relationship_ids = [_id(i) for i in range(30, 34)]
    link_ids = [_id(i) for i in range(40, 48)]

    temp = "TEMP " if temporary_tables else ""
    await conn.execute(
        f"CREATE {temp}TABLE companions (id UUID PRIMARY KEY, project_id UUID NOT NULL)"
    )
    await conn.execute(
        f"CREATE {temp}TABLE behaviors (id UUID PRIMARY KEY, project_id UUID NOT NULL, "
        "key TEXT UNIQUE NOT NULL, source_code TEXT NOT NULL)"
    )
    await conn.execute(
        f"CREATE {temp}TABLE relationships (id UUID PRIMARY KEY, companion_id UUID NOT NULL)"
    )
    await conn.execute(
        f"CREATE {temp}TABLE companion_behavior_links (id UUID PRIMARY KEY, "
        "companion_id UUID NOT NULL, "
        "relationship_id UUID NULL, behavior_id UUID NOT NULL REFERENCES behaviors(id), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    )
    await conn.execute(
        f"CREATE {temp}TABLE jobs (companion_id UUID, behavior_key TEXT, status TEXT NOT NULL)"
    )
    await conn.execute(
        "INSERT INTO behaviors VALUES ($1, $2, $3, $4)",
        old_behavior_id,
        project_id,
        "old",
        "keep-me",
    )
    await conn.execute(
        "INSERT INTO behaviors VALUES ($1, $2, $3, $4)",
        new_behavior_id,
        project_id,
        "new-v1",
        "new-source",
    )

    for index, companion_id in enumerate(companion_ids):
        await conn.execute("INSERT INTO companions VALUES ($1, $2)", companion_id, project_id)
        await conn.execute(
            "INSERT INTO relationships VALUES ($1, $2)",
            relationship_ids[index],
            companion_id,
        )
        await conn.execute(
            "INSERT INTO companion_behavior_links "
            "(id, companion_id, behavior_id) VALUES ($1, $2, $3)",
            link_ids[index],
            companion_id,
            old_behavior_id,
        )
        await conn.execute(
            "INSERT INTO companion_behavior_links (id, companion_id, relationship_id, behavior_id) "
            "VALUES ($1, $2, $3, $4)",
            link_ids[index + 4],
            companion_id,
            relationship_ids[index],
            old_behavior_id,
        )

    targets = [
        {
            "link_id": link_ids[0],
            "relationship_id": None,
            "expected_behavior_id": old_behavior_id,
        },
        {
            "link_id": link_ids[4],
            "relationship_id": relationship_ids[0],
            "expected_behavior_id": old_behavior_id,
        },
    ]
    return project_id, companion_ids, old_behavior_id, new_behavior_id, targets, link_ids


@pytest.mark.live
async def test_safe_switch_changes_only_explicit_companion_and_is_idempotent(synthetic_conn):
    conn = synthetic_conn
    project_id, companions, old_id, new_id, targets, links = await _seed(conn)

    result = await BehaviorRepository.switch_companion_behavior_links(
        conn,
        companion_id=companions[0],
        project_id=project_id,
        behavior_key="old",
        new_behavior_id=new_id,
        targets=targets,
    )
    assert result == {"switched": 2, "already_switched": False}
    retry = await BehaviorRepository.switch_companion_behavior_links(
        conn,
        companion_id=companions[0],
        project_id=project_id,
        behavior_key="old",
        new_behavior_id=new_id,
        targets=targets,
    )
    assert retry == {"switched": 2, "already_switched": True}

    target_rows = await conn.fetch(
        "SELECT behavior_id FROM companion_behavior_links WHERE id = ANY($1::uuid[])",
        [links[0], links[4]],
    )
    assert {row["behavior_id"] for row in target_rows} == {new_id}
    other_rows = await conn.fetch(
        "SELECT behavior_id FROM companion_behavior_links WHERE companion_id = ANY($1::uuid[])",
        companions[1:],
    )
    assert len(other_rows) == 6
    assert all(row["behavior_id"] == old_id for row in other_rows)
    definition = await conn.fetchrow("SELECT source_code FROM behaviors WHERE id = $1", old_id)
    assert definition["source_code"] == "keep-me"


@pytest.mark.live
async def test_safe_switch_rejects_missing_override_stale_expectation_and_active_jobs(
    synthetic_conn,
):
    conn = synthetic_conn
    project_id, companions, old_id, new_id, targets, _links = await _seed(conn)

    with pytest.raises(ValueError, match="incomplete"):
        await BehaviorRepository.switch_companion_behavior_links(
            conn,
            companion_id=companions[0],
            project_id=project_id,
            behavior_key="old",
            new_behavior_id=new_id,
            targets=targets[:1],
        )
    with pytest.raises(ValueError, match="incomplete"):
        await BehaviorRepository.switch_companion_behavior_links(
            conn,
            companion_id=companions[0],
            project_id=project_id,
            behavior_key="old",
            new_behavior_id=new_id,
            targets=targets + [
                {
                    "link_id": _id(41),
                    "relationship_id": None,
                    "expected_behavior_id": old_id,
                }
            ],
        )
    unchanged = await conn.fetchval(
        "SELECT COUNT(*) FROM companion_behavior_links "
        "WHERE companion_id = $1 AND behavior_id = $2",
        companions[0],
        old_id,
    )
    assert unchanged == 2

    await conn.execute(
        "UPDATE companion_behavior_links SET behavior_id = $1 WHERE id = $2",
        new_id,
        targets[0]["link_id"],
    )
    with pytest.raises(ValueError, match="expected behavior_id changed"):
        await BehaviorRepository.switch_companion_behavior_links(
            conn,
            companion_id=companions[0],
            project_id=project_id,
            behavior_key="old",
            new_behavior_id=new_id,
            targets=targets,
        )

    await conn.execute(
        "UPDATE companion_behavior_links SET behavior_id = $1 WHERE id = $2",
        old_id,
        targets[0]["link_id"],
    )
    for active_status in ("pending", "claimed", "running"):
        await conn.execute("DELETE FROM jobs")
        await conn.execute(
            "INSERT INTO jobs VALUES ($1, 'old', $2)", companions[0], active_status
        )
        with pytest.raises(ValueError, match="active behavior jobs"):
            await BehaviorRepository.switch_companion_behavior_links(
                conn,
                companion_id=companions[0],
                project_id=project_id,
                behavior_key="old",
                new_behavior_id=new_id,
                targets=targets,
            )


@pytest.mark.live
async def test_safe_switch_rolls_back_all_links_when_an_update_fails(synthetic_conn):
    conn = synthetic_conn
    project_id, companions, old_id, new_id, targets, _links = await _seed(conn)
    failing_id = targets[1]["link_id"]
    await conn.execute(
        f"""CREATE FUNCTION pg_temp.fail_selected_link() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.id = '{failing_id}'::uuid THEN
            RAISE EXCEPTION 'synthetic mid-switch failure';
          END IF;
          RETURN NEW;
        END; $$"""
    )
    await conn.execute(
        "CREATE TRIGGER fail_selected_link BEFORE UPDATE ON companion_behavior_links "
        "FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_selected_link()"
    )

    with pytest.raises(asyncpg.PostgresError, match="synthetic mid-switch failure"):
        await BehaviorRepository.switch_companion_behavior_links(
            conn,
            companion_id=companions[0],
            project_id=project_id,
            behavior_key="old",
            new_behavior_id=new_id,
            targets=targets,
        )
    rows = await conn.fetch(
        "SELECT behavior_id FROM companion_behavior_links WHERE companion_id = $1",
        companions[0],
    )
    assert len(rows) == 2
    assert all(row["behavior_id"] == old_id for row in rows)


@pytest.mark.live
async def test_safe_switch_serializes_with_a_concurrent_link_change(synthetic_conn):
    conn = synthetic_conn
    schema = f"safe_switch_{uuid4().hex}"
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    other = await asyncpg.connect(os.environ["PM_SAFE_SWITCH_TEST_DSN"])
    try:
        await conn.execute(f'SET search_path TO "{schema}"')
        await other.execute(f'SET search_path TO "{schema}"')
        project_id, companions, old_id, new_id, targets, _links = await _seed(
            conn, temporary_tables=False
        )
        raced_id = _id(22)
        await conn.execute(
            "INSERT INTO behaviors VALUES ($1, $2, 'raced', 'raced-source')",
            raced_id,
            project_id,
        )

        async with other.transaction():
            await other.execute(
                "UPDATE companion_behavior_links SET behavior_id = $1 WHERE id = $2",
                raced_id,
                targets[0]["link_id"],
            )
            switch_task = asyncio.create_task(
                BehaviorRepository.switch_companion_behavior_links(
                    conn,
                    companion_id=companions[0],
                    project_id=project_id,
                    behavior_key="old",
                    new_behavior_id=new_id,
                    targets=targets,
                )
            )
            await asyncio.sleep(0.1)
            assert not switch_task.done(), "switch should wait for the concurrent writer"

        with pytest.raises(ValueError, match="incomplete"):
            await switch_task
        current = await conn.fetchval(
            "SELECT behavior_id FROM companion_behavior_links WHERE id = $1",
            targets[0]["link_id"],
        )
        assert current == raced_id
        assert old_id != new_id
    finally:
        await other.close()
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
