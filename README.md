# ATField

基于 [EVA](https://github.com/usepr/eva) 演进的智能体内核，capability-based 安全模型，流式响应，记忆压缩。

## 架构

- **单文件核心**: `eva.py` (~1200 行)，Agent / ToolRegistry / Memory / LLMClient
- **TUI 薄前端**: `eva_tui.py`，通过 JSON over subprocess 与后端通信
- **测试套件**: `tests/` (161 tests, 140+ passing)

## 安全边界（当前）

- 默认拒绝：写操作需用户确认
- 本地 capability 判断：无需 LLM 审查只读命令
- 审计日志：`.eva/audit/{date}.jsonl`
- `-a` 模式：高亮警告，仅开发环境

## 安全边界（未来 / 待完成）

- **沙箱**：firejail / sandbox-exec（未实现）
- **Prompt 防火墙**：未实现
- **HMAC 签名保护**：未实现
- **工具插件化**：Schema 注册已完成，插件加载未实现

## 快速开始

```bash
# 配置 .env 或环境变量
poetry run python eva.py

# TUI 模式
poetry run python eva_tui.py

# 允许所有命令（危险，仅开发）
poetry run python eva.py -a
```

## 项目结构

```
eva.py           # 单文件核心
eva_tui.py       # TUI 薄前端
pyproject.toml   # 依赖配置
tests/            # 单元测试套件
todo/             # 设计文档
```

## 设计原则

1. 默认拒绝，显式授权（capability-based）
2. 本地策略判断，无需 LLM 做安全决策
3. 流式响应 + 记忆压缩突破上下文限制
4. 跨平台：Windows PowerShell / Linux Bash

## License

Apache-2.0
