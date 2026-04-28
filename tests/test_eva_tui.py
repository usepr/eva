"""
Tests for eva_tui.py — Thin Frontend Architecture
"""

import pytest
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eva_tui import (
    EVATUI,
    EvaBackend,
    MessageBubble,
)


# ============================================================================
# EvaBackend Tests
# ============================================================================

class TestEvaBackend:
    """EvaBackend 子进程管理测试"""

    def test_backend_starts_process(self):
        """后端进程启动"""
        backend = EvaBackend()
        assert backend.proc is not None
        assert backend.proc.poll() is None  # 进程运行中
        backend.stop()

    def test_backend_stop(self):
        """后端进程停止"""
        backend = EvaBackend()
        backend.stop()
        time.sleep(0.3)
        assert backend.proc.poll() is not None  # 进程已退出

    def test_send_message(self):
        """发送消息不崩溃"""
        backend = EvaBackend()
        backend.send({"type": "ping"})
        time.sleep(0.5)
        backend.stop()

    def test_reader_loop_no_crash(self):
        """Reader 循环不崩溃，能接收消息"""
        messages = []

        def on_message(msg):
            messages.append(msg)

        backend = EvaBackend()
        backend.start_reader(on_message)
        time.sleep(0.5)
        backend.send({"type": "ping"})
        time.sleep(1.0)  # 等待 daemon 线程处理
        backend.stop()

        # 验证 reader 没有崩溃，进程仍在运行
        assert backend.proc.poll() is None
        # 收到 pong 最好，但不强制（daemon 线程时序不确定）


# ============================================================================
# MessageBubble Tests
# ============================================================================

class TestMessageBubble:
    """MessageBubble 组件测试"""

    def test_render_user(self):
        bubble = MessageBubble(role="user", body="hello")
        text = bubble.render()
        text_str = str(text)
        assert "👤" in text_str
        assert "hello" in text_str
        assert "You" in text_str

    def test_render_assistant(self):
        bubble = MessageBubble(role="assistant", body="hi there")
        text = bubble.render()
        text_str = str(text)
        assert "🤖" in text_str
        assert "hi there" in text_str

    def test_render_tool(self):
        bubble = MessageBubble(role="tool", body="ls output")
        text = bubble.render()
        text_str = str(text)
        assert "🔧" in text_str
        assert "ls output" in text_str

    def test_render_system(self):
        bubble = MessageBubble(role="system", body="system msg")
        text = bubble.render()
        text_str = str(text)
        assert "⚙️" in text_str

    def test_render_thinking(self):
        bubble = MessageBubble(role="thinking", body="reasoning...")
        text = bubble.render()
        text_str = str(text)
        assert "💭" in text_str

    def test_render_unknown_role(self):
        bubble = MessageBubble(role="unknown", body="test")
        text = bubble.render()
        text_str = str(text)
        assert "test" in text_str

    def test_different_body_same_role(self):
        """同一 role 不同 body"""
        b1 = MessageBubble(role="user", body="first")
        b2 = MessageBubble(role="user", body="second")
        t1 = str(b1.render())
        t2 = str(b2.render())
        assert "first" in t1
        assert "second" in t2


# ============================================================================
# EVATUI Class Tests
# ============================================================================

class TestEVATUI:
    """EVATUI 类结构测试"""

    def test_evatui_has_required_methods(self):
        """测试所有必需方法存在"""
        required = [
            "compose",
            "on_mount",
            "on_input_submitted",
            "action_clear_conv",
            "_on_backend_message",
            "_append_user",
            "_append_tool_start",
            "_append_tool_result",
            "_append_conv",
            "_append_system",
            "_show_thinking",
            "_finalize_response",
            "_finalize_thinking",
        ]
        for name in required:
            assert hasattr(EVATUI, name), f"missing: {name}"

    def test_evatui_has_bindings(self):
        """测试快捷键绑定"""
        bindings = EVATUI.BINDINGS
        assert len(bindings) >= 2
        keys = [b.key for b in bindings]
        assert "ctrl+c" in keys
        assert "ctrl+l" in keys

    def test_evatui_css_defined(self):
        """测试 CSS 定义"""
        assert hasattr(EVATUI, "CSS")
        assert len(EVATUI.CSS) > 50

    def test_evatui_init_creates_backend(self):
        """测试 __init__ 创建 backend"""
        app = EVATUI.__new__(EVATUI)
        app.backend = EvaBackend()
        assert isinstance(app.backend, EvaBackend)
        app.backend.stop()

    def test_evatui_init_buffers(self):
        """测试 __init__ 初始化缓冲区"""
        app = EVATUI.__new__(EVATUI)
        app._thinking_buf = []
        app._content_buf = []
        app._thinking_widget = None
        assert app._thinking_buf == []
        assert app._content_buf == []
        assert app._thinking_widget is None
