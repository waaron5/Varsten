"""Fixtures for the validation scenarios. The harness itself lives in
harness.py (importable from scenario files); this wires it into pytest with
provider mocking and guaranteed teardown."""

import httpx
import pytest
from harness import SimProvider, create_sim_env, teardown_sim_env
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.proxy import http_client


@pytest.fixture
def sim_env(monkeypatch):
    """The committed validation environment (see harness module docstring), with
    the SimProvider wired into the proxy's upstream client and the project's
    provider key configured. Torn down by cascade even on scenario failure."""
    provider = SimProvider()
    env = create_sim_env(provider)
    monkeypatch.setattr(settings, "proxy_openai_keys", {str(env.project_id): "sk-vsim"})
    monkeypatch.setattr(http_client, "_client", httpx.AsyncClient(transport=httpx.MockTransport(provider.handler)))
    try:
        yield env
    finally:
        teardown_sim_env(env)


@pytest.fixture
async def data_plane():
    """Async client over the real app (no session overrides): the proxy uses its
    own AsyncSessionLocal sessions against committed state, like production."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
