# ATField

基于 [EVA](https://github.com/usepr/eva) 演进的智能体内核，capability-based 安全模型，流式响应，记忆压缩。

## 架构

- **单文件核心**: `eva.py` (~1200 行)，Agent / ToolRegistry / Memory / LLMClient
- **TUI 薄前端**: `eva_tui.py`，通过 JSON over subprocess 与后端通信
- **测试套件**: `tests/` (181 tests，unit/protocol/integration/e2e 四层)

## 安全边界（当前）

- ✅ **Capability-based 默认拒绝**：READ_FS/WRITE_FS/EXEC/NETWORK/SESSION/MEMORY
- ✅ **只读白名单**：ls/cat/grep 等 30+ 命令无需确认直接执行
- ✅ **写操作需用户确认**：rm/mv/dd 等关键词触发确认提示
- ✅ **审计日志**：`.eva/audit/{date}.jsonl`（含 tool/cap/result_len/denied/exit_code）
- ✅ **统一错误码**：EVAError + ExitCode（CONFIG_ERROR/NETWORK_ERROR/TOOL_DENIED）
- ✅ **离线模式**：`--offline` / `EVA_OFFLINE=1` 跳过模型探测
- ⬜ **沙箱执行**：firejail / sandbox-exec（未实现）
- ⬜ **Prompt 防火墙**：InputGuard（未实现）
- ⬜ **HMAC 签名保护**：Memory 类（未实现）

## 快速开始

```bash
# 标准启动
poetry run python eva.py

# 离线模式（跳过模型探测，不联网）
poetry run python eva.py --offline

# TUI 模式
poetry run python eva_tui.py

# 允许所有命令（危险，仅开发）
poetry run python eva.py -a
```

## 项目结构

```
eva.py              # 单文件核心
eva_tui.py           # TUI 薄前端
pyproject.toml      # 依赖配置
tests/
  unit/             # 纯函数、类单元
  protocol/         # 协议编解码、字段完整性
  integration/      # Agent step/resume 回路
  e2e/              # TUI 子进程冒烟
todo/               # 设计文档
```

## 设计原则

1. 默认拒绝，显式授权（capability-based）
2. 本地策略判断，无需 LLM 做安全决策
3. 流式响应 + 记忆压缩突破上下文限制
4. 跨平台：Windows PowerShell / Linux Bash

## License

Apache-2.0
