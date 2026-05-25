# Universal Environment Switching

AgentSecrets supports **universal environment switching** programmatically in the Python SDK without requiring any modifications to the running local proxy daemon.

---

## How It Works

The active environment context is universal across your project context. This active environment state is saved on disk at:
`.agentsecrets/project.json`

The local AgentSecrets proxy daemon resolves credentials dynamically on **every request** by loading the project context directly from this file. 

Therefore, to switch environments programmatically, the Python SDK can execute the CLI command once in the background:
```bash
agentsecrets environment switch <env>
```

Once executed, the project context file on disk is updated. The running proxy automatically loads the updated environment context on subsequent credential resolution requests, with no restart required.

---

## SDK Programmatic Usage

### 1. The Global `settings` Object
You can import the global `settings` object and update its `environment` property. The SDK will automatically invoke the CLI command in the background to switch environments:

```python
from agentsecrets import settings

# Switches project configuration to "staging" in the background
settings.environment = "staging"
```

If the CLI command fails (e.g. if the CLI binary is not installed or the environment name is invalid), a `ValueError` is raised.

---

### 2. Initialization via `init()`
You can specify the initial environment context when calling the global `init()` helper:

```python
from agentsecrets import init

# Initializes transparent interception and configures the environment context
init(intercept=True, environment="production")
```

---

### 3. Constructor Initialization
You can specify the environment directly when instantiating the main client:

```python
from agentsecrets import AgentSecrets

# Switches environment and sets up the client
client = AgentSecrets(environment="staging")
```
