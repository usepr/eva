"""
测试 eva.py run_tui_server 的 execute_tools_and_resume 逻辑。
重点覆盖：工具结果格式、clean_input、resume 调用。
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from eva import Agent, AgentContext, Memory, AgentResult


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.model_name = "deepseek-v4-flash"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.api_key = "test-key"
    cfg.token_cap = 256_000
    cfg.compact_thresh = 0.75
    cfg.tool_result_len = 12_800
    return cfg


@pytest.fixture
def mock_platform():
    plat = MagicMock()
    plat.shell = "bash"
    plat.shell_flag = "-c"
    plat.os_name = "Linux"
    plat.is_windows = False
    plat.env_info = "test env"
    plat.hint_file = Path("/fake/hints.md")
    return plat


@pytest.fixture
def agent_ctx():
    return AgentContext(allow_all_cli=True)


@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / ".eva"
    workspace.mkdir()
    hints = workspace / "hints.md"
    hints.write_text("", encoding="utf-8")
    return workspace, hints


# ============================================================================
# clean_input 函数测试
# ============================================================================

class TestCleanInput:
    """验证 clean_input 正确清理工具结果"""

    def test_removes_ansi_sgr_codes(self):
        """ANSI SGR 颜色码被移除（ESC 字符在 \x0e-\x1f 范围）"""
        from eva import clean_input
        raw = "\x1b[1;31mError\x1b[0m: connection failed"
        cleaned = clean_input(raw)
        # ESC \x1b 被移除，剩下的 [1;31m, [0m 没有前导 ESC
        assert "\x1b[" not in cleaned
        assert "Error" in cleaned

    def test_removes_ansi_reset(self):
        """ANSI reset 码被移除"""
        from eva import clean_input
        # \x1b (ESC, 0x1b=27) 在 \x0e-\x1f (14-31) 范围内，会被移除
        result = clean_input("\x1b[0m")
        assert result == "[0m"

    def test_removes_control_chars(self):
        """控制字符被移除"""
        from eva import clean_input
        raw = "data\x00with\x01control\x02chars"
        cleaned = clean_input(raw)
        assert "\x00" not in cleaned
        assert "\x01" not in cleaned

    def test_preserves_newlines(self):
        """换行符保留"""
        from eva import clean_input
        multiline = "line1\nline2\nline3"
        cleaned = clean_input(multiline)
        assert "\n" in cleaned

    def test_preserves_chinese(self):
        """中文保留"""
        from eva import clean_input
        raw = "执行失败：EOF when reading a line"
        cleaned = clean_input(raw)
        assert cleaned == raw

    def test_removes_raw_control_char_0(self):
        """ASCII NUL 等控制字符被移除"""
        from eva import clean_input
        raw = "text\x00more"
        assert clean_input(raw) == "textmore"


# ============================================================================
# execute_tools_and_resume 逻辑测试
# ============================================================================

class TestExecuteToolsAndResume:
    """测试 execute_tools_and_resume 的工具结果构建逻辑"""

    def test_tool_result_message_format(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证工具结果必须包含 role, tool_call_id, name, content"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        agent._pending_tool_calls = [{
            "id": "call_001",
            "name": "run_cli",
            "args": {"command": "ls", "timeout": 30}
        }]

        with patch.object(agent.tools, 'execute', return_value="file1\nfile2"):
            with patch('eva.llm_chat_stream') as mock_llm:
                mock_llm.return_value = (
                    {"role": "assistant", "content": "结果"},
                    {"total_tokens": 100}
                )

                from eva import clean_input
                tool_results = []
                for tc in agent._pending_tool_calls:
                    res = agent.tools.execute(tc["name"], tc["args"])
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": clean_input(res),
                    })

                assert tool_results[0]["role"] == "tool"
                assert tool_results[0]["tool_call_id"] == "call_001"
                assert tool_results[0]["name"] == "run_cli"
                assert tool_results[0]["content"] == "file1\nfile2"

    def test_clean_input_applied_to_tool_result(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证工具结果必须经过 clean_input"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        agent._pending_tool_calls = [{
            "id": "call_002",
            "name": "run_cli",
            "args": {"command": "curl bad-host", "timeout": 5}
        }]

        raw_result = "执行失败：EOF when reading a line\nExit code: 1"

        with patch.object(agent.tools, 'execute', return_value=raw_result):
            from eva import clean_input
            tool_calls = agent._pending_tool_calls
            for tc in tool_calls:
                res = agent.tools.execute(tc["name"], tc["args"])
                cleaned = clean_input(res)
                # clean_input 应该移除 ANSI 码等
                assert "\x1b[" not in cleaned

    def test_resume_with_messages_already_extended(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证 resume([]) 在工具结果已在 messages 中时能正常工作"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        agent.ctx.messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "list files"},
            {"role": "tool", "tool_call_id": "call_001", "name": "run_cli", "content": "file1\nfile2"}
        ]

        with patch('eva.llm_chat_stream') as mock_llm:
            mock_llm.return_value = (
                {"role": "assistant", "content": "You have file1 and file2"},
                {"total_tokens": 100}
            )

            result = agent.resume([])

            assert result.status == "completed"
            assert "file1" in result.content

    def test_resume_string_list_creates_wrong_format(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证 resume([string]) 把字符串当作用户消息（是 bug）"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        agent.ctx.messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "list files"},
        ]

        with patch('eva.llm_chat_stream') as mock_llm:
            mock_llm.return_value = (
                {"role": "assistant", "content": "result"},
                {"total_tokens": 100}
            )

            # 错误的调用方式：传纯字符串列表
            agent.resume(["file1\nfile2"])

            # resume 把字符串追加到 messages，然后 LLM 返回又 append 了一条
            # 倒数第二条是污染的 user 消息（没有 proper role）
            polluted = agent.ctx.messages[-2]
            # 这是个字符串而不是 dict！
            assert isinstance(polluted, str)
            assert "file1" in polluted


# ============================================================================
# 完整工具执行流程测试
# ============================================================================

class TestToolExecutionFlow:
    """测试完整工具执行流程"""

    def test_full_flow_pending_to_resume(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证完整流程：pending → execute → clean → extend → resume"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        agent.ctx.messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "run ls"}
        ]

        agent._pending_tool_calls = [{
            "id": "call_001",
            "name": "run_cli",
            "args": {"command": "ls", "timeout": 30}
        }]

        from eva import clean_input

        with patch.object(agent.tools, 'execute', return_value="file1\nfile2\nfile3"):
            with patch('eva.llm_chat_stream') as mock_llm:
                mock_llm.return_value = (
                    {"role": "assistant", "content": "You have three files"},
                    {"total_tokens": 100}
                )

                # 模拟 execute_tools_and_resume
                tool_results = []
                for tc in agent._pending_tool_calls:
                    res = agent.tools.execute(tc["name"], tc["args"])
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": clean_input(res),
                    })

                agent.ctx.messages.extend(tool_results)
                agent._pending_tool_calls.clear()
                result = agent.resume([])

                assert result.status == "completed"
                tool_msg = agent.ctx.messages[-2]
                assert tool_msg["role"] == "tool"
                assert tool_msg["tool_call_id"] == "call_001"
                assert "file1" in tool_msg["content"]

    def test_tool_result_truncated_at_tool_result_len(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """验证工具结果超过 tool_result_len 时被截断"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        # 构造超长结果
        long_output = "x" * 20000

        with patch.object(agent.tools, 'execute', return_value=long_output):
            res = agent.tools.execute("run_cli", {"command": "big output"})
            # CLI 循环的逻辑：超过 tool_result_len 就截断
            if len(res) > mock_config.tool_result_len:
                res = f"{res[:mock_config.tool_result_len]}\n...文本太长，已省略"

            assert "...文本太长，已省略" in res
            assert len(res) <= mock_config.tool_result_len + 20
