# Security and privacy

## Data boundary
Default `--provider rules` is local and makes no network requests. `--provider jev` sends selected anchor text, source context, destination title and bounded destination text to TypeSafe. Use it only for public material or material you are authorized to share. Jev charges and its data-handling terms belong to the provider. This repository does not claim zero-retention or offline semantic inference.

Set TYPESAFE_API_KEY outside source control. The tool reads that variable only; it does not discover browser sessions, dotenv files or other provider credentials. Keys, response bodies and raw HTTP exceptions must not appear in error reports. Only api.typesafe.ai receives the bearer key and API redirects are disabled.

## Read-only is not a substitute for review
Reports contain source text. Treat them as potentially sensitive; do not commit or upload customer reports without approval. Only an explicit --output writes a report; pages are not edited. A local report is not automatically safe to share publicly.

Select the built website folder, not your home directory. The collector rejects dangerous broad roots, skips dependency/control folders and does not follow directory symlinks or escaping file symlinks. Size/count limits protect the collector and API. The local collector is not a sandbox for mutually untrusted OS users; avoid concurrent adversarial filesystem mutation.

## Model and content risks
Jev can be steered by adversarial state. Precise questions, bounded data and human review reduce exposure; they do not prove prompt-injection resistance. Model values are heuristic signals, not security authorization, truth certification, accessibility compliance or Google rankings. A confidently incorrect judgment is possible.

Inline HTML hiding is handled conservatively; external stylesheets, dynamically generated content and full browser accessibility behavior are out of scope. JavaScript is never executed. Do not treat these reports as a full accessibility audit.

## Failure behavior
Malformed input or API output, invalid credentials, timeouts and exhausted retry budgets produce explicit failures. Skipped or unevaluated links never become passes. Runtime errors and incomplete semantic coverage always take precedence over baseline and severity gating. Operational failures use exit 2.

## Reporting vulnerabilities
Open a minimal issue without customer data or secrets. If disclosure would enable abuse, use the repository owner's contact route on their GitHub profile instead of publishing exploit details. No response-time SLA is promised.
