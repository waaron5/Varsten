"""A local, zero-cost OpenAI-compatible stub for manual onboarding walkthroughs.

The "Quick eval" and "Production SDK" onboarding paths are inline: they need a
real chat-completion response to prove the first-request moment, the fail-open
self-test, and what the Dashboard/Proof pages look like with live traffic. This
script stands in for the real OpenAI API so that proof can happen with no real
provider account, no API key, and no spend.

It implements just enough of the OpenAI wire format for the proxy's OpenAI
adapter (``app/proxy/providers/openai.py``): ``GET /v1/models`` (the connect-time
key-validation probe — see ``app/proxy/provider_validation.py``, which accepts
any 200 as a valid key) and ``POST /v1/chat/completions``, both streaming and
non-streaming. Every response is unmistakably fake so nobody confuses it with a
real model's answer.

Usage, from ``backend/``:

    uv run python scripts/fake_provider.py

Then point the backend's OpenAI upstream at it and use any string as the OpenAI
key when connecting a provider in onboarding (e.g. ``sk-fake-local-test``):

    # backend/.env
    OPENAI_BASE_URL=http://127.0.0.1:9100

Restart the API after changing ``.env`` so the new upstream takes effect.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FAKE_CONTENT = (
    "This is a canned response from the local Varsten fake-provider stub "
    "(scripts/fake_provider.py). No real model was called."
)


def _usage_for(body: dict) -> dict:
    prompt_chars = len(json.dumps(body.get("messages", []), default=str))
    in_tok = max(1, prompt_chars // 4)
    out_tok = max(1, len(FAKE_CONTENT) // 4)
    return {"prompt_tokens": in_tok, "completion_tokens": out_tok, "total_tokens": in_tok + out_tok}


def _completion_payload(body: dict) -> dict:
    model = body.get("model") or "gpt-4o-mini"
    return {
        "id": f"chatcmpl-fake-{time.time_ns()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": FAKE_CONTENT}, "finish_reason": "stop"}],
        "usage": _usage_for(body),
    }


def _stream_chunks(body: dict) -> list[bytes]:
    model = body.get("model") or "gpt-4o-mini"
    base = {"id": f"chatcmpl-fake-{time.time_ns()}", "object": "chat.completion.chunk", "model": model}
    events = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"content": FAKE_CONTENT}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    if body.get("stream_options", {}).get("include_usage"):
        events.append({**base, "choices": [], "usage": _usage_for(body)})
    lines = [f"data: {json.dumps(e)}\n\n".encode() for e in events]
    lines.append(b"data: [DONE]\n\n")
    return lines


class FakeProviderHandler(BaseHTTPRequestHandler):
    delay_ms = 0.0
    calls = 0

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?", 1)[0]
        if not path.endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

        type(self).calls += 1
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}

        if not body.get("stream"):
            return self._json(200, _completion_payload(body))

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        for chunk in _stream_chunks(body):
            self.wfile.write(chunk)
        return None

    def do_GET(self) -> None:
        # Any GET (in particular /v1/models, the connect-time key-validation
        # probe) succeeds with 200, so any string is accepted as a valid key.
        if self.path.split("?", 1)[0] == "/__stats":
            return self._json(200, {"calls": type(self).calls})
        return self._json(200, {"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model"}]})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[fake-provider] {self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--delay-ms", type=float, default=0.0, help="Artificial latency per completion call.")
    args = parser.parse_args()

    FakeProviderHandler.delay_ms = args.delay_ms
    server = ThreadingHTTPServer(("127.0.0.1", args.port), FakeProviderHandler)
    print(f"[fake-provider] listening on http://127.0.0.1:{args.port}")
    print(f"[fake-provider] set OPENAI_BASE_URL=http://127.0.0.1:{args.port} in backend/.env and restart the API")
    print("[fake-provider] any string works as the OpenAI key when connecting a provider (e.g. sk-fake-local-test)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
