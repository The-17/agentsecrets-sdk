# Transparent HTTP Interception & The Credential Helper

This guide explains how to use transparent HTTP interception and how the `credential` helper dynamically generates zero-knowledge placeholders to integrate with third-party SDKs (such as Stripe, OpenAI, or LangChain).

---

## 1. How the `credential` Helper Works

The `credential` helper (`agentsecrets.credential`) is a dynamic placeholder generator. Its sole job is to construct standard AgentSecrets placeholder strings in your code **without ever containing or loading actual secret values**.

### Under the Hood
The `credential` object is an instance of `CredentialHelper`. It overrides `__getattr__`, `__getitem__`, and `get()` to dynamically return `AS_SECRET_` prefixed strings:

```python
from agentsecrets import credential

# 1. Attribute Access (recommended)
print(credential.STRIPE_SECRET_KEY)  # Output: "AS_SECRET_STRIPE_SECRET_KEY"

# 2. Dictionary/Item Access
print(credential["OPENAI_API_KEY"])   # Output: "AS_SECRET_OPENAI_API_KEY"

# 3. Method Access (mimicking standard dict behavior)
print(credential.get("GITHUB_TOKEN")) # Output: "AS_SECRET_GITHUB_TOKEN"
```

### Why is this necessary?
* **Zero Process Memory Exposure**: By using `credential.KEY_NAME`, your Python process memory only holds the string `"AS_SECRET_KEY_NAME"`. Even if a malicious dependency scans the process memory or your agent is subjected to a prompt injection attack, there is **no secret value** to extract.
* **No Hardcoded Magic Strings**: Instead of typing `"AS_SECRET_STRIPE_KEY"` manually, the helper provides clean autocomplete support and readable python syntax.

---

## 2. Transparent Interception Flow

When you call `init(intercept=True)`, the SDK dynamically patches the transport layers of both `requests` and `httpx` (sync + async).

### Request Lifecycle

1. **Setting the Placeholder**: You pass the placeholder to your HTTP client or third-party SDK (e.g. `stripe.api_key = credential.STRIPE_KEY`).
2. **Outbound Trigger**: The HTTP client prepares and sends the HTTP request.
3. **Interception**: Our wrapped transport method catches the outgoing request before it hits the socket/network.
4. **Header Scan**: The interceptor scans request headers for values starting with `AS_SECRET_` or `Bearer AS_SECRET_`.
5. **Rerouting**:
   * It deletes the original placeholder authorization header.
   * It changes the request destination URL to `http://localhost:8765/proxy`.
   * It injects tracking headers:
     * `X-AS-Target-URL`: The real destination (e.g., `https://api.stripe.com/v1/charges`).
     * `X-AS-Method`: The HTTP method (e.g., `POST`).
     * `X-AS-Inject-Bearer` or `X-AS-Inject-Header-<HeaderName>`: The name of the secret key to resolve.
6. **Dynamic Resolution**: The request is sent to the local `agentsecrets` proxy. The proxy reads the active environment configuration (from `.agentsecrets/project.json`), pulls the corresponding decrypted secret from the OS keychain, attaches it, and performs the real API call to the upstream server.
7. **Response Propagation**: The response from the upstream API is returned back to your code. Your HTTP client or SDK receives the response exactly as if it called the upstream API directly.

---

## 3. Integrating Third-Party SDKs

Because interception is hooked at the network client level, **any library** that utilizes standard `requests` or `httpx` clients under the hood will route securely through AgentSecrets.

### Stripe Python SDK
```python
import stripe
from agentsecrets import init, credential

# Enable interception and target the development environment
init(intercept=True, environment="development")

# Stripe stores "AS_SECRET_STRIPE_KEY" in memory
stripe.api_key = credential.STRIPE_KEY

# This built-in call is automatically intercepted and resolved!
charge = stripe.Charge.create(
    amount=2500,
    currency="usd",
    source="tok_visa"
)
print(f"Charged: {charge.id}")
```

### OpenAI SDK
The OpenAI SDK uses `httpx` (async and sync) under the hood:
```python
from openai import OpenAI
from agentsecrets import init, credential

init(intercept=True, environment="production")

# OpenAI stores the placeholder in memory
client = OpenAI(api_key=credential.OPENAI_API_KEY)

# The network call is intercepted transparently
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### LangChain Tools
```python
from langchain_community.tools.tavily_search import TavilySearchResults
from agentsecrets import init, credential

init(intercept=True)

# Tavily client uses requests under the hood and will be intercepted
tavily_tool = TavilySearchResults(api_wrapper_api_key=credential.TAVILY_API_KEY)
```
