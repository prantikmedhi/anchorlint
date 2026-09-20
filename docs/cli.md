# CLI reference

```text
anchorlint --help
anchorlint --version
anchorlint audit PATH --base-url URL
  [--provider rules|jev] [--model MODEL] [--max-links N]
  [--format json|markdown|html] [--output FILE]
  [--baseline JSON] [--fail-on error|warning|never]
```

- PATH: built HTML directory or versioned inventory JSON. An empty collection is an error.
- --base-url: public HTTP(S) origin and optional site prefix; required for HTML. Inventory base_url supplies the default for JSON.
- --provider: `rules` default. `jev` explicitly permits bounded provider requests.
- --model: `jev-1.13.0` default. Only relevant to Jev requests.
- --max-links: positive distinct-evaluation budget; default 25. Each evaluation may use bounded HTTP retries, so this is not a raw network-attempt count. Read coverage when repeated inputs are memoized or the budget is exhausted.
- --format: `markdown` default. JSON is the machine interface.
- --output: explicit report file; otherwise report to stdout, diagnostics to stderr.
- --baseline: prior JSON report. Only matching stable findings are treated as existing.
- --fail-on: `error` default, `warning` includes both warning and error, `never` disables only the findings gate.

Exit 0 means complete with no new finding meeting the gate; exit 1 means new findings meet it; exit 2 means invalid input, provider/operation failure or incomplete semantic coverage. Baselines and `never` do not convert incomplete work into success.

The [inventory guide](inventory.md) documents import boundaries. The [CI guide](ci.md) explains how to review and maintain baselines.
