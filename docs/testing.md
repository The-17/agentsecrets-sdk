# Testing with MockAgentSecrets

When writing unit tests for your tools, agent workflows, or applications, you don't need a running proxy daemon or live system keychain access. The SDK includes a built-in mock utility: `MockAgentSecrets`.

---

## 1. Core Mocking Behavior

`MockAgentSecrets` inherits from the standard `AgentSecrets` class but bypasses all CLI and network calls. It records every interaction locally so you can assert on them.

Import the mock client from `agentsecrets.testing`:

```python
from agentsecrets.testing import MockAgentSecrets

# 1. Initialize with predefined secrets (keys and mock values)
mock_client = MockAgentSecrets(
    secrets={"STRIPE_KEY": "sk_test_mock_value", "OPENAI_KEY": "openai_mock_value"}
)
```

---

## 2. Testing API Calls

When `mock_client.call()` is called, it returns a stubbed HTTP response (defaulting to HTTP 200 with `{"ok": True}`) and appends a `CallRecord` to its `calls` list.

### Asserting on Calls
```python
# Make the call inside your tool/code
mock_client.call("https://api.stripe.com/v1/charges", bearer="STRIPE_KEY", method="POST")

# Assert that the call was recorded correctly
assert len(mock_client.calls) == 1
assert mock_client.calls[0].url == "https://api.stripe.com/v1/charges"
assert mock_client.calls[0].bearer == "STRIPE_KEY"
assert mock_client.calls[0].method == "POST"
```

### Zero-Knowledge in Tests
Even in mock test mode, **the call record never stores the secret values** in its properties. `mock_client.calls[0].bearer` contains the key name `"STRIPE_KEY"`, not `"sk_test_mock_value"`. The zero-knowledge design remains structurally intact during testing.

### Setting Custom Responses
You can configure the mock client to return custom status codes or bodies:

```python
from agentsecrets.models import AgentSecretsResponse

custom_response = AgentSecretsResponse(
    status_code=201,
    headers={"Content-Type": "application/json"},
    body=b'{"id": "ch_123", "status": "succeeded"}'
)

mock_client = MockAgentSecrets(default_response=custom_response)
response = mock_client.call("https://api.stripe.com/v1/charges")

assert response.status_code == 201
assert response.json()["id"] == "ch_123"
```

---

## 3. Testing Process Spawning

When `mock_client.spawn()` is called, it records a `SpawnRecord` containing the command list, and returns a default `SpawnResult` with exit code `0`.

### Asserting on Spawns
```python
mock_client.spawn(["python", "manage.py", "migrate"])

# Verify the command list was received
assert len(mock_client.spawns) == 1
assert mock_client.spawns[0].command == ["python", "manage.py", "migrate"]
```

### Custom Spawn Results
Verify how your code handles process execution failures:

```python
from agentsecrets.models import SpawnResult

failed_result = SpawnResult(exit_code=1, stderr="database connection failed")
mock_client = MockAgentSecrets(default_spawn_result=failed_result)

result = mock_client.spawn(["python", "manage.py", "migrate"])
assert result.exit_code == 1
assert result.stderr == "database connection failed"
```

---

## 4. Using as a Context Manager

You can clean up tests easily by using the mock client as a context manager:

```python
with MockAgentSecrets() as mock:
    # Execute code under test
    mock.call("https://api.github.com/user", bearer="GITHUB_TOKEN")
    
assert len(mock.calls) == 1
```
This is fully compatible with mocking frameworks like `unittest.mock.patch` when replacing global instances.
