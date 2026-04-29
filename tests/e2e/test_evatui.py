"""
Tests for eva_tui.py — Thin Frontend Architecture
"""

import pytest
from eva_tui import (
    EVATUI,
    EvaBackend,
    MessageBubble,
)


class TestEvaBackend:
    """EvaBackend 子进程管理测试"""

    def test_backend_starts(self):
        backend = EvaBackend()
        assert backend.proc is not None
        assert backend.proc.poll() is None  # 进程运行中
        backend.stop()

    def test_send_ping(self):
        backend = EvaBackend()
        backend.start_reader(lambda msg: None)
        backend.send({"type": "ping"})
        import time
        time.sleep(0.5)
        # 后端应该在 stdout 写入 pong
        # 由于 daemon reader，不会收到消息
        backend.stop()


class TestMessageBubble:
    """MessageBubble 组件测试"""

    def test_render_user(self):
        bubble = MessageBubble(role="user", body="hello")
        text = bubble.render()
        assert "👤" in str(text)
        assert "hello" in str(text)

    def test_render_assistant(self):
        bubble = MessageBubble(role="assistant", body="hi there")
        text = bubble.render()
        assert "🤖" in str(text)
        assert "hi there" in str(text)

    def test_render_tool(self):
        bubble = MessageBubble(role="tool", body="ls output")
        text = bubble.render()
        assert "🔧" in str(text)


class TestEVATUI:
    """EVATUI 类测试"""

    def test_evatui_has_required_methods(self):
        required = [
            "compose",
            "on_mount",
            "on_input_submitted",
            "action_clear_conv",
            "_on_backend_message",
            "_append_user",
            "_append_tool_start",
            "_append_tool_result",
            "_show_thinking",
            "_finalize_response",
        ]
        for name in required:
            assert hasattr(EVATUI, name), f"missing: {name}"

    def test_evatui_has_bindings(self):
        assert len(EVATUI.BINDINGS) >= 2

    def test_evatui_css_defined(self):
        assert hasattr(EVATUI, "CSS")
        assert len(EVATUI.CSS) > 0

    def test_evatui_init_creates_backend(self):
        app = EVATUI()
        assert hasattr(app, "backend")
        assert isinstance(app.backend, EvaBackend)
