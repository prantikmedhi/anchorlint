# Verification and limits

## Executed locally on the release candidate

- Python 3.13: **76 unittest tests passed** after the first independent review's fixes.
- Ruff and documentation-reference/metadata checks passed.
- Wheel and source distribution built successfully.
- Every packaged Python module was byte-compared with the final source snapshot; this is not a stale-wheel smoke.
- A fresh isolated environment installed the wheel and ran the actual CLI: help/version, JSON/Markdown/HTML export, fixture findings, a baseline, and a valid inventory.
- Existing local downloadable assets were not flagged broken; a missing asset still was.
- Missing TypeSafe credentials produced explicit partial JSON and **exit 2**, with zero provider calls, rather than fabricated scores.
- The project's own documentation audit had no broken-link errors. Its deliberately noindex 404 page and that page's same-page skip link produce expected noindex review metadata.

The [CI workflow](https://github.com/prantikmedhi/anchorlint/actions/workflows/ci.yml) repeats tests on Python 3.11 and 3.13, rebuilds the distribution and verifies an installed wheel. Read the actual run for a particular commit; this document does not claim a future run will pass. Pages deploys only the exact commit from successful same-repository main CI.

## What is not verified

**Live Jev inference was not run: no TypeSafe key was configured.** Provider tests use labeled local response doubles and validate transport/schema/error handling. They do not measure Jev accuracy, latency, calibration or actual billing.

The release does not establish SEO improvement, reduced review time, customer demand or a ranking effect. Those need a labeled evaluation and real users. Default semantic thresholds are conservative heuristics, not measured probabilities of search impact.

Windows installation instructions are supplied, but this release was not runtime-tested on Windows. Browser-harness visual QA was unavailable in the build environment; static document structure, assets and link correctness were checked separately. A deployed HTTP check is separate from visual browser verification.

## Documentation discoverability

The site includes canonical URLs, unique titles/descriptions, a sitemap, structured source-code metadata, a share image and llms.txt. These are discovery aids, not indexing guarantees. On a GitHub Pages project URL, the project's robots.txt is a published reference copy: crawlers consult robots.txt at the host root, outside this repository's deployment scope. No unrelated root-site configuration is changed.[30]

## Reproduce

```sh
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check src tests scripts
python scripts/check_docs.py
python -m build
```

Install the resulting wheel into a fresh environment, then run `python scripts/smoke.py` with that environment's Python from the source archive. Do not use a pre-existing editable install as evidence that the wheel works.

## Sources

[30] https://developers.google.com/search/docs/crawling-indexing/robots/create-robots-txt
