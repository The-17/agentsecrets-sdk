# Management API Reference

The management API provides programmatic control over the AgentSecrets workspace lifecycle, projects, secrets, allowed domains, and audit logging.

---

## 1. Workspaces Client (`client.workspaces`)

Manage workspaces, memberships, and tenant switching.

### Methods
* **`list()`**: Returns a list of all workspaces.
* **`create(name: str)`**: Creates a new workspace.
* **`switch(name: str)`**: Programmatically sets the active workspace globally.
* **`members()`**: Lists members and roles in the active workspace.
* **`invite(email: str, role: str = "member")`**: Sends a membership invitation.

### Scoped Contexts
Use `with client.use_workspace(name)` to temporarily query or run actions inside another workspace:
```python
with client.use_workspace("Client_B"):
    # This call is isolated to Client_B's credential allowlist
    client.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")
```

---

## 2. Projects Client (`client.projects`)

Organize credentials under project namespaces.

### Methods
* **`list()`**: Lists all projects under the active workspace.
* **`create(name: str)`**: Creates a new project.
* **`use(name: str)`**: Switches the active project globally.

### Scoped Contexts
```python
with client.use_project("microservice-b"):
    # This spawn receives Microservice-B's secrets
    client.spawn(["node", "index.js"])
```

---

## 3. Secrets Client (`client.secrets`)

Synchronize and provision credentials.

### Methods
* **`list()`**: Returns a list of secret keys (names only, never values).
* **`set(key: str, value: str)`**: Programmatically sets or overwrites a local secret value in the OS keychain.
* **`delete(key: str)`**: Deletes a secret key.
* **`diff()`**: Compares the local secret state against the cloud backup:
  * Returns a `DiffResult` containing `has_drift`, `local_only`, `remote_only`, and `out_of_sync` lists.
* **`sync(force: bool = False)`**: Pulls the remote backup state to the local keychain.
* **`push(force: bool = False)`**: Encrypts and uploads local credentials to the secure cloud resolver backup.

---

## 4. Allowlist Client (`client.allowlist`)

Enforce domain boundary checks.

### Methods
* **`list()`**: Returns allowed destination domains.
* **`add(domains: str | list[str])`**: Appends domains to the allowlist. Requires admin privileges.
* **`remove(domain: str)`**: Removes a domain. Requires admin privileges.
* **`log(last: int = 100)`**: Returns a list of block events from blocked requests.

---

## 5. Proxy & Logs Client (`client.proxy`)

Control the background daemon and view audit logs.

### Methods
* **`start()`**: Launches the proxy daemon background process.
* **`stop()`**: Terminates the proxy daemon process.
* **`status()`**: Returns a `ProxyStatus` detailing uptime, port, and health.
* **`logs(last: int = 100, status: str | None = None, secret: str | None = None)`**: 
  * Queries transaction audit logs.
  * Allows filtering by status (e.g. `BLOCKED`, `ALLOWED`) or by the specific secret key name used.
  * Returns list of `AuditEvent` elements (containing timestamps, target URLs, HTTP methods, and status codes).
