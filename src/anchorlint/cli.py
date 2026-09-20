"""Offline-first command line interface."""
import argparse
import sys
import os
from pathlib import Path
from .core import audit, load_inventory, InputError, read_json
from .reports import render_report, exit_status, validate_baseline, apply_baseline
from . import __version__


def _failure(provider, message):
    return {'schema_version': 1, 'version': __version__, 'provider': provider, 'status': 'failed',
            'coverage': {key: 0 for key in ('pages', 'links', 'rules_evaluated', 'semantic_calls', 'semantic_evaluated',
                                           'semantic_not_evaluated', 'semantic_errors', 'semantic_eligible', 'semantic_cache_hits')},
            'findings': [], 'all_findings': 0, 'errors': [{'code': 'input_error', 'message': message}],
            'semantic_evaluations': [], 'page_evidence': [], 'usage': {'input_tokens': 0, 'output_tokens': 0}, 'duration_ms': 0.0}


def _check_output(output, source, baseline):
    if output is None:
        return
    resolved = output.resolve()
    if (output.is_symlink() or not output.parent.is_dir() or output.name.startswith('.env')
            or (output.exists() and (not output.is_file() or output.stat().st_nlink > 1))
            or not os.access(output.parent, os.W_OK)):
        raise InputError('Output must be an unshared regular file, not .env or a symlink, in an existing writable directory')
    # Filesystem identity also catches case- and Unicode-equivalent directory names.
    if resolved == source.resolve() or (source.is_dir() and any(parent.samefile(source) for parent in resolved.parents)):
        raise InputError('Output must be outside the audited input')
    for protected in (source, baseline):
        if protected is not None and (resolved == protected.resolve() or
                (output.exists() and protected.is_file() and output.samefile(protected))):
            raise InputError('Output must not overwrite the input or baseline')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='anchorlint', description='Read-only internal-link evidence auditing.')
    parser.add_argument('--version', action='version', version=f'anchorlint {__version__}')
    subcommands = parser.add_subparsers(dest='command', required=True)
    audit_parser = subcommands.add_parser('audit', help='Audit a built HTML directory or canonical JSON inventory offline by default.')
    audit_parser.add_argument('path', type=Path)
    audit_parser.add_argument('--base-url', help='Required for HTML; defaults to base_url in JSON inventories.')
    audit_parser.add_argument('--format', choices=('json', 'markdown', 'html'), default='markdown')
    audit_parser.add_argument('--output', type=Path, help='Write only this report file; default is stdout.')
    audit_parser.add_argument('--provider', choices=('rules', 'jev'), default='rules', help='Jev explicitly sends selected text to its hosted API.')
    audit_parser.add_argument('--model', default='jev-1.13.0', help='Pinned Jev model identifier.')
    audit_parser.add_argument('--max-links', type=int, default=25, help='Maximum distinct Jev calls, 1..10000 (default 25).')
    audit_parser.add_argument('--baseline', type=Path, help='Compare stable findings against an AnchorLint JSON report.')
    audit_parser.add_argument('--fail-on', choices=('error', 'warning', 'never'), default='error')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    output_safe = False
    try:
        _check_output(args.output, args.path, args.baseline)
        output_safe = True
        inventory = load_inventory(args.path, args.base_url)
        baseline = read_json(args.baseline) if args.baseline is not None else None
        if args.baseline is not None:
            validate_baseline(baseline)
        report = audit(inventory, provider=args.provider, model=args.model, max_links=args.max_links)
        if baseline is not None:
            apply_baseline(report, baseline)
    except (InputError, OSError) as exc:
        message = str(exc) if isinstance(exc, InputError) else 'Cannot access the requested input or output.'
        report = _failure(args.provider, message)
        print('anchorlint: ' + message, file=sys.stderr)
    output = render_report(report, args.format)
    try:
        if args.output is not None and output_safe:
            args.output.write_text(output, encoding='utf-8')
        else:
            sys.stdout.write(output)
    except OSError:
        print('anchorlint: Unable to write the report.', file=sys.stderr)
        return 2
    return exit_status(report, args.fail_on)
