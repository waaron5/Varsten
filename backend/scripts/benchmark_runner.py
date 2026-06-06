"""Benchmark simulator: prove Varsten's savings on a realistic prompt workload.

Streams a dataset of real LLM prompts through the live Varsten proxy and reports
the aggregate savings percentage the engine measures, broken down by lever. This
is how we generate verifiable go-to-market numbers before onboarding a client.

It drives the real proxy IN-PROCESS (ASGI), so the semantic cache, smart-routing
predicate, and token-trim transform all execute exactly as they do in production,
and the same ledger / experiment math the dashboard uses computes the result.

Upstream modes:
  default (fake)  A deterministic local OpenAI stand-in. The run is free and
                  offline. Savings are a pure function of token counts and the
                  pricing catalog, so the percentages are methodologically real
                  even though the completions are simulated. Cache hits come from
                  repeated prompts (--dup-rate), routing from small prompts, trim
                  from large multi-turn prompts.
  --real          Hit OpenAI for genuine completions (needs OPENAI access and
                  spends money). Validates the same math on real outputs.

Usage:
  uv run python -m scripts.benchmark_runner --limit 600 --dup-rate 0.25
  uv run python -m scripts.benchmark_runner --dataset sharegpt.json --real
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.security import hash_api_key
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    ApiKey,
    LeverConfig,
    OrgMembership,
    Organization,
    Project,
    ProxyPolicy,
    UsageEvent,
    User,
)
from app.proxy import experiment
from app.proxy.predicate import DEFAULT_PREDICATE
from app.proxy.embedding import embedding_input
from app.savings import month_start
from scripts.seed_demo import _seed_prices

BENCH_ORG = "Varsten Benchmark Co"
BENCH_PROJECT = "Benchmark"
BENCH_USER_EMAIL = "benchmark@varsten.local"
BENCH_API_KEY = "vk_benchmark_local_key"
INCUMBENT = "gpt-4o"
CANDIDATE = "gpt-4o-mini"


# --- workspace setup ------------------------------------------------------------


def setup_workspace(db, holdback: Decimal) -> Project:
    """Idempotently create the benchmark org/project/key, price the models, and
    activate the levers the proxy will execute: semantic cache (always on), a
    smart-routing policy (small prompts -> cheaper model) and a token-trim policy
    (large prompts get compressed) on the incumbent model."""
    org = db.scalar(select(Organization).where(Organization.name == BENCH_ORG))
    if org is None:
        org = Organization(name=BENCH_ORG)
        db.add(org)
        db.flush()
    project = db.scalar(
        select(Project).where(Project.organization_id == org.id, Project.name == BENCH_PROJECT)
    )
    if project is None:
        project = Project(organization_id=org.id, name=BENCH_PROJECT)
        db.add(project)
        db.flush()
    user = db.scalar(select(User).where(User.email == BENCH_USER_EMAIL))
    if user is None:
        user = User(email=BENCH_USER_EMAIL, name="Benchmark", auth_provider_subject="bench|varsten")
        db.add(user)
        db.flush()
    if not db.scalar(
        select(OrgMembership).where(
            OrgMembership.organization_id == org.id, OrgMembership.user_id == user.id
        )
    ):
        db.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))

    key_hash = hash_api_key(BENCH_API_KEY)
    if not db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash)):
        db.add(ApiKey(project_id=project.id, name="Benchmark key", key_prefix=BENCH_API_KEY[:7], key_hash=key_hash))

    _seed_prices(db)

    # Lever metadata (dashboard); the hot path is gated by the policies below.
    for lever, mode in {"semantic_cache": "auto", "smart_routing": "approve", "token_trim": "auto"}.items():
        cfg = db.scalar(
            select(LeverConfig).where(LeverConfig.project_id == project.id, LeverConfig.lever == lever)
        )
        if cfg is None:
            db.add(LeverConfig(organization_id=org.id, project_id=project.id, lever=lever, automation_mode=mode))
        else:
            cfg.enabled = True

    _activate_policy(db, org, project, "smart_routing", {"candidate_model": CANDIDATE, "predicate": dict(DEFAULT_PREDICATE)}, holdback)
    _activate_policy(db, org, project, "token_trim", {}, holdback)
    db.commit()
    return project


def _activate_policy(db, org, project, lever: str, params: dict, holdback: Decimal) -> None:
    policy = db.scalar(
        select(ProxyPolicy).where(
            ProxyPolicy.project_id == project.id, ProxyPolicy.lever == lever, ProxyPolicy.target_key == INCUMBENT
        )
    )
    if policy is None:
        policy = ProxyPolicy(
            organization_id=org.id, project_id=project.id, lever=lever,
            target_type="model", target_key=INCUMBENT,
        )
        db.add(policy)
    policy.params = params
    policy.enabled = True
    policy.holdback_percent = holdback
    policy.activated_at = datetime.now(timezone.utc)


def reset_usage(db, project: Project) -> None:
    """Clear prior benchmark traffic so a re-run reports only this run."""
    db.execute(delete(UsageEvent).where(UsageEvent.project_id == project.id))
    db.commit()


# --- fake upstream (default) ----------------------------------------------------


def _fake_tokens(body: dict) -> tuple[int, int]:
    """Deterministic token counts from the (possibly trimmed) prompt, so trimming
    a request genuinely lowers its billed input tokens."""
    chars = len(embedding_input(body))
    in_tok = max(1, chars // 4)
    out_tok = max(16, in_tok // 5)
    return in_tok, out_tok


def install_fake_upstream() -> None:
    """Patch the proxy's upstream + embedding calls with deterministic local
    stand-ins so the run is free and offline."""
    from app.proxy import router as proxy_router

    # The proxy builds absolute upstream URLs from this base; give it a valid one
    # so httpx is happy even though the MockTransport ignores the host.
    settings.openai_base_url = "https://upstream.benchmark.local"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        in_tok, out_tok = _fake_tokens(payload)
        model = payload.get("model", INCUMBENT)
        return httpx.Response(200, json={
            "id": "chatcmpl-bench", "object": "chat.completion", "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok, "total_tokens": in_tok + out_tok},
        })

    real = httpx.AsyncClient

    # Override ONLY the router's httpx.AsyncClient, via a shim that delegates every
    # other attribute (RequestError, etc.) to the real module. Mutating the global
    # httpx.AsyncClient would also hijack this script's own ASGI client.
    class _HttpxShim:
        AsyncClient = staticmethod(lambda *a, **k: real(transport=httpx.MockTransport(handler)))

        def __getattr__(self, name):
            return getattr(httpx, name)

    proxy_router.httpx = _HttpxShim()

    async def fake_embed(text: str, key: str) -> list[float]:
        # Deterministic per-text vector: identical prompts collide (and hit the
        # exact cache first anyway); distinct prompts are far apart, so no false
        # semantic matches inflate the cache number.
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.gauss(0, 1) for _ in range(settings.embedding_dimensions)]

    proxy_router.embed = fake_embed


# --- dataset --------------------------------------------------------------------


def _messages_from_sharegpt(conv: dict) -> list[dict] | None:
    """One ShareGPT conversation -> chat messages up to (and including) the last
    human turn, so there is a request to answer."""
    role_map = {"human": "user", "user": "user", "gpt": "assistant", "system": "system", "assistant": "assistant"}
    turns = conv.get("conversations") or conv.get("items") or []
    msgs: list[dict] = []
    for t in turns:
        role = role_map.get(t.get("from") or t.get("role") or "", "")
        content = t.get("value") or t.get("content") or ""
        if role and content:
            msgs.append({"role": role, "content": content})
    while msgs and msgs[-1]["role"] != "user":
        msgs.pop()
    return msgs or None


def _synthetic_dataset(n: int) -> list[list[dict]]:
    """A representative mix when no real dataset is supplied. Every conversation is
    UNIQUE (random entities/ids), so cache hits come only from the modelled
    --dup-rate, not accidental collisions — keeping the savings split realistic:
      ~45% short prompts  -> route to the cheaper model
      ~55% long multi-turn-> token trim (large context past the window)
    A real ShareGPT file via --dataset is the right input for a marketing number;
    this keeps the tool runnable and the distribution honest when offline."""
    rng = random.Random(42)
    short_templates = [
        "What's the capital of {x}?", "Convert {n} USD to EUR.", "Is {n} a prime number?",
        "Translate '{x}' to Spanish.", "Summarize in one line: order {x} ships on the {n}th.",
        "Define the term '{x}' in one sentence.", "What is {n} times {m}?",
    ]
    words = ["onboarding", "latency", "webhook", "invoice", "schema", "quota", "tenant", "rollback", "embedding", "cursor"]
    preamble = (
        "You are a meticulous support agent for an enterprise SaaS product. "
        "Follow the policy guide and cite the relevant section in every answer. "
    ) * 6
    out: list[list[dict]] = []
    for i in range(n):
        uid = f"{i}-{rng.randrange(10**9)}"  # makes each conversation distinct
        if rng.random() < 0.45:  # short -> route-eligible
            tmpl = rng.choice(short_templates)
            content = tmpl.format(x=f"{rng.choice(words)}-{uid}", n=rng.randint(2, 999), m=rng.randint(2, 99))
            out.append([{"role": "user", "content": content}])
        else:  # long multi-turn -> trim-eligible
            msgs = [{"role": "system", "content": f"{preamble} (session {uid})"}]
            for turn in range(rng.randint(8, 16)):
                topic = f"{rng.choice(words)}-{uid}-{turn}"
                msgs.append({"role": "user", "content": f"{preamble} Question {turn}: how do I configure {topic}?"})
                msgs.append({"role": "assistant", "content": f"To configure {topic}, open settings and apply the {topic} policy."})
            msgs.append({"role": "user", "content": f"{preamble} Final ({uid}): summarize every step above."})
            out.append(msgs)
    return out


# HuggingFace datasets-server: fetch a subset as JSON rows without downloading the
# whole dataset. ShareGPT-style datasets expose a `conversations` [{from,value}].
_HF_ROWS = "https://datasets-server.huggingface.co/rows"
_DEFAULT_SHAREGPT = "Aeala/ShareGPT_Vicuna_unfiltered"


def fetch_sharegpt_subset(count: int, dataset: str, cache_dir: str = ".cache") -> list[dict]:
    """Download a `count`-row subset of a ShareGPT-style dataset via the HF
    datasets-server (paginated, 100/req), cached to disk for repeat runs. Returns
    the raw rows ({conversations:[...]}). Raises on network failure so the caller
    can fall back."""
    import urllib.parse
    import urllib.request

    cache = Path(cache_dir) / f"{dataset.replace('/', '_')}_{count}.json"
    if cache.exists():
        print(f"Using cached ShareGPT subset ({cache}).", file=sys.stderr)
        return json.loads(cache.read_text())

    rows: list[dict] = []
    offset = 0
    while len(rows) < count:
        length = min(100, count - len(rows))
        params = urllib.parse.urlencode(
            {"dataset": dataset, "config": "default", "split": "train", "offset": offset, "length": length}
        )
        with urllib.request.urlopen(f"{_HF_ROWS}?{params}", timeout=40) as resp:
            data = json.load(resp)
        batch = [r["row"] for r in data.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += length
        print(f"  fetched {len(rows)}/{count} conversations…", file=sys.stderr)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    print(f"Cached {len(rows)} ShareGPT conversations to {cache}.", file=sys.stderr)
    return rows


def load_dataset(source: str, path: str | None, dataset_id: str, limit: int) -> list[list[dict]]:
    rows: list[dict] | None = None
    if path:
        raw = json.loads(Path(path).read_text())
        rows = raw if isinstance(raw, list) else raw.get("data", [])
    elif source == "sharegpt":
        try:
            rows = fetch_sharegpt_subset(limit, dataset_id)
        except Exception as exc:  # noqa: BLE001 - offline / dataset hiccup -> synthetic
            print(f"ShareGPT fetch failed ({exc}); falling back to synthetic.", file=sys.stderr)
            rows = None
    if rows is None:
        print("Using the built-in synthetic workload.", file=sys.stderr)
        return _synthetic_dataset(limit)

    out: list[list[dict]] = []
    for conv in rows:
        msgs = _messages_from_sharegpt(conv) if isinstance(conv, dict) else None
        if msgs:
            out.append(msgs)
        if len(out) >= limit:
            break
    if not out:
        print("Dataset yielded no usable conversations; using synthetic.", file=sys.stderr)
        return _synthetic_dataset(limit)
    print(f"Loaded {len(out)} real conversations.", file=sys.stderr)
    return out


def build_requests(convs: list[list[dict]], dup_rate: float) -> list[list[dict]]:
    """Turn conversations into chat-completion message lists, injecting exact
    duplicates at dup_rate to model the repeated queries a real workload sees
    (which the semantic cache serves at $0)."""
    rng = random.Random(7)
    requests: list[list[dict]] = []
    for msgs in convs:
        requests.append(msgs)
        if rng.random() < dup_rate:
            requests.append(msgs)  # exact repeat -> cache hit
    rng.shuffle(requests)
    return requests


# --- run ------------------------------------------------------------------------


@dataclass
class Tally:
    sent: int = 0
    cache_hits: int = 0
    routed: int = 0
    trimmed: int = 0
    control: int = 0
    errors: int = 0
    statuses: dict = field(default_factory=dict)


async def stream_requests(requests: list[list[dict]], concurrency: int) -> Tally:
    tally = Tally()
    transport = httpx.ASGITransport(app=app)
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(transport=transport, base_url="http://benchmark", timeout=60) as client:
        async def one(messages: list[dict]) -> None:
            async with sem:
                body = {"model": INCUMBENT, "messages": messages, "stream": False}
                try:
                    r = await client.post(
                        "/v1/chat/completions",
                        headers={"Authorization": f"Bearer {BENCH_API_KEY}"},
                        json=body,
                    )
                except Exception:
                    tally.errors += 1
                    return
                tally.sent += 1
                if r.status_code != 200:
                    tally.errors += 1
                    return
                cache = r.headers.get("X-Varsten-Cache")
                if cache in ("hit", "semantic"):
                    tally.cache_hits += 1
                if r.headers.get("X-Varsten-Routed"):
                    tally.routed += 1
                if r.headers.get("X-Varsten-Trim") == "applied":
                    tally.trimmed += 1
                if r.headers.get("X-Varsten-Arm") == "control":
                    tally.control += 1

        await asyncio.gather(*(one(m) for m in requests))
    return tally


# --- report ---------------------------------------------------------------------


def _d(value) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def report(db, project: Project, tally: Tally) -> None:
    start = month_start(datetime.now(timezone.utc))
    events = list(
        db.scalars(select(UsageEvent).where(UsageEvent.project_id == project.id))
    )
    actual_spend = sum((_d(e.cost_usd) for e in events), Decimal("0"))

    # Per-event measured savings: cache hits ($0, full avoided) and routed
    # treatment requests (incumbent - candidate) both record saved_usd directly.
    cache_saved = Decimal("0")
    routing_saved = Decimal("0")
    for e in events:
        meta = e.event_metadata or {}
        saved = _d(meta.get("saved_usd")) if meta.get("saved_usd") is not None else Decimal("0")
        if meta.get("cache") in ("hit", "semantic"):
            cache_saved += saved
        elif meta.get("routed"):
            routing_saved += saved

    # Token-trim is a same-model A/B (untrimmed control vs trimmed treatment);
    # its savings come from the experiment, like the dashboard's Active trims card.
    trim_ab = experiment.compute_experiment(db, project.id, INCUMBENT, INCUMBENT, start)
    trim_saved = max(_d(trim_ab.get("measured_savings_usd")), Decimal("0"))

    total_saved = cache_saved + routing_saved + trim_saved
    naive_spend = actual_spend + total_saved
    pct = (total_saved / naive_spend * 100) if naive_spend > 0 else Decimal("0")

    def line(label: str, value: Decimal) -> str:
        share = (value / naive_spend * 100) if naive_spend > 0 else Decimal("0")
        return f"  {label:<16} ${value:>12.4f}   {share:>5.1f}%"

    print("\n" + "=" * 58)
    print("  VARSTEN BENCHMARK — measured savings")
    print("=" * 58)
    print(f"  Requests sent          {tally.sent}")
    print(f"  Cache hits             {tally.cache_hits}")
    print(f"  Routed (smart routing) {tally.routed}")
    print(f"  Trimmed                {tally.trimmed}")
    print(f"  Held back (control)    {tally.control}")
    print(f"  Errors                 {tally.errors}")
    print("-" * 58)
    print(f"  Naive retail spend     ${naive_spend:.4f}")
    print(f"  Varsten optimized      ${actual_spend:.4f}")
    print("-" * 58)
    print("  Savings by lever       amount          share")
    print(line("semantic_cache", cache_saved))
    print(line("smart_routing", routing_saved))
    print(line("token_trim", trim_saved))
    print("-" * 58)
    print(f"  TOTAL SAVED            ${total_saved:.4f}")
    print(f"  AGGREGATE SAVINGS      {pct:.1f}%")
    print("=" * 58)
    print("  Method: cache + routing are per-request measured (direct); token_trim")
    print("  is a concurrent A/B (untrimmed holdback vs trimmed). Costs come from")
    print("  the versioned pricing catalog. Re-run with --real for genuine outputs.")
    print()


# --- entrypoint -----------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Varsten savings benchmark simulator")
    parser.add_argument("--source", choices=["synthetic", "sharegpt"], default="synthetic",
                        help="Workload source: built-in synthetic, or auto-download a real ShareGPT subset")
    parser.add_argument("--sharegpt-dataset", default=_DEFAULT_SHAREGPT,
                        help="HuggingFace dataset id for --source sharegpt")
    parser.add_argument("--dataset", help="Path to a local ShareGPT-style JSON file (overrides --source)")
    parser.add_argument("--limit", type=int, default=500, help="Max conversations to ingest")
    parser.add_argument("--dup-rate", type=float, default=0.25, help="Fraction of prompts repeated (drives cache)")
    parser.add_argument("--holdback", type=float, default=0.15, help="Holdback fraction per policy (control arm)")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent in-flight requests")
    parser.add_argument("--real", action="store_true", help="Use real OpenAI instead of the fake upstream")
    parser.add_argument("--keep", action="store_true", help="Keep prior benchmark traffic (default resets)")
    args = parser.parse_args()

    if not args.real:
        install_fake_upstream()

    db = SessionLocal()
    try:
        project = setup_workspace(db, Decimal(str(args.holdback)))
        # Register the project's provider key so the proxy will forward.
        settings.proxy_openai_keys = {**settings.proxy_openai_keys, str(project.id): "sk-benchmark"}
        if not args.keep:
            reset_usage(db, project)
        convs = load_dataset(args.source, args.dataset, args.sharegpt_dataset, args.limit)
        requests = build_requests(convs, args.dup_rate)
        print(f"Streaming {len(requests)} requests through the proxy "
              f"({'REAL OpenAI' if args.real else 'fake upstream'})…", file=sys.stderr)
        tally = asyncio.run(stream_requests(requests, args.concurrency))
        db.expire_all()  # re-read what the proxy committed on its own sessions
        report(db, project, tally)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
