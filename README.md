# AgentSecrets SDK

> Build tools and agents on zero-knowledge secrets infrastructure.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Go 1.21+](https://img.shields.io/badge/Go-1.21+-00ADD8?logo=go)](https://go.dev/)
[![Node 18+](https://img.shields.io/badge/node-18+-339933?logo=node.js&logoColor=white)](https://nodejs.org/)

---

## What This Is

The AgentSecrets SDK is the programmatic interface to AgentSecrets infrastructure. It lets you build tools, MCP servers, and AI agents where credential values never enter your code — or the code of anyone using what you build.

```python
from agentsecrets import AgentSecrets

client = AgentSecrets()

response = client.call(
    "https://api.stripe.com/v1/balance",
    bearer="STRIPE_KEY"
)
```

You pass a key name. The SDK resolves the value from the OS keychain, injects it at the transport layer, and returns only the API response. The value is not in your code. Not as a variable. Not as a return value. Not in any log. Not in the context of any agent using your tool.

---

## The Infrastructure Argument

Every secrets SDK today works the same way: retrieve the value, hand it to your code.

```
vault.get("STRIPE_KEY")  →  sk_live_51H...  →  now it's in memory
                                              →  prompt injection can reach it
                                              →  malicious plugin can reach it
                                              →  every user of your tool inherits the risk
```

The AgentSecrets SDK has no `get()`. No `retrieve()`. The only operations are: make the call, or spawn the process. In both cases, the value resolves inside the proxy and never crosses into application code.

```
client.call(bearer="STRIPE_KEY")  →  proxy resolves from OS keychain
                                   →  injects into outbound HTTP request
                                   →  returns API response only
                                   →  value never entered your code
```

This is the shift: instead of your code retrieving credentials and using them, your code references credentials by name and the infrastructure handles everything else. The zero-knowledge guarantee is not a policy, it is structural — the value has nowhere to go except into the request.

**The multiplier:** When you build a tool on the AgentSecrets SDK and publish it, every user of that tool gets zero-knowledge credential management automatically. They do not need to understand the architecture. They do not need to configure anything beyond setting up AgentSecrets once. The infrastructure guarantee extends from your code to theirs without them knowing it is there.

That is what it means to build on infrastructure rather than implement a pattern.

---

## What You Can Build

**MCP servers with no credential storage**
An MCP server built on the SDK has no credential values in any config file, environment variable, or agent context. Users install it, set their secrets in AgentSecrets once, and every tool in the server works. The credentials never leave the OS keychain.

**Agent framework integrations**
LangChain tools, CrewAI tools, AutoGen function tools — any agent framework integration built on the SDK gives the agent full API access with zero credential exposure. The agent calls the tool. The tool calls the SDK. The SDK calls the proxy. The agent never held anything.

**Multi-tenant developer tools**
The scoped workspace context lets a single tool operate across multiple workspaces — multiple clients, multiple credential sets — without global state changes and without the tool ever holding credential values. Each workspace is isolated. Each call is audited.

**CI/CD and deployment pipelines (Coming soon)**
Service tokens will let automated environments authenticate to AgentSecrets without an interactive session or OS keychain. One token, set as an environment variable, replaces every credential that would otherwise live in pipeline configuration files.

**Autonomous agent workflows**
The management layer gives agents full programmatic control of the credentials lifecycle — checking drift, syncing from cloud, switching workspaces, reading audit logs — all without ever accessing a credential value. The agent operates the infrastructure. It never sees what the infrastructure holds.

---

## How It Works

The SDK sits in front of the AgentSecrets proxy. The proxy sits in front of every API call.

```
Your code              AgentSecrets             Target API
──────────             ────────────             ──────────
client.call()    →     proxy receives request
                       resolves key from
                       OS keychain              →  injects credential
                                                   into HTTP request
                       returns API response     ←  API responds
      ←  response
         (no credential value)
```

Authentication is resolved from the environment — no credentials are passed into the SDK:

1. **Local proxy running** — SDK connects to `localhost:8765`, inherits the session from `agentsecrets login`. This is the path for local development, MCP servers, and persistent servers.

2. **Cloud Resolver (Coming soon)** — SDK authenticates directly to the AgentSecrets cloud using a service token (`AGENTSECRETS_TOKEN`). This will be the path for CI/CD pipelines, Docker containers, and automated environments.

3. **No active session** — SDK raises `AgentSecretsNotRunning` with actionable instructions.

The SDK never accepts a username, password, or API key as a parameter. Authentication happens outside the SDK, in the environment. This is intentional — if the SDK accepted credentials as parameters, developers would eventually hardcode them, which is the exact problem this infrastructure exists to solve.

---

## SDK Layers

The SDK ships in two layers. Each serves a distinct use case.

**Layer 1 — The Call Layer**
Make authenticated API calls and spawn credential-injected processes. This is what 90% of tools need. One client, two methods: `call()` and `spawn()`. Import the SDK, make the call, the zero-knowledge guarantee is in place.

**Layer 2 — The Management Layer**
Full programmatic control of the AgentSecrets lifecycle. Workspace and project management, secrets operations, drift detection, audit log access. This is what AI agents need to operate the credentials infrastructure autonomously.

## Documentation Guides

Explore the detailed architecture and usage guides in the [docs/](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs) folder:

* **[Introduction & Concepts](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/introduction.md)**: Architectural overview, prerequisites, and quick start.
* **[Core API Reference](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/core_api.md)**: Detailed API reference for secure calls (`call()`) and process spawning (`spawn()`).
* **[Transparent HTTP Interception](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/http_interception.md)**: Patching standard clients (requests/httpx) and third-party SDKs (Stripe, OpenAI, LangChain) with zero-knowledge credential placeholders.
* **[Universal Environment Switching](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/universal_environment_switching.md)**: Programmatic project environment switching.
* **[Management API Reference](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/management_api.md)**: Programmatic control over workspaces, projects, secrets, allowlists, and audit logs.
* **[Error Handling & Diagnostics](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/error_handling.md)**: Custom exceptions, trigger causes, and recovery procedures.
* **[Testing Guide](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/testing.md)**: Mock testing with `MockAgentSecrets`.
* **[Practical Tutorials](file:///wsl.localhost/Ubuntu/home/theapiartist/work/agentsecrets-sdk/docs/tutorials.md)**: Building MCP servers, secure LangChain agents, and multi-tenant scripts.

---

## Language Support

| Language | Package | Docs | Status |
|---|---|---|---|
| Python | `pip install agentsecrets` | [python/README.md](python/README.md) | 🔨 In development |
| Go | `go get github.com/The-17/agentsecrets-sdk/go` | [go/README.md](go/README.md) | 📋 Planned |
| JavaScript | `npm install @the-17/agentsecrets-sdk` | [javascript/README.md](javascript/README.md) | 📋 Planned |

Each language has its own README with full installation, usage, and API reference for that ecosystem. The infrastructure guarantees are identical across all three.

---

## Repository Structure

```
agentsecrets-sdk/
├── README.md                  This file
├── python/                    Python SDK
│   ├── README.md
│   └── agentsecrets/
├── go/                        Go SDK (planned)
│   └── README.md
└── javascript/                JavaScript SDK (planned)
    └── README.md
```

---

## Built on AgentSecrets

These projects are built on the SDK. Each one is proof of the infrastructure claim.

| Project | What it does | Status |
|---|---|---|
| [Zeroknowledge MCP](https://github.com/The-17/zero-knowledge-mcp) | Template for building MCP servers with zero credential storage | Completed |
| agentsecrets-langchain | Zero-knowledge API calls in any LangChain agent | Coming soon |

Building something on the SDK? Open a PR to add it here.

---

## Quick Start

**Prerequisites:** [AgentSecrets CLI](https://github.com/The-17/agentsecrets) installed and running.

```bash
# Install the CLI
brew install The-17/tap/agentsecrets   # macOS / Linux
npm install -g @the-17/agentsecrets    # all platforms
pip install agentsecrets-cli

# Set up
agentsecrets init
agentsecrets secrets set STRIPE_KEY=sk_live_...
agentsecrets workspace allowlist add api.stripe.com
agentsecrets proxy start
```

Then install the SDK for your language and make your first call. See the language-specific README for the full guide.

---

## Contributing

Found a bug? [Open an issue](https://github.com/The-17/agentsecrets-sdk/issues)
Have an idea? [Start a discussion](https://github.com/The-17/agentsecrets-sdk/discussions)

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup.

---

## Links

- **AgentSecrets CLI**: [github.com/The-17/agentsecrets](https://github.com/The-17/agentsecrets)
- **ClawHub**: [clawhub.ai/SteppaCodes/agentsecrets](https://clawhub.ai/SteppaCodes/agentsecrets)
- **Security**: hello@theseventeen.co — response within 24 hours

---

MIT License — Built by [The Seventeen](https://theseventeen.co)

---

**The agent operates it. The agent never sees it.**
