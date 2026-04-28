"""
补充测试 for eva_tui.py — 针对以下 bug 的测试覆盖：
1. strip_ansi / _render_md 无测试
2. EVATUI 实例变量初始化不完整
3. 消息处理状态流转无测试
4. 工具执行进度指示无测试
5. on_input_submitted 未重置所有状态
6. action_toggle_debug 无测试
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from eva_tui import (
    EVATUI,
    EvaBackend,
    strip_ansi,
)


# ============================================================================
# 1. strip_ansi 工具函数测试
# ============================================================================

class TestStripAnsi:
    """测试 ANSI 转义码去除函数"""

    def test_strip_ansi_removes_sgr_codes(self):
        """测试 ANSI SGR 颜色码"""
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
        assert strip_ansi("\x1b[1;32mbold green\x1b[0m") == "bold green"

    def test_strip_ansi_removes_cursor_codes(self):
        """测试 ANSI 光标/擦除码"""
        assert strip_ansi("\x1b[2Kclear\x1b[0m") == "clear"
        assert strip_ansi("\x1b[J\x1b[0m") == ""

    def test_strip_ansi_handles_empty_string(self):
        assert strip_ansi("") == ""

    def test_strip_ansi_preserves_plain_text(self):
        assert strip_ansi("plain text **bold**") == "plain text **bold**"

    def test_strip_ansi_handles_mixed_content(self):
        """Rich 渲染后的典型输出"""
        raw = "\x1b[2m**thinking**\x1b[0m\n\x1b[0m"
        assert strip_ansi(raw) == "**thinking**\n"

    def test_strip_ansi_removes_reset_all(self):
        assert strip_ansi("\x1b[0m") == ""

    def test_strip_ansi_removes_dim_code(self):
        """测试 \x1b[2m 暗色码"""
        assert strip_ansi("\x1b[2m\x1b[0m") == ""

    def test_strip_ansi_multiple_codes(self):
        """多个 ANSI 码连续出现"""
        text = "\x1b[1;31m\x1b[4m\x1b[0mtext\x1b[0m"
        assert strip_ansi(text) == "text"


# ============================================================================
# 2. EVATUI 实例变量初始化测试
# ============================================================================

class TestEVATUIInit:
    """测试 EVATUI 实例变量正确初始化"""

    def test_evatui_init_initializes_tool_widget(self):
        """验证 _tool_widget 在 __init__ 中初始化为 None"""
        app = EVATUI(debug=False)
        assert hasattr(app, '_tool_widget')
        assert app._tool_widget is None
        app.backend.stop()

    def test_evatui_init_initializes_all_buffers(self):
        """验证所有缓冲区和 widget 变量正确初始化"""
        app = EVATUI(debug=True)
        assert app._thinking_buf == []
        assert app._content_buf == []
        assert app._thinking_widget is None
        assert app._tool_widget is None
        assert app._debug is True
        app.backend.stop()

    def test_evatui_init_default_debug_false(self):
        """验证 debug 默认为 False"""
        app = EVATUI()
        assert app._debug is False
        app.backend.stop()

    def test_evatui_has_render_md_method(self):
        """验证 _render_md 方法存在且可调用"""
        app = EVATUI.__new__(EVATUI)
        assert hasattr(app, '_render_md')
        assert callable(app._render_md)


# ============================================================================
# 3. Markdown 渲染测试
# ============================================================================

class TestRenderMarkdown:
    """测试 Markdown 渲染"""

    def test_render_md_bold_text(self):
        """测试粗体渲染"""
        app = EVATUI.__new__(EVATUI)
        result = app._render_md("**bold text**")
        result_str = str(result)
        assert "bold text" in result_str

    def test_render_md_heading(self):
        app = EVATUI.__new__(EVATUI)
        result = app._render_md("### Heading")
        result_str = str(result)
        assert "Heading" in result_str

    def test_render_md_strips_ansi_first(self):
        """验证 _render_md 内部调用 strip_ansi"""
        app = EVATUI.__new__(EVATUI)
        # 包含 ANSI 码的 Markdown
        result = app._render_md("\x1b[1m**bold with ANSI**\x1b[0m")
        result_str = str(result)
        # ANSI 码应该被去除
        assert "\x1b[" not in result_str
        assert "bold with ANSI" in result_str

    def test_render_md_plain_text(self):
        """纯文本应该直接返回"""
        app = EVATUI.__new__(EVATUI)
        result = app._render_md("plain text without markdown")
        result_str = str(result)
        assert "plain text" in result_str

    def test_render_md_code_block(self):
        app = EVATUI.__new__(EVATUI)
        result = app._render_md("```python\nprint('hello')\n```")
        result_str = str(result)
        assert "print" in result_str


# ============================================================================
# 4. 消息处理状态流转测试（需要 mock call_from_thread）
# ============================================================================

class TestEVATUIStateTransitions:
    """测试消息处理状态流转"""

    def test_thinking_event_buffers_to_buf(self):
        """thinking 事件应该缓冲到 _thinking_buf（通过 mock call_from_thread）"""
        app = EVATUI(debug=False)
        app._thinking_buf = []
        app._content_buf = []

        # Mock call_from_thread so it runs the callback immediately
        def fake_call_from_thread(cb, *args):
            cb(*args)

        app.call_from_thread = fake_call_from_thread
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._on_backend_message({
            "type": "event",
            "event": "thinking",
            "data": "thinking part 1"
        })

        assert len(app._thinking_buf) == 1
        assert "thinking part 1" in app._thinking_buf[0]
        app.backend.stop()

    def test_content_event_buffers_to_buf(self):
        """content 片段应该累积到 _content_buf"""
        app = EVATUI(debug=False)
        app._content_buf = []

        app._on_backend_message({
            "type": "event",
            "event": "content",
            "data": "response content"
        })

        assert len(app._content_buf) == 1
        assert "response content" in app._content_buf[0]
        app.backend.stop()

    def test_multiple_thinking_events_accumulate(self):
        """多个 thinking 片段应该累积"""
        app = EVATUI(debug=False)
        app._thinking_buf = []

        def fake_call_from_thread(cb, *args):
            cb(*args)

        app.call_from_thread = fake_call_from_thread
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        for i in range(3):
            # Mock the widget's remove method to avoid Textual app context issues
            if app._thinking_widget is not None:
                app._thinking_widget.remove = MagicMock()
            app._on_backend_message({
                "type": "event",
                "event": "thinking",
                "data": f"part {i}"
            })

        assert len(app._thinking_buf) == 3
        app.backend.stop()

    def test_multiple_content_events_accumulate(self):
        """多个 content 片段应该累积"""
        app = EVATUI(debug=False)
        app._content_buf = []

        for i in range(2):
            app._on_backend_message({
                "type": "event",
                "event": "content",
                "data": f"content {i}"
            })

        assert len(app._content_buf) == 2
        app.backend.stop()

    def test_ready_message_triggers_initial_greeting(self):
        """ready 消息应该触发初始问候"""
        app = EVATUI(debug=False)
        app.backend = MagicMock()
        app._thinking_buf = []
        app._content_buf = []

        app._on_backend_message({"type": "ready"})

        # 应该发送用户消息
        app.backend.send.assert_called_once()
        call_args = app.backend.send.call_args[0][0]
        assert call_args["type"] == "user_message"
        app.backend.stop()


# ============================================================================
# 5. 工具执行进度指示测试
# ============================================================================

class TestToolExecutionIndicator:
    """测试工具执行进度指示"""

    def test_append_tool_start_removes_thinking_widget(self):
        """_append_tool_start 应该清理 thinking widget"""
        app = EVATUI(debug=False)
        mock_thinking = MagicMock()
        app._thinking_widget = mock_thinking
        app._tool_widget = None

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._append_tool_start("run_cli", {"command": "ls"})

        # 验证 remove 被调用
        mock_thinking.remove.assert_called_once()
        # 验证 _thinking_widget 被设为 None
        assert app._thinking_widget is None
        app.backend.stop()

    def test_append_tool_start_creates_tool_widget(self):
        """_append_tool_start 应该创建 _tool_widget"""
        app = EVATUI(debug=False)
        app._thinking_widget = None
        app._tool_widget = None

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._append_tool_start("run_cli", {"command": "ls"})

        assert app._tool_widget is not None
        mock_scroll.mount.assert_called_once()
        app.backend.stop()

    def test_append_tool_result_removes_tool_widget(self):
        """_append_tool_result 应该移除 _tool_widget"""
        app = EVATUI(debug=False)
        mock_tool = MagicMock()
        app._tool_widget = mock_tool

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._append_tool_result("call_00_test", "command output")

        # 验证 remove 被调用
        mock_tool.remove.assert_called_once()
        # 验证 _tool_widget 被设为 None
        assert app._tool_widget is None
        app.backend.stop()

    def test_append_tool_result_renders_result(self):
        """_append_tool_result 应该渲染 Markdown 结果"""
        app = EVATUI(debug=False)
        app._tool_widget = MagicMock()

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._append_tool_result("call_00_test", "**formatted result**")

        # 应该 mount 一个新的 Static 显示结果
        assert mock_scroll.mount.called
        app.backend.stop()

    def test_append_tool_start_without_thinking_widget(self):
        """_append_tool_start 在没有 thinking_widget 时也应该工作"""
        app = EVATUI(debug=False)
        app._thinking_widget = None
        app._tool_widget = None

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._append_tool_start("run_cli", {"command": "ls"})

        assert app._tool_widget is not None
        app.backend.stop()


# ============================================================================
# 6. 响应终结处理测试
# ============================================================================

class TestResponseFinalization:
    """测试 _finalize_response 处理"""

    def test_finalize_response_clears_buffers(self):
        """_finalize_response 应该清空所有缓冲区"""
        app = EVATUI(debug=False)
        app._thinking_buf = ["thinking1", "thinking2"]
        app._content_buf = ["content1"]
        app._thinking_widget = MagicMock()
        app._tool_widget = MagicMock()
        app.backend = MagicMock()

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._finalize_response({"status": "completed"})

        assert app._thinking_buf == []
        assert app._content_buf == []
        app.backend.stop()

    def test_finalize_response_sends_save_session(self):
        """_finalize_response 应该发送 save_session"""
        app = EVATUI(debug=False)
        app._thinking_buf = []
        app._content_buf = []
        app._thinking_widget = None
        app._tool_widget = None
        app.backend = MagicMock()

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._finalize_response({"status": "completed"})

        app.backend.send.assert_called_once_with({"type": "save_session"})
        app.backend.stop()

    def test_finalize_thinking_removes_widget(self):
        """_finalize_thinking 应该移除 thinking widget"""
        app = EVATUI(debug=False)
        mock_widget = MagicMock()
        app._thinking_widget = mock_widget

        app._finalize_thinking()

        mock_widget.remove.assert_called_once()
        assert app._thinking_widget is None
        app.backend.stop()

    def test_finalize_thinking_handles_none_widget(self):
        """_finalize_thinking 处理 None widget 不应报错"""
        app = EVATUI(debug=False)
        app._thinking_widget = None

        # 不应抛出异常
        app._finalize_thinking()
        assert app._thinking_widget is None
        app.backend.stop()

    def test_finalize_response_with_empty_content(self):
        """_finalize_response 处理空内容不应崩溃"""
        app = EVATUI(debug=False)
        app._thinking_buf = []
        app._content_buf = []
        app._thinking_widget = None
        app._tool_widget = None
        app.backend = MagicMock()

        mock_scroll = MagicMock()
        with patch.object(app, 'query_one', return_value=mock_scroll):
            app._finalize_response({"status": "completed", "content": "", "reasoning": ""})

        # 应该仍然发送 save_session
        app.backend.send.assert_called_once_with({"type": "save_session"})
        app.backend.stop()


# ============================================================================
# 7. 输入提交状态重置测试
# ============================================================================

class TestInputSubmitted:
    """测试 on_input_submitted 状态重置"""

    def _make_mock_event(self, value):
        """创建模拟的 Input.Submitted 事件"""
        mock_input = MagicMock()
        mock_input.value = value
        mock_input.clear = MagicMock()
        event = MagicMock()
        event.value = value
        event.input = mock_input
        return event

    def test_input_submitted_resets_all_buffers(self):
        """提交输入后所有缓冲区应该重置"""
        app = EVATUI(debug=False)
        app._thinking_buf = ["old thinking"]
        app._content_buf = ["old content"]
        app._thinking_widget = MagicMock()
        app._tool_widget = MagicMock()
        app.backend = MagicMock()

        event = self._make_mock_event("new message")

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        assert app._thinking_buf == []
        assert app._content_buf == []
        app.backend.stop()

    def test_input_submitted_resets_thinking_widget(self):
        """提交输入后 _thinking_widget 应该重置"""
        app = EVATUI(debug=False)
        app._thinking_widget = MagicMock()
        app._tool_widget = None
        app.backend = MagicMock()

        event = self._make_mock_event("test")

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        assert app._thinking_widget is None
        app.backend.stop()

    def test_input_submitted_resets_tool_widget(self):
        """提交输入后 _tool_widget 应该重置"""
        app = EVATUI(debug=False)
        app._thinking_widget = None
        app._tool_widget = MagicMock()
        app.backend = MagicMock()

        event = self._make_mock_event("test")

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        assert app._tool_widget is None
        app.backend.stop()

    def test_input_submitted_sends_user_message(self):
        """提交输入后应该发送 user_message 到后端"""
        app = EVATUI(debug=False)
        app._thinking_buf = []
        app._content_buf = []
        app._thinking_widget = None
        app._tool_widget = None
        app.backend = MagicMock()

        event = self._make_mock_event("hello world")

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        app.backend.send.assert_called_once()
        call_args = app.backend.send.call_args[0][0]
        assert call_args["type"] == "user_message"
        assert call_args["content"] == "hello world"
        app.backend.stop()

    def test_input_submitted_ignores_empty_message(self):
        """空消息应该被忽略"""
        app = EVATUI(debug=False)
        app.backend = MagicMock()

        event = self._make_mock_event("   ")

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        app.backend.send.assert_not_called()
        app.backend.stop()

    def test_input_submitted_clears_input(self):
        """提交输入后应该清空输入框"""
        app = EVATUI(debug=False)
        app._thinking_buf = []
        app._content_buf = []
        app._thinking_widget = None
        app._tool_widget = None
        app.backend = MagicMock()

        mock_input = MagicMock()
        mock_input.value = "test message"
        mock_input.clear = MagicMock()
        event = MagicMock()
        event.value = "test message"
        event.input = mock_input

        with patch.object(app, '_append_user'):
            app.on_input_submitted(event)

        mock_input.clear.assert_called_once()
        app.backend.stop()


# ============================================================================
# 8. Debug 模式切换测试
# ============================================================================

class TestDebugMode:
    """测试 debug 模式切换"""

    def test_action_toggle_debug_flips_debug_state(self):
        """Ctrl+D 应该切换 debug 状态"""
        app = EVATUI(debug=False)
        app.query_one = MagicMock(return_value=MagicMock())

        app.action_toggle_debug()
        assert app._debug is True

        app.action_toggle_debug()
        assert app._debug is False
        app.backend.stop()

    def test_action_toggle_debug_updates_header(self):
        """切换 debug 应该更新 header 显示"""
        app = EVATUI(debug=False)
        mock_static = MagicMock()
        app.query_one = MagicMock(return_value=mock_static)

        app.action_toggle_debug()

        mock_static.update.assert_called_once()
        # 验证 DEBUG ON 出现在更新内容中
        update_arg = mock_static.update.call_args[0][0]
        assert "DEBUG ON" in update_arg
        app.backend.stop()

    def test_debug_init_false_by_default(self):
        """debug 默认值为 False"""
        app = EVATUI(debug=False)
        assert app._debug is False
        app.backend.stop()


# ============================================================================
# 9. action_clear_conv 测试
# ============================================================================

class TestClearConversation:
    """测试清空对话功能"""

    def test_action_clear_conv_removes_all_children(self):
        """清空对话应该移除所有子 widget"""
        app = EVATUI(debug=False)

        mock_child1 = MagicMock()
        mock_child2 = MagicMock()
        mock_scroll = MagicMock()
        mock_scroll.children = [mock_child1, mock_child2]
        app.query_one = MagicMock(return_value=mock_scroll)

        app.action_clear_conv()

        mock_child1.remove.assert_called_once()
        mock_child2.remove.assert_called_once()
        app.backend.stop()


# ============================================================================
# 10. _append_system 测试
# ============================================================================

class TestAppendSystem:
    """测试 _append_system 方法"""

    def test_append_system_mounts_static(self):
        """_append_system 应该 mount 一个 Static"""
        app = EVATUI(debug=False)
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._append_system("test message")

        mock_scroll.mount.assert_called_once()
        app.backend.stop()


# ============================================================================
# 11. _append_user 测试
# ============================================================================

class TestAppendUser:
    """测试 _append_user 方法"""

    def test_append_user_mounts_static(self):
        """_append_user 应该 mount 一个 Static"""
        app = EVATUI(debug=False)
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._append_user("hello")

        mock_scroll.mount.assert_called_once()
        app.backend.stop()


# ============================================================================
# 12. _append_conv 测试
# ============================================================================

class TestAppendConv:
    """测试 _append_conv 方法"""

    def test_append_conv_mounts_static(self):
        """_append_conv 应该 mount 一个 Static"""
        app = EVATUI(debug=False)
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._append_conv("assistant", "response content")

        mock_scroll.mount.assert_called_once()
        app.backend.stop()


# ============================================================================
# 13. _show_thinking 测试
# ============================================================================

class TestShowThinking:
    """测试 _show_thinking 方法"""

    def test_show_thinking_mounts_widget(self):
        """_show_thinking 应该 mount 一个 Static"""
        app = EVATUI(debug=False)
        app._thinking_widget = None
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._show_thinking("thinking text")

        mock_scroll.mount.assert_called_once()
        assert app._thinking_widget is not None
        app.backend.stop()

    def test_show_thinking_removes_old_widget(self):
        """_show_thinking 应该移除旧的 widget"""
        app = EVATUI(debug=False)
        old_mock = MagicMock()
        app._thinking_widget = old_mock
        mock_scroll = MagicMock()
        app.query_one = MagicMock(return_value=mock_scroll)

        app._show_thinking("new thinking")

        # 旧的 widget 应该被移除
        old_mock.remove.assert_called_once()
        # 新的 widget 应该被 mount
        mock_scroll.mount.assert_called_once()
        # _thinking_widget 应该指向新 widget
        assert app._thinking_widget is not None
        assert app._thinking_widget is not old_mock
        app.backend.stop()
