"""Evidence-preserving serialization and baseline gates."""
import json
from html import escape
import string
import re
from .core import InputError


def validate_baseline(baseline):
    """Accept versioned AnchorLint reports, not silently malformed suppression lists."""
    if (not isinstance(baseline, dict) or type(baseline.get('schema_version')) is not int
            or baseline['schema_version'] != 1 or not isinstance(baseline.get('version'), str)
            or not isinstance(baseline.get('provider'), str) or baseline['provider'] not in {'rules', 'jev'}
            or not isinstance(baseline.get('status'), str) or baseline['status'] not in {'complete', 'partial', 'failed'}
            or not isinstance(baseline.get('coverage'), dict) or not isinstance(baseline.get('errors'), list)
            or not isinstance(baseline.get('findings'), list)):
        raise InputError('Baseline must be a schema-version 1 AnchorLint JSON report')
    if type(baseline.get('all_findings')) is not int or baseline['all_findings'] != len(baseline['findings']):
        raise InputError('Baseline finding count does not match its records')
    fingerprints = set()
    for finding in baseline['findings']:
        if (not isinstance(finding, dict) or not isinstance(finding.get('fingerprint'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', finding['fingerprint'])
                or not isinstance(finding.get('severity'), str) or finding['severity'] not in {'error', 'warning', 'info'}):
            raise InputError('Baseline contains an invalid finding')
        if finding['fingerprint'] in fingerprints:
            raise InputError('Baseline contains duplicate finding fingerprints')
        fingerprints.add(finding['fingerprint'])
    return fingerprints


def apply_baseline(report, baseline):
    fingerprints = validate_baseline(baseline)
    for finding in report['findings']:
        finding['is_new'] = finding['fingerprint'] not in fingerprints
    return report


def exit_status(report, fail_on='error'):
    """0 complete/pass; 1 new configured severity; 2 operational/incomplete."""
    if fail_on not in {'error', 'warning', 'never'}:
        raise InputError('fail_on must be error, warning or never')
    if report['status'] != 'complete' or report['errors']:
        return 2
    severities = {'error', 'warning'} if fail_on == 'warning' else ({'error'} if fail_on == 'error' else set())
    return int(any(finding['is_new'] and finding['severity'] in severities for finding in report['findings']))


def render_report(report, format='markdown'):
    """Serialize a report without modifying evidence."""
    if format == 'html':
        return _html(report)
    if format == 'markdown':
        return _markdown(report)
    if format != 'json':
        raise InputError('format must be json, markdown or html')
    return json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + '\n'


def _display(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) if isinstance(value, (dict, list)) else str(value)


def _md(value):
    # Entities are parsed as text, never as Markdown syntax or autolink URLs.
    return ''.join(f'&#{ord(char)};' if char in string.punctuation or ord(char) < 32 or ord(char) == 127 else char
                   for char in _display(value))


def _markdown(report):
    lines = ['# AnchorLint audit', '', 'Version: ' + _md(report['version']),
             'Provider: ' + _md(report['provider']), 'Status: ' + _md(report['status']), '',
             'Evidence and conservative heuristics, not ranking predictions or accessibility certification.', '',
             '## Findings', '', '| Severity | Rule | Source | Target | Anchor | New |',
             '| --- | --- | --- | --- | --- | --- |']
    for finding in report['findings']:
        lines.append('| ' + ' | '.join(_md(finding.get(key, '')) for key in ('severity', 'rule', 'source_url', 'target_url', 'anchor', 'is_new')) + ' |')
    for title, key in [('Errors', 'errors'), ('Coverage', 'coverage'), ('Finding evidence', 'findings'),
                       ('Semantic evaluations', 'semantic_evaluations'), ('Page metadata', 'page_evidence')]:
        lines.extend(['', '## ' + title, ''])
        values = report.get(key, [])
        if isinstance(values, dict):
            lines.extend('- ' + _md(name) + ': ' + _md(value) for name, value in values.items())
        else:
            lines.extend('- ' + _md(value) for value in values)
        if not values:
            lines.append('None.')
    return '\n'.join(lines) + '\n'


def _html(report):
    def e(value):
        return escape(_display(value), quote=True)
    rows = []
    for finding in report['findings']:
        cells = ''.join('<td>' + e(finding.get(key, '')) + '</td>' for key in ('severity', 'rule', 'source_url', 'target_url', 'anchor', 'context', 'is_new'))
        rows.append('<tr>' + cells + '</tr>')
    details = ''.join('<h2>' + title + '</h2><pre>' + e(report.get(key, [])) + '</pre>'
                      for title, key in [('Errors', 'errors'), ('Coverage', 'coverage'), ('Finding evidence', 'findings'),
                                         ('Semantic evaluations', 'semantic_evaluations'), ('Page metadata', 'page_evidence')])
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            '<title>AnchorLint audit report</title><style>'
            'body{font:16px/1.6 system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:90rem;color:#17202a;background:#fff}'
            'h1,h2{line-height:1.25}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aab;padding:.5rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:1rem;background:#f4f5f6} .scroll{overflow:auto}caption{text-align:left;font-weight:600}'
            '</style></head><body><main><h1>AnchorLint audit</h1><p>Version ' + e(report['version'])
            + ' · Provider ' + e(report['provider']) + ' · Status ' + e(report['status']) + '</p>'
            '<p>Evidence and conservative heuristics, not ranking predictions or accessibility certification.</p>'
            '<div class="scroll"><table><caption>Findings</caption><thead><tr>'
            + ''.join('<th scope="col">' + name + '</th>' for name in ('Severity', 'Rule', 'Source', 'Target', 'Anchor', 'Context', 'New'))
            + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' + details + '</main></body></html>\n')

