# Error Handling & Troubleshooting

Every exception thrown by the AgentSecrets SDK contains structured properties, diagnostic information, and recovery instructions to help your code (or an autonomous AI agent) resolve issues dynamically.

---

## 1. Exception Hierarchy

All custom exceptions inherit from the base class:
`agentsecrets.errors.AgentSecretsError`

```
AgentSecretsError
 ├── CLIError
 ├── CLINotFound
 ├── ProxyConnectionError
 ├── AgentSecretsNotRunning
 ├── DomainNotAllowed
 ├── SecretNotFound
 ├── SessionExpired
 ├── UpstreamError
 └── PermissionDenied
```

---

## 2. Core Exceptions Reference

### `AgentSecretsNotRunning`
* **Cause**: The SDK could not connect to the local proxy, and auto-start was either disabled or failed.
* **Resolution**: Run `agentsecrets proxy start` in your shell, or verify the port setting matches your daemon.

### `DomainNotAllowed`
* **Properties**: `e.domain` (the blocked destination host).
* **Cause**: The request destination domain is not registered on your workspace allowlist.
* **Resolution**: Run `agentsecrets workspace allowlist add <domain>` (e.g. `agentsecrets workspace allowlist add api.stripe.com`).

### `SecretNotFound`
* **Properties**: `e.key` (the missing secret name).
* **Cause**: The secret key referenced in `call()`, `spawn()`, or by the interceptor does not exist in the active project keychain.
* **Resolution**: Provision the secret using the CLI: `agentsecrets secrets set <KEY_NAME>=<value>`.

### `SessionExpired`
* **Cause**: Your local developer session has expired or the token TTL has elapsed.
* **Resolution**: Run `agentsecrets login` on your system to authenticate.

### `UpstreamError`
* **Properties**: `e.status_code`, `e.body`, `e.url`.
* **Cause**: The injection succeeded and the local proxy forwarded the request, but the upstream API returned an HTTP error code (>= 400).
* **Resolution**: Inspect the response body or check the upstream API documentation.

### `PermissionDenied`
* **Cause**: Your user account does not have the required role (e.g. attempting to add domains to the allowlist without being a workspace administrator).
* **Resolution**: Contact your workspace administrator to upgrade your access level.

---

## 3. Dynamic Resolution Pattern

You can write robust python wrappers that catch exceptions and tell the user (or instruct an LLM) exactly how to resolve them:

```python
from agentsecrets import AgentSecrets
from agentsecrets.errors import DomainNotAllowed, SecretNotFound, AgentSecretsNotRunning

client = AgentSecrets()

try:
    response = client.call("https://api.stripe.com/v1/charges", bearer="STRIPE_KEY")
except AgentSecretsNotRunning:
    print("Action Required: Please launch the AgentSecrets daemon. Run: agentsecrets proxy start")
except DomainNotAllowed as e:
    print(f"Action Required: Domain '{e.domain}' is blocked. Run: agentsecrets workspace allowlist add {e.domain}")
except SecretNotFound as e:
    print(f"Action Required: Secret '{e.key}' is missing. Run: agentsecrets secrets set {e.key}=<your_api_key>")
```
This is especially powerful for AI agents that run terminal tools; they can parse the exception message, execute the required CLI recovery command themselves, and retry the operation autonomously.
