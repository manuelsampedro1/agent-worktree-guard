import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_worktree_guard import cli


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


class WorktreeGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snapshot_tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        run(["git", "init", "-q"], self.repo)
        run(["git", "config", "user.name", "Agent Worktree Guard"], self.repo)
        run(["git", "config", "user.email", "agent-worktree-guard@example.com"], self.repo)
        (self.repo / "README.md").write_text("stable\n", encoding="utf-8")
        run(["git", "add", "README.md"], self.repo)
        run(["git", "commit", "-qm", "initial"], self.repo)

    def tearDown(self):
        self.snapshot_tmp.cleanup()
        self.tmp.cleanup()

    def snapshot_path(self):
        path = Path(self.snapshot_tmp.name) / "snapshot.json"
        rc = cli.main(["snapshot", "--base-dir", str(self.repo), "--output", str(path)])
        self.assertEqual(rc, 0)
        return path

    def test_snapshot_records_dirty_file_hashes(self):
        notes = self.repo / "notes"
        notes.mkdir()
        (notes / "draft.md").write_text("user draft\n", encoding="utf-8")

        snapshot = json.loads(self.snapshot_path().read_text(encoding="utf-8"))

        self.assertEqual(snapshot["schema"], "agent-worktree-guard/v1")
        paths = {entry["path"] for entry in snapshot["dirty"]}
        self.assertIn("notes/draft.md", paths)
        entry = next(item for item in snapshot["dirty"] if item["path"] == "notes/draft.md")
        self.assertEqual(len(entry["sha256"]), 64)

    def test_check_passes_when_allowed_agent_path_changes(self):
        notes = self.repo / "notes"
        notes.mkdir()
        (notes / "draft.md").write_text("user draft\n", encoding="utf-8")
        snapshot = self.snapshot_path()

        src = self.repo / "src"
        src.mkdir()
        (src / "change.py").write_text("print('agent')\n", encoding="utf-8")

        rc = cli.main(["check", str(snapshot), "--base-dir", str(self.repo), "--allow", "src/**"])

        self.assertEqual(rc, 0)

    def test_check_blocks_protected_file_drift(self):
        notes = self.repo / "notes"
        notes.mkdir()
        draft = notes / "draft.md"
        draft.write_text("user draft\n", encoding="utf-8")
        snapshot = self.snapshot_path()

        draft.write_text("agent touched this\n", encoding="utf-8")

        rc = cli.main(["check", str(snapshot), "--base-dir", str(self.repo), "--allow", "src/**"])

        self.assertEqual(rc, 1)

    def test_check_blocks_unexpected_new_dirty_path(self):
        snapshot = self.snapshot_path()
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "deploy.sh").write_text("#!/bin/sh\n", encoding="utf-8")

        rc = cli.main(["check", str(snapshot), "--base-dir", str(self.repo), "--allow", "src/**"])

        self.assertEqual(rc, 1)

    def test_check_outputs_json_report(self):
        snapshot = self.snapshot_path()
        (self.repo / "README.md").write_text("changed\n", encoding="utf-8")

        rc = cli.main(["check", str(snapshot), "--base-dir", str(self.repo), "--allow", "README.md", "--format", "json"])

        self.assertEqual(rc, 0)

    def test_module_exit_code_blocks_drift(self):
        notes = self.repo / "notes"
        notes.mkdir()
        draft = notes / "draft.md"
        draft.write_text("user draft\n", encoding="utf-8")
        snapshot = self.snapshot_path()
        draft.write_text("agent touched this\n", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        proc = subprocess.run(
            [
                "python3",
                "-m",
                "agent_worktree_guard",
                "check",
                str(snapshot),
                "--base-dir",
                str(self.repo),
                "--allow",
                "src/**",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )

        self.assertEqual(proc.returncode, 1)
        self.assertIn("Protected file drifted", proc.stdout)


if __name__ == "__main__":
    unittest.main()
