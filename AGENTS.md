# Working on AnchorLint

## Authority
User-visible behavior is specified in PRD.md; implementation truth is the tested code. If they disagree, fix the implementation or explicitly document a reviewed limitation. ARCHITECTURE.md describes ownership. This is an auditing tool, never an autonomous site editor.

## Development rules
1. Read the affected path end to end and the existing tests before editing.
2. Use test-driven vertical slices: reproduce a failure, run it, implement the smallest fix, rerun the test and full suite.
3. Never replace a failed provider call with a demo result, zero score or success. Mock provider data belongs only in tests and must be labeled.
4. Never read credentials except the explicitly configured TYPESAFE_API_KEY. Tests must use their own fixture values and no network. Never print keys, raw HTTP errors or private content.
5. Preserve exact extracted evidence. Put all math, limits and final policy in code. Jev asks atomic bounded questions; it does not write explanations.
6. Keep default audits offline. Do not add a crawler, CMS writer, arbitrary provider endpoint, MCP server, browser or dashboard without an explicit scope change.
7. Low-confidence signals go to review. Unknown, not evaluated and failed are distinct from clean.
8. Keep package version, CLI, JSON contract, docs, examples and agent skill aligned.
9. HTML/Markdown reports must treat input as hostile. Test escaping and unsafe URL schemes. Do not follow symlinks outside a selected root.
10. A pull request is complete only after tests, lint, clean wheel install and docs validation have actually run. Report exact commands and remaining limitations.

## Checks
```sh
python -m unittest discover -s tests -v
ruff check src tests
python -m build
python scripts/check_docs.py
```

Do not publish package releases, merge branches or change user agent configuration without authorization. The portable skill in skills/anchorlint is documentation for users to install intentionally, not an auto-installed integration.
