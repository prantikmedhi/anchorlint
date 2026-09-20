# Architecture

```text
Built HTML / inventory JSON
          |
          v
    local extraction -> normalized pages + link occurrences
          |
          v
    deterministic checks ----------------------+
          |                                   |
          +-> optional bounded Jev requests    |
               promise + relevance + label     |
                         |                     |
                         v                     v
                 validation + policy -> evidence findings
                                            |
                                    baseline + severity gate
                                            |
                                   JSON / Markdown / HTML
```

- `core.py`: explicit-root collection, URL resolution, deterministic checks, semantic policy, coverage, fingerprints and baseline comparison.
- `jev.py`: fixed official transport, bounded inputs/retries, strict answer validation, usage/model provenance, sanitized failure boundary.
- `reports.py`: display-only rendering. No remote assets, dynamic content execution or website mutations.
- `cli.py`: argument validation, input/output orchestration and exit-code contract.

## Trust boundaries
HTML and inventory text are untrusted data. They are never instructions to the program. Only an explicit Jev audit sends selected excerpts to a third party. The model is advisory; it cannot invoke a tool, fetch a URL, alter a page or control the filesystem. The API key travels only to the official HTTPS endpoint; redirects are disabled.

## State and reproducibility
No service, account database or persistent model cache is needed. A report is the audit record. A baseline is a prior report, not an exemption from operational failures. In-run repeated semantic inputs may share a request. Model/version and request usage are preserved. Changes in model, source context or prompt can change results; review baselines rather than blindly regenerating them.

## Deliberate limits
Built HTML only: no JavaScript execution, HTTP status verification, private browsing, production crawling, redirects discovery, CSS cascade or accessibility-tree computation. HTML fragments can only be checked against extracted targets. Conservative URL policies are documented with the inventory format. See SECURITY.md for limits and residual risk.
