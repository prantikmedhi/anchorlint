# Jev integration

Jev evaluates supplied state against typed questions; it does not generate a new explanation or rewrite a page.[1]
Choice returns one declared option plus its probability distribution and confidence.[4]
Score returns a position across ordered descriptive levels.[5]
Noul returns a yes probability with no separate confidence field.[6]

AnchorLint deliberately uses two Nouls (anchor promise and contextual relevance) plus a Choice (informative/generic/misleading/insufficient_context). The raw signals are retained; thresholds and review policy live in local code. An uncertain or contradictory result is not silently labeled clean.

## Provider contract

- Official endpoint: `POST https://api.typesafe.ai/v1/systemone`.
- Bearer authentication from `TYPESAFE_API_KEY` only.
- Body: `model`, `state`, `questions`; answers keyed by the question IDs.
- Default model: `jev-1.13.0`; `--model` can override it. Responses record the resolved model.
- No redirects, alternate endpoints, browser credentials or automatic fallback provider.[2][3]

The project checks required answer IDs, types, finite numbers and ranges, full Choice probability coverage, label membership, confidence, model identity and token-usage fields. Provider errors are sanitized, not transformed into zero scores.

## Boundaries and cost
Rules mode is offline. Jev mode sends selected source context and destination excerpts to TypeSafe; use only authorized content. At research time the official model page listed $0.042 per million input tokens and free output tokens. Confirm current account pricing before use. There is no claim that requests are free.[3]

Fields are bounded and truncation is reported. A run also has a positive `--max-links` budget for distinct logical evaluations. Each evaluation can make up to three HTTP attempts for transient server responses; the count is not an absolute HTTP-attempt cap. Token totals cover successful responses only, not unknown billing for failed attempts. Unevaluated coverage remains explicit, and incomplete Jev coverage is operational exit 2. Reports include provider usage, requested/resolved model and elapsed time rather than invented benchmark numbers.

## Limitations
The provider documents problems with arithmetic, dates, indirection, irrelevant context and adversarial state. A typed or high-confidence answer can be wrong. Keep deterministic work in code; treat semantic findings as review signals. Default thresholds are product policy, not calibrated SEO probabilities.[8]

The application and optional portable skill are MIT-licensed. No official Jev weights are distributed. This is an open-source integration with a hosted optional dependency, not an offline Jev model.[3][9]

## Verification
Unit tests use explicit fixture responses and no credentials. Those tests validate request/response handling, not Jev's live accuracy. A live smoke must use the actual adapter and authorized public/example text; missing credentials are a real blocker and are never substituted with a fake result.

## Sources

[1] https://docs.typesafe.ai/introduction.md — introduction
[2] https://docs.typesafe.ai/api.md — api
[3] https://docs.typesafe.ai/models.md — models
[4] https://docs.typesafe.ai/primitives/choice.md — primitives/choice
[5] https://docs.typesafe.ai/primitives/score.md — primitives/score
[6] https://docs.typesafe.ai/primitives/noul.md — primitives/noul
[8] https://docs.typesafe.ai/model-jaggedness/jev-1.13.md — model-jaggedness/jev-1.13
[9] https://docs.typesafe.ai/sdk/python.md — sdk/python
