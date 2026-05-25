# AgentSecrets Python SDK

The official Python client for [AgentSecrets](https://github.com/The-17/agentsecrets) — zero-knowledge secrets infrastructure for AI agents.

* **Documentation Guides**:
  * [Introduction & Core Concepts](../docs/introduction.md)
  * [Core API Reference (`call` & `spawn`)](../docs/core_api.md)
  * [Transparent HTTP Interception (Stripe, OpenAI, LangChain)](../docs/http_interception.md)
  * [Universal Environment Switching Guide](../docs/universal_environment_switching.md)
  * [Management API Reference](../docs/management_api.md)
  * [Error Handling & Troubleshooting](../docs/error_handling.md)
  * [Testing with `MockAgentSecrets`](../docs/testing.md)
  * [Practical Developer Tutorials](../docs/tutorials.md)

```python
from agentsecrets import AgentSecrets

client = AgentSecrets()

response = client.call(
    "https://api.stripe.com/v1/balance",
    bearer="STRIPE_KEY"
)
```

You pass a key name. The SDK resolves the value from the OS keychain, injects it at the transport layer, and returns only the API response. The value never enters your Python process. Not as a variable. Not as a return value. Not in any log.

---

## Why Build on This

Every other approach to credential management puts the value somewhere your code can reach it:

```python
# Every other approach
key = os.getenv("STRIPE_KEY")        # value is in your process memory
key = vault.get("STRIPE_KEY")        # value is in your process memory
key = keyring.get_password(...)      # value is in your process memory
                                      # prompt injection can reach it
                                      # malicious plugin can reach it
                                      # anyone using your tool inherits the risk
```

The AgentSecrets SDK has no `get()`. The only way to use a credential is to make the call or spawn the process. The value resolves inside the proxy and never crosses into your code.

When you build a tool, an MCP server, or an agent integration on this SDK, that guarantee extends to your users automatically. They get zero-knowledge credential management without knowing AgentSecrets exists.

---

## Prerequisites

Everyone who uses a tool built on this SDK needs:

1. **An AgentSecrets account** — [sign up here](https://github.com/The-17/agentsecrets)
2. **The AgentSecrets CLI** installed and running

Install the CLI:

```bash
# Homebrew (recommended)
brew install The-17/tap/agentsecrets

# pip
pip install agentsecrets-cli

# npm
npm install -g @the-17/agentsecrets
```

Set up a project:

```bash
agentsecrets init
agentsecrets project create my-project
agentsecrets secrets set STRIPE_KEY=sk_live_...
agentsecrets workspace allowlist add api.stripe.com
agentsecrets proxy start
```

> **Why is the CLI required?**
> The CLI manages everything your code should never touch — keychain access, session
> tokens, workspace context, and proxy lifecycle. The SDK delegates all credential
> operations to the running proxy so that values never enter your Python process.

---

## Install

```bash
pip install agentsecrets
```

Requires Python 3.10+.

---

## Quick Start

```python
from agentsecrets import AgentSecrets

client = AgentSecrets()

response = client.call(
    "https://api.stripe.com/v1/charges",
    method="POST",
    bearer="STRIPE_KEY",
    body={"amount": 1000, "currency": "usd", "source": "tok_visa"},
)
print(response.json())
```

---

## Transparent HTTP Interception

If you are using standard HTTP clients like `requests` or `httpx` and want to keep your code unchanged, you can enable transparent interception. With interception active, any outbound HTTP request using standard clients that contains an `AS_SECRET_` placeholder value in its headers will be automatically intercepted, stripped of the placeholder, and routed through the local AgentSecrets proxy.

This is extremely useful when integrating with existing AI agent libraries (like LangChain, LlamaIndex, or the OpenAI SDK) where you cannot easily modify the underlying HTTP request calls.

### Usage

```python
from agentsecrets import init, credential
import httpx

# 1. Initialize the transparent interceptor
# Optionally pass context settings: port, workspace, project, or environment.
init(intercept=True, environment="development")

# 2. Use the credential helper to define a placeholder
stripe_token = credential.STRIPE_API_KEY  # yields "AS_SECRET_STRIPE_API_KEY"

# 3. Call the API using standard httpx (sync & async) or requests
# The call is intercepted, routed through the proxy, resolved, and sent.
response = httpx.get(
    "https://api.stripe.com/v1/charges",
    headers={"Authorization": f"Bearer {stripe_token}"}
)
print(response.json())
```

Alternatively, you can enable interception and configure the environment directly in the `AgentSecrets` constructor:

```python
from agentsecrets import AgentSecrets, credential
import requests

# Enable interception in the client constructor
client = AgentSecrets(intercept=True, environment="development")

# Make standard requests call
response = requests.get(
    "https://api.stripe.com/v1/balance",
    headers={"Authorization": f"Bearer {credential.STRIPE_API_KEY}"}
)
```

### Integrating with Third-Party SDKs (e.g., Stripe, OpenAI)

Because the interceptor hooks at the `requests` and `httpx` transport level, you can use official third-party libraries seamlessly while keeping your credential keys 100% zero-knowledge:

```python
import stripe
from agentsecrets import init, credential

# 1. Enable interception globally
init(intercept=True, environment="production")

# 2. Set the placeholder on the Stripe SDK
stripe.api_key = credential.STRIPE_SECRET_KEY  # Yields "AS_SECRET_STRIPE_SECRET_KEY"

# 3. Call standard Stripe methods — they route securely through the proxy automatically!
charge = stripe.Charge.create(
    amount=2000,
    currency="usd",
    source="tok_visa",
)
```

---

## Universal Environment Switching

The active environment context is universal across your project (stored on disk in `.agentsecrets/project.json`). The running proxy resolves credentials based on this file dynamically. 

You can switch the project's active environment context programmatically through the global `settings` object or `init()` function. Setting the environment shells out to the CLI in the background to update the active environment configuration:

```python
from agentsecrets import settings

# Programmatically switch the project's active environment
settings.environment = "staging"  # Runs 'agentsecrets environment switch staging' under the hood
```

---

## Authenticated API Calls

Six injection styles — one for every auth pattern.

```python
# Bearer token — Stripe, OpenAI, GitHub, most modern APIs
response = client.call(
    "https://api.stripe.com/v1/balance",
    bearer="STRIPE_KEY"
)

# Custom header — SendGrid, Twilio, API Gateway
response = client.call(
    "https://api.sendgrid.com/v3/mail/send",
    method="POST",
    body=email_payload,
    header={"X-Api-Key": "SENDGRID_KEY"}
)

# Query parameter — Google Maps, weather APIs
response = client.call(
    "https://maps.googleapis.com/maps/api/geocode/json",
    query={"key": "GMAP_KEY", "address": "Lagos, Nigeria"}
)

# Basic auth — Jira, legacy REST APIs
# Store as "username:password" or "user@email.com:api_token"
response = client.call(
    "https://yourcompany.atlassian.net/rest/api/2/issue",
    basic="JIRA_CREDS"
)

# JSON body injection
response = client.call(
    "https://api.example.com/oauth/token",
    method="POST",
    body={"grant_type": "client_credentials"},
    body_field={"client_secret": "CLIENT_SECRET"}
)

# Form field injection
response = client.call(
    "https://oauth.example.com/token",
    method="POST",
    form_field={"api_key": "API_KEY"}
)
```

Combine multiple injection styles in one call:

```python
response = client.call(
    "https://api.example.com/data",
    bearer="AUTH_TOKEN",
    header={"X-Org-ID": "ORG_SECRET"},
    query={"version": "API_VERSION"}
)
```

### Auth Styles Reference

| Style | Parameter | Injects as |
|---|---|---|
| Bearer | `bearer="KEY"` | `Authorization: Bearer <value>` |
| Basic | `basic="KEY"` | `Authorization: Basic base64(<value>)` |
| Custom header | `header={"X-Api-Key": "KEY"}` | `X-Api-Key: <value>` |
| Query param | `query={"key": "KEY"}` | `?key=<value>` |
| JSON body | `body_field={"path": "KEY"}` | `{"path": "<value>"}` |
| Form field | `form_field={"field": "KEY"}` | `field=<value>` |

### The Response Object

```python
response = client.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")

response.status_code    # int — HTTP status from upstream API
response.body           # str — raw response body
response.json()         # dict — parsed JSON (raises if not valid JSON)
response.headers        # dict — response headers from upstream API
response.redacted       # bool — True if an echoed credential was redacted
response.duration_ms    # int — round-trip duration in milliseconds
```

Note: `response` has no field containing the injected credential value. This is structural.

---

## Async

```python
response = await client.async_call(
    "https://api.openai.com/v1/models",
    bearer="OPENAI_KEY"
)
```

Every `call()` parameter is supported in `async_call()`.

---

## Process Spawning

Spawn any process with secrets from the active project injected as environment variables at launch. The calling code never sees the values. When the process exits, the secrets are gone.

```python
# Wrap the Stripe MCP server
result = client.spawn("stripe", ["mcp"])

# Wrap a Node.js server
result = client.spawn("node", ["server.js"])

# Use secrets from a specific project without a global switch
result = client.spawn("python", ["manage.py", "migrate"], project="payments-service")

# Run in background — returns immediately
proc = client.spawn_async("stripe", ["mcp"])

# Capture output for scripting or testing
result = client.spawn("python", ["manage.py", "test"], capture=True)
if result.exit_code != 0:
    print(result.stderr)
```

`spawn()` result fields: `exit_code`, `stdout` (if `capture=True`), `stderr` (if `capture=True`).

---

## Management

Full programmatic access to everything the CLI does.

### Status

```python
status = client.status()
# status.user_email, status.workspace_name, status.project_name
# status.last_pull, status.proxy_running, status.storage_mode
```

### Secrets

```python
keys = client.secrets.list()         # key names only — never values
client.secrets.set("KEY", value)     # provision a secret programmatically
client.secrets.delete("KEY")

diff = client.secrets.diff()
# diff.has_drift, diff.local_only, diff.remote_only, diff.out_of_sync

if diff.has_drift:
    client.secrets.sync()            # pull cloud state to keychain

client.secrets.push()                # upload local secrets to cloud (encrypted)
```

### Workspaces

```python
client.workspaces.list()
client.workspaces.create("Acme Engineering")
client.set_workspace("Acme Engineering")      # global switch
client.workspaces.invite("alice@acme.com", role="member")
client.workspaces.members()
```

**Scoped workspace context** — global state unchanged after exit:

```python
# Useful for multi-tenant tools operating across multiple workspaces
with client.workspace("Client A") as ws:
    response = ws.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")

with client.workspace("Client B") as ws:
    response = ws.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")
```

### Projects

```python
client.projects.list()
client.projects.create("payments-service")
client.set_project("payments-service")        # global switch

# Scoped project context
with client.project("payments-service") as proj:
    result = proj.spawn("python", ["manage.py", "migrate"])
```

### Domain Allowlist

```python
client.allowlist.list()
client.allowlist.add("api.stripe.com")
client.allowlist.add(["api.stripe.com", "api.openai.com"])   # multiple at once
client.allowlist.remove("api.stripe.com")
client.allowlist.log(last=20)
```

Note: `allowlist.add()` and `allowlist.remove()` require admin role and prompt for password verification. They cannot be called in non-interactive environments.

### Proxy and Audit Log

```python
client.proxy.start()
client.proxy.stop()
client.proxy.status()    # running, port, session_valid, uptime_seconds

logs = client.proxy.logs(last=10)
for event in logs:
    print(event.timestamp, event.method, event.target_url, event.status_code)

# Filter by status or secret key
blocked = client.proxy.logs(last=50, status="BLOCKED")
stripe_calls = client.proxy.logs(secret="STRIPE_KEY")
```

Every `AuditEvent` contains timestamps, key names, endpoints, and status codes. The struct has no value field — it is structurally impossible for a credential value to appear in any log entry.

---

## Configuration

```python
from agentsecrets import AgentSecrets

client = AgentSecrets()                                       # default
client = AgentSecrets(port=9000)                              # custom proxy port
client = AgentSecrets(workspace="Acme", project="payments")   # explicit context
client = AgentSecrets(auto_start=False)                       # no proxy auto-start
```

Environment variables read automatically — no constructor argument needed:

```bash
AGENTSECRETS_PORT=9000                   # override proxy port
AGENTSECRETS_WORKSPACE=Acme             # override active workspace
AGENTSECRETS_PROJECT=payments            # override active project
```

---

## CI/CD and Production (Coming Soon)

On machines where you cannot run the CLI interactively — CI/CD pipelines, production servers, Docker containers — you will soon be able to use a service token instead of the local proxy.

This path is currently on the roadmap and will allow the SDK to authenticate directly to the AgentSecrets cloud resolver.

---

## Error Handling

Every error tells you what happened and what to do.

```python
from agentsecrets import (
    AgentSecrets,
    AgentSecretsNotRunning,
    DomainNotAllowed,
    SecretNotFound,
    UpstreamError,
)

try:
    response = client.call(
        "https://api.stripe.com/v1/balance",
        bearer="STRIPE_KEY"
    )
except AgentSecretsNotRunning:
    # Proxy not running
    # Error message includes full install and setup instructions
    raise
except DomainNotAllowed as e:
    print(f"Run: agentsecrets workspace allowlist add {e.domain}")
except SecretNotFound as e:
    print(f"Run: agentsecrets secrets set {e.key}=<value>")
except UpstreamError as e:
    # Injection succeeded — the upstream API itself returned an error
    print(f"API returned {e.status_code}: {e.body}")
```

| Exception | Cause | Recovery |
|---|---|---|
| `AgentSecretsNotRunning` | Proxy not running | `agentsecrets proxy start` |
| `DomainNotAllowed` | Domain not on workspace allowlist | `agentsecrets workspace allowlist add <domain>` |
| `SecretNotFound` | Key not in active project | `agentsecrets secrets set <KEY>=<value>` |
| `ProxyConnectionError` | Proxy running but unreachable | `agentsecrets proxy status` |
| `SessionExpired` | Session TTL expired | `agentsecrets login` |
| `UpstreamError` | Upstream API error (injection succeeded) | Check upstream API docs |
| `PermissionDenied` | Insufficient workspace role | Contact workspace admin |
| `WorkspaceNotFound` | Workspace does not exist | Check workspace name |
| `ProjectNotFound` | Project does not exist | Check project name |

All exceptions extend `AgentSecretsError`.

---

## Testing

Test without a running proxy and without real credentials.

```python
from agentsecrets.testing import MockAgentSecrets

mock = MockAgentSecrets(secrets={"STRIPE_KEY": "sk_test_mock"})

response = mock.call(
    "https://api.stripe.com/v1/balance",
    bearer="STRIPE_KEY"
)

# Assert the right call was made
assert mock.calls[0].url == "https://api.stripe.com/v1/balance"
assert mock.calls[0].bearer == "STRIPE_KEY"

# mock.calls[0].value does not exist
# The zero-knowledge guarantee is structural, not conditional — even in test mode
```

---

## Development

```bash
git clone https://github.com/The-17/agentsecrets-sdk
cd agentsecrets-sdk/python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

---

## Links

- **AgentSecrets CLI**: [github.com/The-17/agentsecrets](https://github.com/The-17/agentsecrets)
- **SDK repo**: [github.com/The-17/agentsecrets-sdk](https://github.com/The-17/agentsecrets-sdk)
- **ClawHub**: [clawhub.ai/SteppaCodes/agentsecrets](https://clawhub.ai/SteppaCodes/agentsecrets)
- **Security**: engineering@theseventeen.co

---

MIT License — [The Seventeen](https://github.com/The-17)