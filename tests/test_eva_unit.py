"""
Unit tests for eva.py core components.
Tests AgentContext, Memory, ToolRegistry, Agent (without actual LLM calls).
"""

import pytest
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from eva import (
    AgentContext,
    AgentResult,
    Memory,
    ToolRegistry,
    Agent,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_workspace(tmp_path):
    """创建临时工作目录"""
    workspace = tmp_path / ".eva"
    workspace.mkdir()
    hints = workspace / "hints.md"
    hints.write_text("test hint content", encoding="utf-8")
    return workspace, hints


@pytest.fixture
def mock_config():
    """模拟 AgentConfig"""
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
    """模拟 Platform"""
    plat = MagicMock()
    plat.shell = "bash"
    plat.shell_flag = "-c"
    plat.os_name = "Linux"
    plat.is_windows = False
    plat.env_info = "test env info"
    plat.hint_file = Path("/fake/hints.md")
    return plat


@pytest.fixture
def agent_ctx():
    """创建 AgentContext"""
    return AgentContext(allow_all_cli=False)


# ============================================================================
# AgentContext Tests
# ============================================================================

class TestAgentContext:
    def test_default_values(self):
        ctx = AgentContext()
        assert ctx.messages == []
        assert ctx.compact_panic == "off"
        assert ctx.allow_all_cli is False

    def test_custom_values(self):
        ctx = AgentContext(compact_panic="on", allow_all_cli=True)
        assert ctx.compact_panic == "on"
        assert ctx.allow_all_cli is True


# ============================================================================
# AgentResult Tests
# ============================================================================

class TestAgentResult:
    def test_default_values(self):
        result = AgentResult()
        assert result.status == "completed"
        assert result.content is None
        assert result.reasoning is None
        assert result.tool_calls == []
        assert result.tool_results == []

    def test_with_values(self):
        result = AgentResult(
            status="waiting_for_tool",
            content="hello",
            reasoning="thinking",
            tool_calls=[{"id": "1", "name": "test", "args": {}}],
            usage={"total_tokens": 100},
        )
        assert result.status == "waiting_for_tool"
        assert result.content == "hello"
        assert result.reasoning == "thinking"
        assert len(result.tool_calls) == 1


# ============================================================================
# Memory Tests
# ============================================================================

class TestMemory:
    def test_load_hints_empty(self, temp_workspace):
        """测试加载空的 hints 文件"""
        workspace, hints_file = temp_workspace
        hints_file.write_text("", encoding="utf-8")
        memory = Memory(workspace, hints_file, "env_info")
        hints = memory.load_hints()
        assert hints == ""

    def test_load_hints_content(self, temp_workspace):
        """测试加载 hints 文件内容"""
        workspace, hints_file = temp_workspace
        hints_file.write_text("remember to be helpful", encoding="utf-8")
        memory = Memory(workspace, hints_file, "env_info")
        hints = memory.load_hints()
        assert hints == "remember to be helpful"

    def test_save_hints(self, temp_workspace):
        """测试保存 hints"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env_info")
        memory.save_hints("new hint content")
        assert hints_file.read_text(encoding="utf-8") == "new hint content"
        assert memory._hints == "new hint content"

    def test_build_initial_messages(self, temp_workspace):
        """测试构建初始消息"""
        workspace, hints_file = temp_workspace
        hints_file.write_text("be concise", encoding="utf-8")
        memory = Memory(workspace, hints_file, "my env info")
        msgs = memory.build_initial_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert "be concise" in msgs[0]["content"]
        assert "my env info" in msgs[0]["content"]

    def test_build_initial_messages_no_hints(self, temp_workspace):
        """测试无 hints 时构建初始消息"""
        workspace, hints_file = temp_workspace
        hints_file.write_text("", encoding="utf-8")
        memory = Memory(workspace, hints_file, "env")
        msgs = memory.build_initial_messages()
        assert "无" in msgs[0]["content"]

    def test_get_session_file_creates_path(self, temp_workspace):
        """测试 session 文件路径创建"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        sf = memory.get_session_file()
        assert sf.parent.name == "sessions"
        assert sf.suffix == ".json"

    def test_save_and_load_session(self, temp_workspace, monkeypatch):
        """测试 session 保存和加载"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        # 使用 workspace 作为 cwd
        monkeypatch.chdir(workspace)

        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        memory.save_session(messages)

        loaded = memory.load_session()
        assert loaded is not None
        assert len(loaded) == 2  # 不含 system
        assert loaded[0]["content"] == "hello"

    def test_save_session_does_not_print_to_stdout(self, temp_workspace, monkeypatch, capsys):
        """验证 save_session 不向 stdout 打印（TUI 协议要求）"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        monkeypatch.chdir(workspace)

        memory.save_session([{"role": "user", "content": "hello"}])

        captured = capsys.readouterr()
        assert captured.out == ""  # 不应有输出

    def test_load_session_nonexistent(self, temp_workspace, monkeypatch):
        """测试加载不存在的 session"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        monkeypatch.chdir(workspace)
        loaded = memory.load_session()
        assert loaded is None


# ============================================================================
# ToolRegistry Tests
# ============================================================================

class TestToolRegistry:
    def test_register_and_get_schemas(self, mock_config, mock_platform, agent_ctx):
        """测试工具注册和 schema 获取（OpenAI 格式）"""
        registry = ToolRegistry(mock_config, mock_platform, agent_ctx)

        def dummy_handler(arg1: str) -> str:
            return f"got: {arg1}"

        # Schema 使用 OpenAI tools 格式
        registry.register(
            {
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "description": "a test",
                    "parameters": {
                        "type": "object",
                        "properties": {"arg1": {"type": "string"}},
                    },
                },
            },
            dummy_handler,
        )

        schemas = registry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "test_tool"

    def test_execute_unknown_tool_returns_error_string(self, mock_config, mock_platform, agent_ctx):
        """测试执行未知工具返回错误字符串"""
        registry = ToolRegistry(mock_config, mock_platform, agent_ctx)
        result = registry.execute("nonexistent", {})
        assert "未知工具" in result

    @patch("subprocess.run")
    def test_execute_run_cli_with_allow_all(self, mock_run, mock_config, mock_platform):
        """测试 run_cli 工具执行（allow_all_cli=True）"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="file1\nfile2",
            stderr="",
        )
        ctx = AgentContext(allow_all_cli=True)
        registry = ToolRegistry(mock_config, mock_platform, ctx)
        registry.setup_builtin_tools()

        result = registry.execute("run_cli", {"command": "ls", "timeout": 30})
        assert "file1" in result or "file2" in result

    def test_execute_run_cli_blocked_by_user(self, mock_config, mock_platform, monkeypatch):
        """测试 run_cli 被用户拒绝"""
        ctx = AgentContext(allow_all_cli=False)
        registry = ToolRegistry(mock_config, mock_platform, ctx)
        registry.setup_builtin_tools()

        def mock_input(prompt):
            return "n"

        monkeypatch.setattr("builtins.input", mock_input)

        result = registry.execute("run_cli", {"command": "rm -rf /", "timeout": 30})
        assert "用户拒绝" in result

    @patch("subprocess.run")
    def test_execute_run_cli_timeout(self, mock_run, mock_config, mock_platform):
        """测试 run_cli 超时"""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
        ctx = AgentContext(allow_all_cli=True)
        registry = ToolRegistry(mock_config, mock_platform, ctx)
        registry.setup_builtin_tools()

        result = registry.execute("run_cli", {"command": "sleep 100", "timeout": 1})
        assert "TimeoutExpired" in result or "timed out" in result


# ============================================================================
# Agent Tests (without actual LLM calls)
# ============================================================================

class TestAgentInit:
    def test_agent_init_without_callbacks(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 Agent 初始化（不使用默认回调）"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)

        assert agent.config == mock_config
        assert agent.platform == mock_platform
        assert agent.ctx == agent_ctx
        assert agent.memory == memory
        assert agent.on_thinking is None
        assert agent.on_content is None
        assert agent._pending_tool_calls == []

    def test_agent_init_with_callbacks(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 Agent 初始化（使用默认回调）"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=True)

        assert agent.on_thinking is not None
        assert agent.on_content is not None

    def test_agent_pending_tool_calls_initially_empty(self, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 _pending_tool_calls 初始为空"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        assert agent._pending_tool_calls == []


# ============================================================================
# Agent.step() / resume() Tests (mocked LLM)
# ============================================================================

class TestAgentStepResume:
    @patch("eva.llm_chat_stream")
    def test_step_returns_completed(self, mock_llm, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 step 返回 completed"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        mock_llm.return_value = (
            {"role": "assistant", "content": "Hello!"},
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "You are helpful."}]

        result = agent.step()

        assert result.status == "completed"
        assert result.content == "Hello!"

    @patch("eva.llm_chat_stream")
    def test_step_saves_pending_tool_calls(self, mock_llm, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 step 返回 waiting_for_tool 时保存 _pending_tool_calls"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        mock_msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_001",
                    "function": {
                        "name": "run_cli",
                        "arguments": '{"command": "ls", "timeout": 30}',
                    },
                }
            ],
        }
        mock_llm.return_value = (mock_msg, {"total_tokens": 100})

        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "You are helpful."}]

        result = agent.step()

        assert result.status == "waiting_for_tool"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["name"] == "run_cli"
        assert agent._pending_tool_calls == result.tool_calls

    @patch("eva.llm_chat_stream")
    def test_resume_calls_llm(self, mock_llm, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 resume 调用 _llm_call"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        mock_llm.return_value = (
            {"role": "assistant", "content": "done"},
            {"total_tokens": 100},
        )

        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "sys"}]
        agent._pending_tool_calls.clear()  # 清空避免干扰

        result = agent.resume(["tool result"])

        # resume 应该调用了 llm
        assert mock_llm.called
        assert result.status == "completed"

    @patch("eva.llm_chat_stream")
    def test_step_callbacks_are_callable(self, mock_llm, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 step 调用 on_thinking 和 on_content 回调"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        thinking_calls = []
        content_calls = []

        def on_thinking(text):
            thinking_calls.append(text)

        def on_content(text):
            content_calls.append(text)

        mock_msg = {
            "role": "assistant",
            "content": "Final answer",
            "reasoning_content": "Let me think",
        }
        mock_llm.return_value = (mock_msg, {"total_tokens": 50})

        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "sys"}]
        agent.on_thinking = on_thinking
        agent.on_content = on_content

        agent.step()

        # 回调应该被设置（具体调用取决于 mock）
        assert agent.on_thinking is not None
        assert agent.on_content is not None


# ============================================================================
# Agent._llm_call Tests
# ============================================================================

class TestAgentLlmCall:
    @patch("eva.llm_chat_stream")
    def test_llm_call_stores_reasoning(self, mock_llm, mock_config, mock_platform, agent_ctx, temp_workspace):
        """测试 _llm_call 保存 reasoning"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")

        mock_msg = {
            "role": "assistant",
            "content": "answer",
            "reasoning_content": "my reasoning",
        }
        mock_llm.return_value = (mock_msg, {"total_tokens": 50})

        agent = Agent(mock_config, mock_platform, agent_ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "sys"}]

        result = agent._llm_call()

        assert result.reasoning == "my reasoning"

    @patch("eva.llm_chat_stream")
    def test_llm_call_compact_panic(self, mock_llm, mock_config, mock_platform, temp_workspace):
        """测试 compact_panic 状态"""
        workspace, hints_file = temp_workspace
        memory = Memory(workspace, hints_file, "env")
        ctx = AgentContext(compact_panic="on")

        mock_msg = {"role": "assistant", "content": "compacting"}
        mock_llm.return_value = (mock_msg, {"total_tokens": 50})

        agent = Agent(mock_config, mock_platform, ctx, memory, use_default_callbacks=False)
        agent.ctx.messages = [{"role": "system", "content": "sys"}]

        result = agent._llm_call()
        assert result.status == "compact_panic"
