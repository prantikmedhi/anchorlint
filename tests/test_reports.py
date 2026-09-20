"""Report fidelity, escaping, baseline and CI-gate tests."""
import copy
import importlib
import json
import unittest
from anchorlint.core import audit, InputError


class ReportTests(unittest.TestCase):
    def reports(self):
        try:
            return importlib.import_module('anchorlint.reports')
        except ModuleNotFoundError:
            self.fail('Report serialization must be implemented')

    def report(self):
        return audit({'schema_version': 1, 'base_url': 'https://example.com/', 'pages': [
            {'url': 'https://example.com/', 'title': 'Home', 'text': 'Body', 'links': [
                {'href': '/missing/', 'anchor': '<script>alert("x")</script> [click](javascript:x) | `danger`',
                 'context': 'Quoted & exact\n# Fake heading'}]}]})

    def test_json_roundtrip_preserves_exact_report_evidence(self):
        report = self.report()
        raw = self.reports().render_report(report, 'json')
        self.assertEqual(json.loads(raw), report)
        self.assertTrue(raw.endswith('\n'))

    def test_html_is_standalone_escaped_and_never_links_untrusted_urls(self):
        from html.parser import HTMLParser
        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
        report = self.report()
        report['errors'] = [{'code': '<img src=x onerror=alert(1)>', 'message': 'javascript:alert(1)'}]
        report['findings'][0]['target_url'] = 'data:text/html,<script>bad</script>'
        rendered = self.reports().render_report(report, 'html')
        parser = Tags()
        parser.feed(rendered)
        tags = [tag for tag, attrs in parser.tags]
        self.assertIn('html', tags)
        self.assertIn('h1', tags)
        self.assertIn('table', tags)
        self.assertIn('caption', tags)
        for tag in ('script', 'iframe', 'img', 'link', 'a'):
            self.assertNotIn(tag, tags)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertIn('Quoted &amp; exact', rendered)
        self.assertTrue(any(attrs.get('name') == 'viewport' for tag, attrs in parser.tags))
        self.assertTrue(any(attrs.get('http-equiv') == 'Content-Security-Policy' for tag, attrs in parser.tags))
        self.assertNotIn('onerror=', ' '.join(str(attrs) for tag, attrs in parser.tags))

    def test_markdown_escapes_untrusted_structure_and_includes_coverage(self):
        import html
        report = self.report()
        rendered = self.reports().render_report(report, 'markdown')
        self.assertTrue(rendered.startswith('# AnchorLint audit'))
        self.assertIn('## Coverage', rendered)
        self.assertIn('## Finding evidence', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('[click](javascript:', rendered)
        self.assertNotIn('`danger`', rendered)
        self.assertNotIn('\n# Fake heading', rendered)
        self.assertIn('<script>alert("x")</script>', html.unescape(rendered))
        self.assertIn('semantic_evaluated', html.unescape(rendered))
        with self.assertRaises(InputError):
            self.reports().render_report(report, 'invalid')

    def test_baseline_rejects_wrong_type_enum_fields_as_input_errors(self):
        for field in ('provider', 'status', 'severity'):
            for value in ([], {}, None, True, 1, 'unknown'):
                with self.subTest(field=field, value=value):
                    baseline = self.report()
                    record = baseline['findings'][0] if field == 'severity' else baseline
                    record[field] = value
                    with self.assertRaises(InputError):
                        self.reports().validate_baseline(baseline)
                    with self.assertRaises(InputError):
                        self.reports().apply_baseline(self.report(), baseline)

    def test_baseline_suppresses_only_identical_findings_and_never_runtime_failure(self):
        reports = self.reports()
        self.assertTrue(hasattr(reports, 'apply_baseline'), 'baseline comparison is required')
        baseline = self.report()
        current = self.report()
        reports.apply_baseline(current, baseline)
        self.assertFalse(current['findings'][0]['is_new'])
        self.assertEqual(reports.exit_status(current), 0)
        changed = self.report()
        changed['findings'][0]['fingerprint'] = 'a' * 64
        reports.apply_baseline(changed, baseline)
        self.assertTrue(changed['findings'][0]['is_new'])
        self.assertEqual(reports.exit_status(changed), 1)
        self.assertEqual(reports.exit_status(changed, 'never'), 0)
        warning = self.report()
        warning['findings'][0]['severity'] = 'warning'
        self.assertEqual(reports.exit_status(warning), 0)
        self.assertEqual(reports.exit_status(warning, 'warning'), 1)
        for state in ('partial', 'failed'):
            current['status'] = state
            self.assertEqual(reports.exit_status(current, 'never'), 2)
        current['status'] = 'complete'
        current['errors'] = [{'code': 'provider_error', 'message': 'Failure'}]
        self.assertEqual(reports.exit_status(current, 'never'), 2)
        for bad in ({}, {'schema_version': True, 'findings': []},
                    {**baseline, 'findings': [{'fingerprint': 'not-a-fingerprint'}]},
                    {**baseline, 'all_findings': 99}):
            with self.subTest(bad=bad), self.assertRaises(InputError):
                reports.apply_baseline(self.report(), bad)


if __name__ == '__main__':
    unittest.main()
