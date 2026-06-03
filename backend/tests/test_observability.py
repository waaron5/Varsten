"""Request-id propagation and structured-logging behavior."""


def test_request_id_generated_when_absent(client):
    res = client.get("/health")
    assert res.status_code == 200
    rid = res.headers.get("x-request-id")
    assert rid and len(rid) == 32  # uuid4 hex


def test_request_id_echoed_when_provided(client):
    res = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert res.headers.get("x-request-id") == "trace-abc-123"
