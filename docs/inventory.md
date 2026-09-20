# Input and inventory format

Audit built HTML or import a versioned JSON inventory. An inventory is supplied evidence, not proof that pages were fetched live. The CLI validates the entire input before any paid call.

See [the JSON Schema](../schemas/inventory.schema.json) and [runnable example](../examples/inventory.json):
```sh
anchorlint audit examples/inventory.json --format json
```

Top level requires schema_version 1, base_url and a nonempty pages array. Every page needs an absolute HTTP(S) url, title, text and links. Optional headings and ids are arrays of strings; noindex is a boolean. Each link needs href, anchor and context; optional line is a positive integer. Optional assets is an array of non-HTML file URLs, defaulting to an empty array for older inventories. Unknown fields are ignored. Duplicate object keys, duplicate normalized page or asset URLs, invalid types, nonfinite JSON numbers (including exponent overflow) and cross-origin records are rejected. JSON integer conversion errors are sanitized input errors, not tracebacks.

The inventory's required base_url must be valid even when --base-url overrides it. Page and asset origins are checked against the effective base; an override does not rewrite their absolute URLs.

## Non-HTML assets: existence only
Supply known downloadable/static resources as URL strings, not page objects:
```json
{
  "schema_version": 1,
  "base_url": "https://example.com/",
  "pages": [{
    "url": "https://example.com/",
    "title": "Documentation",
    "text": "Read the product manual.",
    "links": [{"href": "manual.pdf#page=2", "anchor": "product manual", "context": "Read the product manual."}]
  }],
  "assets": ["https://example.com/manual.pdf"]
}
```

Directory collection inventories regular files other than .html/.htm by URL, without opening or reading their bytes. The existing selected-root, excluded-folder/.env-file, symlink and directory-entry protections still apply. Directory symlinks are not followed; escaping symlinks are rejected; safe in-root file symlinks may identify assets. Special non-HTML files are skipped. This is not MIME detection or PDF/image/ZIP parsing, and assets cannot substitute for the required HTML pages.

Asset URLs must be absolute HTTP(S), on the same effective origin, and identify non-HTML files rather than directories. Credentials, unsafe characters, malformed escapes, query/fragment components, dot path segments, normalized duplicates and overlap with page URLs are rejected. Asset URL strings are normalized for identity; link href evidence is retained exactly. Cross-record and normalization checks are enforced at runtime in addition to the JSON Schema.

A link to an inventoried asset is not a broken link, including when its href has a query or fragment. An absent asset remains a broken link. Asset content and fragments are **not checked**; no missing-fragment or semantic-pass claim is made for them. Jev records status not_evaluated with reason non_html_target, makes no request for that asset and does not consume its call budget. This inherent exclusion does not make paid coverage partial. Anchor-label rules still apply to links to assets.

## URL and extraction policy
- Only one exact origin per inventory, including scheme and non-default port. HTTP and HTTPS are not automatically merged. External URLs are classified, never fetched.
- Queries/fragments are removed for local file identity; the original href remains evidence. Sites where query strings select different content need separate preprocessing; this tool cannot infer that routing.
- index.html/index.htm map to the containing directory URL. Trailing slash and extensionless routes are not guessed universally. Supply actual built paths.
- Percent-encoded paths and fragments are decoded for lookup under a documented static-file model. No network or framework rewrites are inferred.
- HTML base and canonical hints are recorded but do not remap local evidence. A deployment relying on a base element needs a pre-resolved inventory to avoid misleading route checks.
- Visible text is extracted from static markup with whitespace normalization. Nested anchor spans and image alt text are retained; script/style/template/noscript content and explicitly hidden markup are excluded. Hidden/excluded contexts do not supply title, body, robots, base or canonical metadata. The first duplicate HTML attribute wins, and implied paragraph closure handles inline descendants. This is not a full browser HTML tree builder, CSS cascade or accessibility-name computation.
- Missing destination means absent from this input, not a measured production 404. HTML fragments are checked separately against exact extracted IDs/named anchors, with the standard case-insensitive top fallback when no literal target matches. Asset fragments are not checked.

## Bounds
The collector limits page count, total link occurrences, text sizes, total HTML bytes, directory entries, nesting and element count. Assets are capped at 100,000 URLs; each raw and normalized URL is capped at 2,000,000 characters. Normalized asset URLs share the 8,000,000-character aggregate input-evidence budget with page evidence. Asset byte sizes are not read into memory or counted as HTML bytes. JSON input is bounded. Limits reject excessive input rather than silently issuing paid calls on a partial inventory. See the constants and validation in core.py for the executable limit contract.

Before findings or paid calls, an aggregate report-evidence preflight bounds repeated conflict target lists. Jev also reserves destination title/text copies for each evaluation and up to two semantic findings per link, sharing the 8,000,000-character expansion budget with conflict evidence. Excessive expansion is rejected, not silently truncated; this is a conservative evidence bound rather than an exact serialized-report byte count.

Every Jev semantic record retains available destination title/text as target_evidence, including positive, skipped and failed evaluations; it is null when no HTML destination evidence exists. These are supplied/extracted fields, not evidence that the model evaluated every character. Jev separately bounds fields sent to the provider and records original/sent lengths and truncation. Read all coverage and review metadata; a bounded excerpt is not the whole destination page.
