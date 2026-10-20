"""Exercise the optional Node browser adapter without installing or launching one."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BrowserEvidenceProbeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_probe_behavior(self):
        result = subprocess.run(
            [shutil.which("node"), "--test", str(ROOT / "tests/browser_evidence_probe.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_executable_reports_actual_runtime_without_launch_or_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = self.fake_adapter(root)
            result = self.run_example(entry, "--runtime-only")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["browser"], "actual-connected-browser")
            self.assertEqual((root / "calls.txt").read_text().splitlines(), [
                '{"noDefaults":true,"timeout":10000}', "disconnect",
            ])

    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_executable_retains_mismatch_and_disconnects_before_testing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = self.fake_adapter(root)
            expected = root / "expected.json"
            expected.write_text(json.dumps({**self.expected_runtime(), "browser": "old-browser"}))
            output = root / "report.json"
            result = self.run_example(entry, "--url", "http://127.0.0.1:8080/",
                                      "--expected", str(expected), "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["result"], "failed")
            self.assertEqual(report["checks"]["runtime"]["observations"]["actual"]["browser"],
                             "actual-connected-browser")
            self.assertEqual(report["cleanup"], [{"name": "connection", "result": "closed"}])
            self.assertNotIn("new-context", (root / "calls.txt").read_text())

    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_executable_cannot_omit_browser_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = self.fake_adapter(root)
            expected = root / "expected.json"
            expected.write_text(json.dumps({"node": self.expected_runtime()["node"]}))
            output = root / "report.json"
            result = self.run_example(entry, "--url", "http://127.0.0.1:8080/",
                                      "--expected", str(expected), "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("preserve captured browser", json.loads(output.read_text())["error"])
            self.assertNotIn("new-context", (root / "calls.txt").read_text())

    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_executable_rejects_unsupported_focus_override_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = self.fake_adapter(root, version="1.55.0")
            result = self.run_example(entry, "--runtime-only")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires Playwright >=1.60", result.stderr)
            self.assertFalse((root / "calls.txt").exists())

    @unittest.skipUnless(shutil.which("node"), "optional browser example needs Node.js")
    def test_executable_continues_cleanup_after_context_close_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entry = self.fake_adapter(root, fail_context=True)
            expected = root / "expected.json"
            expected.write_text(json.dumps(self.expected_runtime()))
            output = root / "report.json"
            result = self.run_example(entry, "--url", "http://127.0.0.1:8080/",
                                      "--expected", str(expected), "--output", str(output))
            self.assertNotEqual(result.returncode, 0)
            report = json.loads(output.read_text())
            self.assertEqual(report["error"], "page creation failed")
            self.assertEqual(report["cleanup"][0]["result"], "failed")
            self.assertEqual(report["cleanup"][1], {"name": "connection", "result": "closed"})
            self.assertEqual((root / "calls.txt").read_text().splitlines()[-1], "disconnect")

    @staticmethod
    def expected_runtime():
        return {
            "browser": "actual-connected-browser", "automation": "1.64.0-alpha",
            "node": subprocess.check_output([shutil.which("node"), "--version"], text=True).strip(),
        }

    @staticmethod
    def fake_adapter(root, version="1.64.0-alpha", fail_context=False):
        (root / "package.json").write_text(json.dumps({"name": "fixture", "version": version}))
        entry = root / "index.mjs"
        context = """
      newContext: async () => ({
        newPage: async () => { throw new Error('page creation failed'); },
        close: async () => { throw new Error('context close failed'); },
      }),
""" if fail_context else """
      newContext: () => { record('new-context'); throw new Error('unexpected test'); },
"""
        entry.write_text("""
import { appendFileSync } from 'node:fs';
const record = value => appendFileSync(new URL('./calls.txt', import.meta.url), value + '\\n');
export const chromium = {
  connectOverCDP: async (endpoint, options) => {
    record(JSON.stringify(options));
    return {
      version: () => 'actual-connected-browser',
""" + context + """
      close: async () => record('disconnect'),
    };
  },
};
""")
        return entry

    @staticmethod
    def run_example(entry, *arguments):
        return subprocess.run([
            shutil.which("node"),
            str(ROOT / "skills/to-sdd-pipeline/scripts/browser_evidence_example.mjs"),
            "--playwright-entry", str(entry), "--owned-endpoint", "http://127.0.0.1:9222",
            *arguments,
        ], cwd=entry.parent, capture_output=True, text=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
