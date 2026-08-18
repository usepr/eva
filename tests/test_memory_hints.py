import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


EVA_FILE = Path(__file__).resolve().parents[1] / "eva.py"


class FakeModelsResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return b'{"data":[{"id":"deepseek-v4-flash","max_model_len":1000000}]}'


class MemoryHintsTest(unittest.TestCase):
    def test_compaction_uses_new_hints_without_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            eva_home = temp_path / "eva-home"
            project_dir = temp_path / "project"
            project_dir.mkdir()
            old_cwd = os.getcwd()

            try:
                os.chdir(project_dir)
                with patch.dict(
                    os.environ,
                    {
                        "EVA_API_KEY": "test",
                        "EVA_BASE_URL": "https://example.invalid/v1",
                        "EVA_MODEL_NAME": "deepseek-v4-flash",
                        "EVA_HOME": str(eva_home),
                    },
                    clear=False,
                ), patch("urllib.request.urlopen", return_value=FakeModelsResponse()):
                    eva = runpy.run_path(str(EVA_FILE))
            finally:
                os.chdir(old_cwd)

            namespace = eva["leave_memory_hints"].__globals__
            namespace["messages"] = [
                {"role": "system", "content": namespace["SYSTEM_PROMPT"]},
                {"role": "user", "content": "current task"},
                {"role": "assistant", "content": "current work"},
                {"role": "user", "content": namespace["COMPACT_PROMPT"]},
                {"role": "assistant", "content": "archiving memory"},
            ]
            namespace["COMPACT_PANIC"] = True

            namespace["leave_memory_hints"]("NEW_HINT")

            self.assertEqual(Path(namespace["HINT_FILE"]).read_text(encoding="utf-8"), "NEW_HINT")
            self.assertIn("NEW_HINT", namespace["messages"][0]["content"])
            self.assertEqual(namespace["memory_hints"], "NEW_HINT")
            self.assertFalse(namespace["COMPACT_PANIC"])
            self.assertIn(
                "NEW_HINT",
                namespace["build_system_prompt"](
                    namespace["memory_hints"],
                    namespace["COMPACT_NOTE"],
                ),
            )

            namespace["messages"].extend(
                [
                    {"role": "user", "content": "next task"},
                    {"role": "assistant", "content": "next work"},
                    {"role": "user", "content": namespace["COMPACT_PROMPT"]},
                    {"role": "assistant", "content": "archiving memory again"},
                ]
            )
            namespace["COMPACT_PANIC"] = True

            namespace["leave_memory_hints"]("SECOND_HINT")

            self.assertEqual(Path(namespace["HINT_FILE"]).read_text(encoding="utf-8"), "SECOND_HINT")
            self.assertIn("SECOND_HINT", namespace["messages"][0]["content"])
            self.assertNotIn("NEW_HINT", namespace["messages"][0]["content"])
            self.assertEqual(namespace["memory_hints"], "SECOND_HINT")


if __name__ == "__main__":
    unittest.main()
