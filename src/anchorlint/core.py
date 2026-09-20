"""Bounded offline input collection and evidence-based link auditing."""
import json
import hashlib
import math
from . import __version__
from html.parser import HTMLParser
import posixpath
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

MAX_PAGES = 10000
MAX_ASSETS = 100000
MAX_LINKS = 100000
MAX_TEXT_CHARS = 2_000_000
MAX_JSON_BYTES = 32_000_000
MAX_EVIDENCE_CHARS = 8_000_000


class InputError(ValueError):
    """Invalid, unsafe or excessive input; safe to display to a user."""


def normalize_url(value):
    """HTTP(S) file identity: decoded path, no query/fragment, index alias."""
    if not isinstance(value, str) or not value or re.search(r'[\x00-\x20\x7f\\]', value):
        raise InputError('URLs must be nonempty HTTP(S) URLs without whitespace or backslashes')
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        scheme = parts.scheme.lower()
        host = parts.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            host = '[' + host + ']'
        port = parts.port
        netloc = host + (f':{port}' if port is not None and port != {'http': 80, 'https': 443}[scheme] else '')
        if re.search(r'%(?![0-9a-fA-F]{2})', parts.path):
            raise ValueError
        path = unquote(parts.path or '/', errors='strict')
        if re.search(r'[\x00-\x1f\x7f\\]', path):
            raise ValueError
        trailing = path.endswith('/')
        path = '/' + posixpath.normpath('/' + path.lstrip('/')).lstrip('/')
        if path.rsplit('/', 1)[-1].lower() in {'index.html', 'index.htm'}:
            path = path.rsplit('/', 1)[0] + '/'
        elif trailing and path != '/':
            path += '/'
        return urlunsplit((scheme, netloc, quote(path, safe='/~!$&\'()*+,;=:@-._'), '', ''))
    except (ValueError, UnicodeError):
        raise InputError('URLs must be valid HTTP(S) URLs without credentials') from None


def _origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc


def _text(value, field):
    if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS or re.search(r'[\ud800-\udfff]', value):
        raise InputError(f'{field} must be a string of at most {MAX_TEXT_CHARS} characters')
    return value


def _evidence_size(page):
    return (sum(len(page[key]) for key in ('url', 'title', 'text'))
            + sum(len(value) for key in ('ids', 'headings') for value in page[key])
            + sum(len(link[key]) for link in page['links'] for key in ('href', 'anchor', 'context')))


def validate_inventory(data, base_url=None):
    """Validate the entire inventory before audit/provider work. Ignore unknown fields."""
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise InputError('Inventory schema_version must be 1')
    base = normalize_url(data.get('base_url'))
    if base_url is not None:
        base = normalize_url(base_url)
    raw_pages = data.get('pages')
    if not isinstance(raw_pages, list) or not 1 <= len(raw_pages) <= MAX_PAGES:
        raise InputError(f'Inventory must contain 1..{MAX_PAGES} pages')
    pages, seen, link_count, evidence_chars = [], set(), 0, 0
    for item in raw_pages:
        if not isinstance(item, dict):
            raise InputError('Every page must be an object')
        url = normalize_url(item.get('url'))
        if _origin(url) != _origin(base):
            raise InputError('Inventory pages must share the base URL origin')
        if url in seen:
            raise InputError('Duplicate normalized page URL')
        seen.add(url)
        page = {'url': url, 'title': _text(item.get('title'), 'page.title'),
                'text': _text(item.get('text'), 'page.text'), 'evidence_source': 'inventory'}
        for field in ('headings', 'ids'):
            values = item.get(field, [])
            if not isinstance(values, list) or len(values) > MAX_LINKS:
                raise InputError(f'page.{field} must be a bounded list of strings')
            page[field] = [_text(value, field) for value in values]
        noindex = item.get('noindex', False)
        if type(noindex) is not bool:
            raise InputError('page.noindex must be a boolean')
        page['noindex'] = noindex
        links = item.get('links')
        if not isinstance(links, list):
            raise InputError('page.links must be an array')
        link_count += len(links)
        if link_count > MAX_LINKS:
            raise InputError(f'Inventory exceeds {MAX_LINKS} links')
        page['links'] = []
        for i, link in enumerate(links, 1):
            if not isinstance(link, dict):
                raise InputError('Every link must be an object')
            record = {key: _text(link.get(key), f'link.{key}') for key in ('href', 'anchor', 'context')}
            if 'line' in link:
                if type(link['line']) is not int or link['line'] < 1:
                    raise InputError('link.line must be a positive integer')
                record['line'] = link['line']
            record['occurrence'] = i
            page['links'].append(record)
        evidence_chars += _evidence_size(page)
        if evidence_chars > MAX_EVIDENCE_CHARS:
            raise InputError('Aggregate evidence character limit exceeded')
        pages.append(page)
    raw_assets = data.get('assets', [])
    if not isinstance(raw_assets, list) or len(raw_assets) > MAX_ASSETS:
        raise InputError(f'Inventory assets must be an array of at most {MAX_ASSETS} URLs')
    assets = []
    for raw_url in raw_assets:
        url = _text(normalize_url(_text(raw_url, 'asset.url')), 'asset.url')
        path = unquote(urlsplit(raw_url).path)
        if (_origin(url) != _origin(base) or '?' in raw_url or '#' in raw_url
                or not path or path.endswith('/') or posixpath.splitext(path)[1].lower() in {'.html', '.htm'}
                or any(part in {'.', '..'} for part in path.split('/'))):
            raise InputError('Assets must be same-origin non-HTML file URLs without query, fragment or dot segments')
        if url in seen:
            raise InputError('Duplicate normalized asset or page URL')
        seen.add(url)
        assets.append(url)
        evidence_chars += len(url)
        if evidence_chars > MAX_EVIDENCE_CHARS:
            raise InputError('Aggregate evidence character limit exceeded')
    return {'schema_version': 1, 'base_url': base, 'pages': pages, 'assets': assets}


def resolve_link(source_url, href):
    """Classify a link and resolve identity without fetching any resource."""
    candidate = href.strip()
    try:
        if re.search(r'[\x00-\x1f\x7f\\]', candidate):
            raise ValueError
        parts = urlsplit(candidate)
        if parts.scheme.lower() in {'mailto', 'tel', 'javascript'}:
            return {'classification': parts.scheme.lower(), 'target_url': candidate, 'identity': None, 'fragment': ''}
        if parts.scheme and parts.scheme.lower() not in {'http', 'https'}:
            return {'classification': 'unsupported', 'target_url': candidate, 'identity': None, 'fragment': ''}
        absolute = urljoin(source_url, candidate)
        identity = normalize_url(absolute)
        fragment_raw = urlsplit(absolute).fragment
        if re.search(r'%(?![0-9a-fA-F]{2})', fragment_raw):
            raise ValueError
        fragment = unquote(fragment_raw, errors='strict')
        kind = 'internal' if _origin(identity) == _origin(source_url) else 'external'
        if kind == 'internal' and identity == source_url:
            kind = 'same-page'
        return {'classification': kind, 'identity': identity, 'fragment': fragment,
                'target_url': identity + ('#' + fragment_raw if fragment_raw else '')}
    except (ValueError, UnicodeError):
        return {'classification': 'invalid', 'target_url': candidate, 'identity': None, 'fragment': ''}


def _finding(report, page, link, target_url, rule, severity, message, **extra):
    record = {'rule': rule, 'severity': severity, 'message': message, 'source_url': page['url'],
              'target_url': target_url, 'href': link.get('href', ''), 'anchor': link.get('anchor', ''),
              'context': link.get('context', ''), 'occurrence': link.get('occurrence', 0),
              'source_file': page.get('source_file'), 'line': link.get('line'),
              'evidence_source': page.get('evidence_source', 'inventory'), 'is_new': True, **extra}
    identity = [record[key] for key in ('source_url', 'target_url', 'rule', 'occurrence', 'anchor', 'context')]
    if 'model' in record:
        identity.extend([report.get('model'), record['model']['model_requested'], record['model']['model_resolved'], record.get('target_evidence')])
    record['fingerprint'] = hashlib.sha256(json.dumps(identity, ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
    report['findings'].append(record)
    return record


GENERIC_ANCHORS = {'click here', 'here', 'read more', 'learn more', 'more', 'link', 'this link', 'details', 'view more', 'continue'}


def _label(anchor):
    return ' '.join(anchor.casefold().split()).strip(' .!?:;,')


def _has_fragment(page, fragment):
    return not fragment or fragment in page['ids'] or fragment.lower() == 'top'


def audit(inventory, provider='rules', max_links=25, model='jev-1.13.0', client=None):
    """Audit a previously collected inventory. Rules mode is always offline."""
    validated = validate_inventory(inventory)
    for original, normalized in zip(inventory['pages'], validated['pages']):
        if original.get('evidence_source') == 'html':
            for key in ('source_file', 'evidence_source', 'robots', 'ignored_base', 'ignored_canonical'):
                normalized[key] = original.get(key)
    inventory = validated
    if provider not in {'rules', 'jev'}:
        raise InputError('provider must be rules or jev')
    if type(max_links) is not int or not 1 <= max_links <= 10000:
        raise InputError('max_links must be an integer from 1 to 10000')
    pages = {page['url']: page for page in inventory['pages']}
    assets = set(inventory['assets'])
    page_labels, report_evidence_chars = {}, 0
    # At most three rule findings; Jev adds an evaluation and two findings.
    # Reserve all possible copies even for cached, skipped or failed evaluations.
    record_copies = 6 if provider == 'jev' else 3
    for page in pages.values():
        source_file_chars = len(page.get('source_file') or '')
        report_evidence_chars += _evidence_size(page) + source_file_chars
        if page['noindex']:
            report_evidence_chars += 2 * len(page['url']) + source_file_chars
        if report_evidence_chars > MAX_EVIDENCE_CHARS:
            raise InputError('Aggregate report evidence limit exceeded')
        labels, occurrences = {}, {}
        for link in page['links']:
            resolved = resolve_link(page['url'], link['href'])
            label = _label(link['anchor'])
            # Relative hrefs repeat the source path; normalization may percent-encode
            # Unicode. Measure the actual derived strings, not just the raw href.
            link_chars = (len(page['url']) + len(resolved['target_url']) + source_file_chars
                          + sum(len(link[key]) for key in ('href', 'anchor', 'context')))
            report_evidence_chars += (record_copies * link_chars + len(label)
                                      + len(resolved['identity'] or '') + len(resolved['fragment']))
            if provider == 'jev':
                report_evidence_chars += len(page['url'])  # Possible provider-error record.
            if report_evidence_chars > MAX_EVIDENCE_CHARS:
                raise InputError('Aggregate report evidence limit exceeded')
            if resolved['classification'] in {'internal', 'same-page'} and label:
                labels.setdefault(label, set()).add(resolved['target_url'])
                occurrences[label] = occurrences.get(label, 0) + 1
        for label, targets in labels.items():
            if len(targets) > 1 and label not in GENERIC_ANCHORS:
                report_evidence_chars += occurrences[label] * sum(len(url) + 4 for url in targets)
                if report_evidence_chars > MAX_EVIDENCE_CHARS:
                    raise InputError('Aggregate conflict report evidence limit exceeded')
        page_labels[page['url']] = labels
    if provider == 'jev':
        for page in pages.values():
            for link in page['links']:
                target = pages.get(resolve_link(page['url'], link['href'])['identity'])
                if target is not None:
                    # Share the same budget with link copies and conflict evidence.
                    report_evidence_chars += 3 * (len(target['text']) + len(target['title']))
                    if report_evidence_chars > MAX_EVIDENCE_CHARS:
                        raise InputError('Aggregate destination report evidence limit exceeded')
    coverage = {'pages': len(pages), 'links': 0, 'rules_evaluated': 0, 'semantic_calls': 0,
                'semantic_evaluated': 0, 'semantic_not_evaluated': 0, 'semantic_errors': 0,
                'semantic_eligible': 0, 'semantic_cache_hits': 0, 'classifications': {}}
    report = {'schema_version': 1, 'version': __version__, 'provider': provider, 'status': 'complete',
              'model': model if provider == 'jev' else None, 'max_links': max_links,
              'coverage': coverage, 'findings': [], 'errors': [], 'all_findings': 0,
              'semantic_evaluations': [], 'page_evidence': [],
              'usage': {'input_tokens': 0, 'output_tokens': 0}, 'duration_ms': 0.0}
    for page in pages.values():
        report['page_evidence'].append({key: page.get(key) for key in ('url', 'title', 'headings', 'noindex', 'robots', 'ignored_base', 'ignored_canonical', 'source_file', 'evidence_source')})
        if page['noindex']:
            _finding(report, page, {}, page['url'], 'noindex-page', 'info', 'Page declares noindex metadata; no ranking inference is made.')
        labels = page_labels[page['url']]
        for link in page['links']:
            coverage['links'] += 1
            coverage['rules_evaluated'] += 1
            resolved = resolve_link(page['url'], link['href'])
            kind = resolved['classification']
            coverage['classifications'][kind] = coverage['classifications'].get(kind, 0) + 1
            if kind == 'invalid':
                _finding(report, page, link, resolved['target_url'], 'invalid-url', 'error', 'URL cannot be safely resolved.')
            if kind == 'javascript':
                _finding(report, page, link, resolved['target_url'], 'javascript-link', 'warning', 'JavaScript link is not a navigable document URL.')
            if kind not in {'internal', 'same-page'}:
                continue
            label = _label(link['anchor'])
            if not label:
                _finding(report, page, link, resolved['target_url'], 'empty-anchor', 'warning', 'Link has no visible anchor text; inspect its intended label.')
            elif label in GENERIC_ANCHORS:
                _finding(report, page, link, resolved['target_url'], 'generic-anchor', 'warning', 'Generic anchor supplies insufficient destination evidence.')
            elif len(labels.get(label, ())) > 1:
                _finding(report, page, link, resolved['target_url'], 'label-conflict', 'warning', 'The same label names different destinations on this source page; review intent.',
                         conflicting_targets=sorted(labels[label]))
            target = pages.get(resolved['identity'])
            if target is not None and target['noindex']:
                _finding(report, page, link, resolved['target_url'], 'noindex-target', 'warning', 'Destination declares noindex metadata; verify this is intentional.')
            if target is None:
                if resolved['identity'] not in assets:
                    _finding(report, page, link, resolved['target_url'], 'broken-link', 'error', 'Target is absent from the local inventory.')
            elif not _has_fragment(target, resolved['fragment']):
                _finding(report, page, link, resolved['target_url'], 'missing-fragment', 'error', 'Target page has no matching ID or named anchor.')
    if provider == 'jev':
        memo = {}
        for page in pages.values():
            for link in page['links']:
                resolved = resolve_link(page['url'], link['href'])
                target = pages.get(resolved['identity'])
                record = {'source_url': page['url'], 'target_url': resolved['target_url'],
                          'href': link['href'], 'anchor': link['anchor'], 'context': link['context'],
                          'occurrence': link['occurrence'], 'status': 'not_evaluated',
                          'target_evidence': {'title': target['title'], 'text': target['text']} if target is not None else None}
                report['semantic_evaluations'].append(record)
                reason = None
                if resolved['classification'] not in {'internal', 'same-page'}:
                    reason = 'not_internal'
                elif resolved['identity'] in assets:
                    reason = 'non_html_target'
                elif target is None:
                    reason = 'broken_target'
                elif not _has_fragment(target, resolved['fragment']):
                    reason = 'missing_fragment'
                elif not _label(link['anchor']):
                    reason = 'empty_anchor'
                elif _label(link['anchor']) in GENERIC_ANCHORS:
                    reason = 'generic_anchor'
                elif len(target['text'].strip()) < 40 or not link['context'].strip():
                    reason = 'insufficient_context'
                if reason:
                    record['reason'] = reason
                    coverage['semantic_not_evaluated'] += 1
                    if reason in {'empty_anchor', 'generic_anchor', 'insufficient_context'}:
                        _finding(report, page, link, resolved['target_url'], 'semantic-insufficient-evidence', 'warning', 'Insufficient visible evidence for a semantic assessment; human review is required.', reason=reason)
                    continue
                coverage['semantic_eligible'] += 1
                inputs = (link['anchor'], link['context'], target['title'], target['text'])
                cache_key = (model, *inputs)
                if cache_key in memo:
                    result = memo[cache_key]
                    coverage['semantic_cache_hits'] += 1
                    record['cached'] = True
                elif coverage['semantic_calls'] >= max_links:
                    record['reason'] = 'budget'
                    coverage['semantic_not_evaluated'] += 1
                    report['status'] = 'partial'
                    if not any(error['code'] == 'budget_exhausted' for error in report['errors']):
                        report['errors'].append({'code': 'budget_exhausted', 'message': 'Model-call budget exhausted; eligible links remain unevaluated.'})
                    continue
                else:
                    try:
                        if client is None:
                            from .jev import JevClient
                            client = JevClient(model=model)
                        coverage['semantic_calls'] += 1
                        result = client.evaluate(*inputs)
                    except (RuntimeError, OSError, ValueError):
                        result = None
                        report['errors'].append({'code': 'provider_error', 'message': 'Jev evaluation failed; verify configuration or retry.',
                                                 'source_url': page['url'], 'occurrence': link['occurrence']})
                    memo[cache_key] = result
                    record['cached'] = False
                    if result is not None:
                        for key in report['usage']:
                            report['usage'][key] += result['usage'][key]
                        report['duration_ms'] += result['duration_ms']
                if result is None:
                    record['reason'] = 'provider_error'
                    coverage['semantic_errors'] += 1
                    coverage['semantic_not_evaluated'] += 1
                    report['status'] = 'partial'
                    continue
                coverage['semantic_evaluated'] += 1
                record.update(status='evaluated', model=result)
                extra = {'model': result, 'target_evidence': record['target_evidence']}
                signals = result['signals']
                promise, relevance, label = signals['promise'], signals['relevance'], signals['label']
                contradictions = ((promise <= 0.2 and relevance >= 0.8) or (relevance <= 0.2 and promise >= 0.8)
                                  or (label == 'informative' and min(promise, relevance) <= 0.2)
                                  or (label == 'misleading' and promise >= 0.8))
                clear_warning = (promise <= 0.2 and label == 'misleading') or relevance <= 0.2
                clear_positive = promise >= 0.7 and relevance >= 0.7 and label == 'informative'
                truncated = any(field.get('truncated', False) for field in result['truncation'].values())
                review = (signals['confidence'] < 0.7 or contradictions or truncated or label in {'generic', 'insufficient_context'}
                          or not (clear_warning or clear_positive))
                assessment = 'review' if review else ('warning' if clear_warning else 'no-issue-signaled')
                report['semantic_evaluations'][-1]['assessment'] = assessment
                if review:
                    _finding(report, page, link, resolved['target_url'], 'semantic-review', 'warning', 'Uncertain, generic, contradictory or truncated model evidence requires human review.', **extra)
                else:
                    if promise <= 0.2 and label == 'misleading':
                        _finding(report, page, link, resolved['target_url'], 'semantic-mismatch', 'warning', 'Model signals a possible anchor-promise mismatch; verify the supplied evidence.', **extra)
                    if relevance <= 0.2:
                        _finding(report, page, link, resolved['target_url'], 'context-mismatch', 'warning', 'Model signals low relevance to the source context; verify the supplied evidence.', **extra)
    report['all_findings'] = len(report['findings'])
    return report


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError('Duplicate JSON object key')
        result[key] = value
    return result


_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
_BLOCK = set('address article aside blockquote br dd div dl dt fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 header hr li main nav ol p pre section table td th tr ul'.split())
_EXCLUDED = {'script', 'style', 'template', 'noscript'}


class _HTML(HTMLParser):
    """Small static-text tree; no CSS engine, JS execution or external resources."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': 'document', 'children': [], 'hidden': False, 'parent': None}
        self.stack = [self.root]
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(reversed(attrs))  # HTML keeps the first duplicate attribute.
        if tag in {'p', 'li', 'a'}:
            for i in range(len(self.stack) - 1, 0, -1):
                if tag == 'li' and self.stack[i]['tag'] in {'ul', 'ol'}:
                    break
                if self.stack[i]['tag'] == tag:
                    self.stack = self.stack[:i]
                    break
        if tag in _BLOCK and tag != 'br':
            for i in range(len(self.stack) - 1, 0, -1):
                if self.stack[i]['tag'] == 'p':
                    self.stack = self.stack[:i]
                    break
                if self.stack[i]['tag'] in _BLOCK or self.stack[i]['tag'] in _EXCLUDED:
                    break
        if len(self.stack) > 256 or len(self.nodes) > 200000:
            raise InputError('HTML nesting or element limit exceeded')
        style = attrs.get('style') or ''
        hidden = (self.stack[-1]['hidden'] or tag in _EXCLUDED or 'hidden' in attrs or 'inert' in attrs
                  or (attrs.get('aria-hidden') or '').lower() == 'true'
                  or bool(re.search(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\s*(?:!important)?\s*(?:;|$)', style, re.I)))
        node = {'tag': tag, 'attrs': attrs, 'children': [], 'parent': self.stack[-1],
                'hidden': hidden, 'line': self.getpos()[0]}
        self.stack[-1]['children'].append(node)
        self.nodes.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]['tag'] == tag:
                self.stack = self.stack[:i]
                return

    def handle_data(self, text):
        self.stack[-1]['children'].append(text)


def _render(node):
    if isinstance(node, str):
        return node
    if node['hidden'] or node['tag'] in {'head', 'title'}:
        return ''
    if node['tag'] == 'img':
        return node['attrs'].get('alt') or ''
    text = ''.join(_render(child) for child in node['children'])
    return ' ' + text + ' ' if node['tag'] in _BLOCK else text


def _visible(node):
    return ' '.join(_render(node).split())


def _extract_html(text, url, source_file):
    parser = _HTML()
    parser.feed(text)
    parser.close()
    nodes = parser.nodes
    metadata_nodes = [node for node in nodes if not node['hidden']]
    body = next((node for node in metadata_nodes if node['tag'] == 'body'), parser.root)
    title = next((' '.join(''.join(_render(child) for child in node['children']).split()) for node in metadata_nodes if node['tag'] == 'title'), '')
    robots = [node['attrs'].get('content') or '' for node in metadata_nodes if node['tag'] == 'meta'
              and (node['attrs'].get('name') or '').lower() in {'robots', 'googlebot', 'bingbot'}]
    # Base/canonical hints are recorded, never allowed to remap local evidence.
    page = {'url': url, 'title': title, 'text': _visible(body), 'headings': [], 'ids': [],
            'robots': robots, 'noindex': any(re.search(r'\b(noindex|none)\b', value, re.I) for value in robots),
            'links': [], 'source_file': source_file, 'evidence_source': 'html',
            'ignored_base': [node['attrs'].get('href') or '' for node in metadata_nodes if node['tag'] == 'base'],
            'ignored_canonical': [node['attrs'].get('href') or '' for node in metadata_nodes if node['tag'] == 'link'
                                  and 'canonical' in (node['attrs'].get('rel') or '').lower().split()]}
    context_cache = {}
    evidence_chars = len(page['text']) + len(page['title'])
    for node in nodes:
        attrs = node['attrs']
        ancestor = node
        while ancestor is not None and ancestor['tag'] not in _EXCLUDED:
            ancestor = ancestor['parent']
        if ancestor is not None:
            continue
        if attrs.get('id'):
            page['ids'].append(attrs['id'])
        if node['tag'] == 'a' and attrs.get('name'):
            page['ids'].append(attrs['name'])
        if node['hidden']:
            continue
        if node['tag'] in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            page['headings'].append(_visible(node))
        if node['tag'] == 'a' and 'href' in attrs:
            context = node['parent']
            while context['parent'] and context['tag'] not in {'p', 'li', 'dt', 'dd', 'figcaption', 'blockquote'}:
                context = context['parent']
            if context is parser.root:
                context = node['parent']
            cache_key = id(context)
            if cache_key not in context_cache:
                context_cache[cache_key] = _visible(context)
            anchor, context_text = _visible(node), context_cache[cache_key]
            evidence_chars += len(attrs['href'] or '') + len(anchor) + len(context_text)
            if evidence_chars > MAX_EVIDENCE_CHARS or len(page['links']) >= MAX_LINKS:
                raise InputError('Aggregate extracted link evidence limit exceeded')
            page['links'].append({'href': attrs['href'] or '', 'anchor': anchor,
                                  'context': context_text, 'line': node['line'],
                                  'occurrence': len(page['links']) + 1})
    return page


def collect_html(root, base_url):
    base = normalize_url(base_url)
    if not base.endswith('/'):
        base += '/'
    root = Path(root).resolve()
    if root == Path.home().resolve() or root in Path.home().resolve().parents:
        raise InputError('Choose a built-site directory, not a home or filesystem root')
    excluded = {'.git', '.env', 'node_modules', '.venv', 'venv', 'vendor', '__pycache__', '.hg', '.svn'}
    pages, paths, assets, entries, total_bytes = [], [], [], 0, 0
    evidence_chars = 0
    def walk_error(error):
        raise InputError('Cannot read a directory under the input root')
    try:
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(name for name in dirs if name not in excluded)
            files = sorted(name for name in files if name not in excluded and not name.startswith('.env'))
            entries += len(dirs) + len(files)
            if entries > 200000:
                raise InputError('Directory entry limit exceeded')
            for name in dirs + files:
                path = Path(directory) / name
                if path.is_symlink() and not path.resolve().is_relative_to(root):
                    raise InputError('Symlink escapes the input root')
            dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
            for name in files:
                path = Path(directory) / name
                if path.suffix.lower() not in {'.html', '.htm'}:
                    if path.is_file():
                        assets.append(_text(normalize_url(base + quote(path.relative_to(root).as_posix())), 'asset.url'))
                        if len(assets) > MAX_ASSETS:
                            raise InputError('Asset count limit exceeded')
                        evidence_chars += len(assets[-1])
                        if evidence_chars > MAX_EVIDENCE_CHARS:
                            raise InputError('Aggregate extracted evidence character limit exceeded')
                    continue
                if not path.is_file():
                    raise InputError('HTML input must be a regular file')
                size = path.stat().st_size
                total_bytes += size
                if size > MAX_TEXT_CHARS or total_bytes > 128_000_000:
                    raise InputError('HTML input byte limit exceeded')
                paths.append(path)
                if len(paths) > MAX_PAGES:
                    raise InputError('HTML page limit exceeded')
        for path in sorted(paths):
            relative = path.relative_to(root).as_posix()
            page = _extract_html(path.read_text(encoding='utf-8'), normalize_url(base + quote(relative)), relative)
            evidence_chars += _evidence_size(page)
            if evidence_chars > MAX_EVIDENCE_CHARS:
                raise InputError('Aggregate extracted evidence character limit exceeded')
            pages.append(page)
    except (OSError, UnicodeError, RecursionError):
        raise InputError('Cannot read bounded UTF-8 HTML input') from None
    inventory = {'schema_version': 1, 'base_url': base, 'pages': pages, 'assets': assets}
    validate_inventory(inventory)
    return inventory


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise InputError('Nonfinite JSON number')
    return number


def read_json(path):
    """Read bounded strict JSON for inventory or baseline import."""
    path = Path(path)
    try:
        if not path.is_file():
            raise InputError('JSON input must be a regular file')
        if path.stat().st_size > MAX_JSON_BYTES:
            raise InputError(f'JSON input exceeds {MAX_JSON_BYTES} bytes')
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object,
                          parse_float=_finite_float, parse_constant=_finite_float)
    except InputError:
        raise
    except (OSError, ValueError, RecursionError):
        raise InputError('Cannot read valid UTF-8 inventory JSON') from None
    return data


def load_inventory(path, base_url=None):
    """Load canonical inventory or an explicit built HTML root without writes."""
    path = Path(path)
    if path.is_dir():
        return collect_html(path, base_url)
    return validate_inventory(read_json(path), base_url)
