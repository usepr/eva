# ATField

**ATField** (AT Field) is a secure, capability-based AI agent kernel built on [EVA](https://github.com/usepr/eva). It provides an interactive LLM-powered agent with shell command execution, session persistence, and memory compression — designed for secure, auditable shell automation.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/lint-ruff-blue.svg)](https://github.com/astral-sh/ruff)
[![Tests: 181](https://img.shields.io/badge/tests-181-brightgreen.svg)](#testing)

## Features

- **Capability-Based Security** — Six granular capabilities (READ_FS/WRITE_FS/EXEC/NETWORK/SESSION/MEMORY). Default-deny, explicit-grant model.
- **Zero LLM Security Decision** — Local keyword matching decides capability grants. No LLM used for security decisions.
- **Streaming Response** — Real-time token-by-token display via TUI.
- **Memory Compression** — Automatic session compaction at 75% token capacity, preserving long-term context.
- **Audit Logging** — JSONL logs with tool/capability/exit_code/result_len per operation.
- **Offline Mode** — No network at import time. Model probing is lazy.
- **Cross-Platform** — Windows PowerShell / Linux Bash abstraction.
- **181 Tests** — Four-layer test suite (unit/protocol/integration/e2e).

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  eva_tui.py (Textual TUI — frontend)                        │
│  • Rich chat UI with streaming thinking/content events       │
│  • Communicates with backend via JSON over stdin/stdout      │
└─────────────────────────┬────────────────────────────────────┘
                          │ subprocess
┌─────────────────────────▼────────────────────────────────────┐
│  eva.py (core kernel — backend)                              │
│  • Agent: LLM loop, tool calling, memory management          │
│  • ToolRegistry: capability gate, command execution          │
│  • Memory: session persistence, hints, compression           │
│  • LLMClient: streaming DeepSeek API client                  │
└──────────────────────────────────────────────────────────────┘
```

## Installation

```bash
# Clone
git clone https://github.com/gckellan/eva.git
cd eva

# Install dependencies
poetry install

# Configure (create .env)
cp .env.example .env
# Edit .env: set EVA_API_KEY, EVA_BASE_URL, EVA_MODEL_NAME
```

## Quick Start

```bash
# Interactive TUI (recommended)
poetry run python eva_tui.py

# Interactive CLI
poetry run python eva.py

# Single query
poetry run python eva.py -u "今天杭州天气如何"

# Offline mode (no network on import)
EVA_OFFLINE=1 poetry run python eva.py
```

## Configuration

Create a `.env` file in the project root:

```bash
EVA_API_KEY="sk-..."
EVA_BASE_URL="https://api.deepseek.com/v1"
EVA_MODEL_NAME="deepseek-v4-pro"
```

Or export environment variables:

```bash
export EVA_API_KEY="sk-..."
export EVA_BASE_URL="https://api.deepseek.com/v1"
export EVA_MODEL_NAME="deepseek-v4-pro"
poetry run python eva.py
```

## Security Model

ATField uses a **capability-based access control (CBAC)** model. All operations require explicit capabilities.

| Capability | Description |
|------------|-------------|
| `READ_FS` | Read filesystem (ls, cat, grep, etc.) |
| `WRITE_FS` | Write filesystem (write files, create directories) |
| `EXEC` | Execute arbitrary shell commands |
| `NETWORK` | Network requests |
| `SESSION` | Manage sessions |
| `MEMORY` | Access and modify persistent memory |

### Default Behavior

- **Read-only commands** (ls, cat, grep, etc.) → execute directly without confirmation
- **Write/mutating commands** (rm, mv, dd, etc.) → require `--allow-all` flag or explicit grant
- **Unknown commands** → blocked by default, require `EXEC` capability

### Enabling Full Execution

```bash
# Allow all commands (dangerous — for development only)
poetry run python eva.py -a        # CLI
poetry run python eva_tui.py -a    # TUI
```

### Audit Log

All tool executions are logged to `.eva/audit/{date}.jsonl`:

```json
{"time":"2026-04-29T18:35:01.277","tool":"run_cli","command_hash":"abc123","exit_code":0,"cap":["EXEC"],"result_len":156,"denied":false}
```

## Project Structure

```
eva.py              # Core agent kernel (~1200 lines)
eva_tui.py          # Textual TUI frontend (~400 lines)
pyproject.toml      # Poetry + tool configuration
.env                # API credentials (gitignored)
tests/              # 181 tests across 4 layers
  unit/             # Pure unit tests (AgentContext, Memory, ToolRegistry)
  protocol/         # Message schema, field contracts
  integration/      # Agent step/resume loop (mock LLM)
  e2e/              # TUI subprocess smoke tests
todo/               # Design documents and hardening roadmap
```

## Testing

```bash
# All tests
poetry run pytest tests/ -q

# By layer
poetry run pytest tests/unit/ -q
poetry run pytest tests/protocol/ -q
poetry run pytest tests/integration/ -q
poetry run pytest tests/e2e/ -q

# Lint
poetry run ruff check eva.py eva_tui.py
```

## Security Hardening Roadmap

| Feature | Status |
|---------|--------|
| Capability-based security model | ✅ Implemented |
| Read-only command whitelist | ✅ Implemented |
| Audit logging | ✅ Implemented |
| Offline mode (no import network) | ✅ Implemented |
| Sandbox execution (firejail/sandbox-exec) | ⬜ Planned |
| Prompt injection firewall (InputGuard) | ⬜ Planned |
| HMAC-signed memory (tamper-proof) | ⬜ Planned |

See [todo/hardening_plan.md](todo/hardening_plan.md) for detailed design specs.

## Design Principles

1. **Default-deny, explicit-grant** — No operation allowed without explicit capability
2. **Local policy over LLM** — Security decisions made locally, not by LLM
3. **Streaming + compression** — Real-time tokens, memory compression at 75% capacity
4. **Cross-platform** — Windows PowerShell / Linux Bash abstracted behind `IS_WINDOWS` check

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.