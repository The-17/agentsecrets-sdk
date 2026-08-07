# Tutorials & Practical Guides

This guide walks you through building real-world applications, tools, and integrations using the AgentSecrets SDK.

---

## Tutorial 1: Building a Secure MCP Server (Model Context Protocol)

Model Context Protocol (MCP) servers allow AI assistants (like Anthropic Claude) to interact with external tools and data sources. Usually, you have to configure these servers with API keys in configuration files (like `claude_desktop_config.json`). With AgentSecrets, the server runs completely without credentials.

### Step 1: Set up the Secrets in the CLI
Register the GitHub token with the CLI once on your machine:
```bash
agentsecrets project create github-mcp
agentsecrets secrets set GITHUB_TOKEN=ghp_...
agentsecrets workspace allowlist add api.github.com
agentsecrets proxy start
```

### Step 2: Implement the MCP Server
Create a python script `server.py` using the Python MCP SDK:

```python
import os
import sys
from mcp.server.fastmcp import FastMCP
from agentsecrets import AgentSecrets

# 1. Initialize the AgentSecrets client targeting our project
client = AgentSecrets(project="github-mcp")
mcp = FastMCP("Secure GitHub Server")

@mcp.tool()
def get_repository_details(owner: str, repo: str) -> str:
    """Fetches metadata about a GitHub repository."""
    # 2. Make the API call with zero-knowledge token injection
    response = client.call(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"Accept": "application/vnd.github.v3+json"},
        bearer="GITHUB_TOKEN"
    )
    
    if response.status_code != 200:
        return f"Error: GitHub API returned status {response.status_code}"
        
    data = response.json()
    return f"Repo: {data['full_name']} | Stars: {data['stargazers_count']} | Forks: {data['forks_count']}"

if __name__ == "__main__":
    mcp.run()
```

### Step 3: Run the Server
Configure the server in Claude Desktop config without passing any credentials:
```json
{
  "mcpServers": {
    "github-secure": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```
Claude can now query repositories, but the GitHub token is never stored in config files, never printed in MCP logs, and never exposed to the LLM.

---

## Tutorial 2: Securing LangChain Agent Tools

AI agents are susceptible to prompt injection. If an agent has access to raw API keys in its memory or process environment, a compromised prompt can extract them. The HTTP Interceptor solves this globally.

### Step 1: Set up Tavily Search Key
```bash
agentsecrets secrets set TAVILY_API_KEY=tvly-...
agentsecrets workspace allowlist add api.tavily.com
agentsecrets proxy start
```

### Step 2: Write the Secure Agent
Enable transparent HTTP interception and run your agent:

```python
from agentsecrets import init, credential
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType

# 1. Enable interception
init(environment="development")

# 2. Instantiate tools using the credential placeholder
# TavilySearchResults uses requests internally; its call will be intercepted
tavily_tool = TavilySearchResults(api_wrapper_api_key=credential.TAVILY_API_KEY)

# 3. Initialize OpenAI using the credential placeholder
# ChatOpenAI uses httpx internally; its call will also be intercepted
llm = ChatOpenAI(
    model="gpt-4o", 
    api_key=credential.OPENAI_API_KEY  # Resolves dynamically on chat completion
)

agent = initialize_agent(
    tools=[tavily_tool],
    llm=llm,
    agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True
)

# 4. Run the Agent
response = agent.run("Search the web for the latest advancements in quantum computing.")
print(response)
```
No API key values exist in your Python process variables or LangChain's internal execution state.

---

## Tutorial 3: Multi-Tenant Workspace Scripting

If you run a SaaS script that syncs data across multiple corporate clients, managing separate credentials can lead to security risks or state bleeding. Scoped contexts allow you to switch workspaces on the fly.

```python
from agentsecrets import AgentSecrets
import time

# Initialize main client
client = AgentSecrets()

clients = ["Client_Alpha", "Client_Beta", "Client_Gamma"]

for client_name in clients:
    print(f"\n--- Processing workspace: {client_name} ---")
    
    # 1. Scope all calls inside this block to the specific workspace
    with client.use_workspace(client_name):
        try:
            # 2. Call the endpoint — resolving "STRIPE_KEY" from this client's workspace
            response = client.call(
                "https://api.stripe.com/v1/balance",
                bearer="STRIPE_KEY"
            )
            
            # The value returned is strictly from the client's Stripe account
            balance = response.json()
            available = balance["available"][0]["amount"]
            print(f"Stripe balance for {client_name}: ${available / 100:.2f}")
            
        except Exception as e:
            print(f"Failed to process client {client_name}: {e}")
            
# Once outside the loop, the workspace is automatically restored to the original global context
```
This guarantees that workspace credentials never bleed into other accounts, and operations are strictly isolated.

---

## Tutorial 4: Securing a Custom AI Agent Reasoning Loop

Many developers build custom AI agent systems (using standard APIs directly rather than heavy frameworks like LangChain). It is simple to plug in AgentSecrets to secure these environments.

Below is a complete, minimal implementation of a custom AI agent that uses standard `requests` to call the Anthropic Claude or OpenAI API. It executes tool actions based on LLM decisions without exposing any keys in memory.

### Step 1: Set up the Secrets
Ensure the LLM API key and target API domains are configured in your workspace:
```bash
agentsecrets secrets set ANTHROPIC_API_KEY=sk-ant-xxx
agentsecrets workspace allowlist add api.anthropic.com
agentsecrets workspace allowlist add api.weatherapi.com
agentsecrets proxy start
```

### Step 2: Build the Secure Agent Loop
Create `agent.py`:
```python
import requests
import json
from agentsecrets import init, credential

# 1. Initialize AgentSecrets interception
init(environment="development")

# 2. Define tools using secure placeholders
WEATHER_API_KEY_REF = credential.WEATHER_API_KEY # returns "AS_SECRET_WEATHER_API_KEY"
ANTHROPIC_KEY_REF = credential.ANTHROPIC_API_KEY # returns "AS_SECRET_ANTHROPIC_API_KEY"

def fetch_weather(location: str) -> str:
    # Requests is patched. The placeholder is intercepted and injected by the proxy.
    url = f"https://api.weatherapi.com/v1/current.json?q={location}"
    response = requests.get(
        url,
        headers={"key": WEATHER_API_KEY_REF} # Injected securely at the proxy
    )
    if response.status_code == 200:
        return response.json().get("current", {}).get("condition", {}).get("text", "Unknown")
    return "Failed to fetch weather."

def run_agent_turn(user_query: str) -> str:
    # Outbound call to Claude is intercepted; the real key is injected on-the-fly.
    headers = {
        "x-api-key": ANTHROPIC_KEY_REF,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    payload = {
        "model": "claude-3-5-sonnet-latest",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": f"User query: '{user_query}'. Should we fetch weather? Answer YES or NO."}]
    }
    
    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload
    )
    
    decision = res.json()["content"][0]["text"].strip()
    if "YES" in decision:
        return f"Agent Action: Weather is {fetch_weather('London')}."
    return "Agent Action: Did not fetch weather."

if __name__ == "__main__":
    # The application runs with zero raw API keys in memory!
    print(run_agent_turn("What is the weather in London right now?"))
```

