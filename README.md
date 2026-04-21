# ATField

基于 [EVA](https://github.com/usepr/eva) 演进的智能体内核，目标是在保持极简架构的同时，构建安全可信的 Agent 运行时。

当前版本为单文件原型，核心功能已可用，正在向生产级内核逐步加固。

## 当前功能

- 交互式 LLM Agent，支持流式响应（含 thinking 过程展示）
- `run_cli` 工具执行 shell 命令，默认只读，危险操作需 LLM 审查 + 用户确认
- `leave_memory_hints` 工具实现记忆压缩，突破上下文窗口限制
- 按工作目录隔离的 Session，自动保存/恢复对话历史
- 跨平台支持（Windows PowerShell / Linux Bash）

## 快速开始

```bash
export EVA_API_KEY="sk-xxxxxxxx"
export EVA_BASE_URL="https://api.deepseek.com/v1"
export EVA_MODEL_NAME="deepseek-reasoner"

python3 eva.py
```

## 待办工作 (TODO)

- [ ] **零依赖化**：将 `requests` 替换为 `http.client` 标准库实现
- [ ] **Capability 权限系统**：从"默认开放+审查"改为"默认拒绝+显式授权"
- [ ] **沙箱执行**：所有命令通过 firejail 容器化运行
- [ ] **Prompt 防火墙**：防止用户输入覆盖系统指令
- [ ] **审计日志**：结构化记录所有操作，哈希链防篡改
- [ ] **工具插件化**：从硬编码工具改为注册中心 + Schema 校验
- [ ] **记忆完整性**：hints / sessions 文件增加 HMAC 签名保护
- [ ] **配置系统**：从环境变量迁移到 `dataclass` + `policies.yaml`
- [ ] **项目骨架拆分**：从单文件演进为分层模块结构

## 设计原则

1. 默认拒绝，显式授权
2. 零外部依赖（运行时仅 Python 标准库）
3. 自主进化，但受控进化
4. 极简即安全

## License

Apache-2.0
