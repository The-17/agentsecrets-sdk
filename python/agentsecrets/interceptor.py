from __future__ import annotations
from typing import Any
from .config import settings

def parse_placeholder(value: str | bytes) -> tuple[str, str] | None:
    """Parse a header value to check if it's an AgentSecrets placeholder.

    Returns:
        tuple[str, str]: (style, secret_key) where style is 'bearer' or 'header'
        None: if the value is not a placeholder
    """
    if isinstance(value, bytes):
        try:
            val_str = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif isinstance(value, str):
        val_str = value
    else:
        return None

    val_strip = val_str.strip()
    if val_strip.upper().startswith("BEARER AS_SECRET_"):
        return "bearer", val_strip[17:]
    if val_strip.startswith("AS_SECRET_"):
        return "header", val_strip[10:]
    return None

def install_interceptor() -> None:
    """Hooks requests and httpx to intercept placeholders and route via local proxy."""

    # --- 1. Patch requests ---
    try:
        import requests
        original_send = requests.Session.send

        def secure_send(
            session: requests.Session,
            request: requests.PreparedRequest,
            **kwargs: Any,
        ) -> requests.Response:
            injections = []
            for name, value in list(request.headers.items()):
                parse_result = parse_placeholder(value)
                if parse_result is not None:
                    style, secret_key = parse_result
                    injections.append({
                        "style": style,
                        "target": name if style == "header" else "",
                        "secret_key": secret_key
                    })
                    del request.headers[name]

            if injections:
                original_url = request.url or ""
                # Dynamically read port from settings
                proxy_url = f"http://localhost:{settings.port}/proxy"

                request.url = proxy_url
                request.headers["X-AS-Target-URL"] = original_url
                request.headers["X-AS-Method"] = request.method or "GET"

                for inj in injections:
                    if inj["style"] == "bearer":
                        request.headers["X-AS-Inject-Bearer"] = inj["secret_key"]
                    elif inj["style"] == "header":
                        request.headers[f"X-AS-Inject-Header-{inj['target']}"] = inj["secret_key"]

            return original_send(session, request, **kwargs)

        requests.Session.send = secure_send  # type: ignore[method-assign,assignment]
    except ImportError:
        pass

    # --- 2. Patch httpx ---
    try:
        import httpx

        # Sync client send patching
        original_httpx_send = httpx.Client.send

        def secure_httpx_send(
            client: httpx.Client,
            httpx_request: httpx.Request,
            **kwargs: Any,
        ) -> httpx.Response:
            injections = []
            for name, value in list(httpx_request.headers.items()):
                parse_result = parse_placeholder(value)
                if parse_result is not None:
                    style, secret_key = parse_result
                    injections.append({
                        "style": style,
                        "target": name if style == "header" else "",
                        "secret_key": secret_key
                    })
                    del httpx_request.headers[name]

            if injections:
                original_url = str(httpx_request.url)
                proxy_url = f"http://localhost:{settings.port}/proxy"

                httpx_request.url = httpx.URL(proxy_url)
                httpx_request.headers["X-AS-Target-URL"] = original_url
                httpx_request.headers["X-AS-Method"] = httpx_request.method

                for inj in injections:
                    if inj["style"] == "bearer":
                        httpx_request.headers["X-AS-Inject-Bearer"] = inj["secret_key"]
                    elif inj["style"] == "header":
                        header_name = f"X-AS-Inject-Header-{inj['target']}"
                        httpx_request.headers[header_name] = inj["secret_key"]

            return original_httpx_send(client, httpx_request, **kwargs)

        httpx.Client.send = secure_httpx_send  # type: ignore[method-assign,assignment]

        # Async client send patching
        original_httpx_async_send = httpx.AsyncClient.send

        async def secure_httpx_async_send(
            client: httpx.AsyncClient,
            httpx_request: httpx.Request,
            **kwargs: Any,
        ) -> httpx.Response:
            injections = []
            for name, value in list(httpx_request.headers.items()):
                parse_result = parse_placeholder(value)
                if parse_result is not None:
                    style, secret_key = parse_result
                    injections.append({
                        "style": style,
                        "target": name if style == "header" else "",
                        "secret_key": secret_key
                    })
                    del httpx_request.headers[name]

            if injections:
                original_url = str(httpx_request.url)
                proxy_url = f"http://localhost:{settings.port}/proxy"

                httpx_request.url = httpx.URL(proxy_url)
                httpx_request.headers["X-AS-Target-URL"] = original_url
                httpx_request.headers["X-AS-Method"] = httpx_request.method

                for inj in injections:
                    if inj["style"] == "bearer":
                        httpx_request.headers["X-AS-Inject-Bearer"] = inj["secret_key"]
                    elif inj["style"] == "header":
                        header_name = f"X-AS-Inject-Header-{inj['target']}"
                        httpx_request.headers[header_name] = inj["secret_key"]

            return await original_httpx_async_send(client, httpx_request, **kwargs)

        httpx.AsyncClient.send = secure_httpx_async_send  # type: ignore[method-assign,assignment]
    except ImportError:
        pass
