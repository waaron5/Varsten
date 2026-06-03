"""The recommendation engine must stay off the synchronous read path: dashboard
reads serve stored recommendations and recompute at most once per staleness
window, not on every request."""
from app import recommendations as recs_mod
from app.core.config import settings


def _b(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _count_refreshes(monkeypatch) -> dict:
    calls = {"n": 0}
    real = recs_mod.refresh_recommendations

    def counting(db, project, *args, **kwargs):
        calls["n"] += 1
        return real(db, project, *args, **kwargs)

    monkeypatch.setattr(recs_mod, "refresh_recommendations", counting)
    return calls


def test_reads_recompute_at_most_once_per_window(client, provision, monkeypatch):
    token = provision(sub="auth0|gate", email="gate@example.com")["api_key"]
    calls = _count_refreshes(monkeypatch)

    # First read recomputes (no prior stamp); the rest are served from storage.
    client.get("/v1/metrics/overview", headers=_b(token))
    client.get("/v1/metrics/overview", headers=_b(token))
    client.get("/v1/command-center", headers=_b(token))
    client.get("/v1/engine/recommendations", headers=_b(token))
    client.get("/v1/recommendations", headers=_b(token))

    assert calls["n"] == 1


def test_expired_window_recomputes(client, provision, monkeypatch):
    # Zero window means every read is past staleness.
    monkeypatch.setattr(settings, "recommendations_max_age_seconds", 0)
    token = provision(sub="auth0|gate", email="gate@example.com")["api_key"]
    calls = _count_refreshes(monkeypatch)

    client.get("/v1/metrics/overview", headers=_b(token))
    client.get("/v1/metrics/overview", headers=_b(token))

    assert calls["n"] == 2
