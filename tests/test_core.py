"""Offline behavioral tests; provider doubles never perform HTTP."""
import importlib
import json
from pathlib import Path
import tempfile
import unittest


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def core(self):
        try:
            return importlib.import_module('anchorlint.core')
        except ModuleNotFoundError:
            self.fail('anchorlint.core must implement the local audit API')

    def inventory(self, pages=None, **extra):
        return {'schema_version': 1, 'base_url': 'https://example.com/',
                'pages': pages or [self.page()], **extra}

    def page(self, url='https://example.com/', links=None, **extra):
        return {'url': url, 'title': 'Home', 'text': 'Useful visible content for readers.',
                'links': links or [], **extra}

    def link(self, href='/guide/', anchor='Guide', context='Read the Guide for details.', **extra):
        return {'href': href, 'anchor': anchor, 'context': context, **extra}

    def load(self, data, **kwargs):
        path = self.root / 'inventory.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        return self.core().load_inventory(path, **kwargs)

    def test_inventory_preserves_evidence_and_supplies_defaults(self):
        data = self.inventory([self.page(links=[self.link(anchor='  Guide & API  ', line=7)])])
        result = self.load(data)
        page = result['pages'][0]
        self.assertEqual(page['url'], 'https://example.com/')
        self.assertEqual(page['headings'], [])
        self.assertEqual(page['ids'], [])
        self.assertIs(page['noindex'], False)
        self.assertEqual(page['links'][0]['anchor'], '  Guide & API  ')
        self.assertEqual(page['links'][0]['line'], 7)
        self.assertEqual(page['links'][0]['occurrence'], 1)
        self.assertEqual(page['evidence_source'], 'inventory')
        self.assertEqual(result['assets'], [])

    def test_inventory_rejects_invalid_and_excessive_records_before_audit(self):
        core = self.core()
        self.assertTrue(hasattr(core, 'InputError'), 'invalid input needs an explicit InputError')
        cases = [
            {}, self.inventory(pages=[]), self.inventory(schema_version=True),
            self.inventory(base_url='file:///tmp/'),
            self.inventory(base_url='https://user:secret@example.com/'),
            self.inventory([self.page(url='https://other.test/')]),
            self.inventory([self.page(), self.page(url='https://EXAMPLE.com:443/index.html?q=1')]),
            self.inventory([self.page(title=3)]), self.inventory([self.page(noindex=1)]),
            self.inventory([self.page(ids=['ok', 1])]),
            self.inventory([self.page(links=[self.link(line=True)])]),
            self.inventory([self.page(links=[self.link(line=0)])]),
            self.inventory([self.page(links=[{'href': '/'}])]),
            self.inventory([{'url': 'https://example.com/', 'title': 'Missing', 'links': []}]),
        ]
        # The helper has a nonempty default; this case must be explicitly empty.
        cases[1]['pages'] = []
        for data in cases:
            with self.subTest(data=data), self.assertRaises(core.InputError):
                self.load(data)
        oversized = self.inventory([self.page(text='x' * (core.MAX_TEXT_CHARS + 1))])
        with self.assertRaises(core.InputError):
            self.load(oversized)
        path = self.root / 'bad.json'
        for raw in ['{', '{"schema_version":1,"schema_version":1}', 'NaN']:
            path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(core.InputError):
                core.load_inventory(path)

    def test_html_extracts_visible_wording_occurrences_and_metadata(self):
        html = """<!doctype html><title>Help &amp; API</title>
<meta name="robots" content="noindex,follow"><base href="https://evil.test/">
<link rel="canonical" href="https://elsewhere.test/">
<body><h1 id="intro">Help <span>center</span></h1>
<p>Read <a href="/guide/?x=1#part">the <span>API</span> <img alt="guide"></a> today.</p>
<p>Again <a href="/guide/">the API guide</a>.</p><a name="legacy"></a>
<p hidden>Hidden <a href="/hidden">secret</a></p><p aria-hidden="true">Aria secret</p>
<p style="display: none !important">CSS secret</p><div style="visibility:hidden">Other secret</div>
<script>bad code</script><style>bad style</style><template>bad template</template>
<a href="#intro"><span>Go</span><span>back</span></a></body>"""
        (self.root / 'index.html').write_text(html)
        try:
            result = self.core().load_inventory(self.root, 'https://example.com/docs/')
        except ValueError as exc:
            self.fail(f'HTML directory collection is required: {exc}')
        page = result['pages'][0]
        self.assertEqual(page['url'], 'https://example.com/docs/')
        self.assertEqual(page['title'], 'Help & API')
        self.assertEqual(page['headings'], ['Help center'])
        self.assertEqual(page['ids'], ['intro', 'legacy'])
        self.assertTrue(page['noindex'])
        self.assertEqual(page['robots'], ['noindex,follow'])
        self.assertEqual(page['ignored_base'], ['https://evil.test/'])
        self.assertEqual(page['ignored_canonical'], ['https://elsewhere.test/'])
        self.assertEqual(len(page['links']), 3)
        link = page['links'][0]
        self.assertEqual(link['anchor'], 'the API guide')
        self.assertEqual(link['context'], 'Read the API guide today.')
        self.assertEqual(link['href'], '/guide/?x=1#part')
        self.assertEqual(link['line'], 5)
        self.assertEqual(page['links'][2]['anchor'], 'Goback')
        self.assertEqual(page['source_file'], 'index.html')
        self.assertEqual(page['evidence_source'], 'html')
        for forbidden in ('secret', 'bad code', 'bad style', 'bad template'):
            self.assertNotIn(forbidden, page['text'])

    def test_collection_is_bounded_to_explicit_root_and_excludes_dependencies(self):
        core = self.core()
        (self.root / 'index.html').write_text('<p>Home</p>')
        for folder in ('.git', '.env', 'node_modules', '.venv', 'venv', 'vendor', '__pycache__'):
            excluded = self.root / folder
            excluded.mkdir()
            (excluded / 'private.html').write_text('must not scan')
        result = core.load_inventory(self.root, 'https://example.com/')
        self.assertEqual(len(result['pages']), 1)
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(len(core.load_inventory(self.root, 'https://example.com/')['pages']), 1)
        with tempfile.TemporaryDirectory() as outside:
            outside_file = Path(outside) / 'secret.html'
            outside_file.write_text('do not read')
            link = self.root / 'escape.html'
            link.symlink_to(outside_file)
            with self.assertRaises(core.InputError):
                core.load_inventory(self.root, 'https://example.com/')
            link.unlink()
            link = self.root / 'escape-dir'
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(core.InputError):
                core.load_inventory(self.root, 'https://example.com/')
        with self.assertRaises(core.InputError):
            core.load_inventory(self.root)
        with self.assertRaises(core.InputError):
            core.load_inventory(Path.home(), 'https://example.com/')

    def test_existing_download_is_not_a_broken_link_but_missing_download_is(self):
        (self.root / 'index.html').write_text(
            '<a href="manual.pdf">product manual</a>'
            '<a href="missing.pdf">missing manual</a>')
        (self.root / 'manual.pdf').write_bytes(b'%PDF-1.4 test fixture')
        inventory = self.core().load_inventory(self.root, 'https://example.com/')
        report = self.core().audit(inventory)
        self.assertEqual([f['href'] for f in report['findings'] if f['rule'] == 'broken-link'],
                         ['missing.pdf'])
        self.assertEqual(inventory['assets'], ['https://example.com/manual.pdf'])

    def test_jev_excludes_existing_assets_without_paid_coverage_failure(self):
        from anchorlint.reports import exit_status
        from unittest.mock import patch
        core = self.core()
        (self.root / 'index.html').write_text(
            '<p>Read the <a href="manual.pdf?download=1#page=2">product manual</a>.</p>'
            '<a href="logo.png#view">company logo</a>')
        (self.root / 'manual.pdf').write_bytes(b'%PDF-1.4 test fixture')
        (self.root / 'logo.png').write_bytes(b'not parsed as an image')
        provider = self.provider()
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            report = core.audit(core.load_inventory(self.root, 'https://example.com/'),
                                provider='jev', client=provider, max_links=1)
        self.assertEqual([item.get('reason') for item in report['semantic_evaluations']],
                         ['non_html_target', 'non_html_target'])
        self.assertEqual([item['status'] for item in report['semantic_evaluations']],
                         ['not_evaluated', 'not_evaluated'])
        self.assertTrue(all('model' not in item and 'assessment' not in item
                            for item in report['semantic_evaluations']))
        self.assertEqual(provider.calls, [])
        self.assertEqual(report['coverage']['semantic_calls'], 0)
        self.assertEqual(report['coverage']['semantic_eligible'], 0)
        self.assertEqual(report['coverage']['semantic_not_evaluated'], 2)
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(exit_status(report, 'error'), 0)

    def test_asset_inventory_rejects_malicious_duplicate_and_non_asset_urls(self):
        core = self.core()
        provider = self.provider()
        source = self.page(links=[self.link()])
        target = self.page('https://example.com/guide/', text='Destination evidence. ' * 10)
        cases = [
            {}, '', None, True, 1, [None], [False], [{}], [''],
            ['https://other.test/manual.pdf'], ['http://example.com/manual.pdf'],
            ['https://example.com:444/manual.pdf'], ['https://user:secret@example.com/manual.pdf'],
            ['javascript:alert(1)'], ['file:///tmp/manual.pdf'], ['/manual.pdf'],
            ['https://example.com/%00.pdf'], ['https://example.com/%ZZ.pdf'],
            ['https://example.com/\\\\manual.pdf'], ['https://example.com/\ud800.pdf'],
            ['https://example.com/a/../manual.pdf'], ['https://example.com/%2e%2e/manual.pdf'],
            ['https://example.com/manual.pdf?download=1'], ['https://example.com/manual.pdf#page=2'],
            ['https://example.com/docs/'], ['https://example.com/unscanned.HTML'],
            ['https://example.com/unscanned.htm'], ['https://example.com/guide/'],
            ['https://example.com/shared'],
            ['https://example.com/manual.pdf', 'https://EXAMPLE.com:443/%6Danual.pdf'],
        ]
        for assets in cases:
            for via_json in (False, True):
                with self.subTest(assets=assets, via_json=via_json), self.assertRaises(core.InputError):
                    data = self.inventory([source, target, self.page('https://example.com/shared')], assets=assets)
                    core.audit(self.load(data) if via_json else data, provider='jev', client=provider)
        self.assertEqual(provider.calls, [])

    def test_asset_count_limit_applies_before_html_reads_or_provider_calls(self):
        from unittest.mock import patch
        core = self.core()
        provider = self.provider()
        (self.root / 'index.html').write_text('<p>Home</p>')
        assets = []
        for name in ('one.pdf', 'two.png', 'three.zip'):
            (self.root / name).write_bytes(b'fixture')
            assets.append('https://example.com/' + name)
        with patch.object(core, 'MAX_ASSETS', 2, create=True):
            with self.subTest(input='JSON'), self.assertRaises(core.InputError):
                core.audit(self.inventory(assets=assets), provider='jev', client=provider)
            with self.subTest(input='directory'), patch.object(
                    Path, 'read_text', side_effect=AssertionError('must reject before HTML reads')):
                with self.assertRaises(core.InputError):
                    core.collect_html(self.root, 'https://example.com/')
        self.assertEqual(provider.calls, [])

    def test_asset_urls_share_aggregate_evidence_limit_with_pages(self):
        from unittest.mock import patch
        core = self.core()
        (self.root / 'index.html').write_text('<p>Home</p>')
        assets = []
        for name in ('one.pdf', 'two.png', 'three.zip'):
            (self.root / name).write_bytes(b'fixture')
            assets.append('https://example.com/' + name)
        with patch.object(core, 'MAX_EVIDENCE_CHARS', 50):
            with self.subTest(input='JSON'), self.assertRaises(core.InputError):
                core.validate_inventory(self.inventory([self.page(title='', text='')], assets=assets))
            with self.subTest(input='directory'), patch.object(
                    Path, 'read_text', side_effect=AssertionError('must reject before HTML reads')):
                with self.assertRaises(core.InputError):
                    core.collect_html(self.root, 'https://example.com/')
        with patch.object(core, 'MAX_EVIDENCE_CHARS', 65):
            with self.subTest(input='combined page and asset'), self.assertRaises(core.InputError):
                core.validate_inventory(self.inventory(assets=assets[:1]))

    def test_asset_url_field_limit_covers_raw_and_normalized_urls(self):
        from unittest.mock import patch
        core = self.core()
        with patch.object(core, 'MAX_TEXT_CHARS', 100):
            for path in ('x' * 101 + '.pdf', 'é' * 40 + '.pdf'):
                with self.subTest(path=path), self.assertRaises(core.InputError):
                    core.validate_inventory(self.inventory(assets=['https://example.com/' + path]))
            (self.root / 'index.html').write_text('<p>Home</p>')
            (self.root / ('x' * 101 + '.pdf')).write_bytes(b'fixture')
            with patch.object(Path, 'read_text', side_effect=AssertionError('reject before HTML reads')):
                with self.assertRaises(core.InputError):
                    core.collect_html(self.root, 'https://example.com/')

    def test_asset_collection_keeps_existing_read_only_root_and_symlink_guards(self):
        import os
        from unittest.mock import patch
        core = self.core()
        (self.root / 'index.html').write_text(
            '<a href="files/caf%C3%A9%20manual.pdf#page=2">product manual</a>'
            '<a href="extensionless">plain download</a>'
            '<a href="missing.png#view">missing image</a>')
        folder = self.root / 'files'
        folder.mkdir()
        (folder / 'café manual.pdf').write_bytes(b'\xff invalid UTF-8 fixture')
        (self.root / 'extensionless').write_bytes(b'\x00 fixture')
        with (self.root / 'large.zip').open('wb') as handle:
            handle.truncate(core.MAX_TEXT_CHARS + 1)
        (self.root / 'alias.pdf').symlink_to(folder / 'café manual.pdf')
        (self.root / 'alias-dir').symlink_to(folder, target_is_directory=True)
        for name in ('.git', '.env', 'node_modules', '.venv', 'venv', 'vendor', '__pycache__', '.hg', '.svn'):
            (self.root / name).mkdir()
            (self.root / name / 'private.pdf').write_bytes(b'not evidence')
        (self.root / '.env.production').write_text('not evidence')
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.root / 'pipe.pdf')
        original_open = Path.open
        def html_read_only(path, mode='r', *args, **kwargs):
            self.assertIn(path.suffix.lower(), {'.html', '.htm'}, 'must not read asset bytes')
            self.assertEqual(mode, 'r', 'collector and audit must not write files')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', html_read_only), patch(
                'socket.socket', side_effect=AssertionError('network forbidden')):
            inventory = core.collect_html(self.root, 'https://example.com/docs/')
            report = core.audit(inventory)
        self.assertEqual(set(inventory['assets']), {
            'https://example.com/docs/alias.pdf', 'https://example.com/docs/extensionless',
            'https://example.com/docs/large.zip', 'https://example.com/docs/files/caf%C3%A9%20manual.pdf'})
        self.assertEqual([f['href'] for f in report['findings'] if f['rule'] == 'broken-link'],
                         ['missing.png#view'])
        self.assertFalse(any(f['rule'] == 'missing-fragment' for f in report['findings']))
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.pdf'
            secret.write_bytes(b'not evidence')
            (self.root / 'escape.pdf').symlink_to(secret)
            with patch.object(Path, 'open', side_effect=AssertionError('reject before any read')):
                with self.assertRaises(core.InputError):
                    core.collect_html(self.root, 'https://example.com/')

    def test_asset_json_roundtrip_preserves_normalized_identity_and_semantic_exclusion(self):
        core = self.core()
        data = self.inventory([self.page(links=[
            self.link('files/caf%C3%A9%20manual.pdf?download=1#page=2', 'Product manual'),
            self.link('missing.pdf#page=2', 'Missing manual')])],
            assets=['https://EXAMPLE.com:443/files/caf%C3%A9%20manual.pdf'])
        loaded = self.load(data)
        self.assertEqual(loaded['assets'], ['https://example.com/files/caf%C3%A9%20manual.pdf'])
        self.assertEqual(core.validate_inventory(loaded)['assets'], loaded['assets'])
        provider = self.provider()
        report = core.audit(loaded, provider='jev', client=provider)
        self.assertEqual([f['href'] for f in report['findings'] if f['rule'] == 'broken-link'],
                         ['missing.pdf#page=2'])
        self.assertEqual([item['reason'] for item in report['semantic_evaluations']],
                         ['non_html_target', 'broken_target'])
        self.assertEqual(provider.calls, [])

    def test_asset_schema_contract_matches_runtime_and_published_mirror(self):
        core = self.core()
        project = Path(__file__).resolve().parents[1]
        source = (project / 'schemas/inventory.schema.json').read_text()
        mirror = (project / 'site/inventory.schema.json').read_text()
        schema = json.loads(source)
        self.assertIn('assets', schema['properties'])
        assets = schema['properties']['assets']
        self.assertNotIn('assets', schema['required'])
        self.assertEqual(assets['type'], 'array')
        self.assertEqual(assets['default'], [])
        self.assertEqual(assets['maxItems'], core.MAX_ASSETS)
        self.assertIs(assets['uniqueItems'], True)
        self.assertEqual(assets['items']['type'], 'string')
        self.assertEqual(assets['items']['format'], 'uri')
        self.assertEqual(assets['items']['maxLength'], core.MAX_TEXT_CHARS)
        self.assertEqual(source, mirror)

    def test_repeated_source_and_resolved_urls_preflight_before_findings_or_provider(self):
        from unittest.mock import patch
        core = self.core()
        # Safe-scale review-final.json reproduction, plus percent-encoding expansion.
        for path in ('a' * 15000, 'é' * 2500):
            data = self.inventory([self.page(url='https://example.com/' + path + '/',
                text='Body', links=[self.link('missing', 'Guide', 'Guide') for _ in range(300)])])
            validated = core.validate_inventory(data)
            source = validated['pages'][0]['url']
            target = core.resolve_link(source, 'missing')['target_url']
            self.assertGreater(300 * (len(source) + len(target)), core.MAX_EVIDENCE_CHARS)
            for mode in ('rules', 'jev'):
                provider = self.provider()
                with self.subTest(unicode=path.startswith('é'), mode=mode), patch.object(
                        core, '_finding', side_effect=AssertionError('must preflight before findings')):
                    with self.assertRaisesRegex(core.InputError, 'report evidence limit'):
                        core.audit(data, provider=mode, client=provider)
                self.assertEqual(provider.calls, [])

    def test_report_link_copies_share_one_budget_with_conflicts_and_destinations(self):
        from unittest.mock import patch
        core = self.core()
        cases = [
            ('rules', 'conflict', self.inventory([self.page(links=[
                self.link(f'/missing-{i}/', 'Guide', 'x' * 100) for i in range(10)])])),
            ('jev', 'destination', self.inventory([
                self.page(links=[self.link(context='x' * 100) for _ in range(4)]),
                self.page('https://example.com/guide/', text='Evidence ' * 45)])),
        ]
        for mode, expansion, data in cases:
            provider = self.provider()
            with self.subTest(expansion=expansion), patch.object(core, 'MAX_EVIDENCE_CHARS', 7000):
                core.validate_inventory(data)
                with patch.object(core, '_finding', side_effect=AssertionError('must preflight before findings')):
                    with self.assertRaisesRegex(core.InputError, expansion + ' report evidence limit'):
                        core.audit(data, provider=mode, client=provider)
            self.assertEqual(provider.calls, [])

    def test_short_url_workload_preserves_every_finding_and_evaluation(self):
        core = self.core()
        link = self.link(anchor='  Guide & API  ', context='Exact source context. ' * 3)
        target = self.page('https://example.com/guide/', title='Exact title', text='Exact target text. ' * 5)
        data = self.inventory([self.page(links=[dict(link) for _ in range(300)]), target])
        for mode in ('rules', 'jev'):
            provider = self.provider(promise=0.1, relevance=0.1, label='misleading')
            with self.subTest(mode=mode):
                report = core.audit(data, provider=mode, client=provider, max_links=1)
                self.assertEqual(report['status'], 'complete')
                self.assertEqual(report['coverage']['links'], 300)
                self.assertEqual(report['coverage']['rules_evaluated'], 300)
                self.assertEqual(len(report['findings']), 600 if mode == 'jev' else 0)
                self.assertEqual(len(report['semantic_evaluations']), 300 if mode == 'jev' else 0)
                self.assertEqual(len(provider.calls), 1 if mode == 'jev' else 0)
                if mode == 'jev':
                    self.assertEqual(report['coverage']['semantic_cache_hits'], 299)
                    for record in report['findings'] + report['semantic_evaluations']:
                        self.assertEqual(record['source_url'], data['pages'][0]['url'])
                        self.assertEqual(record['target_url'], target['url'])
                        for key in ('href', 'anchor', 'context'):
                            self.assertEqual(record[key], link[key])
                        self.assertEqual(record['target_evidence'], {'title': target['title'], 'text': target['text']})

    def test_conflict_report_expansion_is_rejected_before_findings_or_provider(self):
        from unittest.mock import patch
        core = self.core()
        data = self.inventory([self.page(noindex=True, links=[
            self.link(f'/missing-{i}/', 'Guide', 'Guide') for i in range(1000)])])
        core.validate_inventory(data)  # Input itself is safely below the limits.
        provider = self.provider()
        for mode in ('rules', 'jev'):
            with self.subTest(mode=mode), patch.object(
                    core, '_finding', side_effect=AssertionError('must preflight before findings')):
                with self.assertRaisesRegex(core.InputError, 'conflict.*limit'):
                    core.audit(data, provider=mode, client=provider)
        self.assertEqual(provider.calls, [])

    def test_first_duplicate_html_attribute_preserves_browser_destination(self):
        (self.root / 'index.html').write_text(
            '<a HREF="/missing/" href="/">Guide</a><div id="first" id="second">Body</div>')
        core = self.core()
        data = core.collect_html(self.root, 'https://example.com/')
        self.assertEqual(data['pages'][0]['links'][0]['href'], '/missing/')
        self.assertEqual(data['pages'][0]['ids'], ['first'])
        self.assertEqual([f['rule'] for f in core.audit(data)['findings']], ['broken-link'])

    def test_implied_paragraph_close_through_inline_descendants_keeps_visible_links(self):
        cases = [
            ('<p hidden><span>Hidden<div><a href="/missing/">Visible guide</a></div>', ['/missing/']),
            ('<p hidden><span>Hidden<br><a href="/hidden/">Hidden guide</a>', []),
            ('<div hidden><p><span>Hidden<div><a href="/hidden/">Still hidden</a></div>', []),
            ('<p hidden><template><div><a href="/hidden/">Template guide</a></div></template>', []),
        ]
        for html, expected in cases:
            with self.subTest(html=html):
                (self.root / 'index.html').write_text(html)
                data = self.core().collect_html(self.root, 'https://example.com/')
                self.assertEqual([link['href'] for link in data['pages'][0]['links']], expected)
                self.assertEqual([f['href'] for f in self.core().audit(data)['findings']], expected)

    def test_oversized_json_integer_has_sanitized_input_error(self):
        core = self.core()
        path = self.root / 'large.json'
        path.write_text(json.dumps(self.inventory())[:-1] + ',"extra":' + '9' * 5000 + '}')
        try:
            core.read_json(path)
        except ValueError as error:
            self.assertIsInstance(error, core.InputError)
            self.assertEqual(str(error), 'Cannot read valid UTF-8 inventory JSON')
        else:
            self.fail('Oversized JSON integer must be rejected')

    def test_json_float_overflow_is_rejected_even_in_unknown_fields(self):
        core = self.core()
        path = self.root / 'number.json'
        for token in ('1e9999', '-1e9999', 'NaN', 'Infinity', '-Infinity'):
            path.write_text(json.dumps(self.inventory())[:-1] + ',"extra":' + token + '}')
            with self.subTest(token=token), self.assertRaisesRegex(core.InputError, 'Nonfinite JSON number'):
                core.load_inventory(path)
        path.write_text(json.dumps(self.inventory())[:-1] + ',"extra":1.5}')
        self.assertEqual(core.read_json(path)['extra'], 1.5)

    def test_hidden_and_template_metadata_cannot_replace_live_page_evidence(self):
        fake = ('<title>Hidden title</title><meta name="robots" content="noindex">'
                '<base href="https://hidden.test/"><link rel="canonical" href="https://hidden.test/">'
                '<body>Hidden body</body>')
        for start, end in (('<template>', '</template>'), ('<noscript>', '</noscript>'),
                           ('<div hidden>', '</div>'), ('<div aria-hidden="true">', '</div>')):
            with self.subTest(start=start):
                (self.root / 'index.html').write_text(start + fake + end +
                    '<title>Live title</title><body><p>Visible body</p></body>')
                data = self.core().collect_html(self.root, 'https://example.com/')
                page = data['pages'][0]
                self.assertEqual(page['title'], 'Live title')
                self.assertEqual(page['text'], 'Visible body')
                self.assertEqual(page['robots'], [])
                self.assertFalse(page['noindex'])
                self.assertEqual(page['ignored_base'], [])
                self.assertEqual(page['ignored_canonical'], [])
                self.assertEqual(self.core().audit(data)['findings'], [])
        (self.root / 'index.html').write_text('<template><title>Hidden template title</title>'
            '<meta name="robots" content="noindex"></template><p>Visible</p>')
        page = self.core().collect_html(self.root, 'https://example.com/')['pages'][0]
        self.assertEqual(page['title'], '')
        self.assertEqual(page['text'], 'Visible')
        self.assertFalse(page['noindex'])

    def test_base_override_does_not_bypass_required_inventory_base_validation(self):
        core = self.core()
        for original in (None, 'not-a-valid-url', 'file:///tmp/', 'https://user:secret@example.com/'):
            data = self.inventory(base_url=original)
            if original is None:
                del data['base_url']
            with self.subTest(original=original), self.assertRaises(core.InputError):
                self.load(data, base_url='https://example.com/')
        result = self.load(self.inventory(), base_url='https://EXAMPLE.com:443/docs/')
        self.assertEqual(result['base_url'], 'https://example.com/docs/')

    def test_html_top_fallback_is_shared_by_rules_and_semantic_eligibility(self):
        hrefs = ['#top', '#ToP', '#%54OP', '#Part', '#part']
        data = self.inventory([self.page(text='Destination evidence. ' * 5, ids=['Part'],
            links=[self.link(href, anchor=f'Section {i}') for i, href in enumerate(hrefs)])])
        core = self.core()
        for mode in ('rules', 'jev'):
            with self.subTest(mode=mode):
                provider = self.provider()
                report = core.audit(data, provider=mode, client=provider)
                self.assertEqual([f['href'] for f in report['findings'] if f['rule'] == 'missing-fragment'],
                                 ['#part'])
                if mode == 'jev':
                    self.assertEqual(report['coverage']['semantic_evaluated'], 4)
                    self.assertEqual(len(provider.calls), 4)
                    self.assertEqual(report['semantic_evaluations'][-1]['reason'], 'missing_fragment')

    def test_every_semantic_record_retains_available_destination_evidence(self):
        target = self.page('https://example.com/guide/', title='Destination', text='Exact target words. ' * 5)
        data = self.inventory([self.page(links=[self.link(), self.link('/guide/#absent'),
            self.link(anchor='Click here'), self.link('/absent/'), self.link('https://outside.test/'),
            self.link('/manual.pdf'), self.link(context='A second request for this guide.')]), target],
            assets=['https://example.com/manual.pdf'])
        for mode in ('positive', 'review', 'failure'):
            provider = self.provider(confidence=0.5 if mode == 'review' else 0.9)
            if mode == 'failure':
                def fail(*args):
                    raise RuntimeError('synthetic provider failure')
                provider.evaluate = fail
            with self.subTest(mode=mode):
                report = self.core().audit(data, provider='jev', client=provider, max_links=1)
                for item in report['semantic_evaluations']:
                    self.assertIn('target_evidence', item)
                    expected = ({'title': target['title'], 'text': target['text']}
                                if item['href'].startswith('/guide/') else None)
                    self.assertEqual(item['target_evidence'], expected)
                if mode == 'positive':
                    self.assertEqual(report['semantic_evaluations'][0]['assessment'], 'no-issue-signaled')

    def test_semantic_destination_copies_are_bounded_before_provider(self):
        from unittest.mock import patch
        core = self.core()
        provider = self.provider()
        data = self.inventory([self.page(links=[self.link()] * 4),
            self.page('https://example.com/guide/', text='Evidence ' * 50)])
        with patch.object(core, 'MAX_EVIDENCE_CHARS', 3000):
            core.validate_inventory(data)
            with self.assertRaisesRegex(core.InputError, 'destination report evidence limit'):
                core.audit(data, provider='jev', client=provider)
        self.assertEqual(provider.calls, [])

    def test_rules_resolve_links_and_fragments_without_network(self):
        from unittest.mock import patch
        core = self.core()
        self.assertTrue(hasattr(core, 'audit'), 'offline audit API is required')
        hrefs = ['../guide/index.html?x=1#caf%C3%A9', '/guide/#legacy', '#intro',
                 '/missing/', '/guide/#absent', 'https://outside.test/path',
                 'mailto:help@example.com', 'tel:123', 'javascript:alert(1)', 'data:text/plain,x',
                 '//example.com/guide/', '/guide/../guide/?q=x', '/%67uide/', 'https://user:pass@example.com/']
        source = self.page(url='https://example.com/docs/', ids=['intro'],
                           links=[self.link(href=href) for href in hrefs])
        target = self.page(url='https://example.com/guide/', ids=['café', 'legacy'])
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            report = core.audit(self.load(self.inventory([source, target])))
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['version'], '0.1.0')
        self.assertEqual(report['provider'], 'rules')
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['coverage']['pages'], 2)
        self.assertEqual(report['coverage']['links'], len(hrefs))
        self.assertEqual(report['coverage']['rules_evaluated'], len(hrefs))
        self.assertEqual(report['coverage']['semantic_calls'], 0)
        self.assertEqual([f['href'] for f in report['findings'] if f['rule'] == 'broken-link'], ['/missing/'])
        missing = [f for f in report['findings'] if f['rule'] == 'missing-fragment']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['href'], '/guide/#absent')
        self.assertEqual(missing[0]['anchor'], 'Guide')
        self.assertEqual(missing[0]['context'], 'Read the Guide for details.')
        self.assertEqual(missing[0]['occurrence'], 5)
        self.assertEqual(missing[0]['source_url'], source['url'])
        self.assertEqual(missing[0]['target_url'], 'https://example.com/guide/#absent')
        self.assertEqual(report['coverage']['classifications']['same-page'], 1)
        for kind in ['external', 'mailto', 'tel', 'javascript', 'unsupported', 'invalid']:
            self.assertEqual(report['coverage']['classifications'][kind], 1)
        self.assertEqual(report['all_findings'], len(report['findings']))

    def test_rules_flag_anchor_labels_and_noindex_with_unique_stable_evidence(self):
        source = self.page(links=[self.link(anchor=''), self.link(anchor='Click here'),
                                  self.link('/guide/', 'Pricing'), self.link('/other/', 'Pricing'),
                                  self.link('/gone/', 'Missing'), self.link('/gone/', 'Missing')])
        target = self.page('https://example.com/guide/', noindex=True)
        data = self.load(self.inventory([source, target, self.page('https://example.com/other/')]))
        report = self.core().audit(data)
        rules = [f['rule'] for f in report['findings']]
        self.assertIn('empty-anchor', rules)
        self.assertIn('generic-anchor', rules)
        self.assertEqual(rules.count('label-conflict'), 2)
        self.assertIn('noindex-page', rules)
        self.assertIn('noindex-target', rules)
        self.assertTrue(report['page_evidence'][1]['noindex'])
        fingerprints = [f['fingerprint'] for f in report['findings']]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))
        self.assertEqual(fingerprints, [f['fingerprint'] for f in self.core().audit(data)['findings']])
        self.assertTrue(all(f['evidence_source'] == 'inventory' for f in report['findings']))

    def test_jev_uses_exact_evidence_and_preserves_provenance(self):
        class ProviderDouble:
            def __init__(self):
                self.calls = []
            def evaluate(self, *args):
                self.calls.append(args)
                return {'model_requested': 'jev-test', 'model_resolved': 'jev-test-resolved',
                        'signals': {'promise': 0.1, 'relevance': 0.1, 'label': 'misleading',
                                    'confidence': 0.9, 'probabilities': {'informative': 0.03, 'generic': 0.03, 'misleading': 0.9, 'insufficient_context': 0.04}},
                        'usage': {'input_tokens': 12, 'output_tokens': 8}, 'duration_ms': 11.5,
                        'truncation': {'target_text': {'original_chars': len(args[3]), 'sent_chars': len(args[3]), 'truncated': False}}}
        provider = ProviderDouble()
        source = self.page(links=[self.link()])
        target = self.page('https://example.com/guide/', title='Target title', text='Long destination text. ' * 10)
        data = self.load(self.inventory([source, target]))
        report = self.core().audit(data, provider='jev', model='jev-test', client=provider)
        self.assertEqual(provider.calls, [('Guide', 'Read the Guide for details.', 'Target title', target['text'])])
        self.assertEqual(report['coverage']['semantic_calls'], 1)
        self.assertEqual(report['coverage']['semantic_evaluated'], 1)
        self.assertEqual(report['usage'], {'input_tokens': 12, 'output_tokens': 8})
        self.assertEqual(report['duration_ms'], 11.5)
        self.assertEqual(report['status'], 'complete')
        findings = {f['rule']: f for f in report['findings']}
        self.assertIn('semantic-mismatch', findings)
        self.assertIn('context-mismatch', findings)
        self.assertEqual(findings['semantic-mismatch']['model']['signals']['promise'], 0.1)
        self.assertEqual(findings['semantic-mismatch']['model']['model_resolved'], 'jev-test-resolved')
        self.assertFalse(findings['semantic-mismatch']['model']['truncation']['target_text']['truncated'])
        self.assertEqual(findings['semantic-mismatch']['target_evidence']['text'], target['text'])

    def provider(self, **signals):
        from types import SimpleNamespace
        calls = []
        def evaluate(*args):
            calls.append(args)
            return {'model_requested': 'jev-test', 'model_resolved': 'jev-test',
                    'signals': {'promise': 0.9, 'relevance': 0.9, 'label': 'informative', 'confidence': 0.9,
                                'probabilities': {'informative': 0.9, 'generic': 0.03, 'misleading': 0.03, 'insufficient_context': 0.04}, **signals},
                    'usage': {'input_tokens': 12, 'output_tokens': 8}, 'duration_ms': 10,
                    'truncation': {}}
        return SimpleNamespace(calls=calls, evaluate=evaluate)

    def test_jev_uncertain_and_contradictory_signals_require_review(self):
        data = self.load(self.inventory([self.page(links=[self.link()]),
            self.page('https://example.com/guide/', text='Sufficient destination evidence. ' * 5)]))
        for signals in ({'confidence': 0.69, 'promise': 0.1, 'relevance': 0.1, 'label': 'misleading'},
                        {'promise': 0.1, 'relevance': 0.9, 'label': 'misleading'},
                        {'promise': 0.9, 'relevance': 0.1}, {'label': 'generic'},
                        {'label': 'insufficient_context'}, {'promise': 0.5, 'relevance': 0.5}):
            with self.subTest(signals=signals):
                report = self.core().audit(data, provider='jev', client=self.provider(**signals))
                self.assertEqual([f['rule'] for f in report['findings']], ['semantic-review'])
                self.assertEqual(report['semantic_evaluations'][0]['assessment'], 'review')
        report = self.core().audit(data, provider='jev', client=self.provider())
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['semantic_evaluations'][0]['assessment'], 'no-issue-signaled')

    def test_jev_budget_memoization_and_ineligible_coverage(self):
        provider = self.provider()
        source = self.page(links=[self.link(), self.link(), self.link(context='Changed context for the Guide.'),
            self.link(anchor=''), self.link(anchor='Click here'), self.link('/missing/'),
            self.link('/guide/#missing'), self.link('/short/'), self.link('mailto:x@example.com')])
        data = self.load(self.inventory([source,
            self.page('https://example.com/guide/', text='Sufficient destination evidence. ' * 5),
            self.page('https://example.com/short/', text='Short')]))
        report = self.core().audit(data, provider='jev', client=provider, max_links=1)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['coverage']['semantic_eligible'], 3)
        self.assertEqual(report['coverage']['semantic_evaluated'], 2)
        self.assertEqual(report['coverage']['semantic_cache_hits'], 1)
        self.assertEqual(report['coverage']['semantic_not_evaluated'], 7)
        self.assertEqual(report['usage']['input_tokens'], 12)
        evaluations = report['semantic_evaluations']
        self.assertEqual(len(evaluations), 9)
        self.assertEqual([item.get('reason') for item in evaluations[2:]],
                         ['budget', 'empty_anchor', 'generic_anchor', 'broken_target', 'missing_fragment', 'insufficient_context', 'not_internal'])
        self.assertEqual([item['status'] for item in evaluations[2:]], ['not_evaluated'] * 7)
        self.assertIn('semantic-insufficient-evidence', [f['rule'] for f in report['findings']])
        self.assertTrue(any(error['code'] == 'budget_exhausted' for error in report['errors']))
        provider = self.provider()
        complete = self.core().audit(data, provider='jev', client=provider, max_links=2)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(complete['status'], 'complete')
        for maximum in (0, -1, True, 1.2, 10001):
            with self.subTest(maximum=maximum), self.assertRaises(self.core().InputError):
                self.core().audit(data, provider='jev', client=provider, max_links=maximum)

    def test_provider_failure_is_sanitized_partial_and_not_a_false_pass(self):
        provider = self.provider()
        def broken(*args):
            provider.calls.append(args)
            raise RuntimeError('TOP_SECRET raw response body')
        provider.evaluate = broken
        data = self.load(self.inventory([self.page(links=[self.link(), self.link()]),
            self.page('https://example.com/guide/', text='Sufficient destination evidence. ' * 5)]))
        try:
            report = self.core().audit(data, provider='jev', client=provider)
        except RuntimeError:
            self.fail('Provider failure must produce an inspectable partial report')
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['coverage']['semantic_calls'], 1)
        self.assertEqual(report['coverage']['semantic_errors'], 2)
        self.assertEqual(report['coverage']['semantic_evaluated'], 0)
        self.assertEqual(report['coverage']['semantic_not_evaluated'], 2)
        self.assertEqual(len(provider.calls), 1)
        self.assertNotIn('TOP_SECRET', json.dumps(report))
        self.assertNotIn('raw response body', json.dumps(report))
        self.assertEqual(report['semantic_evaluations'][0]['reason'], 'provider_error')
        self.assertNotIn('model', report['semantic_evaluations'][0])
        with self.assertRaises(self.core().InputError):
            self.core().audit(data, provider='unknown', client=provider)
        bad = self.inventory([self.page(links=[self.link()]), self.page(title=False)])
        before = len(provider.calls)
        with self.assertRaises(self.core().InputError):
            self.core().audit(bad, provider='jev', client=provider)
        self.assertEqual(len(provider.calls), before)

    def test_audit_accepts_raw_inventory_and_keeps_html_source_evidence(self):
        raw = self.inventory([self.page(url='https://EXAMPLE.com:443/index.html',
                                      links=[self.link('/missing/')])])
        try:
            report = self.core().audit(raw)
        except (KeyError, TypeError):
            self.fail('Public audit API must consume validated defaults and normalized identities')
        self.assertEqual(report['findings'][0]['source_url'], 'https://example.com/')
        self.assertEqual(report['findings'][0]['occurrence'], 1)
        (self.root / 'index.html').write_text('<html><head><title>Not body text</title></head><p>Visible <a href="/gone/">Broken</a>.</p></html>')
        loaded = self.core().load_inventory(self.root, 'https://example.com/')
        self.assertEqual(loaded['pages'][0]['text'], 'Visible Broken.')
        report = self.core().audit(loaded)
        self.assertEqual(report['findings'][0]['source_file'], 'index.html')
        self.assertEqual(report['findings'][0]['line'], 1)
        self.assertEqual(report['findings'][0]['evidence_source'], 'html')

    def test_any_truncated_model_evidence_requires_review_not_a_clean_assessment(self):
        data = self.inventory([self.page(links=[self.link()]),
            self.page('https://example.com/guide/', text='Destination evidence. ' * 10)])
        for field in ('anchor', 'context', 'target_title', 'target_text'):
            with self.subTest(field=field):
                provider = self.provider()
                original = provider.evaluate
                def evaluate(*args):
                    result = original(*args)
                    result['truncation'] = {field: {'original_chars': 100, 'sent_chars': 20, 'truncated': True}}
                    return result
                provider.evaluate = evaluate
                report = self.core().audit(data, provider='jev', client=provider)
                self.assertEqual([f['rule'] for f in report['findings']], ['semantic-review'])
                self.assertEqual(report['semantic_evaluations'][0]['assessment'], 'review')
                self.assertTrue(report['semantic_evaluations'][0]['model']['truncation'][field]['truncated'])

    def test_aggregate_evidence_limits_fail_before_provider_without_truncating_quotes(self):
        from unittest.mock import patch
        core = self.core()
        self.assertTrue(hasattr(core, 'MAX_EVIDENCE_CHARS'), 'aggregate evidence must have a hard cap')
        (self.root / 'index.html').write_text('<body>' + 'Body ' * 80 + '<a href="/guide/">Guide</a>' * 10 + '</body>')
        with patch.object(core, 'MAX_EVIDENCE_CHARS', 1000):
            with self.assertRaises(core.InputError):
                core.load_inventory(self.root, 'https://example.com/')
            data = self.inventory([self.page(links=[self.link(context='Exact words ' * 30)] * 10)])
            with self.assertRaises(core.InputError):
                self.load(data)
        provider = self.provider()
        data = self.inventory([self.page(links=[self.link()] * 20),
                               self.page('https://example.com/guide/', text='Evidence ' * 200)])
        with patch.object(core, 'MAX_EVIDENCE_CHARS', 5000):
            with self.assertRaises(core.InputError):
                core.audit(data, provider='jev', client=provider)
        self.assertEqual(provider.calls, [])

    def test_special_files_and_invalid_unicode_are_rejected_before_read(self):
        import os
        from unittest.mock import patch
        core = self.core()
        if hasattr(os, 'mkfifo'):
            fifo = self.root / 'pipe.json'
            os.mkfifo(fifo)
            with patch.object(Path, 'read_text', side_effect=AssertionError('must not read a special file')):
                with self.assertRaises(core.InputError):
                    core.read_json(fifo)
        with self.assertRaises(core.InputError):
            self.load(self.inventory([self.page(title='\ud800')]))

    def test_semantic_fingerprints_change_with_model_or_destination_evidence(self):
        data = self.inventory([self.page(links=[self.link()]),
            self.page('https://example.com/guide/', text='Destination evidence. ' * 10)])
        provider = self.provider(promise=0.1, relevance=0.1, label='misleading')
        first = self.core().audit(data, provider='jev', client=provider, model='jev-one')
        second = self.core().audit(data, provider='jev', client=provider, model='jev-two')
        self.assertNotEqual(first['findings'][0]['fingerprint'], second['findings'][0]['fingerprint'])
        data['pages'][1]['text'] += 'Changed evidence.'
        third = self.core().audit(data, provider='jev', client=provider, model='jev-one')
        self.assertNotEqual(first['findings'][0]['fingerprint'], third['findings'][0]['fingerprint'])

    def test_body_text_excludes_title_and_template_fragment_targets(self):
        (self.root / 'index.html').write_text('<title>Metadata only</title><p>Visible body.</p><template><div id="not-real">Template text</div></template><p hidden id="real">Hidden body</p>')
        page = self.core().load_inventory(self.root, 'https://example.com/')['pages'][0]
        self.assertEqual(page['title'], 'Metadata only')
        self.assertEqual(page['text'], 'Visible body.')
        self.assertNotIn('not-real', page['ids'])
        self.assertIn('real', page['ids'])

    def test_url_identity_preserves_nondefault_zero_port_and_decoded_paths(self):
        core = self.core()
        cases = {'https://example.com:0/': 'https://example.com:0/',
                 'https://EXAMPLE.com:443/caf%C3%A9/index.html?q=1#part': 'https://example.com/caf%C3%A9/',
                 'http://example.com:8080/a/../b/': 'http://example.com:8080/b/'}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(core.normalize_url(raw), expected)
        for raw in ('https://example.com/%00', 'https://example.com/%ZZ', 'https://example.com:99999/'):
            with self.subTest(raw=raw), self.assertRaises(core.InputError):
                core.normalize_url(raw)

    def test_nested_list_context_keeps_valid_parent_structure(self):
        (self.root / 'index.html').write_text('<ul><li>Outer <a href="/one/">one</a><ul><li>Inner <a href="/two/">two</a></li></ul> tail</li></ul>')
        links = self.core().load_inventory(self.root, 'https://example.com/')['pages'][0]['links']
        self.assertEqual(links[0]['context'], 'Outer one Inner two tail')
        self.assertEqual(links[1]['context'], 'Inner two')


if __name__ == '__main__':
    unittest.main()
