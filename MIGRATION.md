# Migrating from SDK v2.x to v3.x

## No Breaking Changes
SDK v3.0 is **fully backward compatible** with v2.0. Your existing code continues to work.

## Recommended Upgrades

### Use Context Managers (Resource Cleanup)
**Before (v2.x — still works but leaks sockets in long-running services):**
```python
client = AgentSecrets()
response = client.call(...)
# client never cleaned up
```

**After (v3.x — recommended):**
```python
with AgentSecrets() as client:
    response = client.call(...)
# connection pool closed automatically
```

### Async Code: Use `AsyncAgentSecrets`
**Before (v2.x):**
```python
client = AgentSecrets()
response = await client.async_call(...)
```

**After (v3.x — cleaner):**
```python
async with AsyncAgentSecrets() as client:
    response = await client.call(...)  # Note: call, not async_call
```

### Private Imports
If you were importing internal modules (bad practice, but some users do):
```python
# v2.x
from agentsecrets.call import call  # ���� �� �� ❌  Broke in v3.0
from agentsecrets._call import call  # ���� �� �� ❌  Also broke (moved to internal/)

# v3.x (don't do this — use public API)
from agentsecrets.internal._call import call  # Works but unsupported
```

## Solution
Use the public `AgentSecrets` client. If you need lower-level access, file an issue.