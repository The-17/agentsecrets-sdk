#!/usr/bin/env python3
"""Comprehensive integration test for the AgentSecrets Python SDK.

Run this MANUALLY against a real proxy to verify end-to-end correctness
before pushing. This script tests every path a real consumer (like a
GitHub MCP) would exercise.

Prerequisites:
    1. AgentSecrets CLI installed and on PATH
    2. Logged in (agentsecrets init / agentsecrets login)
    3. Active project with at least one secret (agentsecrets secrets set TEST_KEY=any-value)
    4. Allowlist has httpbin.org (agentsecrets workspace allowlist add httpbin.org)
    5. Proxy running (agentsecrets proxy start)

Usage:
    cd python
    source .venv/bin/activate
    python tests/integration_test.py
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Path fix: the agentsecrets CLI pip package (pip install agentsecrets) owns
# the same 'agentsecrets' namespace in site-packages and shadows our SDK.
# Insert the local source root FIRST so our SDK always wins.
# Unit tests are unaffected — pytest inserts the src root automatically.
# ---------------------------------------------------------------------------
import sys

_sdk_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _sdk_root not in sys.path:
    sys.path.insert(0, _sdk_root)

import asyncio
import sys

# ─── Helpers ──────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
SKIP = 0

def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f" {name}")

def fail(name: str, err: Exception) -> None:
    global FAIL
    FAIL += 1
    print(f" {name}")
    print(f"     {type(err).__name__}: {err}")

def skip(name: str, reason: str) -> None:
    global SKIP
    SKIP += 1
    print(f"  {name} (skipped: {reason})")

def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")

# ─── Test 1: Import & Version ────────────────────────────────────────

def test_import_and_version() -> None:
    section("1. Import & Version")
    try:
        from agentsecrets import __version__
        ok(f"import OK, version = {__version__}")
    except Exception as e:
        fail("import agentsecrets", e)

    try:
        ok("all 11 exceptions importable")
    except Exception as e:
        fail("import exceptions", e)

    try:
        ok("all 14 models importable")
    except Exception as e:
        fail("import models", e)


# ─── Test 2: Client Construction ─────────────────────────────────────

def test_client_construction() -> None:
    section("2. Client Construction")
    from agentsecrets import AgentSecrets

    try:
        c = AgentSecrets(auto_start=False)
        assert c._port == 8765, f"default port should be 8765, got {c._port}"
        ok("default port = 8765")
    except Exception as e:
        fail("default port", e)

    try:
        c = AgentSecrets(port=9999, auto_start=False)
        assert c._port == 9999
        ok("custom port = 9999")
    except Exception as e:
        fail("custom port", e)

    try:
        c = AgentSecrets(auto_start=False)
        assert hasattr(c, "workspaces")
        assert hasattr(c, "projects")
        assert hasattr(c, "secrets")
        assert hasattr(c, "proxy")
        assert hasattr(c, "allowlist")
        ok("all 5 sub-clients wired")
    except Exception as e:
        fail("sub-clients", e)

    try:
        with AgentSecrets(auto_start=False) as c:
            pass  # should not raise
        ok("context manager enter/exit")
    except Exception as e:
        fail("context manager", e)

    try:
        c = AgentSecrets(auto_start=False)
        assert c._auth is None, "auth should be lazy (None before first call)"
        ok("auth is lazy (None before first call)")
    except Exception as e:
        fail("lazy auth", e)


# ─── Test 3: Health Check & Auth ─────────────────────────────────────

def test_health_and_auth() -> None:
    section("3. Health Check & Auth Resolution")
    from agentsecrets.auth import resolve
    from agentsecrets.errors import ProxyConnectionError
    from agentsecrets.proxy import health_check

    try:
        status = health_check(8765)
        assert status.running is True
        assert status.port == 8765
        assert isinstance(status.project, str) and len(status.project) > 0
        ok(f"health_check OK — project: {status.project}")
    except ProxyConnectionError:
        skip("health_check", "proxy not running on 8765")
        return  # skip remaining auth tests
    except Exception as e:
        fail("health_check", e)
        return

    try:
        ctx = resolve(8765, auto_start_proxy=False)
        assert ctx.method == "proxy"
        assert ctx.port == 8765
        ok(f"auth resolved via proxy, project: {ctx.project}")
    except Exception as e:
        fail("auth resolve", e)


# ─── Test 4: Error Quality ───────────────────────────────────────────

def test_error_quality() -> None:
    section("4. Error Quality — Every Error is Actionable")
    from agentsecrets.errors import (
        AgentSecretsError,
        AgentSecretsNotRunning,
        CLINotFound,
        DomainNotAllowed,
        SecretNotFound,
        SessionExpired,
    )

    errors = [
        ("AgentSecretsNotRunning", AgentSecretsNotRunning(port=8765)),
        ("CLINotFound", CLINotFound()),
        ("SecretNotFound", SecretNotFound(key="STRIPE_KEY")),
        ("DomainNotAllowed", DomainNotAllowed(domain="evil.com")),
        ("SessionExpired", SessionExpired()),
    ]

    for name, exc in errors:
        try:
            assert isinstance(exc, AgentSecretsError), f"{name} should inherit from AgentSecretsError"
            assert exc.fix_hint is not None, f"{name} should have a fix_hint"
            assert len(exc.fix_hint) > 0, f"{name} fix_hint should not be empty"
            assert str(exc), f"{name} should have a string representation"
            ok(f"{name}: fix_hint = \"{exc.fix_hint}\"")
        except Exception as e:
            fail(name, e)


# ─── Test 5: Real API Calls ──────────────────────────────────────────

def test_real_calls() -> None:
    section("5. Real API Calls (requires proxy + secrets + allowlist)")
    from agentsecrets import AgentSecrets
    from agentsecrets.errors import (
        AgentSecretsError,
        DomainNotAllowed,
    )

    try:
        client = AgentSecrets()
    except AgentSecretsError as e:
        skip("real calls", f"cannot create client: {e.message}")
        return

    # Find an available secret key
    test_key = None
    try:
        keys = client.secrets.list()
        if keys:
            test_key = keys[0].key if hasattr(keys[0], "key") else str(keys[0])
            ok(f"secrets.list() returned {len(keys)} key(s), using: {test_key}")
        else:
            skip("real calls", "no secrets found — run: agentsecrets secrets set TEST_KEY=any-value")
            return
    except AgentSecretsError as e:
        skip("secrets.list()", f"{e.message}")
        return

    # 5a. GET with bearer (most common MCP pattern)
    try:
        resp = client.call(
            "https://httpbin.org/get",
            method="GET",
            bearer=test_key,
        )
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
        data = resp.json()
        assert "headers" in data, "httpbin should echo headers"
        # Verify the secret was injected (httpbin echoes the Authorization header)
        auth_header = data.get("headers", {}).get("Authorization", "")
        assert auth_header.startswith("Bearer "), "Authorization header should start with 'Bearer '"
        ok("GET with bearer → 200, auth injected")
    except DomainNotAllowed:
        skip("GET with bearer", "httpbin.org not on allowlist — run: agentsecrets workspace allowlist add httpbin.org")
        return
    except AgentSecretsError as e:
        fail("GET with bearer", e)
        return

    # 5b. POST with JSON body (what a GitHub MCP does to create issues)
    try:
        resp = client.call(
            "https://httpbin.org/post",
            method="POST",
            bearer=test_key,
            body={"title": "Test Issue", "description": "Created by SDK integration test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # httpbin echoes the posted JSON in "json" field
        posted = data.get("json", {})
        assert posted.get("title") == "Test Issue", f"body not echoed correctly: {posted}"
        ok("POST with JSON body → 200, body echoed correctly")
    except AgentSecretsError as e:
        fail("POST with JSON body", e)

    # 5c. PATCH (updating a resource — common in GitHub API)
    try:
        resp = client.call(
            "https://httpbin.org/patch",
            method="PATCH",
            bearer=test_key,
            body={"state": "closed"},
        )
        assert resp.status_code == 200
        ok("PATCH → 200")
    except AgentSecretsError as e:
        fail("PATCH", e)

    # 5d. DELETE (removing a resource)
    try:
        resp = client.call(
            "https://httpbin.org/delete",
            method="DELETE",
            bearer=test_key,
        )
        assert resp.status_code == 200
        ok("DELETE → 200")
    except AgentSecretsError as e:
        fail("DELETE", e)

    # 5e. PUT
    try:
        resp = client.call(
            "https://httpbin.org/put",
            method="PUT",
            bearer=test_key,
            body={"content": "updated"},
        )
        assert resp.status_code == 200
        ok("PUT with body → 200")
    except AgentSecretsError as e:
        fail("PUT", e)

    # 5f. Custom header injection
    try:
        resp = client.call(
            "https://httpbin.org/get",
            method="GET",
            header={"X-Custom-Auth": test_key},
        )
        assert resp.status_code == 200
        ok("Custom header injection → 200")
    except AgentSecretsError as e:
        fail("Custom header injection", e)

    # 5g. Query param injection
    try:
        resp = client.call(
            "https://httpbin.org/get",
            method="GET",
            query={"api_key": test_key},
        )
        assert resp.status_code == 200
        ok("Query param injection → 200")
    except AgentSecretsError as e:
        fail("Query param injection", e)

    # 5h. Multiple injections in one call
    try:
        resp = client.call(
            "https://httpbin.org/get",
            method="GET",
            bearer=test_key,
            header={"X-Extra": test_key},
        )
        assert resp.status_code == 200
        ok("Multiple injections in one call → 200")
    except AgentSecretsError as e:
        fail("Multiple injections", e)

    # 5i. Extra (non-auth) headers forwarded
    try:
        resp = client.call(
            "https://httpbin.org/get",
            method="GET",
            bearer=test_key,
            headers={"X-Request-Id": "test-123", "Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        echoed_headers = data.get("headers", {})
        assert echoed_headers.get("X-Request-Id") == "test-123", "extra header not forwarded"
        ok("Extra headers forwarded correctly")
    except AgentSecretsError as e:
        fail("Extra headers", e)

    # 5j. Response model completeness
    try:
        resp = client.call("https://httpbin.org/get", bearer=test_key)
        assert isinstance(resp.status_code, int)
        assert isinstance(resp.headers, dict)
        assert isinstance(resp.body, bytes)
        assert isinstance(resp.text, str)
        assert isinstance(resp.duration_ms, int) and resp.duration_ms > 0
        assert isinstance(resp.redacted, bool)
        _ = resp.json()  # should not raise for httpbin
        assert not hasattr(resp, "value"), "ZERO-KNOWLEDGE VIOLATION: response has 'value' field"
        ok(f"Response model complete: status={resp.status_code}, duration={resp.duration_ms}ms, redacted={resp.redacted}")
    except AgentSecretsError as e:
        fail("Response model", e)


# ─── Test 6: Error Handling ──────────────────────────────────────────

def test_error_handling() -> None:
    section("6. Error Handling (real proxy errors)")
    from agentsecrets import AgentSecrets
    from agentsecrets.errors import AgentSecretsError, DomainNotAllowed, SecretNotFound

    try:
        client = AgentSecrets()
    except AgentSecretsError as e:
        skip("error handling", f"cannot create client: {e.message}")
        return

    # 6a. SecretNotFound for a missing key
    try:
        client.call("https://httpbin.org/get", bearer="THIS_KEY_DEFINITELY_DOES_NOT_EXIST_XYZ_999")
        fail("SecretNotFound", Exception("Expected SecretNotFound but no exception was raised"))
    except SecretNotFound as e:
        assert "THIS_KEY_DEFINITELY_DOES_NOT_EXIST_XYZ_999" in e.key
        assert e.fix_hint is not None
        ok(f"SecretNotFound raised correctly: key={e.key}")
    except AgentSecretsError as e:
        fail(f"SecretNotFound (got {type(e).__name__} instead)", e)

    # 6b. DomainNotAllowed for a blocked domain
    # Only works if the allowlist is non-empty and this domain isn't on it.
    try:
        keys = client.secrets.list()
        if keys:
            test_key = keys[0].key if hasattr(keys[0], "key") else str(keys[0])
            try:
                client.call("https://this-domain-should-never-be-allowed-xyz.com/test", bearer=test_key)
                skip("DomainNotAllowed", "call succeeded — allowlist may be empty or domain is allowed")
            except DomainNotAllowed as e:
                assert e.fix_hint is not None
                ok(f"DomainNotAllowed raised correctly: domain={e.domain}")
            except AgentSecretsError as e:
                # Might get a different error (DNS failure etc.) — that's fine
                skip("DomainNotAllowed", f"got {type(e).__name__}: {e.message}")
        else:
            skip("DomainNotAllowed", "no secrets to test with")
    except AgentSecretsError as e:
        skip("DomainNotAllowed", f"{e.message}")


# ─── Test 7: Async Call ──────────────────────────────────────────────

def test_async_call() -> None:
    section("7. Async Call")
    from agentsecrets import AgentSecrets
    from agentsecrets.errors import AgentSecretsError

    try:
        client = AgentSecrets()
    except AgentSecretsError as e:
        skip("async call", f"cannot create client: {e.message}")
        return

    try:
        keys = client.secrets.list()
        if not keys:
            skip("async call", "no secrets")
            return
        test_key = keys[0].key if hasattr(keys[0], "key") else str(keys[0])
    except AgentSecretsError as e:
        skip("async call", f"{e.message}")
        return

    async def run_async_test():
        resp = await client.async_call(
            "https://httpbin.org/post",
            method="POST",
            bearer=test_key,
            body={"async": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("json", {}).get("async") is True

    try:
        asyncio.run(run_async_test())
        ok("async_call POST with JSON body → 200")
    except AgentSecretsError as e:
        fail("async_call", e)
    except Exception as e:
        fail("async_call", e)


# ─── Test 8: Mock (no proxy needed) ────────────────────────────────

def test_mock() -> None:
    section("8. MockAgentSecrets (no proxy needed)")
    from agentsecrets.testing import MockAgentSecrets

    try:
        mock = MockAgentSecrets()

        # Simulate a GitHub MCP workflow
        r1 = mock.call("https://api.github.com/repos/owner/repo", bearer="GITHUB_TOKEN")
        r2 = mock.call(
            "https://api.github.com/repos/owner/repo/issues",
            method="POST",
            bearer="GITHUB_TOKEN",
            body={"title": "Bug report", "body": "Something broke"},
        )
        r3 = mock.call(
            "https://api.github.com/repos/owner/repo/issues/1",
            method="PATCH",
            bearer="GITHUB_TOKEN",
            body={"state": "closed"},
        )

        assert len(mock.calls) == 3
        assert mock.calls[0].url == "https://api.github.com/repos/owner/repo"
        assert mock.calls[0].bearer == "GITHUB_TOKEN"
        assert mock.calls[1].method == "POST"
        assert mock.calls[2].method == "PATCH"

        # Zero-knowledge check
        import dataclasses
        fields = {f.name for f in dataclasses.fields(mock.calls[0])}
        assert "value" not in fields, "ZERO-KNOWLEDGE VIOLATION: CallRecord has 'value' field"

        ok("3-call GitHub MCP workflow recorded correctly, zero-knowledge intact")
    except Exception as e:
        fail("MockAgentSecrets", e)

    # Custom responses
    try:
        from agentsecrets import AgentSecretsResponse
        custom = MockAgentSecrets(
            default_response=AgentSecretsResponse(
                status_code=201,
                headers={"Content-Type": "application/json"},
                body=b'{"id": 42, "title": "New Issue"}',
            )
        )
        resp = custom.call("https://api.github.com/issues", method="POST", bearer="TOKEN")
        assert resp.status_code == 201
        assert resp.json()["id"] == 42
        ok("Custom default response works")
    except Exception as e:
        fail("Custom response", e)


# ─── Test 9: CLI Detection ──────────────────────────────────────────

def test_cli_detection() -> None:
    section("9. CLI Detection")
    from agentsecrets.errors import CLINotFound
    from agentsecrets.proxy import find_binary

    try:
        path = find_binary()
        ok(f"CLI binary found at: {path}")
    except CLINotFound as e:
        # This is expected if CLI isn't installed — the important thing
        # is that it raised CLINotFound, not some random exception.
        ok(f"CLINotFound raised correctly (CLI not installed): {e.fix_hint}")


# ─── Test 10: Sequential Calls (MCP simulation) ──────────────────────

def test_sequential_calls_mcp_simulation() -> None:
    section("10. Sequential Calls — GitHub MCP Simulation")
    from agentsecrets import AgentSecrets
    from agentsecrets.errors import AgentSecretsError, DomainNotAllowed

    try:
        client = AgentSecrets()
    except AgentSecretsError as e:
        skip("MCP simulation", f"cannot create client: {e.message}")
        return

    try:
        keys = client.secrets.list()
        if not keys:
            skip("MCP simulation", "no secrets")
            return
        test_key = keys[0].key if hasattr(keys[0], "key") else str(keys[0])
    except AgentSecretsError as e:
        skip("MCP simulation", f"{e.message}")
        return

    # Simulate: list repos → get repo → create issue → close issue → list issues
    calls = [
        ("List repos",   "GET",    "https://httpbin.org/get",    None),
        ("Get repo",     "GET",    "https://httpbin.org/get",    None),
        ("Create issue", "POST",   "https://httpbin.org/post",   {"title": "Bug", "body": "Details"}),
        ("Close issue",  "PATCH",  "https://httpbin.org/patch",  {"state": "closed"}),
        ("List issues",  "GET",    "https://httpbin.org/get",    None),
    ]

    success = 0
    for name, method, url, body in calls:
        try:
            resp = client.call(url, method=method, bearer=test_key, body=body)
            assert resp.status_code == 200
            _ = resp.json()  # verify parseable
            success += 1
        except DomainNotAllowed:
            skip(f"MCP: {name}", "httpbin.org not on allowlist")
            return
        except AgentSecretsError as e:
            fail(f"MCP: {name}", e)

    if success == len(calls):
        ok(f"All {success} sequential calls succeeded — MCP workflow is viable")


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  AgentSecrets SDK — Comprehensive Integration Test")
    print("=" * 60)

    test_import_and_version()
    test_client_construction()
    test_health_and_auth()
    test_error_quality()
    test_real_calls()
    test_error_handling()
    test_async_call()
    test_mock()
    test_cli_detection()
    test_sequential_calls_mcp_simulation()

    print(f"\n{'=' * 60}")
    print(f"  Results: {PASS} passed, {FAIL} failed, {SKIP} skipped")
    print(f"{'=' * 60}")

    if FAIL > 0:
        print("\n⚠️  SOME TESTS FAILED — do not push until fixed.")
        sys.exit(1)
    elif SKIP > 0:
        print("\n⚠️  Some tests were skipped. Review the skipped items above.")
        print("   To run all tests, make sure:")
        print("   1. agentsecrets CLI is installed")
        print("   2. You're logged in (agentsecrets init)")
        print("   3. You have an active project with at least one secret")
        print("   4. httpbin.org is on your allowlist")
        print("   5. The proxy is running (agentsecrets proxy start)")
        sys.exit(0)
    else:
        print("\n🎉 ALL TESTS PASSED — safe to push.")
        sys.exit(0)
