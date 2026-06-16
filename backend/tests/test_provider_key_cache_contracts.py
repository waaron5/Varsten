from concurrent.futures import ThreadPoolExecutor
from time import perf_counter_ns
from uuid import uuid4

from app.proxy.keys import ProviderKeyCache


def test_cached_provider_key_resolution_avoids_fetch_and_is_under_one_ms():
    calls = {"n": 0}
    project_id = uuid4()

    def fetcher(project_id, provider):
        calls["n"] += 1
        return f"{provider}-secret-for-{project_id}"

    cache = ProviderKeyCache(fetcher=fetcher, ttl_seconds=300)

    assert cache.get(project_id, "anthropic") == f"anthropic-secret-for-{project_id}"
    assert calls["n"] == 1

    start = perf_counter_ns()
    for _ in range(1000):
        assert cache.get(project_id, "anthropic") == f"anthropic-secret-for-{project_id}"
    elapsed_per_lookup_ns = (perf_counter_ns() - start) / 1000

    assert calls["n"] == 1
    assert elapsed_per_lookup_ns < 1_000_000


def test_provider_key_cache_is_thread_safe_for_cached_tenants():
    calls = {"n": 0}
    project_id = uuid4()

    def fetcher(project_id, provider):
        calls["n"] += 1
        return f"{provider}-secret-for-{project_id}"

    cache = ProviderKeyCache(fetcher=fetcher, ttl_seconds=300)
    cache.get(project_id, "gemini")
    assert calls["n"] == 1

    with ThreadPoolExecutor(max_workers=16) as executor:
        values = list(executor.map(lambda _: cache.get(project_id, "gemini"), range(256)))

    assert set(values) == {f"gemini-secret-for-{project_id}"}
    assert calls["n"] == 1
