# SDK Manual Testing Guide

This guide describes how to verify the connection, request interception, and mock capabilities of the Python SDK. 

---

## 1. Environment Configuration

Follow these steps to prepare your local terminal and CLI daemon before running any SDK tests:

### Step A: Configure the Workspace & Mock Secrets
```bash
# Reset local CLI config
agentsecrets init --force

# Create test scope
agentsecrets workspace create "Test Workspace"
agentsecrets project create "sdk-test-project"
agentsecrets environment switch "development"

# Set a mock credential value in your OS Keychain
agentsecrets secrets set MOCK_SERVICE_KEY="mock_secret_value_12345"

# Authorize the target domain
agentsecrets workspace allowlist add httpbin.org
```

### Step B: Start the daemon
```bash
agentsecrets proxy start
```

---

## 2. Manual Test Cases

### Test 1: Verify Connection & Status
Verify that the SDK connects to the active daemon session and resolves context.

Create `test_status.py`:
```python
from agentsecrets import AgentSecrets

# Initialize client
client = AgentSecrets()

# Verify connection to local daemon
status = client.proxy.status()
print(f"✓ Connected on Port: {status.port}")
```

```bash
python test_status.py
# Expected Output:
# ✓ Connected on Port: 8765
```

---

### Test 2: Secure API Calls (`client.call()`)
Verify that credentials are dynamically resolved from your OS Keychain and injected at the transport boundary.

Create `test_call.py`:
```python
from agentsecrets import AgentSecrets

client = AgentSecrets()

# Target httpbin to inspect request headers
response = client.call(
    "https://httpbin.org/headers",
    method="GET",
    bearer="MOCK_SERVICE_KEY"
)

headers = response.json().get("headers", {})
print(f"✓ Authorization Injected: {headers.get('Authorization')}")
```

```bash
python test_call.py
# Expected Output:
# ✓ Authorization Injected: Bearer mock_secret_value_12345
```

---

### Test 3: Transparent Interception (`init()`)
Verify that outgoing calls made by standard libraries (`requests` and `httpx`) are intercepted.

Create `test_interception.py`:
```python
import httpx
import requests
from agentsecrets import init, credential

# Register global interception hooks
init()

# 1. Verify requests library interception
res_req = requests.get(
    "https://httpbin.org/headers",
    headers={"Authorization": f"Bearer {credential.MOCK_SERVICE_KEY}"}
)
auth_req = res_req.json().get("headers", {}).get("Authorization")
print(f"✓ Intercepted requests: {auth_req}")

# 2. Verify httpx library interception
with httpx.Client() as client:
    res_httpx = client.get(
        "https://httpbin.org/headers",
        headers={"Authorization": f"Bearer {credential.MOCK_SERVICE_KEY}"}
    )
auth_httpx = res_httpx.json().get("headers", {}).get("Authorization")
print(f"✓ Intercepted httpx:    {auth_httpx}")
```

```bash
python test_interception.py
# Expected Output:
# ✓ Intercepted requests: Bearer mock_secret_value_12345
# ✓ Intercepted httpx:    Bearer mock_secret_value_12345
```

---

## 3. Clean Up

Shut down the daemon and reset the configuration:
```bash
agentsecrets proxy stop
agentsecrets init --force
```
