# Introduction & Getting Started

AgentSecrets is a security infrastructure designed to keep credential values completely isolated from your AI agents, application code, and logs. This SDK enables Python programs, tools, and MCP servers to work with APIs securely without ever loading sensitive keys into the Python process memory.

---

## The Core Concept: Zero-Knowledge Infrastructure

Traditional secrets management follows a retrieval pattern:
```
Vault/Env  ──(Secret Value)──>  Application Memory  ──(Secret Value)──>  API Endpoint
```
This pattern exposes raw credentials to process memory, logs, third-party dependencies, and LLM context windows (subjecting them to prompt extraction attacks).

AgentSecrets uses an injection pattern:
```
SDK Call  ──(Key Name Placeholder)──>  Proxy Daemon  ──(Real Secret)──>  API Endpoint
```
The SDK never retrieves the secret value. Instead, it translates requests into placeholder-based headers and hands them to the local `agentsecrets` proxy daemon. The proxy resolves the values and forwards the request to the upstream API, returning only the response.

---

## Installation

Install the Python SDK package from PyPI:

```bash
pip install agentsecrets
```

*Requires Python 3.10+.*

---

## CLI Prerequisites

For the SDK to resolve credentials, you must have the **AgentSecrets CLI** installed and running on the host system.

### 1. Install the CLI
```bash
# Using Homebrew (macOS / Linux)
brew install The-17/tap/agentsecrets

# Using pip
pip install agentsecrets-cli

# Using npm
npm install -g @the-17/agentsecrets
```

### 2. Configure a Project & Start the Proxy
Run these commands locally to configure your workspace context:
```bash
# Initialize project config
agentsecrets init

# Create a project namespace
agentsecrets project create my-payment-service

# Provision secrets in the secure OS keychain
agentsecrets secrets set STRIPE_KEY=sk_test_...

# Allow the proxy to send traffic to Stripe
agentsecrets workspace allowlist add api.stripe.com

# Start the background proxy daemon
agentsecrets proxy start
```

---

## Quick Start

Using the SDK to call the Stripe API in a zero-knowledge way:

```python
from agentsecrets import AgentSecrets

# Instantiate the client (automatically resolves local proxy)
client = AgentSecrets()

# Make the call using the key name "STRIPE_KEY"
response = client.call(
    "https://api.stripe.com/v1/charges",
    method="POST",
    bearer="STRIPE_KEY",
    body={"amount": 2000, "currency": "usd", "source": "tok_visa"}
)

# Read the parsed response
print("Status Code:", response.status_code)
print("Response JSON:", response.json())
```
The raw Stripe API key never entered the Python code as a string, variable, or environment variable.
