"""
EVA TUI — 终端图形化界面（薄前端）
通过子进程启动 eva.py --tui 作为后端，通过 JSON 消息通信。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.widgets import Input, Static  # noqa: F401

# ============================================================================
# 工具函数
# ============================================================================

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def strip_ansi(text: str) -> str:
    """去除 ANSI 转义码"""
    return ANSI_RE.sub("", text)


# ============================================================================
# EvaBackend — 子进程管理
# ============================================================================

class EvaBackend:
    """管理 eva.py 子进程通信"""

    def __init__(self, debug: bool = False, allow_all_cli: bool = False):
        self._debug = debug
        self._debug_log: list[str] = []
        Path(".eva").mkdir(exist_ok=True)
        self._debug_file = Path(".eva") / "debug.log"

        args = [sys.executable, "eva.py", "--tui"]
        if debug:
            args.append("--debug")
        if allow_all_cli:
            args.append("-a")

        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def _log(self, direction: str, msg: dict):
        if not self._debug:
            return
        ts = dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] FRONTEND {direction} {json.dumps(msg, ensure_ascii=False)[:200]}"
        self._debug_log.append(line)
        self._debug_file.write_text("\n".join(self._debug_log) + "\n", encoding="utf-8")

    def send(self, msg: dict) -> None:
        self._log("OUT", msg)
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _reader_loop(self, on_message: Callable[[dict], None]) -> None:
        for line in self.proc.stdout:
            msg = json.loads(line.strip())
            self._log("IN", msg)
            on_message(msg)

    def start_reader(self, on_message: Callable[[dict], None]) -> None:
        t = Thread(target=self._reader_loop, args=(on_message,), daemon=True)
        t.start()

    def stop(self) -> None:
        self.proc.terminate()


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
    """EVA 终端图形化界面（薄前端）"""

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
        Binding("ctrl+d", "toggle_debug", "Debug", show=False),
    ]

    def __init__(self, debug: bool = False, allow_all_cli: bool = False):
        super().__init__()
        self._debug = debug
        self._allow_all_cli = allow_all_cli
        self.backend = EvaBackend(debug=debug, allow_all_cli=allow_all_cli)
        self._thinking_buf: list[str] = []
        self._content_buf: list[str] = []
        self._thinking_widget: Static | None = None
        self._tool_widget: Static | None = None

    def compose(self) -> ComposeResult:
        header = "EVA TUI  |  Backend: eva.py --tui"
        if self._debug:
            header += "  [DEBUG]"
        yield Static(header, classes="header")
        yield ScrollableContainer(id="conv_scroll")
        yield Input(placeholder="输入你的问题，按 Enter 发送...", id="user_input")

    def on_mount(self) -> None:
        self.backend.start_reader(self._on_backend_message)
        self.backend.send({"type": "init", "allow_all_cli": self._allow_all_cli})

    def _on_backend_message(self, msg: dict) -> None:
        """处理后端发来的所有 JSON 消息"""
        msg_type = msg.get("type")

        if msg_type == "ready":
            # 后端就绪后，发送初始消息
            self.backend.send({"type": "user_message", "content": "你好，介绍一下你自己"})

        elif msg_type == "event":
            event = msg.get("event")
            if event == "thinking":
                raw = msg.get("data", "")
                self._thinking_buf.append(strip_ansi(raw))
                full = "".join(self._thinking_buf)
                self.call_from_thread(self._show_thinking, full[:80])
            elif event == "content":
                self._content_buf.append(msg.get("data", ""))
            elif event == "tool_start":
                name = msg.get("name", "?")
                args = msg.get("args", {})
                self.call_from_thread(self._append_tool_start, name, args)
            elif event == "tool_result":
                id = msg.get("id", "")
                result = msg.get("result", "")
                self.call_from_thread(self._append_tool_result, id, result)
            elif event == "compact_panic":
                self.call_from_thread(self._append_system, "⚠️ 记忆压缩触发")

        elif msg_type == "tool_call":
            # tool_start 已通知，等待 tool_result 即可
            pass

        elif msg_type == "response":
            self.call_from_thread(self._finalize_response, msg)

        elif msg_type == "session_saved":
            pass  # save 成功，无需 UI 反馈

    def _render_md(self, text: str) -> Text:
        """将 Markdown 文本渲染为 Rich Text"""
        clean = strip_ansi(text)
        console = Console(file=StringIO(), width=120, force_terminal=False)
        console.print(RichMarkdown(clean))
        rendered = console.file.getvalue()
        return Text.from_ansi(rendered)

    def _append_conv(self, role: str, body: str) -> None:
        """向对话区追加一条消息（支持 Markdown 渲染）"""
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        label = Text("🤖 EVA\n", style="bold #e8d5b7")
        content = self._render_md(body)
        bubble = Static(
            label + content,
            classes=f"msg-{role}",
        )
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

    def _append_tool_start(self, name: str, args: dict) -> None:
        """显示工具开始执行"""
        # 清理 thinking 进度条
        if self._thinking_widget:
            self._thinking_widget.remove()
            self._thinking_widget = None
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        args_str = "\n".join(f"{k}: {v}" for k, v in args.items())
        # 显示命令及运行中指示
        self._tool_widget = Static(
            Text(f"🔧 {name}\n{args_str}\n⏳ 执行中...", style="bold #b8a9c9"),
            classes="msg-tool",
        )
        scroll.mount(self._tool_widget)
        scroll.scroll_end(animate=False)

    def _append_tool_result(self, id: str, result: str) -> None:
        """显示工具执行结果（替换运行中指示）"""
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        # 移除运行中 widget（不删 thinking_widget，等 finalize 再删）
        if self._tool_widget:
            self._tool_widget.remove()
            self._tool_widget = None
        # 渲染工具结果（先清理 ANSI，再截断）
        clean = strip_ansi(result)
        display = clean[:500] + ("... 省略" if len(clean) > 500 else "")
        content = self._render_md(display)
        label = Text(f"🔧 工具结果 [{id[:12]}...]\n", style="bold #b8a9c9")
        scroll.mount(Static(
            label + content,
            classes="msg-tool",
        ))
        scroll.scroll_end(animate=False)

    def _append_system(self, text: str) -> None:
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        scroll.mount(Static(
            Text(text, style="bold #ff6b6b"),
        ))
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

    def _finalize_response(self, msg: dict) -> None:
        """处理后端最终响应"""
        self._finalize_thinking()

        thinking_text = "".join(self._thinking_buf)
        content_text = "".join(self._content_buf)

        if thinking_text and content_text:
            full = f"💭 *thinking:*\n_{thinking_text}_\n\n---\n\n{content_text}"
        elif thinking_text:
            full = f"💭 *{thinking_text}*\n\n{content_text}"
        else:
            full = content_text

        if full.strip():
            self._append_conv("assistant", full)

        self.backend.send({"type": "save_session"})
        self._thinking_buf = []
        self._content_buf = []

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_text = event.value.strip()
        if not user_text:
            return
        event.input.clear()

        self._append_user(user_text)
        self.backend.send({"type": "user_message", "content": user_text})
        self._thinking_buf = []
        self._content_buf = []
        self._thinking_widget = None
        self._tool_widget = None

    def action_clear_conv(self) -> None:
        scroll = self.query_one("#conv_scroll", ScrollableContainer)
        for widget in scroll.children:
            widget.remove()

    def action_toggle_debug(self) -> None:
        """切换 debug 模式"""
        self._debug = not self._debug
        self.query_one("Static").update(
            f"EVA TUI  |  Backend: eva.py --tui  [{'DEBUG ON' if self._debug else 'DEBUG OFF'}]"
        )


# ============================================================================
# 入口
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="EVA TUI")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("-a", "--allow-all", action="store_true", help="Allow all CLI commands (dangerous)")
    args = parser.parse_args()

    app = EVATUI(debug=args.debug, allow_all_cli=args.allow_all)
    app.run()
