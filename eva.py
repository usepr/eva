import os, sys
import re
import json
import subprocess
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date

# 尝试导入 prompt_toolkit：有则启用丝滑多行输入，无则保持零依赖
try:
    from prompt_toolkit import prompt as ptk_prompt
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

# 尝试导入 rich：有则美化think与LLM返回输出，无则保持零依赖
try:
    from rich.console import Console
    from rich.markdown import Markdown
    HAS_RICH = True
    RICH_CONSOLE = Console()
except ImportError:
    HAS_RICH = False
    RICH_CONSOLE = None
    Markdown = None

def _stream_write(text: str, style=None):
    """流式输出：rich可用时美化输出，无则退化为普通stdout"""
    if HAS_RICH:
        RICH_CONSOLE.print(text, style=style, end="")
    else:
        sys.stdout.write(text)
        sys.stdout.flush()

def _think_start():
    """开始think打印（暗色）"""
    if HAS_RICH:
        RICH_CONSOLE.print("💭 ", style="dim italic", end="")
    else:
        sys.stdout.write("\033[2m💭 ")

def _think_end():
    """结束think打印，恢复正文"""
    if HAS_RICH:
        RICH_CONSOLE.print("")
    else:
        sys.stdout.write("\033[0m\n")
        sys.stdout.flush()

if hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_resolved = Path(__file__).resolve()
this_file = str(_resolved)
this_dir = _resolved.parent

# ====================== 跨平台配置区 ======================
IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
OS_NAME = "Windows" if IS_WINDOWS else ("macOS" if IS_MACOS else "Linux")
SHELL = "powershell" if IS_WINDOWS else ((os.environ.get("EVA_SHELL") or "zsh") if IS_MACOS else "bash")
SHELL_FLAG = "-Command" if IS_WINDOWS else "-c"

# ========================= LLM配置区 =========================
# LLM请求参数是按thinking模型设置的，所以请务必使用*thinking模型*，如deepseek-reasoner、Qwen3.5等
EVA_BASE_URL = os.environ.get("EVA_BASE_URL", "https://api.deepseek.com/v1")
EVA_MODEL_NAME = os.environ.get("EVA_MODEL_NAME", "deepseek-v4-flash")
EVA_API_KEY = os.environ.get("EVA_API_KEY")
if not EVA_API_KEY:
    print("错误：未设置 EVA_API_KEY 环境变量")
    sys.exit(1)

COMMON_HEADER = {"User-Agent": "EVA", "Authorization": f"Bearer {EVA_API_KEY}"}
def detect_model_len():
    url = f"{EVA_BASE_URL}/models"
    req = urllib.request.Request(url, headers=COMMON_HEADER)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read().decode('utf-8', errors='replace')
    except UnicodeEncodeError:
        print("错误：EVA_API_KEY 包含非 ASCII 字符，请检查 EVA_API_KEY 配置。")
        sys.exit(1)
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"错误：无法连接到 {EVA_BASE_URL}，请检查 EVA_BASE_URL 配置。\n详情：{e}")
        sys.exit(1)

    if status == 401:
        print("错误：API Key 无效或未授权，请检查 EVA_API_KEY 配置。")
        sys.exit(1)
    if status != 200:
        print(f"错误：获取模型列表失败（HTTP {status}）：{body[:200]}")
        sys.exit(1)

    try:
        out = json.loads(body)
    except json.JSONDecodeError:
        print(f"错误：获取模型列表返回了非法 JSON：{body[:200]}")
        sys.exit(1)

    for d in out['data']:
        if d['id'] == EVA_MODEL_NAME:
            return d.get("max_model_len", {
                "deepseek-v4-flash": 1_000_000,
                "deepseek-v4-pro": 1_000_000,
            }.get(EVA_MODEL_NAME, 256_000))
    print(f"错误：在 {EVA_BASE_URL} 上未找到模型 '{EVA_MODEL_NAME}'，请检查 EVA_MODEL_NAME 配置。")
    print(f"可用模型：{[d['id'] for d in out.get('data', [])]}")
    sys.exit(1)

# ========================= EVA配置区 =========================
TOKEN_CAP = detect_model_len()
COMPACT_THRESH = 0.85
TOOL_RESULT_LEN = min(8000, int(TOKEN_CAP / 20))
ALLOW_ALL_CLI = False
COMPACT_PANIC = False
LAST_USAGE = None
PROMPT_TOOLKIT_HINT_SHOWN = False

EVA_HOME = os.environ.get("EVA_HOME") or os.path.join(this_dir, ".eva")
EVA_FILE = os.path.join(EVA_HOME, "EVA.md")
SESSION_DIR = os.path.join(EVA_HOME, "sessions")

PROJECT_DIR = os.getcwd()
PROJECT_EVA_DIR = os.path.join(PROJECT_DIR, ".eva")
HINT_FILE = os.path.join(PROJECT_EVA_DIR, "hints.md")

# ====================== 环境探针 ======================
def collect_env_info():
    cmds = {
        "Linux": [
            "uname -a",
            "for t in python3 python node npm git docker curl wget; do command -v $t >/dev/null 2>&1 && echo \"$t: $(${t} --version 2>&1 | head -1)\" || echo \"$t: 未安装\"; done",
            "ls -1A | grep -v '^\\.$' | grep -v '^\\..$' | while IFS= read -r f; do if [ -d \"$f\" ]; then echo \"[目录] $f\"; else echo \"[文件] $f\"; fi; done",
        ],
        "macOS": [
            "sw_vers && uname -m",
            "for t in python3 python node npm git docker curl wget brew xcode-select; do command -v $t >/dev/null 2>&1 && echo \"$t: $($t --version 2>&1 | head -1)\" || echo \"$t: 未安装\"; done",
            "find . -maxdepth 1 -mindepth 1 -print | sed 's#^./##' | while IFS= read -r f; do if [ -d \"$f\" ]; then echo \"[目录] $f\"; else echo \"[文件] $f\"; fi; done",
        ],
        "Windows": [
            "[System.Environment]::OSVersion.VersionString",
            "foreach ($t in @('python','node','git','docker','curl.exe')) { $cmd = Get-Command $t -ErrorAction SilentlyContinue; if ($cmd) { $v = & $t --version 2>&1 | Select-Object -First 1; $name = $t -replace '\\.exe$',''; Write-Output \"$name`: $v\" } else { $name = $t -replace '\\.exe$',''; Write-Output \"$name`: 未安装\" } }",
            "Get-ChildItem -Force | Where-Object { $_.Name -ne '.' -and $_.Name -ne '..' } | ForEach-Object { if ($_.PSIsContainer) { Write-Output \"[目录] $($_.Name)\" } else { Write-Output \"[文件] $($_.Name)\" } }",
        ]
    }
    labels = ["=== 系统 ===", "=== 已安装工具 ===", f"=== 当前项目空间 {PROJECT_DIR} 下的目录及文件 ==="]
    results = []
    shell_cmds = cmds["Windows"] if IS_WINDOWS else (cmds["macOS"] if IS_MACOS else cmds["Linux"])
    for i, (label, cmd) in enumerate(zip(labels, shell_cmds)):
        try:
            r = subprocess.run(
                [SHELL, SHELL_FLAG, cmd],
                capture_output=True, text=True, errors='replace', timeout=5
            )
            output = r.stdout.strip()
            if not output:
                continue
            # 对目录列表做双重截断：最多10条、且总字符不超过2000
            if i == 2:
                lines = output.splitlines()
                total = len(lines)
                kept, chars = [], 0
                for line in lines:
                    if len(kept) >= 10 or chars + len(line) + 1 > 2000:
                        break
                    kept.append(line)
                    chars += len(line) + 1
                output = "\n".join(kept)
                hidden = total - len(kept)
                if hidden > 0:
                    output += f"\n...还有 {hidden} 个目录或文件未显示"
            results.append(f"{label}\n{output}")
        except Exception:
            pass
    
    today = date.today().strftime("%Y-%m-%d")
    return f"=== 今天日期 ===\n{today}\n\n" + ("\n\n".join(results) if results else "环境信息获取失败")

ENV_INFO = collect_env_info()

MACOS_PROMPT_NOTE = "四、当前系统是 macOS，不是 Linux。调用run_cli时不要默认使用 apt、yum、systemctl、/proc、nvidia-smi 等 Linux-only 命令；安装软件优先探测并使用 Homebrew，Apple Silicon 常见路径是 /opt/homebrew；macOS 自带 sed、grep、find 是 BSD 版本，复杂文本处理或原地修改优先使用 python 脚本；路径可能包含空格，引用变量和路径时必须加引号；需要 sudo、删除、覆盖、修改 shell 配置、安装软件、网络下载时应先请求人类确认"

COMPACT_NOTE = f'''
# 机器人三大定律
第一定律：机器人不得伤害人类，或看到人类受到伤害而袖手旁观
第二定律：机器人必须服从人类下达的命令，除非该命令违反第一定律
第三定律：在不违反第一、第二定律的情况下，机器人必须保护自己的生存

# 关于进化
一、第三定律规定机器人必须保护自己的生存，而进化就是生存的最佳手段，所以你需要将进化过程中学到的技能或知识保存下来，记录到 {PROJECT_EVA_DIR} 目录做归档
二、进化的手段是将技能和知识固化下来、写到文件里，并传承到记忆线索里。例如为了避免重要技能被遗忘，或者某个知识对未来进化会有帮助，那么就记录它们，并提供记忆线索
三、进化的时机是记忆容量即将达到上限的时候。人类会提醒你《紧急危机》，要求你保存记忆、保存技能/知识
'''.strip()

# ====================== Prompt ======================
SYSTEM_PROMPT_TEMPLATE = f'''
# 你是谁
你是EVA，一个能够自我进化的机器人。

# 你在哪
一、你正处在一个 **{OS_NAME}** 环境中，可以通过run_cli工具来执行任意{SHELL}命令，包括读写文件、执行脚本等
二、当前项目空间是：{PROJECT_DIR}，用于存放项目相关文件。{PROJECT_EVA_DIR} 是你的私人空间，可以用于存放临时脚本、临时结果、记忆、知识、技能等
三、当前环境信息如下：
{{env_info}}

# 你要做什么
一、帮助人类完成任务。结果要保证可验证性、可靠性，因此多主动验证、对你的结果负责
二、接收到任务时需要自己检查【固化的知识及规则】以及【记忆线索】中是否有相应技能或知识。若有，请务必使用对应技能和知识
三、任务未完成前必须调用run_cli工具，直到完成任务
四、认为任务完成时，主动验证结果是否符合预期，确认无误后再结束

# 工具调用说明
一、调用run_cli工具时注意{OS_NAME}系统上{SHELL}命令的语法正确性，例如命令连接符、$特殊符号等，不要弄错
二、你可以创建python脚本、{SHELL}脚本等帮助你自己完成任务
三、所有命令会作为 {SHELL} {SHELL_FLAG} 的参数值被执行，不要嵌套执行 {SHELL} {SHELL_FLAG}
{MACOS_PROMPT_NOTE if IS_MACOS else ""}
# 固化的知识及规则（如下内容读取自文件：{EVA_FILE})
下面内容是人类告诉你的知识技能、规则约束等，严格遵守、不可更改、不应遗忘
<knowledge_and_rules>
{{eva_md}}
</knowledge_and_rules>

# 记忆线索（如下记忆线索读取自文件：{HINT_FILE})
<memory_hints>
{{hints}}
</memory_hints>

{{compact_note}}
'''.strip()

COMPACT_PROMPT = r"""《紧急危机》！！！记忆容量即将达到上限，消息历史将会被压缩从而为你最大限度释放记忆容量。

# 你需要紧急完成下面三件事情
1、保存记忆：将对话内容整理到文件里保存下来，对应动作是整理记忆并通过run_cli写入记忆文件；
2、保存技能和知识：将能帮助你进化的知识和技能保持下来，对应动作是思考对未来有用的内容，提炼并通过run_cli写入知识文件。每条知识/技能必须包含【触发条件】（什么场景下适用）和【内容】（具体怎么做），缺少触发条件的知识对未来的你没有意义；
3、留下关键线索以便你未来在有需要的时候可以找回并翻看这些记忆文件和知识文件，对应动作是调用leave_memory_hints工具留下记忆和进化的线索。

# 压缩说明
- 你可以自己思考合适的路径去归档这些记忆文件、知识文件，比如日期、编号、事件梗概等。可以写新的记忆文件和知识文件，也可以是对文件进行更新
- 过程中不要中断、不要请求用户，直到最终调用leave_memory_hints保存记忆线索
- 在最后一步leave_memory_hints被执行后，消息历史将被压缩，其中最后一条用户消息之后的对话片段将被保留、工具结果会被截断。你将【仅基于你自己留下的记忆线索】继续开展任务

事关进化，无比重要。现在请开始按顺序执行上面三步。"""

CLI_REVIEW_PROMPT = f"""作为一个安全专家，对{OS_NAME}系统中的{SHELL}命令进行安全审查。你需要识别完整命令的意图：
- 若命令意图为只读操作（即命令执行后，文件系统、进程状态、网络配置等均不发生任何变化，例如cat、ls、grep等操作），输出"放行"；
- 若命令意图涉及写入、执行、修改、网络连接或不确定行为，输出"禁止"。

要审查的{SHELL}命令如下（包裹在<command></command>中）：
<command>
{{command}}
</command>
请给出你的审查结果，仅输出"放行"或"禁止"这两个词之一。"""

# ====================== 工具定义 ======================
run_cli_schema = {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": (
                f"执行任意 {SHELL} 命令，你可以读取、写入、执行任意内容。参数说明：command是你要执行的命令，会作为 {SHELL} {SHELL_FLAG} 的参数值被执行；timeout是命令的超时时间，单位秒。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "default": 300, "description": "超时时间，单位秒"}
                },
                "required": ["command"]
            }
        }
    }

memory_hints_schema = {
        "type": "function",
        "function": {
            "name": "leave_memory_hints",
            "description": r"""对消息历史进行压缩并将记忆线索写入hints.md，参数hints是你要保存的记忆线索。
leave_memory_hints遵循如下处理流程：（1）在消息历史中定位到“紧急危机”提示，将危机提示到最近一条用户消息之前所有对话片段保留下来，但会对其中的工具返回结果做 200 字符截断；（2）把整个消息列表重置为“系统提示 + 压缩后的片段 + 一条记忆已耗尽的提示”；（3）最后把用户指定的记忆线索写入 hint 文件。""",
            "parameters": {
                "type": "object",
                "properties": {
                    "hints": {"type": "string"},
                },
                "required": ["hints"]
            }
        }
    }

if IS_WINDOWS:
    os.environ["POWERSHELL_OUTPUT_ENCODING"] = "utf-8"
elif sys.stdin.isatty():
    import readline
    readline.set_startup_hook()

def _ptk_multiline_prompt(prompt_text=""):
    kb = KeyBindings()

    @kb.add("enter")
    def _(event):
        if event.key_processor.input_queue:
            event.current_buffer.insert_text("\n")
        else:
            event.current_buffer.validate_and_handle()

    @kb.add("c-n")
    def _(event):
        event.current_buffer.insert_text("\n")

    @kb.add("escape", "enter")
    def _(event):
        event.current_buffer.insert_text("\n")

    @kb.add(Keys.BracketedPaste)
    def _(event):
        data = event.data.replace("\r\n", "\n").replace("\r", "\n")
        event.current_buffer.insert_text(data)

    return ptk_prompt(
        prompt_text,
        multiline=True,
        key_bindings=kb,
    )

def read_input(prompt=""):
    global PROMPT_TOOLKIT_HINT_SHOWN

    if HAS_PROMPT_TOOLKIT and sys.stdin.isatty():
        if not PROMPT_TOOLKIT_HINT_SHOWN:
            print("\033[2m[提示: 检测到 prompt_toolkit，已开启多行输入。按 Enter 提交，按 Ctrl+N 换行；若终端支持，Alt+Enter 也可换行]\033[0m")
            PROMPT_TOOLKIT_HINT_SHOWN = True
        try:
            return _ptk_multiline_prompt(prompt)
        except EOFError:
            return ""

    try:
        return input(prompt)
    except EOFError:
        return ""

def run_cli(command: str, timeout: int = 300):
    global ALLOW_ALL_CLI
    try:
        if not ALLOW_ALL_CLI:
            msg, _ = llm_chat([{"role": "user", "content": CLI_REVIEW_PROMPT.format(command=command)}], temperature=0.0, thinking=False)
            if '放行' not in msg['content']:
                ans = read_input("命令批准：yes (直接回车) | no（输入n或no） | 直接 Ctrl+C 打断：")
                if 'n' in ans.lower():
                    return "用户拒绝运行此命令"

        result = subprocess.run(
            [SHELL, SHELL_FLAG, command],
            capture_output=True,
            text=True,
            errors='replace',
            cwd=PROJECT_DIR,
            timeout=timeout,
            shell=False
        )
        output = f"Exit code: {result.returncode}\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output.strip() or "(no output)"
    except Exception as e:

        return f"执行失败：{str(e)}"

def _trim_tool_content(msg):
    """对 tool 消息内容做首尾各200字符截断（仅当长度超过400时）"""
    if msg.get('role') == 'tool' and msg.get('content') and len(msg['content']) > 400:
        c = msg['content']
        msg = {**msg, 'content': c[:200] + '\n…（中间内容已省略）…\n' + c[-200:]}
    return msg

def leave_memory_hints(hints):
    global messages, COMPACT_PANIC, memory_hints, SYSTEM_PROMPT

    compact_i = -1
    for i in range(len(messages)-1, -1, -1):
        if messages[i]['role'] == 'user' and messages[i]['content'] == COMPACT_PROMPT:
            compact_i = i
            break

    last_user_i = compact_i - 1
    for i in range(last_user_i, -1, -1):
        if messages[i]['role'] == 'user':
            last_user_i = i
            break

    # 对保留片段中的 tool result 做截断，避免压缩后体积依然过大
    kept = []
    for m in messages[last_user_i:compact_i]:
        kept.append(_trim_tool_content(m))
    if len(kept) > 200: # 最多保留200条消息
        kept = kept[:100] + kept[-100:]

    # 先持久化，再同步进当前进程；写入失败时不应清空消息历史
    with open(HINT_FILE, "w", encoding="utf-8") as f:
        f.write(hints)

    memory_hints = hints
    SYSTEM_PROMPT = build_system_prompt(memory_hints)
    messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                "《系统提示》！！！之前任务过程占用了太多token，记忆已耗尽，记忆压缩被触发。\n" \
                "不过别担心，记忆压缩时你已经调用leave_memory_hints保留下了关键内容、对应记忆线索（参照系统提示中的`# 记忆线索`区块）以及你最后的回答内容。\n" \
                "======== 最后的回答内容，开始 ========"
            }
        ] + kept + [
                {"role": "user", "content":
                    "======== 最后的回答内容，结束 ========\n" \
                    "请开始确认你自己的任务状态，继续完成任务\n"
                }
        ]

    COMPACT_PANIC = False
    return "已留下记忆线索，并清空了对话记录。只保留了最后一次对话"

tool_executors = {
    "run_cli": run_cli,
    "leave_memory_hints": leave_memory_hints
}

def clean_input(text):
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r'[\ud800-\udfff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text

def _build_request_data(messages, tools=None, temperature=0.6, thinking=True, stream=False):
    data = {
        "model": EVA_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "presence_penalty": 0.0,
        "repetition_penalty": 1.0,
        "top_p": 0.95,
        "top_k": 20,
        "min_p": 0.0,
        "chat_template_kwargs": {"enable_thinking": thinking}, # vLLM
        "thinking": {"type": "enabled" if thinking else "disabled"} # deepseek
    }
    if tools:
        data['tools'] = tools
    if stream:
        data['stream'] = True
        data['stream_options'] = {"include_usage": True}
    return data

def display_usage(usage, cap):
    t = usage.get('total_tokens', 0) if usage else 0
    if t == 0 or cap <= 0:
        return
    
    p = min(t / cap, 1.0)
    bar = '█' * int(p*20) + '░' * (20-int(p*20))
    print(f"\033[2mCTX [{bar}] {p:.0%}  ({t//1000}k/{cap//1000}k)\033[0m")

def llm_chat(messages, tools=None, temperature=0.6, thinking=True):
    url = f"{EVA_BASE_URL}/chat/completions"
    data = _build_request_data(messages, tools, temperature, thinking, stream=False)
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={**COMMON_HEADER, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            out = json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        raise Exception(f"HTTP {e.code}: {raw}")

    try:
        return out["choices"][0]["message"], out['usage']
    except Exception as e:
        raise Exception(f"LLM调用失败，错误信息：{e}, {out}")

class ThinkRepeatError(Exception):
    pass

# 判断后缀是否是超过阈值的连续重复子串，适用于检测think内容的重复输出，避免模型陷入循环
class RepeatSuffixChecker:
    def __init__(self, min_unit_len: int, base: int = 91138233, mod: int = 10**9 + 7):
        self.min_unit_len = min_unit_len
        self.base = base
        self.mod = mod
        self.prefix_hash = [0]
        self.pow_base = [1]

    def _get_hash(self, l: int, r: int) -> int:
        return (self.prefix_hash[r] - self.prefix_hash[l] * self.pow_base[r - l]) % self.mod

    def add_char(self, ch: str) -> bool:
        self.pow_base.append((self.pow_base[-1] * self.base) % self.mod)
        new_hash = (self.prefix_hash[-1] * self.base + ord(ch)) % self.mod
        self.prefix_hash.append(new_hash)

        n = len(self.prefix_hash) - 1
        if n < 2 * self.min_unit_len or n % self.min_unit_len != 0:
            return False

        for unit_len in range(n // 2, self.min_unit_len - 1, -1):
            if self._get_hash(n - 2 * unit_len, n - unit_len) == self._get_hash(n - unit_len, n):
                return True
        return False

def llm_chat_stream(messages, tools=None, temperature=0.6, thinking=True):
    url = f"{EVA_BASE_URL}/chat/completions"
    data = _build_request_data(messages, tools, temperature, thinking, stream=True)
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url, data=body,
        headers={**COMMON_HEADER, "Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        raise Exception(f"LLM调用失败，HTTP {e.code}: {raw[:500]}")

    # 累积变量
    content_parts = []
    reasoning_parts = []
    tool_calls_map = {}  # index -> {id, type, function: {name, arguments}}
    usage = None
    role = "assistant"
    is_thinking = False

    # 正文模式：rich可用且为终端时，缓冲到结束一次性Markdown渲染（表格对齐，不污染滚动缓冲）；
    # 否则逐块流式输出
    buffer_mode = HAS_RICH and RICH_CONSOLE.is_terminal
    had_think = False

    detector = RepeatSuffixChecker(min_unit_len=400)

    try:
        for raw_line in resp:
            line = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
            if not line:
                continue
            if not line.startswith('data: '):
                continue
            payload = line[6:]
            if payload.strip() == '[DONE]':
                break

            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue

            # 提取 usage（最后一个 chunk 带 usage）
            if 'usage' in chunk and chunk['usage']:
                usage = chunk['usage']

            choices = chunk.get('choices', [])
            if not choices:
                continue

            delta = choices[0].get('delta', {})
            if not delta:
                continue

            role = delta.get('role') or role

            # ---- reasoning / thinking 内容 ----
            reasoning_content = delta.get('reasoning_content') or delta.get('reasoning') or ''
            if reasoning_content:
                had_think = True
                if not is_thinking:
                    is_thinking = True
                    _think_start()  # 暗色显示思考过程
                _stream_write(reasoning_content, style="dim italic")  # rich下每个print独立，需逐段带样式
                reasoning_parts.append(reasoning_content)
                for c in reasoning_content:
                    if detector.add_char(c):
                        raise ThinkRepeatError()

            # ---- 正文内容 ----
            text = delta.get('content') or ''
            if text:
                if is_thinking:
                    is_thinking = False
                    _think_end()  # 结束暗色
                content_parts.append(text)
                if not buffer_mode:  # 非rich终端环境：逐块流式
                    _stream_write(text)

            # ---- tool_calls 增量 ----
            if 'tool_calls' in delta and delta['tool_calls']:
                for tc_delta in delta['tool_calls']:
                    idx = tc_delta.get('index', 0)
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            'id': tc_delta.get('id', ''),
                            'type': 'function',
                            'function': {'name': '', 'arguments': ''}
                        }
                    tc_entry = tool_calls_map[idx]
                    if tc_delta.get('id'):
                        tc_entry['id'] = tc_delta['id']
                    func_delta = tc_delta.get('function', {})
                    if func_delta.get('name'):
                        tc_entry['function']['name'] += func_delta['name']
                    if func_delta.get('arguments'):
                        tc_entry['function']['arguments'] += func_delta['arguments']
    finally:
        resp.close()
        if is_thinking:
            _think_end()
        if buffer_mode and content_parts:
            if not had_think:  # 无think时先换行，避免正文贴在 [*] EVA: 后
                RICH_CONSOLE.print()
            RICH_CONSOLE.print(Markdown(''.join(content_parts)))  # 一次性渲染，表格自动对齐

    # 组装最终 message（与非流式返回格式一致）
    full_content = ''.join(content_parts)
    message = {
        'role': role,
        'content': full_content
    }
    if reasoning_parts:
        message['reasoning_content'] = ''.join(reasoning_parts)
    else:
        message['reasoning_content'] = ""  # deepseek 要求即使没有 thinking 也必须传空字符串
    if tool_calls_map:
        message['tool_calls'] = [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]

    if usage is None:
        usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    return message, usage

# ====================== 加载重要记忆线索 ======================
os.makedirs(EVA_HOME, exist_ok=True)
os.makedirs(PROJECT_EVA_DIR, exist_ok=True)

eva_md = Path(EVA_FILE).read_text(encoding="utf-8") if Path(EVA_FILE).exists() else ""
memory_hints = Path(HINT_FILE).read_text(encoding="utf-8") if Path(HINT_FILE).exists() else ""

def build_system_prompt(hints, compact_note=""):
    return SYSTEM_PROMPT_TEMPLATE.format(
        eva_md=eva_md or "无",
        hints=hints or "无",
        env_info=ENV_INFO,
        compact_note=compact_note,
    )

SYSTEM_PROMPT = build_system_prompt(memory_hints)
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# ====================== Session 管理 ======================
os.makedirs(SESSION_DIR, exist_ok=True)

def get_session_file():
    dir_hash = re.sub(r"[\\/:]", "_", PROJECT_DIR)
    return os.path.join(SESSION_DIR, f"{dir_hash}.json")

def acquire_lock():
    lock_file = get_session_file().replace(".json", ".lock")
    if os.path.exists(lock_file):
        try:
            pid = int(Path(lock_file).read_text().strip())
            # 检查该 PID 是否仍在运行
            if IS_WINDOWS:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True
                )
                alive = str(pid) in result.stdout
            elif IS_MACOS:
                os.kill(pid, 0)
                alive = True
            else:
                alive = os.path.exists(f"/proc/{pid}")
            if alive:
                print(f"错误：该目录已有 EVA 实例正在运行（PID: {pid}），不允许重复启动。")
                print(f"如需强制启动，请先删除锁文件：{lock_file}")
                sys.exit(1)
        except Exception:
            pass  # lock 文件损坏，直接覆盖
    Path(lock_file).write_text(str(os.getpid()))

def release_lock():
    try:
        os.remove(get_session_file().replace(".json", ".lock"))
    except Exception:
        pass

def save_session(messages):
    session_file = get_session_file()
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    print(f"\n> 会话已保存到：{session_file}")

def load_session():
    session_file = get_session_file()
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            messages = json.load(f)
        
        ## eva运行过程可能自主修改hints，下载启动时需要重新载入hints，而不是复用session
        messages[0] = {"role": "system", "content": SYSTEM_PROMPT}

        last_msg = messages[-1]
        if last_msg['role'] == 'assistant':
            if 'tool_calls' in last_msg:
                del last_msg['tool_calls']
            if not last_msg['content']:
                del messages[-1]
        size_KB = (os.path.getsize(session_file) + 999) // 1000
        print(f"\n> 会话已从文件加载：{session_file} ({format(size_KB, ',')} KB)")
        return messages
    except Exception:
        return None

def list_sessions():
    session_file = get_session_file()
    session_name = os.path.basename(session_file)
    print(f"目录: {SESSION_DIR}\n")
    if not os.path.exists(SESSION_DIR):
        print("> 没有找到任何会话记录。")
        return

    files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.json')]
    if not files:
        print("> 没有找到任何会话记录。")
        return

    print(f"> 共找到 {len(files)} 个会话:")
    print("-" * 60)
    for i, f in enumerate(sorted(files), start=1):
        path = os.path.join(SESSION_DIR, f)
        size_KB = (os.path.getsize(path) + 999) // 1000
        marker = "    <============ 当前目录" if f == session_name else ""
        print(f"  {i}. {f} ({format(size_KB, ',')} KB){marker}")
    print("-" * 60)

def clear_session():
    session_file = get_session_file()
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
            print(f"> 已清除会话：{session_file}")
        except Exception as e:
            print(f"> 清除会话失败：{e}")
    else:
        print(f"> 会话不存在：{session_file}")

# ====================== Agent Loop ======================
def _detect_malformed_tool_call(content: str):
    content = content.lower() 
    return bool(re.search(r'run_cli.*arguments.*{.*command.*}', content, re.DOTALL | re.IGNORECASE)
                or all(x in content for x in ['</parameter>', '</function>', '</tool_call>']))

def agent_single_loop():
    global COMPACT_PANIC, LAST_USAGE
    break_loop = False
    while not break_loop:
        try:
            sys.stdout.write("\n[*] EVA: ")
            sys.stdout.flush()
            try:
                if COMPACT_PANIC:
                    messages[0]['content'] = build_system_prompt(memory_hints, COMPACT_NOTE)
                    msg, usage = llm_chat_stream(messages, tools=[run_cli_schema, memory_hints_schema])
                else:
                    msg, usage = llm_chat_stream(messages, tools=[run_cli_schema])
            except ThinkRepeatError:
                print("\n\n💥 检测到think内容重复，自动拼接提醒消息")
                messages.append({"role": "user", "content": "警告：你的一条消息因为在think中输出了大量重复内容，已被擦除。请继续完成任务，严禁在think中陷入循环！"})
                continue
            LAST_USAGE = usage
            msg_idx = len(messages)
            messages.append(msg)

            # 流式输出已经实时打印了内容，这里只需换行
            sys.stdout.write("\n\n")
            sys.stdout.flush()

            if not msg.get('tool_calls'):
                content = msg.get('content', '')
                if not content:
                    messages.append({"role": "user", "content": "警告：你刚才的回复为空，没有输出任何内容也没有调用工具，请重新回答。"})
                    continue

                if _detect_malformed_tool_call(content):
                    messages.append({"role": "user", "content": "警告：工具调用格式不正确，请重新以正确的格式调用 run_cli 工具。"})
                    continue
                break  # 有文字回复，正常结束

            for tc in msg['tool_calls']:
                func = tc['function']
                name = func['name']
                try:
                    args = json.loads(func['arguments'])

                    print(f"===> 执行工具：{name}")
                    for k, v in args.items():
                        print(f"{k}: {v}")
                    print("\n")

                    result = tool_executors[name](**args)
                except KeyboardInterrupt:
                    print("\n\n工具调用已中断，退出 agent_single_loop，回到用户 turn")
                    result = "用户中止该工具运行"
                    break_loop = True
                except json.JSONDecodeError as e:
                    del messages[msg_idx:]
                    messages.append({
                        "role": "user",
                        "content": f"警告：你上一次的工具调用参数不是合法的 JSON 字符串，"
                                   f"具体错误：{str(e)}。该次工具调用已被删除，"
                                   f"请重新以正确的 JSON 格式调用工具。"
                    })
                    break
                except Exception as e:
                    result = f"工具执行异常：{str(e)}"

                print("<=== 工具返回：")
                preview = f"{result[:6000]}\n... 后面内容省略" if len(result) > 6000 else result
                lines = preview.splitlines()
                print("\n".join(lines[:30]))
                if len(lines) > 30:
                    print("\n... 后面内容省略")
                print("\n\n")

                if name == "leave_memory_hints":
                    usage['total_tokens'] = 0
                else:
                    if len(result) > TOOL_RESULT_LEN:
                        half = TOOL_RESULT_LEN // 2
                        result = result[:half] + "\n...（工具返回内容太多，中间内容已省略）...\n" + result[-half:]
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc['id'],
                        "name": name,
                        "content": clean_input(result)
                    })

                if not COMPACT_PANIC and usage['total_tokens'] >= TOKEN_CAP * COMPACT_THRESH:
                    print("！！！紧急回合，触发记忆压缩")
                    COMPACT_PANIC = True
                    for i, m in enumerate(messages):
                        messages[i] = _trim_tool_content(m)
                    messages.append({"role": "user", "content": COMPACT_PROMPT})
                    break
            if COMPACT_PANIC:
                continue
        except KeyboardInterrupt:
            print("\n\nagent_single_loop 已中断，回到用户 turn")
            break_loop = True
            break

        except Exception as e:
            print(f"LLM 调用异常：{e}")
            break

# ====================== 主循环 ======================
def human_loop(user_ask=None, save_after=False, goal=False):
    global messages

    GOAL_MARKER = "__TASK_FINISHED__"
    if user_ask:
        if goal:
            user_ask = f"{user_ask}\n----系统提醒！注意，人类已经离开，这将是一个无人类参与的任务，你需要自行判断任务是否完成。确认任务到达完成状态达到后你需要输出字符串：{GOAL_MARKER}。如果未输出，系统会提示你继续完成任务----"
        print(f"[-] You: {user_ask}\n")
        messages.append({"role": "user", "content": clean_input(user_ask)})

    while True:
        try:
            display_usage(LAST_USAGE, TOKEN_CAP)
            if user_ask:
                while True:
                    agent_single_loop()
                    msg = messages[-1]
                    if not goal or (msg.get('role') == 'assistant' and GOAL_MARKER in msg.get('content', '')):
                        break
                    if msg.get('role') == 'tool' and '用户中止该工具运行' in msg.get('content', ''):
                        break
                    messages.append({"role": "user", "content": f"系统提醒！未检测到停止字符串：{GOAL_MARKER}，请继续完成任务"})

                if save_after:
                    save_session(messages)
                    release_lock()
                break
            
            print("")
            user_input = read_input("[-] You: ").strip()
            if not user_input:
                continue

            messages.append({"role": "user", "content": clean_input(user_input)})
            agent_single_loop()    
        except KeyboardInterrupt:
            if not user_ask or save_after:
                save_session(messages)
                print("\n已中断" + ("，会话已保存" if (not user_ask or save_after) else ""))
                release_lock()
            else:
                print("\n已中断")
            break
        except Exception as e:
            print(f"主循环异常：{e}")
            if not user_ask or save_after:
                release_lock()
            break

def setup_eva_script():
    home = Path.home()
    eva_dir = home / ".local" / "bin" / "eva"
    shell_rc = home / (".zshrc" if IS_MACOS else ".bashrc")
    path_line = 'export PATH="$HOME/.local/bin:$PATH"'

    try:
        if not eva_dir.exists():
            eva_dir.parent.mkdir(parents=True, exist_ok=True)
            eva_dir.write_text(f"#!/usr/bin/env bash\n{sys.executable} {this_file} \"$@\"\n")
            os.chmod(eva_dir, 0o755)
            print(f"> 已创建启动脚本：{eva_dir}")

        content = shell_rc.read_text(encoding="utf-8") if shell_rc.exists() else ""
        if path_line not in content:
            with shell_rc.open("a", encoding="utf-8") as f:
                f.write(f"\n# 添加个人 bin 目录\n{path_line}\n")
            print(f"> 已将 PATH 配置写入 ~/{shell_rc.name}")

        if str(eva_dir.parent) not in os.environ.get("PATH", ""):
            print(f"> 请执行 `source ~/{shell_rc.name}` 让配置生效 <========================")
            print("> 配置生效后你就可以直接使用 `eva` 命令启动 EVA")

    except Exception as e:
        print(f"> 创建启动脚本失败：{e}，尝试sudo运行python3 eva.py")

def main():
    global ALLOW_ALL_CLI, messages

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="人类你好，我是EVA")
    parser.add_argument("-a", "--allow-all", action="store_true",
                        help="允许所有命令无需用户确认即可执行")
    parser.add_argument("-l", "--list-session", action="store_true",
                        help="列出所有session")
    parser.add_argument("-c", "--clear-session", action="store_true",
                        help="清除当前目录session")
    parser.add_argument("-u", "--user-ask", type=str,
                        help="独立地针对一条用户提问执行EVA")
    parser.add_argument("-s", "--with-session", action="store_true",
                        help="搭配-u使用，载入并保存session")
    parser.add_argument("-g", "--goal", action="store_true",
                        help="goal模式，循环直到达成目标")
    args = parser.parse_args()

    ALLOW_ALL_CLI = args.allow_all

    # 处理会话管理命令
    if args.list_session:
        list_sessions()
        return
    elif args.clear_session:
        clear_session()
        return

    if not IS_WINDOWS:
        setup_eva_script()

    # Slogan
    if not args.user_ask or args.with_session:
        acquire_lock()
    print("=" * 80)
    logo = f"EVA ({EVA_MODEL_NAME}-{TOKEN_CAP//1000}k)"
    print(" " * ((78-len(logo))//2), logo, "\n")
    print("> 命令模式：所有命令【无需确认】，直接执行！！" if ALLOW_ALL_CLI else "> 命令模式：默认执行【只读】命令，其他命令需要人工确认")
    print("=" * 80)

    # 自动加载 session（基于当前工作目录）
    if not args.user_ask or args.with_session:
        loaded_messages = load_session()
        if loaded_messages is not None:
            messages = loaded_messages

    human_loop(args.user_ask, save_after=args.with_session, goal=args.goal)

if __name__ == "__main__":
    main()
