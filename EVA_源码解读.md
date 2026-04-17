# EVA 源码解读

> `eva.py` 是一个约 657 行的单文件 AI Agent，基于 OpenAI-compatible API，实现了一个可自我进化、能执行终端命令的对话 Agent。

---

## 目录

1. [整体架构](#整体架构)
2. [模块划分](#模块划分)
3. [核心流程](#核心流程)
4. [关键机制详解](#关键机制详解)
   - [LLM 配置与动态检测](#1-llm-配置与动态检测)
   - [System Prompt 设计](#2-system-prompt-设计)
   - [工具系统](#3-工具系统)
   - [命令安全审查](#4-命令安全审查)
   - [流式输出与 Thinking 显示](#5-流式输出与-thinking-显示)
   - [记忆压缩（Compact）机制](#6-记忆压缩compact机制)
   - [会话持久化](#7-会话持久化)
   - [Agent Loop](#8-agent-loop)
5. [数据流图](#数据流图)
6. [关键变量速查](#关键变量速查)

---

## 整体架构

```
eva.py
├── 配置区（LLM 参数、全局常量）
├── Prompt 模板（SYSTEM_PROMPT、COMPACT_PROMPT、CLI_REVIEW_PROMPT）
├── 工具定义（run_cli_schema、memory_hints_schema）
├── 工具执行器（run_cli、leave_memory_hints）
├── LLM 通信层（llm_chat、llm_chat_stream）
├── 记忆/会话管理（load_session、save_session、leave_memory_hints）
└── 主循环（agent_single_loop → human_loop → main）
```

EVA 是一个典型的 **ReAct 范式 Agent**：
- LLM 接收任务 → 思考 → 调用工具 → 观察结果 → 继续思考，循环直到任务完成
- 额外引入了**记忆压缩**机制应对有限上下文窗口

---

## 模块划分

### L1–L50：导入 & 基础配置
```python
EVA_BASE_URL   # LLM API 地址（默认 deepseek.com）
EVA_MODEL_NAME # 模型名（默认 deepseek-reasoner）
EVA_API_KEY    # API Key
TOKEN_CAP      # 动态检测的模型上下文长度
COMPACT_THRESH # 触发记忆压缩的阈值（默认 75%）
TOOL_RESULT_LEN# 工具返回内容的最大长度（TOKEN_CAP / 20）
WORKSPACE_DIR  # EVA 私人工作目录（./.eva）
HINT_FILE      # 记忆线索文件路径（.eva/hints.md）
ALLOW_ALL_CLI  # 是否跳过命令安全审查
```

### L52–L99：Prompt 模板区
三个核心 Prompt：
- `SYSTEM_PROMPT`：EVA 身份、能力、规则、记忆线索注入
- `COMPACT_PROMPT`：记忆压缩触发时的紧急指令
- `CLI_REVIEW_PROMPT`：命令安全审查（发给 LLM 判断是否放行）

### L102–L215：工具定义与执行
两个工具：`run_cli`（执行终端命令）、`leave_memory_hints`（保存记忆线索）

### L228–L382：LLM 通信层
- `_build_request_data`：统一构建请求体
- `llm_chat`：非流式调用
- `llm_chat_stream`：流式调用，含 thinking 内容实时显示

### L385–L463：记忆与会话管理
- 记忆线索：`hints.md` 文件，每次启动时加载注入到 System Prompt
- 会话文件：`.eva/sessions/<dir_hash>.json`，基于工作目录隔离

### L467–L570：Agent & Human Loop
- `agent_single_loop`：单轮 Agent 循环（LLM → 工具 → LLM...）
- `human_loop`：接收用户输入，驱动 agent_single_loop

### L572–L656：安装脚本 & main 入口
- `setup_eva_script`：自动安装 `eva` 命令到 `~/.local/bin`
- `main`：解析命令行参数，加载会话，启动主循环

---

## 核心流程

```
main()
 ├── setup_eva_script()       # 首次运行安装全局命令
 ├── 解析 argparse 参数
 ├── load_session()           # 加载历史会话
 └── human_loop()
      └── [用户输入]
           ├── 追加 messages
           └── agent_single_loop()
                ├── llm_chat_stream()   # 调用 LLM（流式）
                ├── [有 tool_calls?]
                │    ├── run_cli(command)           # 执行终端命令
                │    │    ├── LLM 安全审查（非放行则询问用户）
                │    │    └── subprocess.run()
                │    └── leave_memory_hints(hints)  # 记忆压缩完成
                │         └── 截断 messages，重置对话
                ├── [token 超 75%?] → 插入 COMPACT_PROMPT，触发记忆压缩
                └── [无 tool_calls] → 跳出循环，返回用户
```

---

## 关键机制详解

### 1. LLM 配置与动态检测

```python
# L21-L32
def detect_model_len():
    url = f"{EVA_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    try:
        resp = requests.get(url, headers=headers)
        out = resp.json()
        for d in out.get('data', []):
            if d['id'] == EVA_MODEL_NAME:
                return d.get('max_model_len', 256_000)
    except Exception:
        pass
    return 256_000  # fallback
```

启动时自动向 `/models` 接口查询模型的最大上下文长度，用于动态设定 `TOKEN_CAP`。若接口不支持（如 MiniMax），fallback 到 256k。

---

### 2. System Prompt 设计

System Prompt 包含 6 个核心区块：

| 区块 | 内容 |
|------|------|
| `你是谁` | EVA 身份定义 |
| `你在哪` | 当前 OS、工作目录、token 容量 |
| `你要做什么` | 任务执行规则、工具调用要求 |
| `工具调用说明` | 命令语法注意事项 |
| `机器人三大定律` | 阿西莫夫三定律，约束行为边界 |
| `关于进化` | 定义何时、如何保存记忆和技能 |
| `记忆线索` | 动态注入 `{hints}` — 上次保存的线索 |

**进化哲学**：三定律第三条"保护自生存" → 进化是最佳手段 → 将技能固化到文件 → 通过 `hints` 传递给下次会话，形成跨会话记忆。

---

### 3. 工具系统

EVA 只有两个工具，设计极简：

#### `run_cli`（L149–L173）

```python
def run_cli(command: str, timeout: int = 30):
    # 1. 安全审查（非 ALLOW_ALL_CLI 模式）
    # 2. subprocess.run([SHELL, SHELL_FLAG, command])
    # 3. 返回 "Exit code: N\n{stdout}\nSTDERR:\n{stderr}"
```

- Linux/macOS：`bash -c <command>`
- Windows：`powershell.exe -Command <command>`
- 工作目录始终是 `os.getcwd()`（启动时目录）

#### `leave_memory_hints`（L175–L210）

记忆压缩完成后 LLM 调用此工具。执行三个动作：
1. 从当前 `messages` 中找到 `COMPACT_PROMPT` 的位置
2. 截断 messages，只保留：新 System Prompt（含新 hints）+ 压缩前最后一次用户消息
3. 将 hints 写入 `hints.md` 文件，供下次启动加载

---

### 4. 命令安全审查

```python
# L153-L157（位于 run_cli 内）
msg, _ = llm_chat([{"role": "user", "content": CLI_REVIEW_PROMPT.format(command=command)}],
                  temperature=0.0, thinking=False)
if '放行' not in msg['content']:
    ans = read_input("Yes (默认) | No | 直接 Ctrl+C 打断：")
    if 'n' in ans.lower():
        return "用户拒绝运行此命令"
```

- 每次 `run_cli` 前，用另一次 LLM 调用（非流式、temperature=0）判断命令是否安全
- 只读操作（`cat`、`ls`、`grep` 等）→ "放行"，直接执行
- 写入/执行/网络操作 → "禁止"，询问用户确认
- `-a` 参数可跳过审查（`ALLOW_ALL_CLI = True`）

---

### 5. 流式输出与 Thinking 显示

```python
# L317-L337（位于 llm_chat_stream 内）
reasoning_content = delta.get('reasoning_content') or delta.get('reasoning') or ''
if reasoning_content:
    if not is_thinking:
        sys.stdout.write('\033[2m💭 ')  # 暗色显示思考过程
    sys.stdout.write(reasoning_content)

text = delta.get('content') or ''
if text:
    if is_thinking:
        sys.stdout.write('\033[0m\n')   # 结束暗色
    sys.stdout.write(text)
```

- `reasoning_content` / `reasoning` 字段：Thinking 模型的内部思考，用 `\033[2m`（暗色）+ 💭 标记区分
- `content` 字段：正式回答，正常颜色
- tool_calls 通过 `tool_calls_map[index]` 增量拼接，最终重组为标准格式

---

### 6. 记忆压缩（Compact）机制

这是 EVA 最核心的创新设计，解决有限上下文窗口问题：

```
Token 使用 >= TOKEN_CAP * 75%
        ↓
向 messages 追加 COMPACT_PROMPT（紧急危机指令）
        ↓
LLM 执行三步：保存记忆 → 保存技能知识 → 调用 leave_memory_hints
        ↓
leave_memory_hints() 执行：
  1. 找到 COMPACT_PROMPT 在 messages 中的位置（compact_i）
  2. 找到 compact_i 前最后一条用户消息（last_user_i）
  3. 重建 messages = [新 system] + messages[last_user_i:compact_i] + [继续提示]
  4. 重置 COMPACT_PANIC = "off"
  5. 写入 hints.md
```

**效果**：LLM 在快撑爆上下文时自动整理并"压缩记忆"，保留精华线索，截断历史对话，无缝继续工作。

---

### 7. 会话持久化

```python
# 会话文件路径规则
session_file = f".eva/sessions/{dir_hash}.json"
# dir_hash 是当前工作目录路径，将 / \ : 替换为 _
```

- **隔离方式**：以工作目录为 key，不同项目目录的会话互不干扰
- **加载时机**：启动时（非 `-u` 模式）自动加载，有残留未执行的 tool_call 则清理
- **保存时机**：用户按 Ctrl+C 中断时自动保存

---

### 8. Agent Loop

```python
# L467-L545
def agent_single_loop():
    while not break_loop:
        msg, usage = llm_chat_stream(messages, tools=[run_cli_schema])
        messages.append(msg)

        if not msg.get('tool_calls'):
            break  # LLM 不再调用工具，任务完成，返回用户

        for tc in msg['tool_calls']:
            result = tool_executors[name](**args)
            messages.append({"role": "tool", "content": result})

            if usage['total_tokens'] >= TOKEN_CAP * COMPACT_THRESH:
                # 触发记忆压缩
                COMPACT_PANIC = "on"
                messages.append({"role": "user", "content": COMPACT_PROMPT})
```

- **COMPACT_PANIC = "on"** 时：额外暴露 `memory_hints_schema` 工具给 LLM，确保 LLM 能调用记忆保存工具
- **工具结果截断**：若结果超过 `TOOL_RESULT_LEN`（TOKEN_CAP/20），截断并提示 LLM 控制读取行数

---

## 数据流图

```
用户输入
    │
    ▼
messages（List[dict]）
    │  role: system / user / assistant / tool
    ▼
llm_chat_stream()
    │  SSE 流式解析
    │  ├── reasoning_content → 暗色打印（思考过程）
    │  └── content → 正常打印（最终回答）
    ▼
msg（assistant message）
    │
    ├── [有 tool_calls]
    │       │
    │       ├── run_cli(command)
    │       │       ├── 安全审查（llm_chat 非流式）
    │       │       └── subprocess.run()
    │       │
    │       └── leave_memory_hints(hints)
    │               └── 截断 messages，写 hints.md
    │
    └── [无 tool_calls] → 返回用户输入
```

---

## 关键变量速查

| 变量 | 类型 | 含义 |
|------|------|------|
| `messages` | `list` | 全局对话历史，贯穿所有函数 |
| `TOKEN_CAP` | `int` | 模型最大上下文 token 数 |
| `COMPACT_THRESH` | `float` | 记忆压缩触发阈值（0.75） |
| `COMPACT_PANIC` | `str` | `"on"/"off"` 标记是否处于压缩紧急状态 |
| `TOOL_RESULT_LEN` | `int` | 工具返回内容最大字符数 |
| `ALLOW_ALL_CLI` | `bool` | 是否跳过命令安全审查 |
| `WORKSPACE_DIR` | `str` | EVA 私人目录 `./.eva` |
| `HINT_FILE` | `str` | 记忆线索文件 `.eva/hints.md` |

---

## 命令行参数

```
python3 eva.py [-h] [-a] [-l] [-c] [-u USER_ASK]

-a / --allow-all      允许所有 CLI 命令无需确认（危险！）
-l / --list-session   列出所有会话文件
-c / --clear-session  清除当前目录的会话
-u / --user-ask TEXT  单次提问模式（非交互）
```

---

## 设计亮点总结

1. **单文件极简**：657 行完成一个功能完整的 Agent，无框架依赖
2. **思考可视化**：流式打印 reasoning_content，暗色显示，区分思考与回答
3. **命令安全双保险**：LLM 审查 + 用户确认，两道防线
4. **自我进化设计**：通过 hints.md 实现跨会话知识传承，三定律赋予进化动机
5. **上下文无限续航**：Compact 机制自动压缩记忆，理论上可无限运行
6. **目录隔离会话**：不同项目互不干扰，符合工程师直觉
