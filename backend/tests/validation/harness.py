"""V0 — the engine validation harness.

Unlike the unit/integration suite, validation scenarios run the engine **the way
production runs it**: real committed rows, the app's own session factories on
both the sync and async stacks, real sweeps invoked deterministically, and the
provider mocked only at the HTTP boundary. The savepoint-isolated fixtures in
tests/conftest.py deliberately wall the sync and async connections off from each
other, which makes a true closed-loop scenario impossible there — so this
harness trades isolation for realism and cleans up after itself instead:

- Every entity is namespaced under a per-run id (org name, model keys, canary
  sentinel), created committed, and torn down by cascade-deleting the org (plus
  the namespaced global pricing/catalog rows). Stale leftovers from crashed
  runs are swept on startup.
- The provider is a stateful in-process simulator (SimProvider) with per-model
  scripted behavior, so scenarios can schedule degradations and failures with
  planted ground truth.
- Every scenario plants a unique content-canary string in all prompts and runs
  ``canary_scan`` over the metadata-only stores; a single leak fails the run.
- Scenarios emit a machine-readable ValidationReport (JSON when
  VALIDATION_REPORT_DIR is set) — the raw material of the proof pack.
"""

import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.security import generate_api_key
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    ApiKey,
    AuditEvent,
    ChangeRequest,
    EngineOutcomePrior,
    EvalRun,
    ModelCatalog,
    ModelPrice,
    Organization,
    OrgMembership,
    Project,
    PromptCompression,
    Recommendation,
    RecommendationAction,
    ReplaySample,
    RequestDecisionEvent,
    UsageEvent,
    User,
)

_NAMESPACE = "vsim"


# --- report ----------------------------------------------------------------------


@dataclass
class ValidationReport:
    """One scenario's evidence: named invariant checks plus metrics."""

    scenario: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value

    def finish(self) -> None:
        """Emit the report (when configured), then enforce every check."""
        report_dir = os.environ.get("VALIDATION_REPORT_DIR")
        if report_dir:
            path = Path(report_dir)
            path.mkdir(parents=True, exist_ok=True)
            (path / f"{self.scenario}.json").write_text(
                json.dumps(
                    {
                        "scenario": self.scenario,
                        "generated_at": datetime.now(UTC).isoformat(),
                        "checks": self.checks,
                        "metrics": self.metrics,
                    },
                    indent=2,
                    default=str,
                )
            )
        failed = [c for c in self.checks if not c["passed"]]
        assert not failed, f"{self.scenario}: {len(failed)} invariant(s) failed: " + "; ".join(
            f"{c['name']} ({c['detail']})" for c in failed
        )


# --- provider simulator ------------------------------------------------------------


@dataclass
class ModelProfile:
    """Scripted behavior for one simulated model. Callables receive the model's
    1-based request ordinal so scenarios can schedule changes ('goes bad after
    request N') with exact ground truth."""

    reply: Callable[[int], str] = lambda n: "Spam"
    # None -> derive prompt tokens from the actual request text (~4 chars/token),
    # so body transforms (trim/compression) measurably change billed input.
    input_tokens: int | None = None
    output_tokens: int = 40
    # Return an (status_code, body) error for this call, or None for success.
    fail: Callable[[int], tuple[int, dict] | None] = lambda n: None

    def prompt_tokens(self, payload: dict) -> int:
        if self.input_tokens is not None:
            return self.input_tokens
        chars = len(json.dumps(payload.get("messages", []), default=str))
        return max(chars // 4, 1)


class SimProvider:
    """Stateful mock upstream. Counts every call per model, records the exact
    bodies it served, and answers embeddings deterministically."""

    def __init__(self) -> None:
        self.models: dict[str, ModelProfile] = {}
        self.calls: dict[str, int] = {}
        self.bodies: list[dict] = []

    def profile(self, model: str, **kwargs) -> ModelProfile:
        prof = ModelProfile(**kwargs)
        self.models[model] = prof
        return prof

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200, json={"data": [{"embedding": [0.1] * 1536, "index": 0}], "usage": {"prompt_tokens": 7}}
            )
        payload = json.loads(request.content)
        model = payload.get("model", "")
        self.bodies.append(payload)
        prof = self.models.get(model)
        if prof is None:
            return httpx.Response(404, json={"error": {"message": f"unknown sim model {model}"}})
        n = self.calls[model] = self.calls.get(model, 0) + 1
        failure = prof.fail(n)
        if failure is not None:
            status_code, body = failure
            return httpx.Response(status_code, json=body)
        text = prof.reply(n)
        prompt_tokens = prof.prompt_tokens(payload)
        completion = {
            "id": f"chatcmpl-sim-{n}",
            "object": "chat.completion",
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": prof.output_tokens,
                "total_tokens": prompt_tokens + prof.output_tokens,
            },
        }
        if payload.get("stream"):
            chunk = {
                "id": completion["id"],
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            }
            usage_chunk = {
                "id": completion["id"],
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [],
                "usage": completion["usage"],
            }
            body_text = f"data: {json.dumps(chunk)}\n\ndata: {json.dumps(usage_chunk)}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, content=body_text.encode(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=completion)


# --- environment --------------------------------------------------------------------


@dataclass
class SimEnv:
    """A committed, namespaced customer environment plus the clients to drive it."""

    run_id: str
    canary: str
    org_id: uuid.UUID
    project_id: uuid.UUID
    api_key: str
    user_sub: str
    provider: SimProvider
    control: TestClient  # control plane, real sync sessions
    model_big: str
    model_small: str
    model_help: str

    def db(self):
        """A fresh committed-mode sync session. Callers close it."""
        return SessionLocal()

    def project(self, db) -> Project:
        return db.get(Project, self.project_id)

    def auth(self) -> dict:
        return {"Authorization": f"Bearer {self.user_sub}"}

    def params(self) -> dict:
        return {"project_id": str(self.project_id)}


def _sweep_stale_runs(db) -> None:
    """Remove leftovers from previous crashed validation runs."""
    stale_orgs = db.scalars(select(Organization).where(Organization.name.like(f"{_NAMESPACE}-%"))).all()
    for org in stale_orgs:
        db.delete(org)
    db.execute(delete(ModelPrice).where(ModelPrice.model_key.like(f"{_NAMESPACE}-%")))
    db.execute(delete(ModelCatalog).where(ModelCatalog.model_key.like(f"{_NAMESPACE}-%")))
    db.execute(delete(User).where(User.email.like(f"%@{_NAMESPACE}.invalid")))
    db.commit()


def create_sim_env(provider: SimProvider, *, sweep_stale: bool = True) -> SimEnv:
    """Create the committed, namespaced environment: org + owner + project + API
    key, three priced models (big -> small catalog substitute, plus a compression
    route), and a control-plane client with no test session overrides.

    ``sweep_stale=False`` skips the stale-run cleanup — required when creating a
    *second* tenant inside a scenario, or the sweep would delete the live first
    tenant (it removes every vsim-* org)."""
    rid = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        if sweep_stale:
            _sweep_stale_runs(db)

        org = Organization(name=f"{_NAMESPACE}-{rid}", plan_tier="performance", subscription_status="active")
        db.add(org)
        db.flush()
        user = User(email=f"owner-{rid}@{_NAMESPACE}.invalid", auth_provider_subject=f"auth0|{_NAMESPACE}-{rid}")
        db.add(user)
        db.flush()
        db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))
        project = Project(organization_id=org.id, name=f"{_NAMESPACE}-project")
        db.add(project)
        db.flush()
        plaintext, prefix, key_hash = generate_api_key()
        db.add(ApiKey(project_id=project.id, name="sim", key_prefix=prefix, key_hash=key_hash))

        model_big = f"{_NAMESPACE}-big-{rid}"
        model_small = f"{_NAMESPACE}-small-{rid}"
        model_help = f"{_NAMESPACE}-help-{rid}"
        effective = datetime(2026, 1, 1, tzinfo=UTC)
        prices = {
            model_big: (Decimal("0.00001000"), Decimal("0.00003000")),
            model_small: (Decimal("0.00000100"), Decimal("0.00000300")),
            model_help: (Decimal("0.00000500"), Decimal("0.00001500")),
        }
        for key, (cin, cout) in prices.items():
            db.add(
                ModelPrice(
                    model_key=key,
                    provider="openai",
                    currency="USD",
                    input_cost_per_token=cin,
                    output_cost_per_token=cout,
                    cache_read_input_token_cost=cin / 2,
                    source="catalog",
                    effective_at=effective,
                )
            )
        db.add(
            ModelCatalog(model_key=model_big, provider="openai", tier="frontier", cheaper_substitute_key=model_small)
        )
        db.add(ModelCatalog(model_key=model_small, provider="openai", tier="small"))
        db.add(ModelCatalog(model_key=model_help, provider="openai", tier="small"))
        db.commit()

        return SimEnv(
            run_id=rid,
            canary=f"VSIM-CANARY-{rid}",
            org_id=org.id,
            project_id=project.id,
            api_key=plaintext,
            user_sub=user.auth_provider_subject,
            provider=provider,
            control=TestClient(app),
            model_big=model_big,
            model_small=model_small,
            model_help=model_help,
        )
    finally:
        db.close()


def teardown_sim_env(env: SimEnv) -> None:
    """Cascade-delete everything the run created."""
    cleanup = SessionLocal()
    try:
        org_row = cleanup.get(Organization, env.org_id)
        if org_row is not None:
            cleanup.delete(org_row)  # cascades projects, events, policies, ...
        cleanup.execute(delete(ModelPrice).where(ModelPrice.model_key.like(f"{_NAMESPACE}-%-{env.run_id}")))
        cleanup.execute(delete(ModelCatalog).where(ModelCatalog.model_key.like(f"{_NAMESPACE}-%-{env.run_id}")))
        user_row = cleanup.scalar(select(User).where(User.auth_provider_subject == env.user_sub))
        if user_row is not None:
            cleanup.delete(user_row)
        cleanup.commit()
    finally:
        cleanup.close()


# --- traffic --------------------------------------------------------------------------


class TrafficFactory:
    """Deterministic request builder for one simulated route."""

    def __init__(self, env: SimEnv, *, model: str, feature: str, system_prompt: str | None):
        self.env = env
        self.model = model
        self.feature = feature
        self.system_prompt = system_prompt
        self._n = 0

    def next_request(self, *, trace_id: str | None = None, user_text: str | None = None) -> tuple[dict, dict]:
        self._n += 1
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append(
            {"role": "user", "content": user_text or f"{self.env.canary} classify item {self.feature}-{self._n}"}
        )
        body = {"model": self.model, "messages": messages, "stream": False}
        metadata = {
            "feature": self.feature,
            "task_type": "classification.intent",
            "task_confidence": 0.95,
            "risk_level": "low",
        }
        if trace_id:
            metadata["trace_id"] = trace_id
        headers = {
            "Authorization": f"Bearer {self.env.api_key}",
            "X-Varsten-Metadata": json.dumps(metadata),
        }
        return body, headers


async def run_traffic(data_plane: AsyncClient, factory: TrafficFactory, count: int, **kwargs) -> list[httpx.Response]:
    """Drive requests through the live proxy; every response must be an HTTP
    success or a faithfully relayed provider error — never a Varsten 5xx."""
    responses = []
    for _ in range(count):
        body, headers = factory.next_request(**kwargs)
        responses.append(await data_plane.post("/v1/chat/completions", headers=headers, json=body))
    return responses


def sim_replay_fn(provider: SimProvider):
    """A replay_fn for the eval runners that answers through the SimProvider —
    the real runner scoring, with the provider boundary mocked exactly like the
    live proxy's. (openai_ops builds its own HTTP client, so the eval path needs
    this explicit injection.)"""

    async def _replay(messages: list[dict], params: dict, model: str, key: str) -> dict | None:
        body = {**(params or {}), "model": model, "messages": messages, "stream": False}
        request = httpx.Request("POST", "https://sim.invalid/v1/chat/completions", content=json.dumps(body).encode())
        response = provider.handler(request)
        return response.json() if response.status_code == 200 else None

    return _replay


async def tie_judge(prompt: str, incumbent: str, candidate: str, key: str) -> tuple[str, str]:
    """A deterministic pairwise judge for validation runs: equivalent answers."""
    return "tie", "sim judge: equivalent"


# --- canary scan ------------------------------------------------------------------------


# The metadata-only stores: prompt/completion text must never appear here. The
# documented content stores (replay corpus, semantic cache, compression artifact
# text) are excluded by design and governed by their own consent/retention.
_SCAN_MODELS = (
    UsageEvent,
    RequestDecisionEvent,
    Recommendation,
    RecommendationAction,
    EvalRun,
    ChangeRequest,
    EngineOutcomePrior,
    AuditEvent,
    PromptCompression,  # stores the rewrite, never the original: canary must not appear
)


def canary_scan(env: SimEnv, report: ValidationReport) -> None:
    """Fail if the content canary leaked into any metadata-only store."""
    db = env.db()
    leaks: list[str] = []
    try:
        for model in _SCAN_MODELS:
            column = getattr(model, "project_id", None) or model.organization_id
            scope = env.project_id if hasattr(model, "project_id") else env.org_id
            rows = db.scalars(select(model).where(column == scope)).all()
            for row in rows:
                blob = json.dumps({c.name: getattr(row, c.name, None) for c in model.__table__.columns}, default=str)
                if env.canary in blob:
                    leaks.append(f"{model.__tablename__}:{getattr(row, 'id', '?')}")
    finally:
        db.close()
    report.check("no_content_canary_leaks", not leaks, leaks or "clean")


def assert_replay_corpus_is_consented_store(env: SimEnv, report: ValidationReport) -> None:
    """The canary SHOULD appear in the replay corpus when capture is on — that is
    the documented content store working, not a leak."""
    db = env.db()
    try:
        rows = db.scalars(select(ReplaySample).where(ReplaySample.project_id == env.project_id)).all()
        carried = any(env.canary in json.dumps(r.request_messages, default=str) for r in rows)
    finally:
        db.close()
    report.check("replay_corpus_captured_content_by_consent", carried, f"{len(rows)} samples")
