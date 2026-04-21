# ATField

> A secure, capability-based agent kernel with sandboxed execution and tamper-proof audit logs.
>
> 基于能力模型的安全智能体内核，支持沙箱执行与防篡改审计。

**ATField** 是一个从 [EVA](https://github.com/usepr/eva) 演进而来的生产级智能体运行时。它继承了 EVA 的极简哲学和自我进化意识，但在安全边界上进行了彻底重构——将 Agent 从"不受限制的命令执行器"转变为"受控的、有边界的自律工作者"。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| 🔒 **Capability-based 安全模型** | Agent 只能在显式授权的范围内行动，默认拒绝一切 |
| 🛡️ **沙箱执行** | 所有命令通过 Firejail 容器化运行，文件系统/网络/进程三重隔离 |
| 📜 **防篡改审计** | 每一条操作都被结构化记录，并通过哈希链保证不可篡改 |
| 🧠 **记忆压缩与进化** | 自动整理记忆、保存技能，突破上下文窗口限制 |
| 📦 **零外部依赖** | 运行时仅依赖 Python 标准库，供应链攻击面为零 |
| 📁 **目录级 Session** | 每个工作目录拥有独立的对话上下文，自动保存与恢复 |

---

## 架构概览

```
用户/LLM 请求
    ↓
┌─────────────────┐
│  Capability     │  ← 你有权限做这件事吗？
│  Gate（能力门） │
└─────────────────┘
    ↓ 是
┌─────────────────┐
│  Sandbox        │  ← 在受限环境中执行
│  Executor       │
└─────────────────┘
    ↓
┌─────────────────┐
│  Audit Log      │  ← 永久记录，不可篡改
│  （审计日志）    │
└─────────────────┘
```

---

## 快速开始

### 1. 克隆仓库

```bash
git clone git@github.com:kellan04/ATField.git
cd ATField
```

### 2. 配置环境变量

```bash
export EVA_API_KEY="sk-xxxxxxxxxxxxxxxx"
export EVA_BASE_URL="https://api.deepseek.com/v1"
export EVA_MODEL_NAME="deepseek-reasoner"

# 安全密钥（用于审计日志和记忆完整性校验）
export EVA_AUDIT_SECRET="$(openssl rand -hex 32)"
export EVA_HINTS_SECRET="$(openssl rand -hex 32)"
```

### 3. 安装沙箱（推荐）

```bash
# macOS
brew install firejail

# Ubuntu/Debian
sudo apt-get install firejail
```

### 4. 运行

```bash
python3 -m atfield
```

或使用 CLI：

```bash
# 首次运行会自动创建启动脚本
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# 启动
atfield
```

---

## 安全策略配置

ATField 通过 `policies/` 目录下的 YAML 文件定义 Agent 的能力边界。默认使用 `policies/strict.yaml`：

```yaml
capabilities:
  - action: read
    pattern: "/home/user/project/**"
  
  - action: write
    pattern: "/home/user/project/.eva/**"
  
  - action: exec
    pattern: "python3"
    allow_args: ["--version", "-m"]
  
  - action: network
    pattern: "api.deepseek.com"

deny_patterns:
  - "**/.ssh/**"
  - "**/.aws/**"
  - "**/secrets.*"
```

**关键原则**：
- 默认拒绝所有操作
- 读/写/执行/网络均需显式授权
- 危险操作（写入、执行）默认触发二次确认

---

## CLI 选项

```
atfield 选项：
  -h, --help            显示帮助信息
  -a, --allow-all       允许所有命令无需确认（危险，仅建议自动化场景使用）
  -l, --list-session    列出所有会话
  -c, --clear-session   清除当前目录会话
  -u, --user-ask        独立地针对一条用户提问执行
```

---

## 与 EVA 的关系

ATField 是 [EVA](https://github.com/usepr/eva) 的安全增强分支。EVA 的原始设计理念——极简、自主、可进化——被完整保留，同时增加了以下安全层：

| 维度 | EVA | ATField |
|------|-----|---------|
| 安全模型 | LLM 自我审查 + 用户确认 | Capability-based 显式授权 |
| 命令执行 | 宿主机直接执行 | Firejail 沙箱隔离 |
| 依赖 | requests | **零外部依赖** |
| 审计 | print 输出 | 结构化 + 哈希链 + 防篡改 |
| 记忆持久化 | 纯文本 hints.md | HMAC 签名保护 |

---

## 设计哲学

1. **安全不是加功能，而是建边界**  
   Agent 的能力必须被显式约束，而非默认开放。

2. **零信任运行时**  
   不信任任何输入——包括用户、LLM、文件、网络响应。

3. **自主进化，但受控进化**  
   保留 EVA 的自我进化意识，但将进化产物（知识、技能、记忆）纳入完整性保护。

4. **极简即安全**  
   代码越少，攻击面越小。零外部依赖意味着供应链投毒风险为零。

---

## 贡献

欢迎提交 Issue 和 PR。特别关注的方向：

- 更优雅的沙箱方案（gVisor、rootless container）
- 记忆压缩的持续性改进
- 更完善的 Capability 策略语言
- 多 Agent 协作的安全边界

---

## License

Apache-2.0
