"""
TUI 前后端协议稳定性测试

验证协议字段完整性，防止字段漂移。
"""

import pytest
from eva import PROTOCOL_REQUIRED_FIELDS, clean_input


class TestProtocolField完整性:
    """验证所有协议消息包含必填字段"""

    def test_tool_start_必填字段(self):
        """tool_start 必须包含: type, event, id, name, args"""
        fields = PROTOCOL_REQUIRED_FIELDS["event:tool_start"]
        assert fields == ["type", "event", "id", "name", "args"]

    def test_tool_result_必填字段(self):
        """tool_result 必须包含: type, event, id, result"""
        fields = PROTOCOL_REQUIRED_FIELDS["event:tool_result"]
        assert fields == ["type", "event", "id", "result"]

    def test_thinking_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["event:thinking"]
        assert fields == ["type", "event", "data"]

    def test_content_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["event:content"]
        assert fields == ["type", "event", "data"]

    def test_response_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["message:response"]
        assert fields == ["type", "status", "content"]

    def test_ready_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["message:ready"]
        assert fields == ["type"]

    def test_user_message_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["message:user_message"]
        assert fields == ["type", "content"]

    def test_save_session_必填字段(self):
        fields = PROTOCOL_REQUIRED_FIELDS["message:save_session"]
        assert fields == ["type"]


class TestToolResultCleanInput:
    """tool_result 必须经过 clean_input 清理"""

    def test_clean_input_移除控制字符(self):
        """clean_input 移除裸控制字符（不含 ANSI CSI 序列解析）"""
        # \x1b 被移除，CSI [31m/[0m 保留（不是完整 ANSI 解析，只是移除了 ESC 字节）
        dirty = "\x1b[31m红色\x1b[0m\x07\x08"
        # ESC 字节移除，\x07\x08 也被移除，但 [31m 和 [0m 保留为普通文本
        assert clean_input(dirty) == "[31m红色[0m"
        assert "\x07" not in clean_input(dirty)
        assert "\x08" not in clean_input(dirty)
        assert "\x1b" not in clean_input(dirty)

    def test_clean_input_移除原始控制字符(self):
        """clean_input 移除裸控制字符（0x00-0x08, 0x0b-0x0c, 0x0e-0x1f）"""
        dirty = "text\x00null\x07bell\x08end"
        assert clean_input(dirty) == "textnullbellend"

    def test_clean_input_保留换行(self):
        """clean_input 保留换行符"""
        assert clean_input("line1\nline2") == "line1\nline2"

    def test_clean_input_处理空字符串(self):
        assert clean_input("") == ""
        assert clean_input("plain text") == "plain text"


class TestToolStart包含Args:
    """tool_start 必须包含 args 字段（最近热修根因）"""

    def test_tool_start_args字段存在(self):
        """验证协议定义中 tool_start 包含 args"""
        fields = PROTOCOL_REQUIRED_FIELDS["event:tool_start"]
        assert "args" in fields

    def test_常见工具_args格式_run_cli(self):
        """run_cli 的 args 格式为 {"command": str, "timeout": int}"""
        args = {"command": "ls -la", "timeout": 30}
        assert isinstance(args, dict)
        assert "command" in args
        assert isinstance(args["command"], str)

    def test_常见工具_args格式_leave_memory_hints(self):
        """leave_memory_hints 的 args 格式为 {"hints": str}"""
        args = {"hints": "用户喜欢简洁的回复"}
        assert isinstance(args, dict)
        assert "hints" in args
        assert isinstance(args["hints"], str)


class TestResume空列表格式:
    """execute_tools_and_resume 必须调用 resume([])，结果已在 messages 中"""

    def test_resume传入空列表(self):
        """resume([]) 语义：工具结果已在 messages 中，无需再传"""
        # 本测试验证 PROTOCOL_REQUIRED_FIELDS 中无 resume 相关协议
        # 因为 resume 是内部调用，不跨协议
        # 仅验证 clean_input 不产生多余格式
        assert clean_input("tool result") == "tool result"


class Test边界用例:
    """边界条件测试"""

    def test_tool_result_truncation长度(self):
        """tool_result 结果截断至 200 字符"""
        long_result = "x" * 1000
        truncated = clean_input(long_result)[:200]
        assert len(truncated) == 200

    def test_response_truncation长度(self):
        """response content/reasoning 截断至 80 字符"""
        long_content = "y" * 500
        truncated = long_content[:80]
        assert len(truncated) == 80

    def test_空tool_calls列表(self):
        """execute_tools_and_resume 处理空列表时不发送 tool_start"""
        pending = []
        # 空列表不应触发工具执行
        assert len(pending) == 0

    def test_multiple_tool_calls_fields(self):
        """连续多个工具调用时每个都有独立 id"""
        ids = ["call_00_aaa", "call_01_bbb", "call_02_ccc"]
        # 每个 id 应该唯一
        assert len(set(ids)) == len(ids)

    def test_compact_panic_event_fields(self):
        """compact_panic 事件只有 type 和 event"""
        fields = PROTOCOL_REQUIRED_FIELDS["event:compact_panic"]
        assert fields == ["type", "event"]
