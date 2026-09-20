"""Black-box checks for the repository's documentation validator."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_docs.py"

class DocumentationCheckerTests(unittest.TestCase):
    def run_checker(self, content, extra=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text(content, encoding="utf-8")
            for name, text in (extra or {}).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            return subprocess.run([sys.executable, str(SCRIPT), str(root)], text=True, capture_output=True)

    def test_valid_local_link(self):
        result = self.run_checker("[Guide](guide.md)\n", {"guide.md": "# Guide\n"})
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_broken_local_link(self):
        result = self.run_checker("[Gone](missing.md)\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing.md", result.stdout)

    def test_site_without_title_is_rejected(self):
        result = self.run_checker("# Readme\n", {"site/index.html": "<html><body>No title</body></html>"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("title", result.stdout)

    def test_fenced_examples_are_not_checked_as_docs(self):
        result = self.run_checker("```md\n[sample](not-a-real-file.md)\n```\n")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

if __name__ == "__main__":
    unittest.main()
