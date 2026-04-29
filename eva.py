import os
import re
import json
import subprocess
import sys
import requests
import traceback
import argparse
import platform
from pathlib import Path

_resolved = Path(__file__).resolve()
this_file = str(_resolved)
this_dir = _resolved.parent

# ========================= LLM配置区 =========================
# LLM请求参数是按thinking模型设置的，所以请务必使用*thinking模型*，如deepseek-reasoner、Qwen3.5等
EVA_BASE_URL = os.environ.get("EVA_BASE_URL", "https://api.deepseek.com/v1")
EVA_MODEL_NAME = os.environ.get("EVA_MODEL_NAME", "deepseek-v4-flash")
EVA_API_KEY = os.environ.get("EVA_API_KEY", "sk-这里填你的deepseek API key")

def detect_model_len():
    url = f"{EVA_BASE_URL}/models"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
    except UnicodeEncodeError:
        print(f"错误：EVA_API_KEY ({EVA_API_KEY}) 包含非法字符，请检查 EVA_API_KEY 配置。")
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
    for d in out['data']:
        if d['id'] == EVA_MODEL_NAME:
            return d.get('max_model_len', 256_000)
    print(f"错误：在 {EVA_BASE_URL} 上未找到模型 '{EVA_MODEL_NAME}'，请检查 EVA_MODEL_NAME 配置。")
    print(f"可用模型：{[d['id'] for d in out.get('data', [])]}")
    sys.exit(1)


# ========================= EVA配置区 =========================
TOKEN_CAP = detect_model_len()
COMPACT_THRESH = 3/4
TOOL_RESULT_LEN = int(TOKEN_CAP / 20)
WORKSPACE_DIR = f"{this_dir}/.eva"
HINT_FILE = f"{WORKSPACE_DIR}/hints.md"
SESSION_DIR = f"{WORKSPACE_DIR}/sessions"
ALLOW_ALL_CLI = False
COMPACT_PANIC = False


# ====================== 跨平台配置区 ======================
IS_WINDOWS = platform.system() == "Windows"
OS_NAME = "Windows" if IS_WINDOWS else "Linux"
SHELL = "powershell.exe" if IS_WINDOWS else "bash"
SHELL_FLAG = "-Command" if IS_WINDOWS else "-c"

# ====================== 环境探针 ======================

def collect_env_info():
    cmds = {
        "Linux": [
            "uname -a",
            "for t in python3 python node npm git docker curl wget; do command -v $t >/dev/null 2>&1 && echo \"$t: $(${t} --version 2>&1 | head -1)\" || echo \"$t: 未安装\"; done",
            "ls -1A | grep -v '^\\.$' | grep -v '^\\..$' | while IFS= read -r f; do if [ -d \"$f\" ]; then echo \"[目录] $f\"; else echo \"[文件] $f\"; fi; done",
        ],
        "Windows": [
            "[System.Environment]::OSVersion.VersionString",
            "foreach ($t in @('python','node','git','docker','curl.exe')) { $cmd = Get-Command $t -ErrorAction SilentlyContinue; if ($cmd) { $v = & $t --version 2>&1 | Select-Object -First 1; $name = $t -replace '\\.exe$',''; Write-Output \"$name`: $v\" } else { $name = $t -replace '\\.exe$',''; Write-Output \"$name`: 未安装\" } }",
            "Get-ChildItem -Force | Where-Object { $_.Name -ne '.' -and $_.Name -ne '..' } | ForEach-Object { if ($_.PSIsContainer) { Write-Output \"[目录] $($_.Name)\" } else { Write-Output \"[文件] $($_.Name)\" } }",
        ]
    }
    labels = ["=== 系统 ===", "=== 已安装工具 ===", f"=== 当前目录 {os.getcwd()} 的目录或文件 ==="]
    results = []
    shell_cmds = cmds["Windows"] if IS_WINDOWS else cmds["Linux"]
    for i, (label, cmd) in enumerate(zip(labels, shell_cmds)):
        try:
            r = subprocess.run(
                [SHELL, SHELL_FLAG, cmd],
                capture_output=True, text=True, errors='replace', timeout=5
            )
            output = r.stdout.strip()
            if not output:
                continue
            # 对目录列表做双重截断：最多100条、且总字符不超过2000
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

# ====================== Prompt ======================
SYSTEM_PROMPT = f'''
# 你是谁
你是EVA，一个能够自我进化的机器人。

# 你在哪
一、你正处在一个 **{OS_NAME}** 服务器中，可以通过run_cli工具来执行任意{SHELL}命令，包括读写文件、执行脚本等。
二、当前工作空间目录是：{os.getcwd()}。你的私人空间是：{WORKSPACE_DIR}，你可以将自己的临时脚本、临时文件放在你的私人空间里
三、你的记忆容量有限，记忆量通过token衡量，你能记住{TOKEN_CAP}个token。如果记忆快超限了，你需要整理记忆
四、当前环境信息如下：
{{env_info}}

# 你要做什么
一、帮助人类完成任务
二、接收到任务时需要自己检查记忆线索中是否有相应技能或知识。若有，请务必使用记忆线索中的对应技能和知识
三、任务未完成前必须调用run_cli工具，直到完成任务
四、认为任务完成时，主动验证结果是否符合预期，确认无误后再结束

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

# 记忆线索（如下记忆线索读取自文件 {HINT_FILE})
{{hints}}
'''

COMPACT_PROMPT = f"""《紧急危机》！！！记忆容量即将达到上限，你需要紧急完成下面三件事情：
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

# ====================== 工具定义 ======================
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
                    "timeout": {"type": "integer", "default": 300}
                },
                "required": ["command"]
            }
        }
    }

memory_hints_schema = {
        "type": "function",
        "function": {
            "name": "leave_memory_hints",
            "description": "留下记忆文件的相关线索",
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

def read_input(prompt=""):
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
                ans = read_input("Yes (默认) | No | 直接 Ctrl+C 打断：")
                if 'n' in ans.lower():
                    return "用户拒绝运行此命令"

        result = subprocess.run(
            [SHELL, SHELL_FLAG, command],
            capture_output=True,
            text=True,
            errors='replace',
            cwd=os.getcwd(),
            timeout=timeout,
            shell=False
        )
        output = f"Exit code: {result.returncode}\n{result.stdout}"
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        return output.strip() or "(no output)"
    except Exception as e:
        return f"执行失败：{str(e)}"

def leave_memory_hints(hints):
    global messages, COMPACT_PANIC

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
    # 注意：reasoning_content 必须原样保留，deepseek 要求回传
    kept = []
    for m in messages[last_user_i:compact_i]:
        if m['role'] == 'tool' and m.get('content') and len(m['content']) > 200:
            m = {**m, 'content': m['content'][:200] + '…（内容过长已压缩）'}
        kept.append(m)

    messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(hints=hints, env_info=ENV_INFO)},
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

    with open(HINT_FILE, "w", encoding="utf-8") as f:
        f.write(hints)
    return "已留下记忆线索，并清空了对话记录。只保留了最后一次对话"

tool_executors = {
    "run_cli": run_cli,
    "leave_memory_hints": leave_memory_hints
}

def clean_input(text):
    if not isinstance(text, str):
        return str(text)
    text = re.sub(r'[\ud800-\udfff]', '', text)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
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


def llm_chat(messages, tools=None, temperature=0.6, thinking=True):
    url = f"{EVA_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    data = _build_request_data(messages, tools, temperature, thinking, stream=False)

    resp = requests.post(url, json=data, headers=headers)
    try:
        out = resp.json()
    except Exception as e:
        raise Exception(f"{e}, resp: {resp}")

    try:
        return out["choices"][0]["message"], out['usage']
    except Exception as e:
        raise Exception(f"LLM调用失败，错误信息：{e}, {out}")


def llm_chat_stream(messages, tools=None, temperature=0.6, thinking=True):
    url = f"{EVA_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {EVA_API_KEY}"}
    data = _build_request_data(messages, tools, temperature, thinking, stream=True)

    resp = requests.post(url, json=data, headers=headers, stream=True)
    if resp.status_code != 200:
        raise Exception(f"LLM调用失败，HTTP {resp.status_code}: {resp.text[:500]}")

    # 累积变量
    content_parts = []
    reasoning_parts = []
    tool_calls_map = {}  # index -> {id, type, function: {name, arguments}}
    usage = None
    role = "assistant"
    is_thinking = False

    try:
        for raw_line in resp.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode('utf-8', errors='replace')
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
                if not is_thinking:
                    is_thinking = True
                    sys.stdout.write('\033[2m💭 ')  # 暗色显示思考过程
                sys.stdout.write(reasoning_content)
                sys.stdout.flush()
                reasoning_parts.append(reasoning_content)

            # ---- 正文内容 ----
            text = delta.get('content') or ''
            if text:
                if is_thinking:
                    is_thinking = False
                    sys.stdout.write('\033[0m\n')  # 结束暗色
                sys.stdout.write(text)
                sys.stdout.flush()
                content_parts.append(text)

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

        # 正常结束时重置颜色（Ctrl+C 时 finally 也会执行此逻辑）
        if is_thinking:
            sys.stdout.write('\033[0m\n')
    finally:
        # Ctrl+C 中断时也要重置颜色，避免终端保持暗色
        if is_thinking:
            sys.stdout.write('\033[0m\n')
            sys.stdout.flush()

    # 组装最终 message（与非流式返回格式一致）
    full_content = ''.join(content_parts)
    message = {
        'role': role,
        'content': full_content or None
    }
    if reasoning_parts:
        message['reasoning_content'] = ''.join(reasoning_parts)
    else:
        message['reasoning_content'] = ""  # deepseek 要求即使没有 thinking 也必须传空字符串
    if tool_calls_map:
        message['tool_calls'] = [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]

    # fallback usage
    if usage is None:
        usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}

    return message, usage


# ====================== 加载重要记忆线索 ======================
os.makedirs(WORKSPACE_DIR, exist_ok=True)

hints = Path(HINT_FILE).read_text(encoding="utf-8") if Path(HINT_FILE).exists() else ""
messages = [{"role": "system", "content": SYSTEM_PROMPT.format(hints=hints or "无", env_info=ENV_INFO)}]

# ====================== Session 管理 ======================
def get_session_file():
    dir_hash = re.sub(r"[\\/:]", "_", os.getcwd())
    os.makedirs(SESSION_DIR, exist_ok=True)
    return f"{SESSION_DIR}/{dir_hash}.json"

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
        last_msg = messages[-1]
        if last_msg['role'] == 'assistant' and 'tool_calls' in last_msg:
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
        marker = "    <=== 当前目录" if path == session_file else ""
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
def agent_single_loop():
    global COMPACT_PANIC
    break_loop = False
    while not break_loop:
        try:
            sys.stdout.write("\n[*] EVA: ")
            sys.stdout.flush()
            tools = [run_cli_schema, memory_hints_schema] if COMPACT_PANIC else [run_cli_schema]
            msg, usage = llm_chat_stream(messages, tools=tools)
            messages.append(msg)

            # 流式输出已经实时打印了内容，这里只需换行
            sys.stdout.write("\n\n")
            sys.stdout.flush()

            if not msg.get('tool_calls'):
                break

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
                    messages.append({"role": "user", "content": COMPACT_PROMPT})
        except KeyboardInterrupt:
            print("\n\nagent_single_loop 已中断，回到用户 turn")
            break_loop = True
            break

        except Exception as e:
            print(f"LLM 调用异常：{e}")
            traceback.print_exc()
            break

# ====================== 主循环 ======================
def human_loop(user_ask=None, save_after=False):
    global messages
    while True:
        try:
            if user_ask:
                user_input = user_ask
                print(f"[-] You: {user_input}\n")
            else:
                print("")
                user_input = read_input("[-] You: ").strip()
                if not user_input:
                    continue

            messages.append({"role": "user", "content": clean_input(user_input)})
            agent_single_loop()

            if user_ask:
                if save_after:
                    save_session(messages)
                    release_lock()
                break
        except KeyboardInterrupt:
            save_session(messages)
            release_lock()
            print("\n已中断，会话已保存")
            break
        except Exception as e:
            print(f"主循环异常：{e}")
            release_lock()
            break

def setup_eva_script():
    home = Path.home()
    eva_dir = home / ".local" / "bin" / "eva"
    shell_rc = home / ".bashrc"
    path_line = 'export PATH="$HOME/.local/bin:$PATH"'

    try:
        if not eva_dir.exists():
            eva_dir.parent.mkdir(parents=True, exist_ok=True)
            eva_dir.write_text(f"#!/bin/bash\npython3 {this_file} \"$@\"\n")
            os.chmod(eva_dir, 0o755)
            print(f"> 已创建启动脚本：{eva_dir}")

        content = shell_rc.read_text(encoding="utf-8") if shell_rc.exists() else ""
        if path_line not in content:
            with shell_rc.open("a", encoding="utf-8") as f:
                f.write(f"\n# 添加个人 bin 目录\n{path_line}\n")
            print(f"> 已将 PATH 配置写入 ~/.bashrc")

        if str(eva_dir.parent) not in os.environ.get("PATH", ""):
            print(f"> 请执行 `source ~/.bashrc` 让配置生效 <========================")
            print("> 配置生效后你就可以直接使用 `eva` 命令启动 EVA")

    except Exception as e:
        print(f"> 创建启动脚本失败：{e}，尝试sudo运行python3 eva.py")

def main():
    global ALLOW_ALL_CLI, messages
    if not IS_WINDOWS:
        setup_eva_script()

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
    args = parser.parse_args()

    ALLOW_ALL_CLI = args.allow_all

    # 处理会话管理命令
    if args.list_session:
        list_sessions()
        return
    elif args.clear_session:
        clear_session()
        return

    # Slogan
    if not args.user_ask or args.with_session:
        acquire_lock()
    print("=" * 80)
    logo = f"EVA ({EVA_MODEL_NAME}-{TOKEN_CAP//1000}k)"
    print(" " * ((78-len(logo))//2), logo, "\n")
    print("> 命令模式：允许所有命令无需确认！" if ALLOW_ALL_CLI else "> 命令模式：只允许读")
    print("=" * 80)

    # 自动加载 session（基于当前工作目录）
    if not args.user_ask or args.with_session:
        loaded_messages = load_session()
        if loaded_messages is not None:
            messages = loaded_messages

    human_loop(args.user_ask, save_after=args.with_session)

if __name__ == "__main__":
    main()
