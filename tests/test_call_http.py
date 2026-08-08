"""End-to-end tests for ``call()`` / ``async_call()`` over the binary delegation.

Under Option B1 ``call()`` does not speak HTTP to the proxy; it runs
``agentsecrets call`` as a subprocess (mirroring :mod:`agentsecrets.spawn`).
These tests mock the subprocess boundary — ``subprocess.run`` for the sync
path and ``asyncio.create_subprocess_exec`` for the async path — so the full
argv-build -> run -> parse/​error-map pipeline is exercised without a real
binary, proxy, or network:

* the invoked argv is ``[binary, "call", "--url", TARGET, ...]``
* dict bodies are JSON-encoded; bytes/str pass through as ``--body``
* stdout ``HTTP <code>\\n\\n<body>`` becomes a faithful ``AgentSecretsResponse``
* the ``[REDACTED_BY_AGENTSECRETS]`` marker sets ``response.redacted``
* non-zero exit maps proxy stderr text to the right SDK exception
* a subprocess timeout surfaces as ``CLIError``

The pure helpers (``_build_call_args``/``_parse_call_stdout``/``_map_call_error``)
are unit-tested in ``test_call.py``.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from agentsecrets.call import _binary_supports_json_call, async_call, call
from agentsecrets.errors import CLIError, DomainNotAllowed, SecretNotFound, UpstreamError
from agentsecrets.models import AgentSecretsResponse

BINARY = "/usr/local/bin/agentsecrets"
TARGET = "https://api.stripe.com/v1/balance"


@pytest.fixture(autouse=True)
def _force_text_mode():
    """Default every test to the text path by pinning the JSON-capability probe.

    ``call()``/``async_call()`` invoke :func:`_binary_supports_json_call`, an
    ``lru_cache``d probe that shells out to ``call --help``.  Left unpinned it
    would run against each test's mocked ``subprocess.run`` and memoise the
    first result process-wide, coupling tests to each other and to run order.
    Pinning it to ``False`` keeps the existing text-mode tests deterministic;
    the JSON-mode tests override this with their own ``True`` patch.
    """
    _binary_supports_json_call.cache_clear()
    with patch("agentsecrets.call._binary_supports_json_call", return_value=False):
        yield
    _binary_supports_json_call.cache_clear()



# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


def _run_result(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a fake ``subprocess.run`` CompletedProcess-like result."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _patch_sync(result: MagicMock):
    """Patch ``find_binary`` + ``subprocess.run`` for the sync ``call()`` path."""
    return patch("agentsecrets.call.find_binary", return_value=BINARY), patch(
        "agentsecrets.call.subprocess.run", return_value=result
    )


def _argv_of(mock_run: MagicMock) -> list[str]:
    """Extract the argv list ``[binary, *args]`` passed to ``subprocess.run``."""
    return mock_run.call_args.args[0]


class TestCallDelegation:
    """Synchronous ``call()`` subprocess behaviour."""

    def test_invokes_binary_with_call_argv(self) -> None:
        find_patch, run_patch = _patch_sync(_run_result(stdout='HTTP 200\n\n{"ok": true}'))
        with find_patch, run_patch as mock_run:
            resp = call(TARGET, bearer="STRIPE_KEY")

        argv = _argv_of(mock_run)
        assert argv[0] == BINARY
        assert argv[1] == "call"
        assert "--url" in argv and TARGET in argv
        assert "--bearer" in argv and "STRIPE_KEY" in argv
        assert isinstance(resp, AgentSecretsResponse)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_method_is_forwarded_uppercased(self) -> None:
        find_patch, run_patch = _patch_sync(_run_result(stdout="HTTP 200\n\n{}"))
        with find_patch, run_patch as mock_run:
            call(TARGET, method="post", bearer="K")

        argv = _argv_of(mock_run)
        assert argv[argv.index("--method") + 1] == "POST"

    def test_dict_body_is_json_encoded(self) -> None:
        find_patch, run_patch = _patch_sync(_run_result(stdout="HTTP 200\n\n{}"))
        with find_patch, run_patch as mock_run:
            call(TARGET, method="POST", body={"amount": 1000, "currency": "usd"})

        argv = _argv_of(mock_run)
        body_arg = argv[argv.index("--body") + 1]
        assert json.loads(body_arg) == {"amount": 1000, "currency": "usd"}

    def test_bytes_body_is_decoded(self) -> None:
        find_patch, run_patch = _patch_sync(_run_result(stdout="HTTP 200\n\n{}"))
        with find_patch, run_patch as mock_run:
            call(TARGET, method="POST", body=b"raw-payload")

        argv = _argv_of(mock_run)
        assert argv[argv.index("--body") + 1] == "raw-payload"

    def test_agent_token_becomes_token_flag(self) -> None:
        find_patch, run_patch = _patch_sync(_run_result(stdout="HTTP 200\n\n{}"))
        with find_patch, run_patch as mock_run:
            call(TARGET, bearer="K", agent_token="agt_xyz")

        argv = _argv_of(mock_run)
        assert argv[argv.index("--token") + 1] == "agt_xyz"

    def test_response_fields_are_populated(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(stdout='HTTP 201\n\n{"created": true}')
        )
        with find_patch, run_patch:
            resp = call(TARGET, bearer="K")

        assert resp.status_code == 201
        assert resp.headers == {}  # binary emits no response headers in text mode
        assert resp.body == b'{"created": true}'
        assert resp.text == '{"created": true}'
        assert resp.redacted is False
        assert resp.duration_ms >= 0

    def test_redacted_flag_set_when_marker_present(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(stdout="HTTP 200\n\nkey is [REDACTED_BY_AGENTSECRETS] here")
        )
        with find_patch, run_patch:
            resp = call(TARGET, bearer="K")

        assert resp.redacted is True

    def test_domain_block_raises_domain_not_allowed(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(
                returncode=1,
                stderr="domain 'api.stripe.com' is not in the workspace allowlist",
            )
        )
        with find_patch, run_patch:
            with pytest.raises(DomainNotAllowed) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.domain == "api.stripe.com"

    def test_secret_not_found_raises_secret_not_found(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(
                returncode=1,
                stderr="secret 'STRIPE_KEY' not found in keychain — run set",
            )
        )
        with find_patch, run_patch:
            with pytest.raises(SecretNotFound) as excinfo:
                call(TARGET, bearer="STRIPE_KEY")
        assert excinfo.value.key == "STRIPE_KEY"

    def test_upstream_error_raises_upstream(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(returncode=1, stderr="upstream connection refused")
        )
        with find_patch, run_patch:
            with pytest.raises(UpstreamError) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.status_code == 502

    def test_generic_failure_raises_cli_error(self) -> None:
        find_patch, run_patch = _patch_sync(
            _run_result(returncode=3, stderr="unexpected boom")
        )
        with find_patch, run_patch:
            with pytest.raises(CLIError) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.exit_code == 3

    def test_timeout_raises_cli_error(self) -> None:
        find_patch = patch("agentsecrets.call.find_binary", return_value=BINARY)
        run_patch = patch(
            "agentsecrets.call.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="call", timeout=1.0),
        )
        with find_patch, run_patch:
            with pytest.raises(CLIError):
                call(TARGET, bearer="K", timeout=1.0)


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


def _fake_proc(*, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> MagicMock:
    """Build a fake asyncio subprocess whose ``communicate()`` is awaitable."""
    proc = MagicMock()
    proc.returncode = returncode

    async def _communicate() -> tuple[bytes, bytes]:
        return stdout, stderr

    proc.communicate = _communicate
    return proc


def _patch_async(proc: MagicMock):
    """Patch ``find_binary`` + ``create_subprocess_exec`` for the async path."""
    async def _create(*_args, **_kwargs):
        return proc

    return patch("agentsecrets.call.find_binary", return_value=BINARY), patch(
        "agentsecrets.call.asyncio.create_subprocess_exec", side_effect=_create
    )


class TestAsyncCallDelegation:
    """``async_call()`` mirrors the sync path (asyncio_mode = auto)."""

    async def test_async_round_trip(self) -> None:
        find_patch, exec_patch = _patch_async(
            _fake_proc(stdout=b'HTTP 200\n\n{"ok": true}')
        )
        with find_patch, exec_patch as mock_exec:
            resp = await async_call(TARGET, bearer="OPENAI_KEY")

        # create_subprocess_exec(binary, *args, ...) -> args[0] is the binary.
        exec_args = mock_exec.call_args.args
        assert exec_args[0] == BINARY
        assert "call" in exec_args
        assert "--bearer" in exec_args and "OPENAI_KEY" in exec_args
        assert resp.json() == {"ok": True}

    async def test_async_secret_not_found(self) -> None:
        find_patch, exec_patch = _patch_async(
            _fake_proc(returncode=1, stderr=b"secret 'OPENAI_KEY' not found in keychain")
        )
        with find_patch, exec_patch:
            with pytest.raises(SecretNotFound) as excinfo:
                await async_call(TARGET, bearer="OPENAI_KEY")
        assert excinfo.value.key == "OPENAI_KEY"

    async def test_async_domain_block(self) -> None:
        find_patch, exec_patch = _patch_async(
            _fake_proc(
                returncode=1,
                stderr=b"domain 'api.openai.com' is not in the workspace allowlist",
            )
        )
        with find_patch, exec_patch:
            with pytest.raises(DomainNotAllowed) as excinfo:
                await async_call(TARGET, bearer="OPENAI_KEY")
        assert excinfo.value.domain == "api.openai.com"


_JSON_MODE = patch(
    "agentsecrets.call._binary_supports_json_call", return_value=True,
)


class TestCallJsonMode:
    """Synchronous ``call()`` JSON-mode behaviour."""

    def test_json_success_round_trip(self) -> None:
        envelope = json.dumps({
            "status": 200,
            "headers": {"Content-Type": ["application/json"]},
            "body": '{"ok": true}',
            "redacted": False,
            "duration_ms": 42,
        })
        find_p, run_p = _patch_sync(_run_result(stdout=envelope))
        with find_p, run_p, _JSON_MODE:
            resp = call(TARGET, bearer="K")

        assert resp.status_code == 200
        assert resp.headers == {"Content-Type": "application/json"}
        assert resp.body == b'{"ok": true}'
        assert resp.text == '{"ok": true}'
        assert resp.json() == {"ok": True}
        assert resp.redacted is False
        assert resp.duration_ms == 42

    def test_json_output_flag_in_argv(self) -> None:
        envelope = json.dumps({
            "status": 200, "headers": {},
            "body": "", "redacted": False, "duration_ms": 10,
        })
        find_p, run_p = _patch_sync(_run_result(stdout=envelope))
        with find_p, run_p as mock_run, _JSON_MODE:
            call(TARGET, bearer="K")

        argv = _argv_of(mock_run)
        assert "--output" in argv
        assert argv[argv.index("--output") + 1] == "json"

    def test_json_redacted_flag(self) -> None:
        envelope = json.dumps({
            "status": 200, "headers": {},
            "body": "", "redacted": True, "duration_ms": 10,
        })
        find_p, run_p = _patch_sync(_run_result(stdout=envelope))
        with find_p, run_p, _JSON_MODE:
            resp = call(TARGET, bearer="K")

        assert resp.redacted is True

    def test_json_domain_block(self) -> None:
        envelope = json.dumps({
            "status": 0,
            "headers": {},
            "body": '{"error": "domain_not_in_allowlist",'
                    ' "domain": "api.stripe.com"}',
            "redacted": False,
            "duration_ms": 0,
            "error": "proxy blocked",
        })
        find_p, run_p = _patch_sync(
            _run_result(returncode=1, stdout=envelope),
        )
        with find_p, run_p, _JSON_MODE:
            with pytest.raises(DomainNotAllowed) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.domain == "api.stripe.com"

    def test_json_secret_not_found(self) -> None:
        envelope = json.dumps({
            "status": 0,
            "headers": {},
            "body": "",
            "redacted": False,
            "duration_ms": 0,
            "error": "secret 'STRIPE_KEY' not found in keychain",
        })
        find_p, run_p = _patch_sync(
            _run_result(returncode=1, stdout=envelope),
        )
        with find_p, run_p, _JSON_MODE:
            with pytest.raises(SecretNotFound) as excinfo:
                call(TARGET, bearer="STRIPE_KEY")
        assert excinfo.value.key == "STRIPE_KEY"

    def test_json_upstream_error(self) -> None:
        envelope = json.dumps({
            "status": 502,
            "headers": {},
            "body": "Bad Gateway",
            "redacted": False,
            "duration_ms": 0,
            "error": "upstream",
        })
        find_p, run_p = _patch_sync(
            _run_result(returncode=1, stdout=envelope),
        )
        with find_p, run_p, _JSON_MODE:
            with pytest.raises(UpstreamError) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.status_code == 502

    def test_json_unparseable_stdout_falls_back_to_stderr(self) -> None:
        find_p, run_p = _patch_sync(_run_result(
            returncode=1,
            stdout="not json",
            stderr="upstream connection refused",
        ))
        with find_p, run_p, _JSON_MODE:
            with pytest.raises(UpstreamError) as excinfo:
                call(TARGET, bearer="K")
        assert excinfo.value.status_code == 502


class TestAsyncCallJsonMode:
    """``async_call()`` JSON-mode behaviour."""

    async def test_async_json_round_trip(self) -> None:
        envelope = json.dumps({
            "status": 200,
            "headers": {"Content-Type": ["application/json"]},
            "body": '{"ok": true}',
            "redacted": False,
            "duration_ms": 42,
        })
        proc = _fake_proc(stdout=envelope.encode("utf-8"))
        find_p, exec_p = _patch_async(proc)
        with find_p, exec_p as mock_exec, _JSON_MODE:
            resp = await async_call(TARGET, bearer="K")

        exec_args = mock_exec.call_args.args
        assert "--output" in exec_args
        assert exec_args[exec_args.index("--output") + 1] == "json"

        assert resp.status_code == 200
        assert resp.headers == {"Content-Type": "application/json"}
        assert resp.body == b'{"ok": true}'
        assert resp.json() == {"ok": True}
        assert resp.redacted is False
        assert resp.duration_ms == 42

    async def test_async_json_domain_block(self) -> None:
        envelope = json.dumps({
            "status": 0,
            "headers": {},
            "body": '{"error": "domain_not_in_allowlist",'
                    ' "domain": "api.stripe.com"}',
            "redacted": False,
            "duration_ms": 0,
            "error": "proxy blocked",
        })
        proc = _fake_proc(
            returncode=1, stdout=envelope.encode("utf-8"),
        )
        find_p, exec_p = _patch_async(proc)
        with find_p, exec_p, _JSON_MODE:
            with pytest.raises(DomainNotAllowed) as excinfo:
                await async_call(TARGET, bearer="K")
        assert excinfo.value.domain == "api.stripe.com"

