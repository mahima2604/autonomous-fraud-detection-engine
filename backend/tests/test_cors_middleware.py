from fastapi import FastAPI, HTTPException
import asyncio
import pytest

from app.cors import install_global_cors


def make_test_app(monkeypatch, cors_origins=None):
    if cors_origins is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", cors_origins)
    app = FastAPI()

    @app.post("/api/orders")
    def create_order():
        return {"status": "simulated"}

    @app.post("/api/http-error")
    def http_error():
        raise HTTPException(status_code=409, detail="Order is not approved")

    @app.post("/api/unhandled-error")
    def unhandled_error():
        raise RuntimeError("isolated test failure")

    return install_global_cors(app)


def request(app, method, path, headers=None):
    messages = []
    pending_request = True
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [(name.lower().encode("ascii"), value.encode("ascii")) for name, value in (headers or {}).items()],
        "client": ("test-client", 1234),
        "server": ("test-server", 80),
    }

    async def receive():
        nonlocal pending_request
        if pending_request:
            pending_request = False
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    async def invoke():
        try:
            await app(scope, receive, send)
        except RuntimeError:
            # ServerErrorMiddleware sends the 500 response, then re-raises for
            # the ASGI server's exception logging.
            pass

    asyncio.run(invoke())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def test_preflight_allows_frontend_origin_and_authorized_post_headers(monkeypatch):
    status, headers, _ = request(
        make_test_app(monkeypatch),
        "OPTIONS",
        "/api/orders",
        {
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert status == 200
    assert headers[b"access-control-allow-origin"] == b"http://localhost:5173"
    assert b"POST" in headers[b"access-control-allow-methods"]
    assert b"authorization" in headers[b"access-control-allow-headers"]


def test_cors_headers_cover_post_success_and_http_error(monkeypatch):
    app = make_test_app(monkeypatch)
    headers = {"Origin": "http://localhost:5173"}

    success_status, success_headers, _ = request(app, "POST", "/api/orders", headers)
    failure_status, failure_headers, failure_body = request(app, "POST", "/api/http-error", headers)

    assert success_status == 200
    assert success_headers[b"access-control-allow-origin"].decode() == headers["Origin"]
    assert failure_status == 409
    assert failure_headers[b"access-control-allow-origin"].decode() == headers["Origin"]
    assert b'"detail":"Order is not approved"' in failure_body


def test_cors_headers_cover_unhandled_server_error(monkeypatch):
    app = make_test_app(monkeypatch)
    origin = "http://localhost:5173"

    status, headers, _ = request(app, "POST", "/api/unhandled-error", {"Origin": origin})

    assert status == 500
    assert headers[b"access-control-allow-origin"].decode() == origin


def test_loopback_frontend_origin_remains_allowed(monkeypatch):
    app = make_test_app(monkeypatch)
    origin = "http://127.0.0.1:5173"

    status, headers, _ = request(app, "POST", "/api/orders", {"Origin": origin})

    assert status == 200
    assert headers[b"access-control-allow-origin"].decode() == origin


def test_custom_allowlist_accepts_configured_origin_only(monkeypatch):
    app = make_test_app(monkeypatch, "https://store.example")
    configured_origin = "https://store.example"
    unlisted_origin = "http://localhost:5173"

    allowed_status, allowed_headers, _ = request(
        app, "POST", "/api/orders", {"Origin": configured_origin}
    )
    denied_status, denied_headers, _ = request(
        app, "POST", "/api/orders", {"Origin": unlisted_origin}
    )

    assert allowed_status == 200
    assert allowed_headers[b"access-control-allow-origin"].decode() == configured_origin
    assert denied_status == 200
    assert b"access-control-allow-origin" not in denied_headers


def test_explicit_empty_allowlist_does_not_enable_defaults(monkeypatch):
    app = make_test_app(monkeypatch, "")
    origin = "http://localhost:5173"

    status, headers, _ = request(app, "POST", "/api/orders", {"Origin": origin})

    assert status == 200
    assert b"access-control-allow-origin" not in headers


def test_wildcard_origin_is_rejected_with_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="explicit origins"):
        install_global_cors(FastAPI())
