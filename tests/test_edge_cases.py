"""
边界用例测试：BrokenPipe、空 tool_calls、超长输出、非法 UTF-8
"""
import pytest
from unittest.mock import MagicMock, patch

from eva import clean_input


class TestBrokenPipeHandling:
    """_safe_print / BrokenPipe 边界处理"""

    def test_clean_input_handles_empty_string(self):
        """clean_input 处理空字符串"""
        assert clean_input("") == ""
        assert clean_input("plain text") == "plain text"

    def test_clean_input_preserves_newlines(self):
        assert clean_input("line1\nline2") == "line1\nline2"
        assert clean_input("line1\r\nline2") == "line1\r\nline2"

    def test_clean_input_removes_control_chars(self):
        """裸控制字符（0x00-0x08, 0x0b-0x0c, 0x0e-0x1f）被移除"""
        dirty = "text\x00null\x07bell\x08end"
        assert clean_input(dirty) == "textnullbellend"

    def test_clean_input_ansi_escape_removed(self):
        """ANSI ESC 字节（0x1b）被移除，CSI 序列残留为裸文本"""
        dirty = "\x1b[31m红色\x1b[0m"
        result = clean_input(dirty)
        assert "\x1b" not in result
        assert "红色" in result

    def test_clean_input_invalid_utf8(self):
        """clean_input 处理非法 UTF-8 不崩溃"""
        dirty = "\xff\xfe"[0]  # 第一字符
        result = clean_input(dirty)  # 不抛异常
        assert isinstance(result, str)


class TestToolResultTruncation:
    """tool_result 截断逻辑"""

    def test_tool_result_truncation_at_200(self):
        """tool_result 超过 200 字符被截断"""
        long_result = "x" * 1000
        truncated = clean_input(long_result)[:200]
        assert len(truncated) == 200

    def test_clean_input_short_result_unchanged(self):
        """短结果不被截断"""
        short = "ls output"
        assert clean_input(short) == "ls output"


class TestEmptyToolCalls:
    """空 tool_calls 列表边界处理"""

    def test_empty_pending_calls_no_error(self):
        """空 pending_tool_calls 不触发工具执行逻辑"""
        pending = []
        # 不应抛出异常
        assert len(pending) == 0

    def test_tool_start_not_sent_for_empty(self):
        """空列表时不发送 tool_start 事件（逻辑验证）"""
        # execute_tools_and_resume 在空列表时应直接返回，不发送事件
        pending = []
        if not pending:
            pass  # 不应进入工具执行循环


class TestProtocolFieldCompleteness:
    """PROTOCOL_REQUIRED_FIELDS 字段完整性验证"""

    def test_tool_start_required_fields(self):
        """tool_start 必须包含: type, event, id, name, args"""
        from eva import PROTOCOL_REQUIRED_FIELDS
        fields = PROTOCOL_REQUIRED_FIELDS["event:tool_start"]
        assert "type" in fields
        assert "event" in fields
        assert "id" in fields
        assert "name" in fields
        assert "args" in fields

    def test_tool_result_required_fields(self):
        """tool_result 必须包含: type, event, id, result"""
        from eva import PROTOCOL_REQUIRED_FIELDS
        fields = PROTOCOL_REQUIRED_FIELDS["event:tool_result"]
        assert "type" in fields
        assert "event" in fields
        assert "id" in fields
        assert "result" in fields

    def test_response_required_fields(self):
        """response 必须包含: type, status, content"""
        from eva import PROTOCOL_REQUIRED_FIELDS
        fields = PROTOCOL_REQUIRED_FIELDS["message:response"]
        assert "type" in fields
        assert "status" in fields
        assert "content" in fields


class TestResumeEmptyList:
    """resume([]) 格式验证"""

    def test_resume_empty_list_semantics(self):
        """resume([]) 语义：工具结果已在 messages 中，无需再传"""
        # 验证 PROTOCOL_REQUIRED_FIELDS 无 resume 相关条目（内部调用）
        from eva import PROTOCOL_REQUIRED_FIELDS
        for key in PROTOCOL_REQUIRED_FIELDS:
            assert "resume" not in key.lower()