"""Exercise the installed wheel, actual CLI, reports and baseline. No network."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    return subprocess.run([sys.executable, "-m", "anchorlint", *map(str, args)], text=True, capture_output=True)

assert run("--help").returncode == 0
assert run("--version").returncode == 0
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    report_path = directory / "audit.json"
    result = run("audit", ROOT / "examples/site", "--base-url", "https://example.com", "--format", "json", "--output", report_path)
    assert result.returncode == 1, (result.returncode, result.stderr)
    report = json.loads(report_path.read_text())
    assert report["status"] == "complete", report
    assert report["coverage"]["pages"] == 3, report["coverage"]
    rules = {finding["rule"] for finding in report["findings"]}
    assert {"broken-link", "missing-fragment", "generic-anchor"} <= rules, rules
    assert report["coverage"]["semantic_calls"] == 0, report["coverage"]
    baseline = run("audit", ROOT / "examples/site", "--base-url", "https://example.com", "--format", "json", "--baseline", report_path)
    assert baseline.returncode == 0, baseline.stderr
    assert not any(f["is_new"] for f in json.loads(baseline.stdout)["findings"])
    for fmt in ("html", "markdown"):
        exported = directory / ("report." + fmt)
        result = run("audit", ROOT / "examples/site", "--base-url", "https://example.com", "--format", fmt, "--output", exported)
        assert result.returncode == 1, (fmt, result.stderr)
        assert exported.stat().st_size > 100
    valid = run("audit", ROOT / "examples/inventory.json", "--format", "json")
    assert valid.returncode == 0, valid.stderr
    assert json.loads(valid.stdout)["status"] == "complete"
    print(json.dumps({"wheel_cli_smoke": "passed", "fixture_pages": report["coverage"]["pages"], "fixture_links": report["coverage"]["links"], "finding_rules": sorted(rules), "baseline": "passed", "formats": ["json", "markdown", "html"], "live_jev": "not_run"}))
