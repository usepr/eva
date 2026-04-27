"""
EVA TUI — 终端图形化界面
使用 Textual + Rich 库，支持 Markdown / JSON 渲染显示。
"""

from __future__ import annotations

import sys
import os
import re
import json as json_module
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Input, Static, Markdown as TuiMarkdown
from textual import widgets
from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.json import JSON
from rich.text import Text
from rich.table import Table
from rich.panel import Panel

from eva import Agent, AgentContext, Memory, AgentResult
from types import SimpleNamespace

# ============================================================================
# EVA 初始化
# ============================================================================

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

IS_WINDOWS = sys.platform == "win32"
OS_NAME = "Windows" if IS_WINDOWS else "Linux"
SHELL = "powershell.exe" if IS_WINDOWS else "bash"
SHELL_FLAG = "-Command" if IS_WINDOWS else "-c"
this_dir = Path(__file__).parent
WORKSPACE_DIR = this_dir / ".eva"
HINT_FILE = WORKSPACE_DIR / "hints.md"


def collect_env_info() -> str:
    try:
        hostname = os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "unknown")
        os_version = os.uname().release if hasattr(os, "uname") else "unknown"
        cwd = os.getcwd()
        py_version = sys.version.split()[0]
        user = os.environ.get("USER") or os.environ.get("USERNAME", "unknown")
        return f"hostname: {hostname}, os: {os_version}, cwd: {cwd}, py: {py_version}, user: {user}"
    except Exception:
        return "environment info unavailable"


def detect_model_len() -> int:
    return 256_000


EVA_BASE_URL = os.environ.get("EVA_BASE_URL", "https://api.deepseek.com/v1")
EVA_MODEL_NAME = os.environ.get("EVA_MODEL_NAME", "deepseek-v4-flash")
EVA_API_KEY = os.environ.get("EVA_API_KEY", "")
TOKEN_CAP = detect_model_len()
COMPACT_THRESH = 3 / 4
TOOL_RESULT_LEN = int(TOKEN_CAP / 20)
ENV_INFO = collect_env_info()


def create_agent() -> Agent:
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
    ctx = AgentContext(allow_all_cli=False)
    return Agent(config_ns, platform_ns, ctx, memory, use_default_callbacks=False)


# ============================================================================
# Rich 渲染辅助
# ============================================================================

def rich_markdown(text: str) -> str:
    """渲染 Markdown 为 Rich 可识别的标记字符串"""
    if not text:
        return ""
    return text  # Rich 自动解析 Markdown


def rich_json(text: str) -> str:
    """格式化 JSON"""
    try:
        obj = json_module.loads(text)
        return json_module.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return text


def is_json(s: str) -> bool:
    s = s.strip()
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


# ============================================================================
# Textual TUI 应用
# ============================================================================

class MessageBubble(Static):
    """单条消息气泡（支持 Markdown/JSON）"""

    def __init__(self, role: str, body: str, **kwargs):
        self.role = role
        self.body = body
        super().__init__(**kwargs)

    def render(self) -> Text:
        color = {
            "user": "#7ee8fa",
            "assistant": "#e8d5b7",
            "tool": "#b8a9c9",
            "system": "#90EE90",
            "thinking": "#555555",
        }.get(self.role, "#ffffff")

        icon = {
            "user": "👤",
            "assistant": "🤖",
            "tool": "🔧",
            "system": "⚙️",
            "thinking": "💭",
        }.get(self.role, "💬")

        role_label = "You" if self.role == "user" else "EVA" if self.role == "assistant" else self.role.title()
        label = f"{icon} {role_label}"

        if self.role == "thinking":
            return Text(f"{label}\n{self.body}", style=f"bold {color}")
        elif self.role == "tool":
            return Text(f"{label}\n{self.body}", style=f"bold {color}")
        else:
            return Text(f"{label}\n{self.body}", style=f"bold {color}")


class EVATUI(App):
    """EVA 终端图形化界面"""

    CSS = """
    Screen {
        background: #0f0f1a;
    }

    #conv_scroll {
        dock: top;
        width: 100%;
        height: 100%;
        background: #0f0f1a;
        scrollbar-size: 1 1;
        scrollbar-color: #7ee8fa;
        padding: 1;
    }

    #input_area {
        dock: bottom;
        height: 3;
        background: #1a1a2e;
        border-top: tall solid #7ee8fa;
    }

    Input {
        dock: bottom;
        height: 3;
        background: #1a1a2e;
        color: #e8d5b7;
        border-top: tall solid #7ee8fa;
    }

    Static {
        color: #e8d5b7;
    }

    .header {
        dock: top;
        height: 3;
        background: #1a1a2e;
        content-align: center middle;
        color: #7ee8fa;
        text-style: bold;
    }

    .msg-assistant {
        color: #e8d5b7;
        margin: 1 0;
    }

    .msg-user {
        color: #7ee8fa;
        margin: 1 0;
    }

    .msg-tool {
        color: #b8a9c9;
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+l", "clear_conv", "Clear", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.agent = create_agent()
        self.agent.on_thinking = self._on_thinking
        self.agent.on_content = self._on_content
        self._thinking_buf: list[str] = []
        self._content_buf: list[str] = []
        self._thinking_widget: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static(f"EVA TUI  |  {EVA_MODEL_NAME}  |  Token Cap: {TOKEN_CAP // 1000}k", classes="header")
        yield ScrollableContainer(id="conv_scroll")
        yield Input(placeholder="输入你的问题，按 Enter 发送...", id="user_input")

    def on_mount(self) -> None:
        self.agent.ctx.messages = self.agent.memory.build_initial_messages()
        history = self.agent.memory.load_session()
        if history:
            self.agent.ctx.messages.extend(history)
        self.agent.ctx.messages.append({
            "role": "user",
            "content": "你好，介绍一下你自己",
        })
        self._run_single_step()

    def _render_rich(self, text: str, style: str = "") -> Text:
        """用 Rich 渲染 Markdown/JSON，返回 Text"""
        from rich.console import Console
        from io import StringIO

        console = Console(file=StringIO(), force_terminal=True, width=120)
        if is_json(text):
            console.print(JSON(text))
        else:
            console.print(RichMarkdown(text))
        rendered = console.file.getvalue()
        return Text.from_ansi(rendered)

    def _append_conv(self, role: str, body: str) -> None:
        """向对话区追加一条消息"""
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        # 用 Rich 渲染 markdown
        try:
            rich_text = self._render_rich(body)
            bubble = Static(rich_text, classes=f"msg-{role}")
        except Exception:
            bubble = Static(body, classes=f"msg-{role}")
        scroll.mount(bubble)
        scroll.scroll_end(animate=False)

    def _append_user(self, text: str) -> None:
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        item = Static(
            Text(f"👤 You\n{text}", style="bold #7ee8fa"),
            classes="msg-user",
        )
        scroll.mount(item)
        scroll.scroll_end(animate=False)

    def _show_thinking(self, text: str) -> None:
        """显示 thinking 进度条"""
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        if self._thinking_widget:
            self._thinking_widget.remove()
        self._thinking_widget = Static(
            Text(f"💭 thinking: {text[:80]}", style="dim #888888"),
            classes="msg-thinking",
        )
        scroll.mount(self._thinking_widget)
        scroll.scroll_end(animate=False)

    def _finalize_thinking(self) -> None:
        """thinking 结束，移除进度条"""
        if self._thinking_widget:
            self._thinking_widget.remove()
            self._thinking_widget = None

    def _process_result(self, result: AgentResult) -> None:
        scroll = self.query_one("#conv_scroll", ScrollableContainer)

        if result.status == "waiting_for_tool":
            # 先显示 content
            content_text = "".join(self._content_buf)
            if content_text:
                self._append_conv("assistant", content_text)
            self._finalize_thinking()

            for tc in result.tool_calls:
                name = tc["name"]
                args = tc["args"]
                args_str = "\n".join(f"{k}: {v}" for k, v in args.items())
                tool_intro = f"🔧 **{name}**\n\n```\n{args_str}\n```\n\n---\n"

                # 工具说明
                scroll.mount(Static(
                    Text(f"🔧 {name}\n{args_str}", style="bold #b8a9c9"),
                    classes="msg-tool",
                ))

                try:
                    res = self.agent.tools.execute(name, args)
                except Exception as e:
                    res = f"执行异常：{str(e)}"

                self.agent.ctx.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": res,
                })

                # 工具结果，用 JSON 或 Markdown 渲染
                # 先去除 ANSI 转义码，避免 Rich markup 解析错误
                clean_res = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", res)
                if is_json(clean_res):
                    formatted = rich_json(clean_res)
                    scroll.mount(Static(
                        Text(formatted, style="#b8a9c9"),
                        classes="msg-tool",
                    ))
                else:
                    display = clean_res[:500] + ("... 省略" if len(clean_res) > 500 else "")
                    scroll.mount(Static(
                        Text(display, style="#b8a9c9"),
                        classes="msg-tool",
                    ))

                scroll.scroll_end(animate=False)

            self._content_buf = []
            self._thinking_buf = []
            resume_result = self.agent.resume([])
            self._process_result(resume_result)
            return

        elif result.status == "compact_panic":
            scroll.mount(Static(
                Text("⚠️ 记忆压缩触发", style="bold #ff6b6b"),
            ))
            scroll.scroll_end(animate=False)
            resume_result = self.agent.resume([])
            self._process_result(resume_result)
            return

        # completed
        content_text = "".join(self._content_buf)
        thinking_text = "".join(self._thinking_buf)
        self._finalize_thinking()

        if thinking_text and content_text:
            full = f"💭 *thinking:*\n_{thinking_text}_\n\n---\n\n{content_text}"
        elif thinking_text:
            full = f"💭 *{thinking_text}*\n\n{content_text}"
        else:
            full = content_text

        if full.strip():
            self._append_conv("assistant", full)

        self.agent.memory.save_session(self.agent.ctx.messages)

    def _run_single_step(self) -> None:
        result = self.agent.step()
        self._process_result(result)

    def _on_thinking(self, text: str) -> None:
        self._thinking_buf.append(text)
        # 更新 thinking 进度
        full = "".join(self._thinking_buf)
        self._show_thinking(full[:80])

    def _on_content(self, text: str) -> None:
        self._content_buf.append(text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return
        event.input.clear()

        self._append_user(user_text)
        self.agent.ctx.messages.append({"role": "user", "content": user_text})

        self._thinking_buf = []
        self._content_buf = []
        self._thinking_widget = None

        self._run_single_step()

    def action_clear_conv(self) -> None:
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        for widget in scroll.children:
            widget.remove()
        self.agent.ctx.messages = self.agent.memory.build_initial_messages()


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    if not EVA_API_KEY:
        print("错误：请设置 EVA_API_KEY 环境变量（可使用 .env 文件）")
        print("或运行：export EVA_API_KEY='your-key'")
        sys.exit(1)
    app = EVATUI()
    app.run()
