# Core API Reference

The core API consists of the main `AgentSecrets` client and its two primary operation layers: **calls** (performing API requests securely) and **spawns** (starting processes with injected secrets).

---

## 1. Main Client Constructor

Instantiate the main SDK client:

```python
from agentsecrets import AgentSecrets

client = AgentSecrets(
    port=8765,              # Custom proxy port (defaults to AGENTSECRETS_PORT env var, or 8765)
    workspace="my-ws",      # Target workspace name (defaults to AGENTSECRETS_WORKSPACE)
    project="my-proj",      # Target project name (defaults to AGENTSECRETS_PROJECT)
    auto_start=True,        # If True, automatically launches the proxy daemon if it's stopped
    intercept=False,        # If True, registers transparent HTTP/HTTPS interception globally
    environment="staging"   # Targets the specified universal project environment
)
```

---

## 2. API Call Layer: `call()` & `async_call()`

Perform secure HTTP/HTTPS requests where authentication values are injected on-transit at the proxy.

### Signature
```python
def call(
    self,
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    bearer: str | None = None,
    basic: str | None = None,
    header: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body_field: dict[str, str] | None = None,
    form_field: dict[str, str] | None = None,
    agent_id: str | None = None,
    timeout: float = 30.0
) -> AgentSecretsResponse
```

### Parameters
* **`url`**: The destination endpoint URL.
* **`method`**: The HTTP method (GET, POST, PUT, PATCH, DELETE, etc.).
* **`body`**: Request payload. Automatically JSON-serialized if passed as dict/list and sets `Content-Type: application/json`.
* **`headers`**: Optional standard, non-sensitive headers to forward.
* **`bearer`**: Key name of the bearer credential to inject as `Authorization: Bearer <value>`.
* **`basic`**: Key name of the basic auth credential to inject as `Authorization: Basic <base64(value)>`.
* **`header`**: A mapping of custom headers to their secret key names. e.g. `header={"X-Api-Key": "API_KEY"}`.
* **`query`**: A mapping of query parameters to their secret key names. e.g. `query={"api_token": "TAVILY_KEY"}`.
* **`body_field`**: A mapping of JSON path fields to their secret key names. e.g. `body_field={"auth.secret": "CLIENT_SECRET"}`.
* **`form_field`**: A mapping of form-data fields to their secret key names.
* **`agent_id`**: Optional session identifier attached to audit logs.
* **`timeout`**: Timeout in seconds.

### The Response Object (`AgentSecretsResponse`)
Returned from successful calls:
* `status_code` (`int`): HTTP status code from the upstream server.
* `headers` (`dict`): The HTTP response headers.
* `body` (`bytes`): Raw binary response body.
* `json()` (`dict`): Helper to parse JSON body response.
* `redacted` (`bool`): Set to `True` if any echoed credentials were redacted in the response stream.
* `duration_ms` (`int`): Complete request lifecycle duration in milliseconds.

---

## 3. Process Spawning Layer: `spawn()` & `spawn_async()`

Spawns a child process on the host machine, resolving all project secrets and injecting them into the child process's environment variables at launch. Once the child process terminates, the secrets vanish.

### Signature
```python
def spawn(
    self,
    command: list[str],
    *,
    capture: bool = True,
    timeout: float | None = None,
    project: str | None = None
) -> SpawnResult
```

### Usage
```python
# Synchronous Spawn (Waits for process completion)
result = client.spawn(["python", "sync_script.py"], capture=True)
print("Exit Code:", result.exit_code)
print("Output:", result.stdout)

# Asynchronous Spawn (Returns immediately)
proc = client.spawn_async(["python", "daemon.py"])
```
* **`capture`**: If True, stdout and stderr are recorded and returned in the `SpawnResult`.
* **`project`**: Scopes the environment variables to a specific project context without changing the main client's state.
