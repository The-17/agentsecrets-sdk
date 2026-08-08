"""Unit tests for the ``agentsecrets call`` delegation helpers.

Under Option B1 the SDK no longer speaks HTTP to the proxy — it shells out
to ``agentsecrets call`` (the one process authorized to hold the proxy
session token) exactly the way :mod:`agentsecrets.spawn` shells out to
``agentsecrets env``.  These tests cover the pure, subprocess-free helpers:

* ``_build_call_args``       — SDK params -> ``agentsecrets call`` argv
* ``_parse_call_stdout``     — ``HTTP <code>\\n\\n<body>`` text -> response
* ``_map_call_error``        — proxy stderr text -> SDK exception
* ``_binary_supports_json_call`` — one-shot ``--output`` capability probe

The end-to-end ``call()`` / ``async_call()`` behaviour (subprocess mocked)
lives in ``test_call_http.py``.
"""

from __future__ import annotations

import json
import warnings
from unittest.mock import MagicMock, patch

import pytest

from agentsecrets.call import (
    _binary_supports_json_call,
    _build_call_args,
    _dispatch_json_result,
    _envelope_body_str,
    _flatten_headers,
    _map_call_error,
    _map_call_json_error,
    _parse_call_json_envelope,
    _parse_call_stdout,
)
from agentsecrets.errors import CLIError, DomainNotAllowed, SecretNotFound, UpstreamError

URL = "https://api.stripe.com/v1/charges"


def _values_for(args: list[str], flag: str) -> list[str]:
    """Every value that immediately follows an occurrence of ``flag`` in argv."""
    return [args[i + 1] for i, a in enumerate(args) if a == flag and i + 1 < len(args)]


class TestBuildCallArgs:
    """Verify SDK params translate into the ``agentsecrets call`` argument list."""

    def test_url_and_method_are_always_present(self) -> None:
        args = _build_call_args(URL)
        assert args[0] == "call"
        assert _values_for(args, "--url") == [URL]
        assert _values_for(args, "--method") == ["GET"]

    def test_method_is_uppercased(self) -> None:
        args = _build_call_args(URL, method="post")
        assert _values_for(args, "--method") == ["POST"]

    def test_bearer_injection(self) -> None:
        args = _build_call_args(URL, bearer="STRIPE_KEY")
        assert _values_for(args, "--bearer") == ["STRIPE_KEY"]

    def test_basic_injection(self) -> None:
        args = _build_call_args(URL, basic="MY_CRED")
        assert _values_for(args, "--basic") == ["MY_CRED"]

    def test_header_injection_is_repeatable(self) -> None:
        args = _build_call_args(
            URL, header={"X-Api-Key": "API_KEY", "X-Org-Id": "ORG_KEY"}
        )
        vals = _values_for(args, "--header")
        assert "X-Api-Key=API_KEY" in vals
        assert "X-Org-Id=ORG_KEY" in vals

    def test_query_injection(self) -> None:
        args = _build_call_args(URL, query={"key": "GOOGLE_KEY"})
        assert _values_for(args, "--query") == ["key=GOOGLE_KEY"]

    def test_body_field_injection(self) -> None:
        args = _build_call_args(URL, body_field={"auth.key": "SECRET"})
        assert _values_for(args, "--body-field") == ["auth.key=SECRET"]

    def test_form_field_injection(self) -> None:
        args = _build_call_args(URL, form_field={"api_key": "KEY"})
        assert _values_for(args, "--form-field") == ["api_key=KEY"]

    def test_agent_token_becomes_token_flag(self) -> None:
        args = _build_call_args(URL, agent_token="agt_abc123")
        assert _values_for(args, "--token") == ["agt_abc123"]

    def test_dict_body_is_json_encoded(self) -> None:
        args = _build_call_args(
            URL, method="POST", body={"amount": 1000, "currency": "usd"}
        )
        (body_arg,) = _values_for(args, "--body")
        assert json.loads(body_arg) == {"amount": 1000, "currency": "usd"}

    def test_str_body_passes_through_verbatim(self) -> None:
        args = _build_call_args(URL, method="POST", body="raw-string-body")
        assert _values_for(args, "--body") == ["raw-string-body"]

    def test_bytes_body_is_decoded(self) -> None:
        args = _build_call_args(URL, method="POST", body=b"raw-bytes-body")
        assert _values_for(args, "--body") == ["raw-bytes-body"]

    def test_multiple_injection_styles_combine(self) -> None:
        args = _build_call_args(
            URL,
            bearer="TOKEN",
            header={"X-Custom": "CUSTOM_KEY"},
            query={"key": "QUERY_KEY"},
        )
        assert _values_for(args, "--bearer") == ["TOKEN"]
        assert _values_for(args, "--header") == ["X-Custom=CUSTOM_KEY"]
        assert _values_for(args, "--query") == ["key=QUERY_KEY"]

    def test_no_injections_yields_only_url_and_method(self) -> None:
        args = _build_call_args(URL)
        # No credential-injection flags present.
        for flag in ("--bearer", "--basic", "--header", "--query",
                     "--body-field", "--form-field", "--token", "--body"):
            assert _values_for(args, flag) == []

    def test_agent_id_has_no_flag_today(self) -> None:
        """The binary's ``call`` identifies the agent by ``--token`` only."""
        args = _build_call_args(URL, agent_id="claude-session-123")
        assert "claude-session-123" not in args
        assert "--agent-id" not in args

    def test_forward_headers_warn_and_are_dropped(self) -> None:
        """Arbitrary forward headers have no binary flag yet -> warn, drop."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            args = _build_call_args(URL, headers={"X-Trace-Id": "abc123"})
        assert any("not yet supported" in str(w.message) for w in caught)
        assert "X-Trace-Id" not in args
        assert "abc123" not in args


class TestParseCallStdout:
    """Verify ``HTTP <code>\\n\\n<body>`` text parsing."""

    def test_status_and_body_are_extracted(self) -> None:
        resp = _parse_call_stdout('HTTP 200\n\n{"ok": true}', duration_ms=12)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert resp.duration_ms == 12

    def test_headers_are_empty_in_text_mode(self) -> None:
        resp = _parse_call_stdout("HTTP 201\n\ncreated", duration_ms=0)
        assert resp.headers == {}

    def test_redacted_marker_sets_flag(self) -> None:
        resp = _parse_call_stdout(
            "HTTP 200\n\nkey is [REDACTED_BY_AGENTSECRETS] here", duration_ms=0
        )
        assert resp.redacted is True

    def test_no_redaction_marker_leaves_flag_false(self) -> None:
        resp = _parse_call_stdout("HTTP 200\n\nclean body", duration_ms=0)
        assert resp.redacted is False

    def test_non_2xx_status_is_preserved(self) -> None:
        resp = _parse_call_stdout("HTTP 404\n\nnot found", duration_ms=0)
        assert resp.status_code == 404
        assert resp.text == "not found"

    def test_missing_http_line_falls_back_to_zero_status(self) -> None:
        resp = _parse_call_stdout("some unexpected output", duration_ms=0)
        assert resp.status_code == 0
        assert resp.text == "some unexpected output"


class TestMapCallError:
    """Verify proxy stderr text maps to the right SDK exception.

    Under delegation the binary prints the proxy's error message to stderr
    and exits non-zero.  The mapping is keyed off that text (not an HTTP
    status), mirroring the shapes the Go proxy emits.
    """

    def test_domain_not_in_allowlist_raises_domain_not_allowed(self) -> None:
        stderr = "Error: domain 'httpbin.org' is not in the workspace allowlist"
        exc = _map_call_error(stderr, 1, "https://httpbin.org/get")
        assert isinstance(exc, DomainNotAllowed)
        assert exc.domain == "httpbin.org"

    def test_domain_not_in_allowlist_token_form(self) -> None:
        stderr = "domain_not_in_allowlist: 'api.stripe.com'"
        exc = _map_call_error(stderr, 1, "https://api.stripe.com")
        assert isinstance(exc, DomainNotAllowed)
        assert exc.domain == "api.stripe.com"

    def test_secret_not_found_extracts_key(self) -> None:
        stderr = (
            "secret 'FAKE_KEY_XYZ' not found in keychain — "
            "use list_secrets to see available keys"
        )
        exc = _map_call_error(stderr, 1, "https://httpbin.org/get")
        assert isinstance(exc, SecretNotFound)
        assert exc.key == "FAKE_KEY_XYZ"

    def test_secret_not_found_in_keychain_phrasing(self) -> None:
        stderr = "secret 'STRIPE_KEY' not found in keychain"
        exc = _map_call_error(stderr, 1, "https://api.stripe.com")
        assert isinstance(exc, SecretNotFound)
        assert exc.key == "STRIPE_KEY"

    def test_upstream_error_maps_to_upstream(self) -> None:
        stderr = "upstream connection refused"
        exc = _map_call_error(stderr, 1, "https://api.stripe.com")
        assert isinstance(exc, UpstreamError)
        assert exc.status_code == 502

    def test_generic_error_falls_back_to_cli_error(self) -> None:
        stderr = "something entirely unexpected happened"
        exc = _map_call_error(stderr, 7, "https://api.stripe.com")
        assert isinstance(exc, CLIError)
        assert exc.exit_code == 7


class TestBinarySupportsJsonCall:
    """The one-shot ``--output`` capability probe (enables the future JSON path)."""

    def setup_method(self) -> None:
        _binary_supports_json_call.cache_clear()

    def teardown_method(self) -> None:
        _binary_supports_json_call.cache_clear()

    def test_true_when_help_advertises_output_flag(self) -> None:
        help_text = "Usage: agentsecrets call [flags]\n  --output string  json|text\n"
        with patch("agentsecrets.call.find_binary", return_value="/bin/agentsecrets"), \
             patch("agentsecrets.call.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=help_text)
            assert _binary_supports_json_call() is True

    def test_false_when_help_lacks_output_flag(self) -> None:
        help_text = "Usage: agentsecrets call [flags]\n  --url string\n  --bearer string\n"
        with patch("agentsecrets.call.find_binary", return_value="/bin/agentsecrets"), \
             patch("agentsecrets.call.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=help_text)
            assert _binary_supports_json_call() is False

    def test_false_when_probe_raises(self) -> None:
        with patch("agentsecrets.call.find_binary", side_effect=OSError("boom")):
            assert _binary_supports_json_call() is False


class TestFlattenHeaders:
    """Verify ``_flatten_headers`` behavior."""

    def test_joins_list_values(self) -> None:
        result = _flatten_headers(
            {"Content-Type": ["application/json", "text/plain"]},
        )
        assert result == {"Content-Type": "application/json, text/plain"}

    def test_passes_through_string_values(self) -> None:
        result = _flatten_headers({"Content-Type": "application/json"})
        assert result == {"Content-Type": "application/json"}

    def test_returns_empty_dict_for_non_dict_input(self) -> None:
        assert _flatten_headers(None) == {}
        assert _flatten_headers([]) == {}


class TestEnvelopeBodyStr:
    """Verify ``_envelope_body_str`` behavior."""

    def test_returns_string_body_as_is(self) -> None:
        assert _envelope_body_str({"body": "some string"}) == "some string"

    def test_returns_empty_string_for_none_body(self) -> None:
        assert _envelope_body_str({"body": None}) == ""
        assert _envelope_body_str({}) == ""

    def test_returns_stringified_body_for_other_types(self) -> None:
        assert _envelope_body_str({"body": {"key": "value"}}) == "{'key': 'value'}"
        assert _envelope_body_str({"body": 42}) == "42"


class TestParseCallJsonEnvelope:
    """Verify ``_parse_call_json_envelope`` behavior."""

    def test_parses_successful_envelope(self) -> None:
        envelope = {
            "status": 200,
            "headers": {"Content-Type": ["application/json"]},
            "body": '{"ok": true}',
            "redacted": False,
            "duration_ms": 42
        }
        resp = _parse_call_json_envelope(envelope, 100)
        assert resp.status_code == 200
        assert resp.headers == {"Content-Type": "application/json"}
        assert resp.json() == {"ok": True}
        assert resp.redacted is False
        assert resp.duration_ms == 42

    def test_non_numeric_status_defaults_to_zero(self) -> None:
        envelope = {"status": "not-a-number", "body": "text"}
        resp = _parse_call_json_envelope(envelope, 100)
        assert resp.status_code == 0

    def test_missing_duration_ms_uses_fallback(self) -> None:
        envelope = {"status": 200, "body": "text"}
        resp = _parse_call_json_envelope(envelope, 100)
        assert resp.duration_ms == 100

    def test_redacted_flag_from_envelope(self) -> None:
        envelope = {"status": 200, "body": "text", "redacted": True}
        resp = _parse_call_json_envelope(envelope, 100)
        assert resp.redacted is True


class TestMapCallJsonError:
    """Verify ``_map_call_json_error`` behavior."""

    def test_domain_not_allowed(self) -> None:
        envelope = {
            "error": "proxy blocked",
            "body": json.dumps({"error": "domain_not_in_allowlist", "domain": "api.stripe.com"}),
        }
        exc = _map_call_json_error(envelope, "https://api.stripe.com")
        assert isinstance(exc, DomainNotAllowed)
        assert exc.domain == "api.stripe.com"

    def test_empty_allowlist(self) -> None:
        envelope = {
            "error": "proxy blocked",
            "body": json.dumps({"error": "empty_allowlist"}),
        }
        exc = _map_call_json_error(envelope, "https://api.stripe.com")
        assert isinstance(exc, DomainNotAllowed)
        # No domain field in body → falls back to the URL.
        assert exc.domain == "https://api.stripe.com"

    def test_secret_not_found(self) -> None:
        envelope = {"error": "secret 'KEY' not found in keychain"}
        exc = _map_call_json_error(envelope, "https://api.stripe.com")
        assert isinstance(exc, SecretNotFound)
        assert exc.key == "KEY"

    def test_upstream_error(self) -> None:
        envelope = {"status": 404, "body": "Not found"}
        exc = _map_call_json_error(envelope, "https://api.stripe.com")
        assert isinstance(exc, UpstreamError)
        assert exc.status_code == 404

    def test_cli_error(self) -> None:
        envelope = {"status": 0, "error": "unknown"}
        exc = _map_call_json_error(envelope, "https://api.stripe.com")
        assert isinstance(exc, CLIError)


class TestDispatchJsonResult:
    """Verify ``_dispatch_json_result`` behavior."""

    def test_success_returns_response(self) -> None:
        stdout = '{"status": 200, "body": "ok", "duration_ms": 10}'
        resp = _dispatch_json_result(stdout, "", 0, "https://example.com", 10)
        assert resp.status_code == 200
        assert resp.text == "ok"
        assert resp.duration_ms == 10

    def test_error_envelope_raises_exception(self) -> None:
        body = json.dumps({"error": "domain_not_in_allowlist", "domain": "example.com"})
        stdout = json.dumps({"error": "proxy blocked", "body": body})
        with pytest.raises(DomainNotAllowed) as exc_info:
            _dispatch_json_result(stdout, "", 0, "https://example.com", 10)
        assert exc_info.value.domain == "example.com"

    def test_non_json_stdout_with_non_zero_returncode(self) -> None:
        stdout = "not json"
        stderr = "domain_not_in_allowlist: 'example.com'"
        with pytest.raises(DomainNotAllowed) as exc_info:
            _dispatch_json_result(stdout, stderr, 1, "https://example.com", 10)
        assert exc_info.value.domain == "example.com"

    def test_non_json_stdout_with_zero_returncode(self) -> None:
        stdout = "not json"
        with pytest.raises(CLIError, match="not json"):
            _dispatch_json_result(stdout, "", 0, "https://example.com", 10)

    def test_empty_stdout_with_zero_returncode(self) -> None:
        with pytest.raises(CLIError, match="empty JSON output"):
            _dispatch_json_result("", "", 0, "https://example.com", 10)
