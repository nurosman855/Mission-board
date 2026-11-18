"""ClearPage's fail-closed agent controls. No network or AI calls at import time.

Agent registration uses Mission Control's native API via an injected transport.
Budget accounting is an application-layer preflight; provider-side hard quotas
are still required before unattended paid execution.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mission_control_bridge import HandoffError, MissionControlBridge


NATIVE_AGENT_ROLES = frozenset({"coder", "reviewer", "tester", "devops", "researcher", "assistant", "agent"})
AGENT_ROLES = {"researcher": ("clearpage-researcher", "researcher"),
               "validator": ("clearpage-validator", "reviewer"),
               "strategist": ("clearpage-strategist", "assistant"),
               "pdf_creator": ("clearpage-pdf-creator", "agent")}


def make_agent_http_transport(base_url: str, api_key: str, *, allow_live_writes: bool = False):
    """Opt-in, narrowly scoped REST transport for agent registration and SOUL."""
    if not allow_live_writes or not api_key or not base_url.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        raise HandoffError("Agent REST transport requires explicit live authorization")
    root = base_url.rstrip("/")

    def send(method: str, path: str, body: dict[str, Any] | None):
        allowed = ((method == "POST" and path == "/api/agents/register") or
                   (method in {"GET", "PUT"} and re.fullmatch(r"/api/agents/[0-9]+/soul", path)))
        if not allowed:
            raise HandoffError("Disallowed agent management endpoint")
        req = Request(root + path, method=method,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=15) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise HandoffError(f"Agent transport failure: {type(error).__name__}") from None
        if not isinstance(payload, dict):
            raise HandoffError("Invalid agent API response")
        return payload

    return send


def agent_instructions(repo_root: Path, role: str) -> str:
    """Load version-controlled SOUL, output contract and one project skill."""
    if role not in AGENT_ROLES:
        raise HandoffError("Unknown ClearPage agent role")
    base = Path(repo_root).resolve() / "clearpage" / "agents" / role
    skill_name = {"researcher": "evidence-first-market-research",
                  "validator": "audit-market-evidence",
                  "strategist": "convert-evidence-to-product-brief",
                  "pdf_creator": "build-verified-printables"}[role]
    paths = [base / "SOUL.md", base / "OUTPUT_CONTRACT.md", base / "skills" / skill_name / "SKILL.md"]
    text_parts: list[str] = []
    for path in paths:
        if not path.resolve().is_relative_to(base) or not path.is_file():
            raise HandoffError(f"Missing or unsafe instruction file: {path.name}")
        content = path.read_text(encoding="utf-8")
        if not content.strip() or len(content) > 40_000:
            raise HandoffError(f"Empty or oversized instruction file: {path.name}")
        text_parts.append(f"## {path.relative_to(base)}\n{content}")
    return "\n\n".join(["# ClearPage authoritative agent instructions", *text_parts])


def register_native_agents(transport: Callable[[str, str, dict[str, Any] | None], dict[str, Any]],
                           repo_root: Path) -> dict[str, int]:
    """Register all configured agents, install instructions in SOUL, verify readback."""
    # Validate every configuration before making the first remote mutation.
    if any(native_role not in NATIVE_AGENT_ROLES for _, native_role in AGENT_ROLES.values()):
        raise HandoffError("Unsupported native Mission Control role")
    configured = {role: agent_instructions(repo_root, role) for role in AGENT_ROLES}
    registrations: dict[str, int] = {}
    for role, (name, native_role) in AGENT_ROLES.items():
        instructions = configured[role]
        response = transport("POST", "/api/agents/register", {"name": name, "role": native_role})
        agent = response.get("agent")
        if (not isinstance(agent, dict) or agent.get("name") != name or
                agent.get("role") != native_role or type(agent.get("id")) is not int):
            raise HandoffError("Mission Control agent registration not confirmed")
        agent_id = agent["id"]
        saved = transport("PUT", f"/api/agents/{agent_id}/soul", {"soul_content": instructions})
        if saved.get("soul_content") != instructions:
            raise HandoffError("Mission Control did not confirm SOUL update")
        readback = transport("GET", f"/api/agents/{agent_id}/soul", None)
        if readback.get("soul_content") != instructions:
            raise HandoffError("Mission Control SOUL/skill readback mismatch")
        registrations[role] = agent_id
    return registrations


class RunLedger:
    """SQLite at-most-once reservation across processes sharing one ledger file.

    Reservations are never automatically retried after a crash. Operators must
    reconcile task state and record a new run ID to recover safely.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.parent.is_dir():
            raise HandoffError("Ledger parent directory must already exist")
        with closing(self._connection()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('RESERVED','COMPLETE','FAILED_NEEDS_REVIEW')),
                created_at INTEGER NOT NULL,
                result_sha256 TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS run_checkpoints (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                research_task_id INTEGER,
                validation_task_id INTEGER
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS worker_leases (
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL CHECK(stage IN ('research','validation')),
                owner TEXT NOT NULL,
                token TEXT NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                PRIMARY KEY(run_id,stage)
            )""")

    def _connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def reserve(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
            raise HandoffError("Invalid run identifier")
        with closing(self._connection()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT INTO runs(run_id,status,created_at) VALUES(?,?,?)",
                           (run_id, "RESERVED", int(time.time())))
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                raise HandoffError("Duplicate run ID; review existing task records before retry") from None

    def finish(self, run_id: str, result: dict[str, Any] | None) -> None:
        status = "COMPLETE" if result is not None else "FAILED_NEEDS_REVIEW"
        digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest() if result is not None else None
        with closing(self._connection()) as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE runs SET status=?, result_sha256=? WHERE run_id=? AND status='RESERVED'",
                                (status, digest, run_id))
            if cursor.rowcount != 1:
                db.rollback()
                raise HandoffError("Run reservation missing or already finalized")
            db.commit()

    def status(self, run_id: str) -> str | None:
        with closing(self._connection()) as db:
            row = db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return row[0] if row else None

    def checkpoint(self, run_id: str, *, research_task_id: int | None = None,
                   validation_task_id: int | None = None) -> None:
        """Monotonic ID binding; refuse reassignment or updates to finalized runs."""
        if (research_task_id is None and validation_task_id is None) or any(
            type(value) is not int or value <= 0 for value in (research_task_id, validation_task_id) if value is not None
        ):
            raise HandoffError("Invalid checkpoint task IDs")
        with closing(self._connection()) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone() != ("RESERVED",):
                db.rollback()
                raise HandoffError("Only reserved runs can be checkpointed")
            db.execute("INSERT OR IGNORE INTO run_checkpoints(run_id) VALUES(?)", (run_id,))
            existing = db.execute("SELECT research_task_id,validation_task_id FROM run_checkpoints WHERE run_id=?",
                                  (run_id,)).fetchone()
            if any(new is not None and old is not None and new != old for old, new in
                   zip(existing, (research_task_id, validation_task_id))):
                db.rollback()
                raise HandoffError("Conflicting task checkpoint; manual reconciliation required")
            db.execute("""UPDATE run_checkpoints
                SET research_task_id=COALESCE(research_task_id,?),
                    validation_task_id=COALESCE(validation_task_id,?) WHERE run_id=?""",
                       (research_task_id, validation_task_id, run_id))
            db.commit()

    def task_ids(self, run_id: str) -> tuple[int | None, int | None]:
        with closing(self._connection()) as db:
            row = db.execute("SELECT research_task_id,validation_task_id FROM run_checkpoints WHERE run_id=?",
                             (run_id,)).fetchone()
        return tuple(row) if row else (None, None)

    def acquire_lease(self, run_id: str, stage: str, owner: str, *, ttl_seconds: int = 60,
                      now_ms: int | None = None) -> str:
        """Single-owner stage lease; expired leases must be reconciled, never stolen."""
        if (stage not in {'research', 'validation'} or not isinstance(owner, str) or
                not owner.strip() or len(owner) > 128 or type(ttl_seconds) is not int or
                not 5 <= ttl_seconds <= 3600):
            raise HandoffError('Invalid worker lease parameters')
        now = int(time.time() * 1000) if now_ms is None else now_ms
        if type(now) is not int or now < 0:
            raise HandoffError('Invalid lease clock')
        token = secrets.token_hex(24)
        with closing(self._connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT status FROM runs WHERE run_id=?', (run_id,)).fetchone() != ('RESERVED',):
                db.rollback()
                raise HandoffError('Lease requires an unfinished run')
            existing = db.execute('SELECT owner,expires_at_ms FROM worker_leases WHERE run_id=? AND stage=?',
                                  (run_id, stage)).fetchone()
            if existing:
                db.rollback()
                raise HandoffError('Stage lease exists; expired leases require manual reconciliation')
            db.execute('INSERT INTO worker_leases(run_id,stage,owner,token,expires_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?)',
                       (run_id, stage, owner, token, now + ttl_seconds * 1000, now))
            db.commit()
        return token

    def heartbeat_lease(self, run_id: str, stage: str, owner: str, token: str,
                        *, ttl_seconds: int = 60, now_ms: int | None = None) -> None:
        if type(ttl_seconds) is not int or not 5 <= ttl_seconds <= 3600:
            raise HandoffError('Invalid heartbeat TTL')
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with closing(self._connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute('''UPDATE worker_leases SET expires_at_ms=?,updated_at_ms=?
                WHERE run_id=? AND stage=? AND owner=? AND token=? AND expires_at_ms>?''',
                (now + ttl_seconds * 1000, now, run_id, stage, owner, token, now))
            if updated.rowcount != 1:
                db.rollback()
                raise HandoffError('Lease expired, missing, or owned by another worker')
            db.commit()

    def lease_state(self, run_id: str, stage: str, *, now_ms: int | None = None) -> str:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with closing(self._connection()) as db:
            row = db.execute('SELECT expires_at_ms FROM worker_leases WHERE run_id=? AND stage=?',
                             (run_id, stage)).fetchone()
        if not row:
            return 'UNCLAIMED'
        return 'ACTIVE' if row[0] > now else 'EXPIRED_NEEDS_REVIEW'

    def release_lease(self, run_id: str, stage: str, owner: str, token: str,
                      *, now_ms: int | None = None) -> None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with closing(self._connection()) as db:
            db.execute('BEGIN IMMEDIATE')
            updated = db.execute('''DELETE FROM worker_leases WHERE run_id=? AND stage=?
                AND owner=? AND token=? AND expires_at_ms>?''', (run_id, stage, owner, token, now))
            if updated.rowcount != 1:
                db.rollback()
                raise HandoffError('Lease cannot be released by this worker')
            db.commit()


def run_once(bridge: MissionControlBridge, ledger: RunLedger, packet: dict[str, Any], run_id: str) -> dict[str, Any]:
    """Use the existing fixture-only bridge with durable duplicate protection."""
    if not isinstance(packet, dict) or packet.get("research_id") != run_id:
        raise HandoffError("Run ID and packet do not match")
    ledger.reserve(run_id)
    try:
        result = bridge.run_fixture(packet, run_id)
    except BaseException:
        ledger.finish(run_id, None)
        raise
    ledger.finish(run_id, result)
    return result


class BudgetedModelCalls:
    """Disabled-by-default preflight for a future model adapter.

    Every invocation reserves the configured worst-case cost before calling the
    adapter. If the adapter fails, the reservation is not refunded.
    """

    def __init__(self, call: Callable[..., Any], *, max_calls: int = 0,
                 max_cost_usd: float = 0.0, per_call_worst_case_usd: float = 0.0,
                 max_prompt_chars: int = 0, max_output_tokens_per_call: int = 0):
        if (type(max_calls) is not int or max_calls < 0 or
                type(max_prompt_chars) is not int or max_prompt_chars < 0 or
                type(max_output_tokens_per_call) is not int or max_output_tokens_per_call < 0 or
                not all(isinstance(x, (int, float)) and math.isfinite(x) and x >= 0
                        for x in (max_cost_usd, per_call_worst_case_usd))):
            raise ValueError("Invalid budget")
        self.call = call
        self.max_calls = max_calls
        self.max_cost_usd = max_cost_usd
        self.per_call_worst_case_usd = per_call_worst_case_usd
        self.max_prompt_chars = max_prompt_chars
        self.max_output_tokens_per_call = max_output_tokens_per_call
        self.calls = 0
        self.reserved_cost_usd = 0.0

    def invoke(self, *, prompt: str, max_output_tokens: int) -> Any:
        if not isinstance(prompt, str) or not prompt.strip() or type(max_output_tokens) is not int or max_output_tokens <= 0:
            raise HandoffError("Prompt and output-token ceiling required")
        if (self.max_calls == 0 or self.per_call_worst_case_usd <= 0 or
                self.max_prompt_chars == 0 or len(prompt) > self.max_prompt_chars or
                self.max_output_tokens_per_call == 0 or max_output_tokens > self.max_output_tokens_per_call or
                self.calls >= self.max_calls or
                self.reserved_cost_usd + self.per_call_worst_case_usd > self.max_cost_usd):
            raise HandoffError("Model budget unavailable or exhausted")
        self.calls += 1
        self.reserved_cost_usd += self.per_call_worst_case_usd
        return self.call(prompt=prompt, max_output_tokens=max_output_tokens)
