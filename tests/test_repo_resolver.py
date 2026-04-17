import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.resolve_cchv_repo import resolve_repo_dir


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "app.py").write_text("# app\n", encoding="utf-8")
    (path / "static").mkdir()
    return path


class ResolveRepoDirTests(unittest.TestCase):
    def test_resolves_repo_when_launcher_lives_inside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp) / "Codex-Claude-History-Viewer")
            script_dir = repo / "scripts"
            script_dir.mkdir()

            result = resolve_repo_dir(script_dir=script_dir, cwd=Path(tmp), env={}, home=Path(tmp))

            self.assertEqual(result, repo.resolve())

    def test_probes_workspace_repos_from_skill_script_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            repo = make_repo(workspace / "repos" / "Codex-Claude-History-Viewer")
            script_dir = workspace / "skills" / "codex-claude-history-viewer" / "scripts"
            script_dir.mkdir(parents=True)

            result = resolve_repo_dir(script_dir=script_dir, cwd=Path(tmp), env={}, home=Path(tmp))

            self.assertEqual(result, repo.resolve())

    def test_explicit_hint_has_priority_over_probe_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            preferred = make_repo(Path(tmp) / "preferred")
            workspace_repo = make_repo(Path(tmp) / "workspace" / "repos" / "Codex-Claude-History-Viewer")
            script_dir = Path(tmp) / "workspace" / "skills" / "codex-claude-history-viewer" / "scripts"
            script_dir.mkdir(parents=True)

            result = resolve_repo_dir(
                hint=str(preferred),
                script_dir=script_dir,
                cwd=Path(tmp),
                env={},
                home=Path(tmp),
            )

            self.assertEqual(result, preferred.resolve())
            self.assertNotEqual(result, workspace_repo.resolve())


if __name__ == "__main__":
    unittest.main()
