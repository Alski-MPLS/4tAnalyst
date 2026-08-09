"""
Feedback store — SQLite backend for engineer decisions and audit log.

Schema follows production.md spec with two additions:
  - feedback table gets src_zone, dst_zone, service as indexed columns so
    get_similar_cases() can query by traffic pattern without parsing JSON.
  - audit_log is append-only; no UPDATE or DELETE is exposed here.

The database file path is controlled by the FEEDBACK_DB env var, defaulting
to <repo-root>/feedback.db.  For Phase 4+ production, swap the connection
string for PostgreSQL by replacing _connect() — the rest of the module is
DB-agnostic via the sqlite3 / DB-API 2.0 interface.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS feedback (
    id                  TEXT PRIMARY KEY,
    request_id          TEXT NOT NULL,          -- ServiceNow ticket ID
    created_at          TEXT NOT NULL,           -- ISO-8601 UTC
    engineer_id         TEXT NOT NULL,
    recommendation_json TEXT NOT NULL,           -- full recommendation snapshot
    decision            TEXT NOT NULL            -- ACCEPTED | MODIFIED | REJECTED
                        CHECK(decision IN ('ACCEPTED','MODIFIED','REJECTED')),
    reason              TEXT,
    modification        TEXT,                    -- what the engineer changed
    platform            TEXT                     -- FORTIGATE (or BOTH for multi-device)
                        CHECK(platform IN ('FORTIGATE','BOTH', NULL)),
    -- denormalised for efficient similarity queries (avoids full JSON scan)
    src_zone            TEXT,
    dst_zone            TEXT,
    service             TEXT,
    flagged_for_review  INTEGER NOT NULL DEFAULT 0,
    flag_note           TEXT
);

CREATE INDEX IF NOT EXISTS idx_feedback_zones
    ON feedback(src_zone, dst_zone, service);

CREATE INDEX IF NOT EXISTS idx_feedback_request
    ON feedback(request_id);

CREATE INDEX IF NOT EXISTS idx_feedback_engineer
    ON feedback(engineer_id);

CREATE INDEX IF NOT EXISTS idx_feedback_decision
    ON feedback(decision);

CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,                   -- ISO-8601 UTC
    engineer_id TEXT NOT NULL,
    action      TEXT NOT NULL,
    ticket_id   TEXT,
    detail_json TEXT NOT NULL                    -- full context snapshot
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp
    ON audit_log(timestamp);

CREATE INDEX IF NOT EXISTS idx_audit_ticket
    ON audit_log(ticket_id);
"""


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads during writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _cursor(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Store class
# ---------------------------------------------------------------------------

class FeedbackStore:
    """
    Thread-safe SQLite feedback store.

    Parameters
    ----------
    db_path : Path to the SQLite file.  Created on first use.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = _connect(db_path)
        self._initialise()

    def _initialise(self) -> None:
        with _cursor(self._conn) as cur:
            cur.executescript(_DDL)
        logger.info("Feedback store ready at %s", self._db_path)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # record_feedback
    # ------------------------------------------------------------------

    def record_feedback(
        self,
        request_id: str,
        engineer_id: str,
        recommendation_json: str,
        decision: str,
        reason: str | None = None,
        modification: str | None = None,
        platform: str | None = None,
        src_zone: str | None = None,
        dst_zone: str | None = None,
        service: str | None = None,
    ) -> str:
        """
        Save an engineer's decision on a recommendation.

        Returns the generated feedback record ID.
        """
        decision_upper = decision.upper()
        if decision_upper not in ("ACCEPTED", "MODIFIED", "REJECTED"):
            raise ValueError(
                f"decision must be ACCEPTED, MODIFIED, or REJECTED — got '{decision}'"
            )

        platform_upper = platform.upper() if platform else None
        if platform_upper and platform_upper not in ("FORTIGATE", "BOTH"):
            raise ValueError(
                f"platform must be FORTIGATE or BOTH — got '{platform}'"
            )

        record_id = str(uuid.uuid4())
        now = _utcnow()

        # Extract zone/service from recommendation JSON if not explicitly provided
        if not src_zone or not dst_zone:
            try:
                rec = json.loads(recommendation_json)
                src_zone = src_zone or rec.get("src_zone", "")
                dst_zone = dst_zone or rec.get("dst_zone", "")
                service = service or rec.get("service", "")
            except (json.JSONDecodeError, AttributeError):
                pass

        with _cursor(self._conn) as cur:
            cur.execute(
                """
                INSERT INTO feedback
                  (id, request_id, created_at, engineer_id, recommendation_json,
                   decision, reason, modification, platform,
                   src_zone, dst_zone, service)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record_id, request_id, now, engineer_id, recommendation_json,
                    decision_upper, reason, modification, platform_upper,
                    src_zone, dst_zone, service,
                ),
            )

        self._write_audit(
            engineer_id=engineer_id,
            action="RECORD_FEEDBACK",
            ticket_id=request_id,
            detail={
                "feedback_id": record_id,
                "decision": decision_upper,
                "platform": platform_upper,
            },
        )

        logger.info(
            "Feedback recorded: %s | %s | %s | %s",
            record_id, request_id, engineer_id, decision_upper,
        )
        return record_id

    # ------------------------------------------------------------------
    # get_similar_cases
    # ------------------------------------------------------------------

    def get_similar_cases(
        self,
        src_zone: str,
        dst_zone: str,
        service: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find past feedback records with a matching traffic pattern.

        Matching strategy (most specific first):
          1. src_zone + dst_zone + service (exact service match)
          2. src_zone + dst_zone only (any service for that zone pair)

        Returns up to `limit` results ordered by most recent first.
        """
        results = []

        with _cursor(self._conn) as cur:
            if service:
                cur.execute(
                    """
                    SELECT id, request_id, created_at, engineer_id, decision,
                           reason, modification, platform, src_zone, dst_zone,
                           service, recommendation_json
                    FROM feedback
                    WHERE src_zone = ? AND dst_zone = ? AND service = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (src_zone, dst_zone, service, limit),
                )
                results = [dict(r) for r in cur.fetchall()]

            # Fall back to zone-pair only if no service matches (or no service given)
            if not results:
                cur.execute(
                    """
                    SELECT id, request_id, created_at, engineer_id, decision,
                           reason, modification, platform, src_zone, dst_zone,
                           service, recommendation_json
                    FROM feedback
                    WHERE src_zone = ? AND dst_zone = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (src_zone, dst_zone, limit),
                )
                results = [dict(r) for r in cur.fetchall()]

        # Parse recommendation_json back to dict for readability
        for r in results:
            try:
                r["recommendation"] = json.loads(r.pop("recommendation_json"))
            except (json.JSONDecodeError, KeyError):
                r["recommendation"] = {}

        return results

    # ------------------------------------------------------------------
    # get_feedback_summary
    # ------------------------------------------------------------------

    def get_feedback_summary(self, days: int = 30) -> dict[str, Any]:
        """
        Aggregate statistics over the last `days` days.

        Returns counts by decision, acceptance rate, top modified zones,
        and flag rate.
        """
        cutoff = _days_ago(days)

        with _cursor(self._conn) as cur:
            # Decision counts
            cur.execute(
                """
                SELECT decision, COUNT(*) as count
                FROM feedback
                WHERE created_at >= ?
                GROUP BY decision
                """,
                (cutoff,),
            )
            decision_rows = cur.fetchall()
            decisions = {r["decision"]: r["count"] for r in decision_rows}
            total = sum(decisions.values())

            # Platform breakdown
            cur.execute(
                """
                SELECT platform, COUNT(*) as count
                FROM feedback
                WHERE created_at >= ? AND platform IS NOT NULL
                GROUP BY platform
                """,
                (cutoff,),
            )
            platform_rows = cur.fetchall()
            platforms = {r["platform"]: r["count"] for r in platform_rows}

            # Top 5 zone pairs by volume
            cur.execute(
                """
                SELECT src_zone, dst_zone, COUNT(*) as count
                FROM feedback
                WHERE created_at >= ?
                  AND src_zone IS NOT NULL AND dst_zone IS NOT NULL
                GROUP BY src_zone, dst_zone
                ORDER BY count DESC
                LIMIT 5
                """,
                (cutoff,),
            )
            top_zones = [
                {"src_zone": r["src_zone"], "dst_zone": r["dst_zone"], "count": r["count"]}
                for r in cur.fetchall()
            ]

            # Flagged for review
            cur.execute(
                """
                SELECT COUNT(*) as count
                FROM feedback
                WHERE created_at >= ? AND flagged_for_review = 1
                """,
                (cutoff,),
            )
            flagged_count = cur.fetchone()["count"]

        accepted = decisions.get("ACCEPTED", 0)
        modified = decisions.get("MODIFIED", 0)
        rejected = decisions.get("REJECTED", 0)

        return {
            "period_days": days,
            "total_decisions": total,
            "accepted": accepted,
            "modified": modified,
            "rejected": rejected,
            "acceptance_rate_pct": round(accepted / total * 100, 1) if total else 0.0,
            "modification_rate_pct": round(modified / total * 100, 1) if total else 0.0,
            "rejection_rate_pct": round(rejected / total * 100, 1) if total else 0.0,
            "flagged_for_review": flagged_count,
            "by_platform": platforms,
            "top_zone_pairs": top_zones,
        }

    # ------------------------------------------------------------------
    # flag_for_review
    # ------------------------------------------------------------------

    def flag_for_review(
        self,
        recommendation_id: str,
        engineer_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        """
        Mark a feedback record for team standards review.

        Returns the updated record summary.
        """
        with _cursor(self._conn) as cur:
            cur.execute(
                "SELECT id, request_id, decision FROM feedback WHERE id = ?",
                (recommendation_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": f"No feedback record found with id '{recommendation_id}'"}

            cur.execute(
                """
                UPDATE feedback
                SET flagged_for_review = 1, flag_note = ?
                WHERE id = ?
                """,
                (note, recommendation_id),
            )

        self._write_audit(
            engineer_id=engineer_id,
            action="FLAG_FOR_REVIEW",
            ticket_id=row["request_id"],
            detail={"feedback_id": recommendation_id, "note": note},
        )

        return {
            "feedback_id": recommendation_id,
            "request_id": row["request_id"],
            "decision": row["decision"],
            "flagged": True,
            "note": note,
        }

    # ------------------------------------------------------------------
    # Audit log (internal write, exposed read for completeness)
    # ------------------------------------------------------------------

    def _write_audit(
        self,
        engineer_id: str,
        action: str,
        detail: dict,
        ticket_id: str | None = None,
    ) -> None:
        """Append an immutable audit log entry."""
        with _cursor(self._conn) as cur:
            cur.execute(
                """
                INSERT INTO audit_log (id, timestamp, engineer_id, action, ticket_id, detail_json)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    _utcnow(),
                    engineer_id,
                    action,
                    ticket_id,
                    json.dumps(detail),
                ),
            )

    def get_audit_log(
        self,
        ticket_id: str | None = None,
        engineer_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return recent audit log entries, optionally filtered."""
        where_clauses = []
        params: list[Any] = []

        if ticket_id:
            where_clauses.append("ticket_id = ?")
            params.append(ticket_id)
        if engineer_id:
            where_clauses.append("engineer_id = ?")
            params.append(engineer_id)

        where = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        params.append(limit)

        with _cursor(self._conn) as cur:
            cur.execute(
                f"""
                SELECT id, timestamp, engineer_id, action, ticket_id, detail_json
                FROM audit_log
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            rows = cur.fetchall()

        results = []
        for r in rows:
            entry = dict(r)
            try:
                entry["detail"] = json.loads(entry.pop("detail_json"))
            except (json.JSONDecodeError, KeyError):
                entry["detail"] = {}
            results.append(entry)

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(days: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
