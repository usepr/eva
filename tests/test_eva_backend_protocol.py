"""
Integration tests for the EVA TUI Backend Protocol.
Tests the JSON message protocol between eva_tui.py (frontend) and eva.py --tui (backend).
Uses actual subprocess with real Agent.

These tests require a valid EVA_API_KEY and are skipped if not available.
"""

import pytest
import json
import subprocess
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eva import AgentContext, Memory, AgentResult


# ============================================================================
# Skip backend tests if no real API key
# ============================================================================

SKIP_BACKEND_TESTS = os.environ.get("EVA_API_KEY", "").startswith("sk-") is False


def get_real_api_key() -> str | None:
    """Get real API key from environment."""
    key = os.environ.get("EVA_API_KEY", "")
    return key if key.startswith("sk-") else None


# ============================================================================
# Backend Protocol Tests
# These require a real API key
# ============================================================================

@pytest.mark.skipif(SKIP_BACKEND_TESTS, reason="Requires real EVA_API_KEY")
class TestBackendProtocol:
    """测试 eva.py --tui 后端的 JSON 协议"""

    @pytest.fixture
    def backend_proc(self):
        """启动后端进程"""
        api_key = get_real_api_key()
        env = {**os.environ, "EVA_API_KEY": api_key}
        proc = subprocess.Popen(
            [sys.executable, "eva.py", "--tui"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        yield proc
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _send_json(self, proc, msg):
        """发送 JSON 消息"""
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def _recv_line(self, proc):
        """接收一行响应（非阻塞读取）"""
        line = proc.stdout.readline()
        if not line:
            stderr = proc.stderr.read()
            raise RuntimeError(f"Backend died. stderr: {stderr}")
        return line.strip()

    def _send_recv(self, proc, msg):
        """发送消息并接收响应"""
        self._send_json(proc, msg)
        line = self._recv_line(proc)
        return json.loads(line)

    def test_ping_returns_pong(self, backend_proc):
        """测试 ping -> pong"""
        resp = self._send_recv(backend_proc, {"type": "ping"})
        assert resp["type"] == "pong"

    def test_init_returns_ready(self, backend_proc):
        """测试 init -> ready"""
        resp = self._send_recv(backend_proc, {"type": "init", "allow_all_cli": False})
        assert resp["type"] == "ready"

    def test_init_with_session_history(self, backend_proc):
        """测试 init 时加载 session_history"""
        resp = self._send_recv(backend_proc, {
            "type": "init",
            "allow_all_cli": False,
            "session_history": [
                {"role": "user", "content": "previous question"},
                {"role": "assistant", "content": "previous answer"},
            ],
        })
        assert resp["type"] == "ready"

    def test_save_session(self, backend_proc):
        """测试 save_session"""
        self._send_recv(backend_proc, {"type": "init", "allow_all_cli": False})
        resp = self._send_recv(backend_proc, {"type": "save_session"})
        assert resp["type"] == "session_saved"

    def test_multiple_pings(self, backend_proc):
        """测试多次 ping"""
        for _ in range(3):
            resp = self._send_recv(backend_proc, {"type": "ping"})
            assert resp["type"] == "pong"

    def test_user_message_returns_response(self, backend_proc):
        """测试 user_message 返回 response"""
        self._send_recv(backend_proc, {"type": "init", "allow_all_cli": False})
        self._send_recv(backend_proc, {"type": "save_session"})  # 不触发 LLM

        # 发消息触发 LLM
        backend_proc.stdin.write(json.dumps({"type": "user_message", "content": "say hello"}) + "\n")
        backend_proc.stdin.flush()

        messages = []
        while True:
            line = backend_proc.stdout.readline()
            if not line:
                break
            msg = json.loads(line.strip())
            messages.append(msg)
            if msg.get("type") == "response":
                break

        responses = [m for m in messages if m.get("type") == "response"]
        assert len(responses) >= 1
        assert responses[0]["status"] in ("completed", "waiting_for_tool")


# ============================================================================
# EvaBackend (Frontend) Integration Tests
# ============================================================================

class TestEvaBackendIntegration:
    """测试 EvaBackend 与后端的集成"""

    def test_backend_responds_to_ping(self):
        """EvaBackend 能接收后端的 pong"""
        from eva_tui import EvaBackend

        backend = EvaBackend()
        received = []

        def on_message(msg):
            received.append(msg)

        backend.start_reader(on_message)
        time.sleep(0.3)
        backend.send({"type": "ping"})
        time.sleep(0.5)
        backend.stop()

        assert len(received) >= 1
        assert any(m.get("type") == "pong" for m in received)

    def test_backend_process_running(self):
        """EvaBackend 启动后进程运行中"""
        from eva_tui import EvaBackend

        backend = EvaBackend()
        assert backend.proc.poll() is None
        backend.stop()


# ============================================================================
# TUI Component Tests
# ============================================================================

class TestMessageBubbleRendering:
    """测试 MessageBubble 渲染"""

    def test_user_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="user", body="hello world")
        text = bubble.render()
        text_str = str(text)
        assert "👤" in text_str
        assert "hello world" in text_str
        assert "You" in text_str

    def test_assistant_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="assistant", body="I am EVA")
        text = bubble.render()
        text_str = str(text)
        assert "🤖" in text_str
        assert "EVA" in text_str

    def test_tool_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="tool", body="ls output")
        text = bubble.render()
        text_str = str(text)
        assert "🔧" in text_str

    def test_system_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="system", body="system message")
        text = bubble.render()
        text_str = str(text)
        assert "⚙️" in text_str

    def test_thinking_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="thinking", body="reasoning...")
        text = bubble.render()
        text_str = str(text)
        assert "💭" in text_str

    def test_unknown_role(self):
        from eva_tui import MessageBubble

        bubble = MessageBubble(role="unknown", body="test")
        text = bubble.render()
        text_str = str(text)
        assert "test" in text_str


class TestEVATUIStructure:
    """测试 EVATUI 类结构"""

    def test_evatui_has_compose(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "compose")
        assert callable(EVATUI.compose)

    def test_evatui_has_on_mount(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "on_mount")
        assert callable(EVATUI.on_mount)

    def test_evatui_has_on_input_submitted(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "on_input_submitted")
        assert callable(EVATUI.on_input_submitted)

    def test_evatui_has_action_clear_conv(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "action_clear_conv")

    def test_evatui_css_defined(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "CSS")
        assert len(EVATUI.CSS) > 50

    def test_evatui_bindings(self):
        from eva_tui import EVATUI
        bindings = EVATUI.BINDINGS
        assert len(bindings) >= 2
        keys = [b.key for b in bindings]
        assert "ctrl+c" in keys
        assert "ctrl+l" in keys


class TestEVATUIMessageHandling:
    """测试 EVATUI 消息处理方法存在"""

    def test_has_on_backend_message(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_on_backend_message")

    def test_has_append_user(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_append_user")

    def test_has_append_tool_start(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_append_tool_start")

    def test_has_append_tool_result(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_append_tool_result")

    def test_has_show_thinking(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_show_thinking")

    def test_has_finalize_response(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_finalize_response")

    def test_has_finalize_thinking(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_finalize_thinking")

    def test_has_append_conv(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_append_conv")

    def test_has_append_system(self):
        from eva_tui import EVATUI
        assert hasattr(EVATUI, "_append_system")
