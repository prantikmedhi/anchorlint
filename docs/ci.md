# CI regression gates and baselines

Build the site before auditing it. Keep the same base URL, tool version and provider/model when comparing reports.

```sh
anchorlint audit ./dist --base-url https://example.com --format json --output audit.json --fail-on warning
```

The command exits 1 for new warnings/errors. Upload the report with your CI system's always-run artifact step so failed audits remain inspectable. Do not put secrets in artifact files.

## Accepting existing findings
Review a JSON report manually, then explicitly commit it as a baseline (only if the content is safe to publish):
```sh
anchorlint audit ./dist --base-url https://example.com --format json --output audit.json --baseline anchorlint-baseline.json --fail-on warning
```

A fingerprint identifies a finding's rule, source, destination and link occurrence/context. Unchanged findings remain visible but are not new. Context or link-order edits can change fingerprints. Model/prompt changes can change semantic decisions. A baseline records accepted findings, not evidence they are fixed.

Never generate a fresh baseline automatically from every failing CI run. That would accept the regression you meant to catch. A baseline does not suppress malformed input, provider errors, unaudited coverage or status failures.

## Jev and pull requests
Do not expose TYPESAFE_API_KEY to untrusted fork pull requests or `pull_request_target` jobs that execute PR code. Use a manually approved trusted-branch workflow for paid audits. Default tests and CI are offline and require no key.

## This repository's CI
The workflow tests Python 3.11/3.13, runs lint and documentation checks, builds distributions, installs a wheel into a fresh environment, and exercises the demonstration CLI. Wheel and source archives are build artifacts, not automatic PyPI publication. The Pages workflow runs only after successful CI for main in this same repository, and checks out that exact tested commit. Fork/PR CI cannot trigger a deployment. Configure repository Pages for GitHub Actions; rerun the CI workflow on main to request another checked deployment.
