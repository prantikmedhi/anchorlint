---
name: anchorlint
description: Use when auditing existing internal links for SEO. Run offline checks, then optional bounded Jev judgments with exact evidence.
---

# AnchorLint

Read-only internal-link audit for built HTML directories and versioned JSON inventories. Install the actual tool first using its repository installation guide. This skill is not the executable and does not add MCP tools.

1. Identify the user-authorized built site directory and correct public base URL. Never scan a home folder or unrelated data.
2. Run `anchorlint audit PATH --base-url URL --format json --output audit.json`.
3. Read the report's status, coverage, errors and finding evidence. Preserve exit 0/1/2: complete/pass, finding gate, operational/incomplete respectively.
4. Report exact source anchor/context and destination; do not invent fixes or ranking predictions.
5. Jev requires explicit data-sharing/cost authorization and TYPESAFE_API_KEY set securely. Use `--provider jev --max-links 25`; do not reveal credentials or use another endpoint.
6. Do not edit pages, accept baselines or publish reports without authorization. Rerun after approved changes.

JSON is authoritative. Low-confidence review and unevaluated coverage are not a pass. This tool does not crawl live sites or certify accessibility. Provider scores are heuristics.
