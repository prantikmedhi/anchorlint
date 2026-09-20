"""Exercise real CLI entry points without credentials or networking."""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'index.html').write_text('<title>Home</title><p>Read <a href="/missing/">the missing guide</a>.</p>')

    def invoke(self, *args):
        try:
            main = importlib.import_module('anchorlint.cli').main
        except ModuleNotFoundError:
            self.fail('CLI main must be implemented')
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch('socket.socket', side_effect=AssertionError('Offline CLI must not use a network')):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def module(self, *args):
        source = str(Path(__file__).resolve().parents[1] / 'src')
        return subprocess.run([sys.executable, '-I', '-c',
            f'import sys,runpy;sys.path.insert(0,{source!r});runpy.run_module("anchorlint",run_name="__main__")', *args],
            capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k not in {'PYTHONPATH', 'TYPESAFE_API_KEY'}}, timeout=20)

    def test_module_version_and_help_work_without_credentials(self):
        version = self.module('--version')
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), 'anchorlint 0.1.0')
        help_result = self.module('--help')
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('audit', help_result.stdout)
        self.assertEqual(self.invoke('--help')[0], 0)

    def test_audit_outputs_machine_readable_json_and_gate_exit(self):
        before = {path: path.read_bytes() for path in self.site.rglob('*') if path.is_file()}
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        code, stdout, stderr = self.invoke(*args)
        self.assertEqual(code, 1, stderr)
        report = json.loads(stdout)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['provider'], 'rules')
        self.assertEqual(report['findings'][0]['rule'], 'broken-link')
        self.assertEqual(stderr, '')
        self.assertEqual(self.invoke(*args, '--fail-on', 'never')[0], 0)
        self.assertEqual(before, {path: path.read_bytes() for path in self.site.rglob('*') if path.is_file()})
        output = self.root / 'report.html'
        code, stdout, stderr = self.invoke('audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'html', '--output', str(output))
        self.assertEqual(code, 1, stderr)
        self.assertEqual(stdout, '')
        self.assertIn('<!doctype html>', output.read_text())
        data = {'schema_version': 1, 'base_url': 'https://example.com/', 'pages': [
            {'url': 'https://example.com/', 'title': 'Home', 'text': 'Body', 'links': []}]}
        path = self.root / 'input.json'
        path.write_text(json.dumps(data))
        code, stdout, stderr = self.invoke('audit', str(path), '--format', 'json')
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)['coverage']['pages'], 1)

    def test_invalid_inputs_produce_failed_json_with_operational_exit(self):
        empty = self.root / 'empty'
        empty.mkdir()
        invalid = self.root / 'invalid.json'
        invalid.write_text('{bad')
        for args in (['audit', str(self.site)], ['audit', str(empty), '--base-url', 'https://example.com/'],
                     ['audit', str(invalid)], ['audit', str(self.root / 'absent.json')]):
            with self.subTest(args=args):
                try:
                    code, stdout, stderr = self.invoke(*args, '--format', 'json', '--fail-on', 'never')
                except (ValueError, OSError):
                    self.fail('Invalid inputs require a report, not an uncaught exception')
                self.assertEqual(code, 2)
                report = json.loads(stdout)
                self.assertEqual(report['status'], 'failed')
                self.assertTrue(report['errors'])
                self.assertTrue(stderr)
        for maximum in ('0', '-1', '10001', 'bad'):
            code, stdout, stderr = self.invoke('audit', str(self.site), '--base-url', 'https://example.com/', '--max-links', maximum)
            self.assertEqual(code, 2)

    def test_cli_baseline_only_suppresses_unchanged_findings(self):
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        baseline = self.root / 'baseline.json'
        baseline.write_text(self.invoke(*args)[1])
        code, stdout, stderr = self.invoke(*args, '--baseline', str(baseline))
        self.assertEqual(code, 0, stderr)
        self.assertFalse(json.loads(stdout)['findings'][0]['is_new'])
        with (self.site / 'index.html').open('a') as file:
            file.write('<p><a href="/new-missing/">A newly broken guide</a></p>')
        code, stdout, stderr = self.invoke(*args, '--baseline', str(baseline))
        self.assertEqual(code, 1, stderr)
        self.assertEqual([f['is_new'] for f in json.loads(stdout)['findings']], [False, True])
        baseline.write_text('{}')
        code, stdout, stderr = self.invoke(*args, '--baseline', str(baseline), '--fail-on', 'never')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)['status'], 'failed')

    def test_module_malformed_baseline_enums_return_failed_json_without_traceback(self):
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        valid = self.invoke(*args)[1]
        baseline = self.root / 'baseline.json'
        output = self.root / 'report.json'
        for field in ('provider', 'status', 'severity'):
            for value in ([], {}):
                for write_output in (False, True):
                    with self.subTest(field=field, value=value, write_output=write_output):
                        data = json.loads(valid)
                        record = data['findings'][0] if field == 'severity' else data
                        record[field] = value
                        baseline.write_text(json.dumps(data))
                        output.unlink(missing_ok=True)
                        result = self.module(*args, '--baseline', str(baseline), '--fail-on', 'never',
                            *(['--output', str(output)] if write_output else []))
                        self.assertEqual(result.returncode, 2, result.stderr)
                        report = json.loads(output.read_text() if write_output else result.stdout)
                        self.assertEqual(report['status'], 'failed')
                        self.assertEqual(report['errors'][0]['code'], 'input_error')
                        self.assertEqual(report['findings'], [])
                        self.assertTrue(result.stderr)
                        self.assertNotIn('Traceback', result.stderr)
                        self.assertEqual(json.loads(baseline.read_text()), data)
                        if write_output:
                            self.assertEqual(result.stdout, '')

    def test_explicit_jev_mode_budget_is_operational_even_with_baseline_and_never(self):
        # Explicitly labeled provider-contract double; no live model output.
        from types import SimpleNamespace
        calls = []
        def evaluate(*inputs):
            calls.append(inputs)
            return {'model_requested': 'test-model', 'model_resolved': 'test-model',
                    'signals': {'promise': 0.9, 'relevance': 0.9, 'label': 'informative', 'confidence': 0.9,
                        'probabilities': {'informative': 0.9, 'generic': 0.04, 'misleading': 0.03, 'insufficient_context': 0.03}},
                    'usage': {'input_tokens': 10, 'output_tokens': 8}, 'duration_ms': 1.0, 'truncation': {}}
        (self.site / 'index.html').write_text('<p>Read <a href="guide.html">the guide</a>.</p><p>Another <a href="guide.html">guide reference</a>.</p>')
        (self.site / 'guide.html').write_text('<title>Guide</title><p>' + 'Useful destination information. ' * 10 + '</p>')
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        baseline = self.root / 'baseline.json'
        baseline.write_text(self.invoke(*args)[1])
        with patch('anchorlint.jev.JevClient', return_value=SimpleNamespace(evaluate=evaluate)) as factory:
            code, stdout, stderr = self.invoke(*args, '--provider', 'jev', '--model', 'test-model', '--max-links', '1', '--baseline', str(baseline), '--fail-on', 'never')
        self.assertEqual(code, 2)
        self.assertTrue(stdout.startswith('{'), stderr)
        report = json.loads(stdout)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['coverage']['semantic_calls'], 1)
        factory.assert_called_once_with(model='test-model')
        self.assertEqual(len(calls), 1)
        baseline.write_text('{}')
        with patch('anchorlint.jev.JevClient') as factory:
            code, stdout, stderr = self.invoke(*args, '--provider', 'jev', '--baseline', str(baseline))
            factory.assert_not_called()
        self.assertEqual(code, 2)
        with patch.dict(os.environ, {}, clear=True):
            code, stdout, stderr = self.invoke(*args, '--provider', 'jev', '--fail-on', 'never')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)['status'], 'partial')

    def test_output_cannot_overwrite_sources_or_follow_symlinks_and_is_preflighted(self):
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        source = self.site / 'index.html'
        before = source.read_bytes()
        alias = self.root / 'alias.json'
        alias.symlink_to(source)
        for output in (source, alias, self.root / 'absent-parent' / 'report.json', self.site):
            with self.subTest(output=output):
                try:
                    code, stdout, stderr = self.invoke(*args, '--output', str(output))
                except OSError:
                    self.fail('Output failure must return operational exit, not an exception')
                self.assertEqual(code, 2)
                self.assertEqual(source.read_bytes(), before)
                self.assertTrue(stderr)
        baseline = self.root / 'baseline.json'
        baseline.write_text(self.invoke(*args)[1])
        before_baseline = baseline.read_bytes()
        code, stdout, stderr = self.invoke(*args, '--baseline', str(baseline), '--output', str(baseline))
        self.assertEqual(code, 2)
        self.assertEqual(baseline.read_bytes(), before_baseline)
        with patch('anchorlint.jev.JevClient') as factory:
            code, stdout, stderr = self.invoke(*args, '--provider', 'jev', '--output', str(alias))
            factory.assert_not_called()
        self.assertEqual(code, 2)

    def test_output_rejects_filesystem_equivalent_input_ancestry(self):
        for name, spelling in (('site', 'SITE'), ('caf\u00e9', 'cafe\u0301')):
            site = self.root / name
            site.mkdir(exist_ok=True)
            (site / 'nested').mkdir()
            for relative in ('index.html', 'nested/guide.html'):
                (site / relative).write_text('<title>Home</title><p>Original audited HTML.</p>')
            alias = self.root / spelling
            for relative in ('index.html', 'nested/guide.html', 'nested/report.json'):
                with self.subTest(spelling=spelling, output=relative):
                    if not alias.exists() or not alias.samefile(site):
                        self.skipTest('Filesystem does not treat these spellings as aliases')
                    before = {path: path.read_bytes() for path in site.rglob('*') if path.is_file()}
                    result = self.module('audit', str(site), '--base-url', 'https://example.com/',
                        '--format', 'json', '--output', str(alias / relative), '--fail-on', 'never')
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(json.loads(result.stdout)['status'], 'failed')
                    self.assertIn('outside the audited input', result.stderr)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertEqual(before, {path: path.read_bytes() for path in site.rglob('*') if path.is_file()})

    def test_output_allows_explicit_overwrite_in_distinct_sibling_directory(self):
        sibling = self.root / 'site-reports'
        sibling.mkdir()
        output = sibling / 'index.html'
        output.write_text('Old report')
        before = (self.site / 'index.html').read_bytes()
        code, stdout, stderr = self.invoke('audit', str(self.site), '--base-url', 'https://example.com/',
            '--format', 'json', '--output', str(output))
        self.assertEqual(code, 1, stderr)
        self.assertEqual(stdout, '')
        self.assertEqual(json.loads(output.read_text())['status'], 'complete')
        self.assertEqual((self.site / 'index.html').read_bytes(), before)

    def test_output_refuses_dotenv_hardlinks_and_sanitizes_late_write_errors(self):
        args = ['audit', str(self.site), '--base-url', 'https://example.com/', '--format', 'json']
        dotenv = self.root / '.env'
        dotenv.write_text('NOT_A_REAL_SECRET=test')
        hardlink = self.root / 'hardlink.json'
        os.link(self.site / 'index.html', hardlink)
        for output in (dotenv, self.root / '.env.production', hardlink):
            with self.subTest(output=output):
                code, stdout, stderr = self.invoke(*args, '--output', str(output))
                self.assertEqual(code, 2)
        self.assertEqual(dotenv.read_text(), 'NOT_A_REAL_SECRET=test')
        with patch.object(Path, 'write_text', side_effect=OSError('PRIVATE exception details')):
            code, stdout, stderr = self.invoke(*args, '--output', str(self.root / 'report.json'))
        self.assertEqual(code, 2)
        self.assertNotIn('PRIVATE', stderr)
        self.assertNotIn('Traceback', stderr)

    def test_null_baseline_is_not_silently_treated_as_absent(self):
        baseline = self.root / 'baseline.json'
        baseline.write_text('null')
        code, stdout, stderr = self.invoke('audit', str(self.site), '--base-url', 'https://example.com/',
            '--format', 'json', '--baseline', str(baseline), '--fail-on', 'never')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
