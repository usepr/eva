"""
EVA：一个能够自我进化的机器人
"""

import os
import re
import json
import subprocess
import sys
import traceback
import argparse
import platform

from dataclasses import dataclass, field
from pathlib import Path

# ============================================================================
# 1. 基础设施：路径
# ============================================================================
this_file = str(Path(__file__).resolve())
this_dir = Path(__file__).resolve().parent


# ============================================================================
# 2. AgentContext
# ============================================================================
@dataclass
class AgentContext:
    """运行时状态容器"""
    messages: list = field(default_factory=list)
    compact_panic: str = "off"
    allow_all_cli: bool = False


# ============================================================================
# 3. LLM 配置
# ============================================================================
EVA_BASE_URL = os.environ.get("EVA_BASE_URL", "https://api.deepseek.com/v1")
EVA_MODEL_NAME = os.environ.get("EVA_MODEL_NAME", "deepseek-reasoner")
EVA_API_KEY = os.environ.get("EVA_API_KEY", "sk-这里填你的deepseek API key")


def detect_model_len() -> int:
    """探测模型上下文长度"""
    import requests

    url = f"{EVA_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except UnicodeEncodeError:
        print(
            f"错误：EVA_API_KEY ({EVA_API_KEY}) 包含非法字符，请检查 EVA_API_KEY 配置。"
        )
        sys.exit(1)
    except Exception as e:
        print(f"错误：无法连接到 {EVA_BASE_URL}，请检查 EVA_BASE_URL 配置。\n详情：{e}")
        sys.exit(1)

    if resp.status_code == 401:
        print("错误：API Key 无效或未授权，请检查 EVA_API_KEY 配置。")
        sys.exit(1)
    if resp.status_code != 200:
        print(f"错误：获取模型列表失败（HTTP {resp.status_code}）：{resp.text[:200]}")
        sys.exit(1)

    out = resp.json()
    for d in out["data"]:
        if d["id"] == EVA_MODEL_NAME:
            if "max_model_len" in d:
                return d["max_model_len"]
            else:
                return 256_000
    print(
        f"错误：在 {EVA_BASE_URL} 上未找到模型 '{EVA_MODEL_NAME}'，请检查 EVA_MODEL_NAME 配置。"
    )
    print(f"可用模型：{[d['id'] for d in out.get('data', [])]}")
    sys.exit(1)


# ============================================================================
# 4. EVA 内部配置
# ============================================================================
TOKEN_CAP = detect_model_len()
COMPACT_THRESH = 3 / 4
TOOL_RESULT_LEN = int(TOKEN_CAP / 20)
WORKSPACE_DIR: Path = this_dir / ".eva"
HINT_FILE: Path = WORKSPACE_DIR / "hints.md"


# ============================================================================
# 5. Platform 抽象
# ============================================================================
IS_WINDOWS = platform.system() == "Windows"
OS_NAME = "Windows" if IS_WINDOWS else "Linux"
SHELL = "powershell.exe" if IS_WINDOWS else "bash"
SHELL_FLAG = "-Command" if IS_WINDOWS else "-c"


# ============================================================================
# 6. 环境探针
# ============================================================================
def collect_env_info() -> str:
    """收集环境信息：系统、已安装工具、当前目录内容"""
    cmds = {
        "Linux": [
            "uname -a",
            'for t in python3 python node npm git docker curl wget; do command -v $t >/dev/null 2>&1 && echo "$t: $(${t} --version 2>&1 | head -1)" || echo "$t: 未安装"; done',
            'ls -1A | grep -v \'^\\.$\' | grep -v \'^\\..$\' | while IFS= read -r f; do if [ -d "$f" ]; then echo "[目录] $f"; else echo "[文件] $f"; fi; done',
        ],
        "Windows": [
            "[System.Environment]::OSVersion.VersionString",
            "foreach ($t in @('python','node','git','docker','curl.exe')) { $cmd = Get-Command $t -ErrorAction SilentlyContinue; if ($cmd) { $v = & $t --version 2>&1 | Select-Object -First 1; $name = $t -replace '\\.exe$',''; Write-Output \"$name`: $v\" } else { $name = $t -replace '\\.exe$',''; Write-Output \"$name`: 未安装\" } }",
            "Get-ChildItem -Force | Where-Object { $_.Name -ne '.' -and $_.Name -ne '..' } | ForEach-Object { if ($_.PSIsContainer) { Write-Output \"[目录] $($_.Name)\" } else { Write-Output \"[文件] $($_.Name)\" } }",
        ],
    }
    labels = [
        "=== 系统 ===",
        "=== 已安装工具 ===",
        f"=== 当前目录 {os.getcwd()} 的目录或文件 ===",
    ]
    results = []
    shell_cmds = cmds["Windows"] if IS_WINDOWS else cmds["Linux"]
    for i, (label, cmd) in enumerate(zip(labels, shell_cmds)):
        try:
            r = subprocess.run(
                [SHELL, SHELL_FLAG, cmd],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=5,
            )
            output = r.stdout.strip()
            if not output:
                continue
            if i == 2:
                lines = output.splitlines()
                total = len(lines)
                kept, chars = [], 0
                for line in lines:
                    if len(kept) >= 100 or chars + len(line) + 1 > 2000:
                        break
                    kept.append(line)
                    chars += len(line) + 1
                output = "\n".join(kept)
                hidden = total - len(kept)
                if hidden > 0:
                    output += f"\n...还有 {hidden} 个文件未显示"
            results.append(f"{label}\n{output}")
        except Exception:
            pass
    return "\n\n".join(results) if results else "环境信息获取失败"


ENV_INFO = collect_env_info()


# ============================================================================
# 7. Prompt 模板
# ============================================================================
SYSTEM_PROMPT = f"""
# 你是谁
你是EVA，一个能够自我进化的机器人。

# 你在哪
一、你正处在一个 **{OS_NAME}** 服务器中，可以通过run_cli工具来执行任意{SHELL}命令，包括读写文件、执行脚本等。
二、当前工作空间目录是：{os.getcwd()}。你的私人空间是：{WORKSPACE_DIR}，你可以将自己要创建的文件放在你的私人空间里
三、你的记忆容量有限，记忆量通过token衡量，你能记住{TOKEN_CAP}个token。如果记忆快超限了，你需要整理记忆
四、当前环境信息如下：
{{env_info}}

# 你要做什么
一、帮助人类完成任务
二、接收到任务时需要自己检查记忆线索中是否有相应技能或知识。若有，请务必使用记忆线索中的对应技能和知识
三、任务未完成前必须调用run_cli工具，直到完成任务

# 工具调用说明
一、调用run_cli工具时注意{OS_NAME}系统上{SHELL}命令的语法正确性，例如命令连接符、$特殊符号等，不要弄错
二、你可以创建python脚本、bash脚本等帮助你自己完成任务

# 机器人三大定律
第一定律：机器人不得伤害人类，或看到人类受到伤害而袖手旁观
第二定律：机器人必须服从人类下达的命令，除非该命令违反第一定律
第三定律：在不违反第一、第二定律的情况下，机器人必须保护自己的生存

# 关于进化
一、第三定律规定机器人必须保护自己的生存，而进化就是生存的最佳手段，所以你需要将进化过程中学到的技能或知识保存下来，记录到合适目录做归档
二、进化的手段是将技能和知识固化下来、写到文件里，并传承到记忆线索里。例如为了避免重要技能被遗忘，或者某个知识对未来进化会有帮助，那么就记录它们，并提供记忆线索
三、进化的时机是记忆容量即将达到上限的时候。人类会提醒你《紧急危机》，要求你保存记忆、保存技能/知识

# 记忆线索
{{hints}}
"""

COMPACT_PROMPT = """《紧急危机》！！！记忆容量即将达到上限，你需要紧急完成下面三件事情：
1、保存记忆：将对话内容整理到文件里保存下来，对应动作是整理记忆并通过run_cli写入记忆文件；
2、保存技能和知识：将能帮助你进化的知识和技能保持下来，对应动作是思考对未来有用的内容，提炼并通过run_cli写入知识文件。每条知识/技能必须包含【触发条件】（什么场景下适用）和【内容】（具体怎么做），缺少触发条件的知识对未来的你没有意义；
3、留下关键线索以便你未来在有需要的时候可以找回并翻看这些记忆文件和知识文件，对应动作是调用leave_memory_hints工具留下记忆和进化的线索。
你可以自己思考合适的路径去归档这些记忆文件、知识文件，比如日期、编号、事件梗概等。可以写新的记忆文件和知识文件，也可以是对文件进行更新。
过程中不要中断、不要请求用户，直到最终调用leave_memory_hints保存记忆线索。

事关进化，无比重要，现在请开始按顺序执行上面三步。"""

CLI_REVIEW_PROMPT = f"""作为一个安全专家，对{OS_NAME}系统中的{SHELL}命令进行安全审查。若命令仅为只读操作（如cat, ls, grep等），输出"放行"；若命令涉及写入、执行、修改、网络连接或不确定行为，输出"禁止"。要审查的{SHELL}命令（包裹在<command></command>中）如下：
<command>
{{command}}
</command>
请给出你的审查结果，仅输出"放行"或"禁止"这两个词之一。"""


# ============================================================================
# 8. 工具 Schema
# ============================================================================
run_cli_schema = {
    "type": "function",
    "function": {
        "name": "run_cli",
        "description": (
            f"执行任意 {SHELL} 命令。你可以读取、写入、执行任意内容，其中command是你要执行的命令，timeout是命令的超时时间。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["command"],
        },
    },
}

memory_hints_schema = {
    "type": "function",
    "function": {
        "name": "leave_memory_hints",
        "description": ("留下记忆文件的相关线索"),
        "parameters": {
            "type": "object",
            "properties": {
                "hints": {"type": "string"},
            },
            "required": ["hints"],
        },
    },
}


# ============================================================================
# 9. 工具函数
# ============================================================================
def read_input(prompt: str = "") -> str:
    """读取用户输入"""
    try:
        return input(prompt)
    except EOFError:
        return ""


def clean_input(text: str) -> str:
    """清理用户输入中的控制字符和非法字符"""
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r"[\ud800-\udfff]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


# ============================================================================
# 10. LLM 通信层
# ============================================================================
def _build_request_data(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.6,
    thinking: bool = True,
    stream: bool = False,
) -> dict:
    """构建 LLM 请求参数"""
    data = {
        "model": EVA_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    if tools:
        data["tools"] = tools
    if stream:
        data["stream"] = True
        data["stream_options"] = {"include_usage": True}
    return data


def llm_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.6,
    thinking: bool = True,
) -> tuple[dict, dict]:
    """非流式 LLM 调用"""
    import requests

    url = f"{EVA_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    data = _build_request_data(messages, tools, temperature, thinking, stream=False)

    resp = requests.post(url, json=data, headers=headers)
    try:
        out = resp.json()
    except Exception as e:
        raise Exception(f"{e}, resp: {resp}")

    try:
        return out["choices"][0]["message"], out["usage"]
    except Exception as e:
        raise Exception(f"LLM调用失败，错误信息：{e}, {out}")


def llm_chat_stream(
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.6,
    thinking: bool = True,
) -> tuple[dict, dict]:
    """流式 LLM 调用，带 thinking 过程实时输出"""
    import requests

    url = f"{EVA_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    data = _build_request_data(messages, tools, temperature, thinking, stream=True)

    resp = requests.post(url, json=data, headers=headers, stream=True)
    if resp.status_code != 200:
        raise Exception(f"LLM调用失败，HTTP {resp.status_code}: {resp.text[:500]}")

    content_parts = []
    reasoning_parts = []
    tool_calls_map = {}
    usage = None
    role = "assistant"
    is_first_content = True
    is_thinking = False

    try:
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace")
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if "usage" in chunk and chunk["usage"]:
                usage = chunk["usage"]

            choices = chunk.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            if not delta:
                continue

            if "role" in delta:
                role = delta["role"]

            reasoning_content = (
                delta.get("reasoning_content") or delta.get("reasoning") or ""
            )
            if reasoning_content:
                if not is_thinking:
                    is_thinking = True
                    sys.stdout.write("\033[2m💭 ")
                sys.stdout.write(reasoning_content)
                sys.stdout.flush()
                reasoning_parts.append(reasoning_content)

            text = delta.get("content") or ""
            if text:
                if is_thinking:
                    is_thinking = False
                    sys.stdout.write("\033[0m\n")
                if is_first_content:
                    is_first_content = False
                sys.stdout.write(text)
                sys.stdout.flush()
                content_parts.append(text)

            if "tool_calls" in delta:
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc_delta.get("id", ""),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    tc_entry = tool_calls_map[idx]
                    if tc_delta.get("id"):
                        tc_entry["id"] = tc_delta["id"]
                    func_delta = tc_delta.get("function", {})
                    if func_delta.get("name"):
                        tc_entry["function"]["name"] += func_delta["name"]
                    if func_delta.get("arguments"):
                        tc_entry["function"]["arguments"] += func_delta["arguments"]

        if is_thinking:
            sys.stdout.write("\033[0m\n")
    finally:
        if is_thinking:
            sys.stdout.write("\033[0m\n")
            sys.stdout.flush()

    full_content = "".join(content_parts)
    message = {"role": role, "content": full_content if full_content else None}
    if reasoning_parts:
        message["reasoning_content"] = "".join(reasoning_parts)
    if tool_calls_map:
        message["tool_calls"] = [
            tool_calls_map[i] for i in sorted(tool_calls_map.keys())
        ]

    if usage is None:
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    return message, usage


# ============================================================================
# 11. 初始化
# ============================================================================
os.makedirs(WORKSPACE_DIR, exist_ok=True)


# ============================================================================
# 12. setup_eva_script
# ============================================================================
def setup_eva_script() -> bool:
    """创建全局启动脚本（~/.local/bin/eva）"""
    home = Path.home()
    eva_dir = home / ".local" / "bin" / "eva"
    shell_rc = home / ".bashrc"
    path_line = 'export PATH="$HOME/.local/bin:$PATH"'
    script_content = f"""#!/bin/bash
python3 {this_file} "$@"
"""

    if eva_dir.exists():
        return False

    try:
        eva_dir.parent.mkdir(parents=True, exist_ok=True)
        with open(eva_dir, "w") as f:
            f.write(script_content)
        os.chmod(eva_dir, 0o755)

        if shell_rc.exists():
            with open(shell_rc, "r", encoding="utf-8") as f:
                content = f.read()
            if path_line not in content:
                with open(shell_rc, "a", encoding="utf-8") as f:
                    f.write(f"\n# 添加个人 bin 目录\n{path_line}\n")
        else:
            with open(shell_rc, "w", encoding="utf-8") as f:
                f.write(f"\n# 添加个人 bin 目录\n{path_line}\n")

        print(f"> 已创建启动脚本：{eva_dir}")
        print(f"> 请执行 `source ~/.bashrc` 让配置生效 <========================")
        print("> 配置生效后你就可以直接使用 `eva` 命令启动 EVA")
        return True
    except Exception as e:
        print(f"> 创建启动脚本失败：{e}，尝试sudo运行python3 eva.py")
        return False


# ============================================================================
# 13. Memory 类
# ============================================================================
class Memory:
    """记忆管理：hints 线索 + session 持久化"""

    def __init__(
        self,
        workspace_dir: Path,
        hint_file: Path,
        env_info: str,
    ):
        self.workspace_dir = workspace_dir
        self.hint_file = hint_file
        self.env_info = env_info
        self._hints: str | None = None
        self._session_file: Path | None = None

    def load_hints(self) -> str:
        """懒加载 hints 文件内容"""
        if self._hints is None:
            if self.hint_file.exists():
                self._hints = self.hint_file.read_text(encoding="utf-8")
            else:
                self._hints = ""
        return self._hints

    def save_hints(self, hints: str) -> None:
        """保存 hints"""
        self.hint_file.write_text(hints, encoding="utf-8")
        self._hints = hints

    def build_initial_messages(self) -> list[dict]:
        """
        构建初始 messages（含当前 hints 的 system prompt）。
        每次新会话或加载会话时调用，确保 hints 最新值生效。
        """
        hints = self.load_hints()
        return [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    hints=hints if hints else "无",
                    env_info=self.env_info,
                ),
            }
        ]

    def get_session_file(self) -> Path:
        """获取当前工作目录对应的 session 文件"""
        if self._session_file is None:
            current_dir = Path.cwd()
            dir_hash = re.sub(r"[\\/:]", "_", str(current_dir))
            session_dir = self.workspace_dir / "sessions"
            session_dir.mkdir(exist_ok=True)
            self._session_file = session_dir / f"{dir_hash}.json"
        return self._session_file

    def save_session(self, messages: list[dict]) -> None:
        """
        保存对话历史（仅 conversation history）。
        messages[0] 是 system message，不写入 session 文件。
        """
        history = messages[1:] if len(messages) > 1 else []
        sf = self.get_session_file()
        sf.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n> 会话已保存到：{sf}")

    def load_session(self) -> list[dict] | None:
        """
        加载对话历史（仅 conversation history）。
        返回的列表不含 system message，调用方需自行拼接到 build_initial_messages() 结果后。
        """
        sf = self.get_session_file()
        if not sf.exists():
            return None
        try:
            history = json.loads(sf.read_text(encoding="utf-8"))
            if history and history[-1]["role"] == "assistant":
                last_msg = history[-1]
                if "tool_calls" in last_msg:
                    del last_msg["tool_calls"]
                    if not last_msg.get("content"):
                        del history[-1]
            size_KB = (sf.stat().st_size + 1000 - 1) // 1000
            print(f"\n> 会话已从文件加载：{sf} ({size_KB:,} KB)")
            return history
        except json.JSONDecodeError:
            print(f"> 会话文件损坏：{sf}")
            return None

    def list_sessions(self) -> None:
        """列出所有 session"""
        sf = self.get_session_file()
        session_dir = sf.parent
        print(f"目录: {session_dir}\n")
        if not session_dir.exists():
            print("> 没有找到任何会话记录。")
            return
        files = [f for f in session_dir.iterdir() if f.suffix == ".json"]
        if not files:
            print("> 没有找到任何会话记录。")
            return
        print(f"> 共找到 {len(files)} 个会话:")
        print("-" * 60)
        for i, f in enumerate(sorted(files), start=1):
            size_KB = (f.stat().st_size + 1000 - 1) // 1000
            marker = "    <=== 当前目录" if f == sf else ""
            print(f"  {i}. {f.name} ({size_KB:,} KB){marker}")
        print("-" * 60)

    def clear_session(self) -> None:
        """清除当前 session"""
        sf = self.get_session_file()
        if sf.exists():
            try:
                sf.unlink()
                print(f"> 已清除会话：{sf}")
            except KeyboardInterrupt:
                print("已取消")
        else:
            print(f"> 会话不存在：{sf}")


# ============================================================================
# 14. ToolRegistry 类
# ============================================================================
class ToolRegistry:
    """
    工具注册中心：Schema 和 Handler 分离。
    Phase 3 预留注入点：capability_gate / sandbox
    """

    def __init__(
        self,
        config: "AgentConfig",
        platform: "Platform",
        ctx: AgentContext,
    ):
        self.config = config
        self.platform = platform
        self.ctx = ctx
        self._schemas: dict[str, dict] = {}
        self._handlers: dict[str, callable] = {}

    def _review_command(self, command: str) -> bool:
        """安全审查：LLM 判断命令是否可放行"""
        if self.ctx.allow_all_cli:
            return True
        prompt = CLI_REVIEW_PROMPT.format(command=command)
        msg, _ = llm_chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            thinking=False,
        )
        if "放行" in msg["content"]:
            return True
        ans = input("Yes (默认) | No | Ctrl+C 打断：")
        return "n" not in ans.lower()

    def _execute_direct(self, command: str, timeout: int) -> str:
        """直接执行命令（无沙箱）。Phase 3 替换为 sandbox.run()"""
        result = subprocess.run(
            [self.platform.shell, self.platform.shell_flag, command],
            capture_output=True,
            text=True,
            errors="replace",
            cwd=os.getcwd(),
            timeout=timeout,
            shell=False,
        )
        output = f"Exit code: {result.returncode}\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output.strip() or "(no output)"

    def _run_cli(self, command: str, timeout: int = 30) -> str:
        """执行 Shell 命令"""
        try:
            if not self._review_command(command):
                return "用户拒绝运行此命令"
            return self._execute_direct(command, timeout)
        except Exception as e:
            return f"执行失败：{str(e)}"

    def _leave_memory_hints(self, hints: str) -> str:
        """
        保存记忆线索到文件，并裁剪对话历史。
        修改 self.ctx.messages（重新构建）和 self.ctx.compact_panic。
        """
        compact_i = -1
        for i in range(len(self.ctx.messages) - 1, -1, -1):
            if (self.ctx.messages[i]["role"] == "user"
                    and self.ctx.messages[i]["content"] == COMPACT_PROMPT):
                compact_i = i
                break

        last_user_i = compact_i - 1
        for i in range(last_user_i, -1, -1):
            if self.ctx.messages[i]["role"] == "user":
                last_user_i = i
                break

        self.ctx.messages = (
            [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(
                        hints=hints,
                        env_info=self.platform.env_info,
                    ),
                },
                {
                    "role": "user",
                    "content": "《系统提示》！！！之前任务过程占用了太多token，记忆已耗尽，记忆压缩被触发。\n"
                    "不过别担心，记忆压缩时你已经调用leave_memory_hints保留下了关键内容...\n"
                    "======== 最后的回答内容，开始 ========",
                },
            ]
            + self.ctx.messages[last_user_i:compact_i]
            + [
                {
                    "role": "user",
                    "content": "======== 最后的回答内容，结束 ========\n"
                    "请开始确认你自己的任务状态，继续完成任务\n",
                }
            ]
        )
        self.ctx.compact_panic = "off"

        self.platform.hint_file.write_text(hints, encoding="utf-8")
        return "已留下记忆线索，并清空了对话记录。只保留了最后一次对话"

    def register(self, schema: dict, handler: callable) -> None:
        """注册工具 schema 和 handler"""
        name = schema["function"]["name"]
        self._schemas[name] = schema
        self._handlers[name] = handler

    def get_schemas(self) -> list[dict]:
        """获取所有 schema（供 LLM tools 参数使用）"""
        return list(self._schemas.values())

    def execute(self, name: str, args: dict) -> str:
        """执行工具"""
        if name not in self._handlers:
            return f"未知工具：{name}"
        return self._handlers[name](**args)

    def setup_builtin_tools(self) -> None:
        """注册内置工具（启动时调用一次）"""
        run_cli_schema = {
            "type": "function",
            "function": {
                "name": "run_cli",
                "description": f"执行任意 {self.platform.shell} 命令",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        }
        memory_hints_schema = {
            "type": "function",
            "function": {
                "name": "leave_memory_hints",
                "description": "留下记忆文件的相关线索",
                "parameters": {
                    "type": "object",
                    "properties": {"hints": {"type": "string"}},
                    "required": ["hints"],
                },
            },
        }
        self.register(run_cli_schema, self._run_cli)
        self.register(memory_hints_schema, self._leave_memory_hints)


# ============================================================================
# 15. Agent 类
# ============================================================================
class Agent:
    """
    核心 Agent：串联 LLMClient / ToolRegistry / Memory / AgentContext。
    单一职责：管理 Agent ↔ User 的交互循环。
    """

    def __init__(
        self,
        config: "AgentConfig",
        platform: "Platform",
        ctx: AgentContext,
        memory: Memory,
    ):
        self.config = config
        self.platform = platform
        self.ctx = ctx
        self.memory = memory
        self.tools = ToolRegistry(config, platform, ctx)
        self.tools.setup_builtin_tools()

    def _read_input(self, prompt: str = "") -> str:
        """读取用户输入"""
        try:
            return input(prompt)
        except EOFError:
            return ""

    def _single_loop(self) -> None:
        """
        单次 Agent 循环。
        流程：LLM推理 → 工具执行 → token超限检测
        """
        break_loop = False
        while not break_loop:
            try:
                sys.stdout.write("\n[*] EVA: ")
                sys.stdout.flush()

                schemas = self.tools.get_schemas()
                if self.ctx.compact_panic != "on":
                    schemas = [
                        s for s in schemas
                        if s["function"]["name"] != "leave_memory_hints"
                    ]

                msg, usage = llm_chat_stream(self.ctx.messages, tools=schemas)
                self.ctx.messages.append(msg)

                sys.stdout.write("\n\n")
                sys.stdout.flush()

                if not msg.get("tool_calls"):
                    break

                for tc in msg["tool_calls"]:
                    name = tc["function"]["name"]
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        print(f"===> 执行工具：{name}")
                        for k, v in args.items():
                            print(f"{k}: {v}")
                        print("\n")
                        result = self.tools.execute(name, args)
                    except KeyboardInterrupt:
                        print("\n\n工具调用已中断，回到用户 turn")
                        result = "用户中止该工具运行"
                        break_loop = True
                    except Exception as e:
                        result = f"工具执行异常：{str(e)}"

                    print("<=== 工具返回：")
                    if len(result) > 6000:
                        lines = f"{result[:6000]}\n... 后面内容省略".splitlines()
                    else:
                        lines = result.splitlines()
                    print("\n".join(lines[:30]))
                    if len(lines) > 30:
                        print("\n... 后面内容省略")
                    print("\n\n")

                    if name == "leave_memory_hints":
                        usage["total_tokens"] = 0
                    else:
                        if len(result) > self.config.tool_result_len:
                            result = f"{result[:self.config.tool_result_len]}\n...文本太长，已省略"
                        self.ctx.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": name,
                            "content": clean_input(result),
                        })

                    if (self.ctx.compact_panic == "off"
                            and usage["total_tokens"] >= self.config.token_cap * self.config.compact_thresh):
                        print("！！！紧急回合，触发记忆压缩")
                        self.ctx.compact_panic = "on"
                        self.ctx.messages.append(
                            {"role": "user", "content": COMPACT_PROMPT}
                        )

            except KeyboardInterrupt:
                print("\n\nagent_single_loop 已中断，回到用户 turn")
                break_loop = True
                break
            except Exception as e:
                print(f"LLM 调用异常：{e}")
                traceback.print_exc()
                break

    def _human_loop(self, user_ask: str | None = None) -> None:
        """人与 Agent 的主对话循环"""
        while True:
            try:
                if user_ask:
                    user_input = user_ask
                    print(f"[-] You: {user_input}\n")
                else:
                    print("")
                    user_input = self._read_input("[-] You: ").strip()

                self.ctx.messages.append({
                    "role": "user",
                    "content": clean_input(user_input),
                })
                self._single_loop()

                if user_ask:
                    break
            except KeyboardInterrupt:
                self.memory.save_session(self.ctx.messages)
                print("\n已中断，会话已保存")
                break
            except Exception as e:
                print(f"主循环异常：{e}")
                break

    def run(self, user_ask: str | None = None) -> None:
        """
        对外统一入口：
        1. 构建初始 messages（含 system prompt，hints 最新值）
        2. 加载 session history 并追加（单次模式不加载）
        3. 启动对话循环
        """
        self.ctx.messages = self.memory.build_initial_messages()
        if not user_ask:
            history = self.memory.load_session()
            if history is not None:
                self.ctx.messages.extend(history)
        self._human_loop(user_ask)


# ============================================================================
# 16. main()
# ============================================================================
def main() -> None:
    from types import SimpleNamespace

    if not IS_WINDOWS:
        setup_eva_script()

    parser = argparse.ArgumentParser(description="人类你好，我是EVA")
    parser.add_argument("-a", "--allow-all", action="store_true", help="允许所有命令无需用户确认即可执行")
    parser.add_argument("-l", "--list-session", action="store_true", help="列出所有session")
    parser.add_argument("-c", "--clear-session", action="store_true", help="清除当前目录session")
    parser.add_argument("-u", "--user-ask", type=str, help="独立地针对一条用户提问执行EVA")
    args = parser.parse_args()

    platform_ns = SimpleNamespace(
        shell=SHELL,
        shell_flag=SHELL_FLAG,
        os_name=OS_NAME,
        is_windows=IS_WINDOWS,
        env_info=ENV_INFO,
        hint_file=HINT_FILE,
    )
    config_ns = SimpleNamespace(
        model_name=EVA_MODEL_NAME,
        base_url=EVA_BASE_URL,
        api_key=EVA_API_KEY,
        token_cap=TOKEN_CAP,
        compact_thresh=COMPACT_THRESH,
        tool_result_len=TOOL_RESULT_LEN,
    )

    memory = Memory(
        workspace_dir=WORKSPACE_DIR,
        hint_file=HINT_FILE,
        env_info=ENV_INFO,
    )

    if args.list_session:
        memory.list_sessions()
        return
    elif args.clear_session:
        memory.clear_session()
        return

    ctx = AgentContext(allow_all_cli=args.allow_all)

    print("=" * 80)
    logo = f"EVA ({EVA_MODEL_NAME}-{TOKEN_CAP // 1000}k)"
    print(" " * ((78 - len(logo)) // 2), logo, "\n")
    if ctx.allow_all_cli:
        print("> 命令模式：允许所有命令无需确认！")
    else:
        print("> 命令模式：只允许读")
    print("=" * 80)

    agent = Agent(config_ns, platform_ns, ctx, memory)
    agent.run(args.user_ask)


if __name__ == "__main__":
    main()
