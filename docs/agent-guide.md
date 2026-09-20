# Use AnchorLint with an agent

AnchorLint exposes a normal CLI and structured JSON. It is not an MCP server and does not require a plugin. Claude Code, Codex and other agents with a shell can call the same interface.

## Safe workflow
1. Ask the user which built website directory to audit. Never scan home folders or unrelated repositories.
2. Confirm the correct public base URL. If the site needs building, use its documented build command.
3. Run deterministic checks first:
```sh
anchorlint audit ./dist --base-url https://example.com --format json --output audit.json
```
4. Preserve the exit code. Parse JSON; check `status`, `coverage`, `errors` and each finding's `is_new` and evidence. A successful process is not enough if the output contradicts it.
5. Summarize concrete issues with source URL, exact anchor, target and evidence. Never describe model outputs as verified search ranking effects.
6. Before `--provider jev`, confirm authorization to send selected page excerpts to TypeSafe, provider costs and the budget. Keys stay in the environment; never print them.
7. Propose changes. Do not edit the website, apply a baseline or publish reports without the user's authorization.
8. After approved website fixes, rebuild and rerun the same audit. Compare the new JSON, not just terminal prose.

## Portable skill
The repository includes [skills/anchorlint/SKILL.md](../skills/anchorlint/SKILL.md). Install it only through your agent's normal explicit skill-install workflow. For Claude Code, a project-scoped `.claude/skills/anchorlint/SKILL.md` can contain it; Codex installations should use that client's documented skill directory. The tool does not alter either client's configuration.

## Example task
> Audit the built site in ./dist for broken or misleading internal links, using https://example.com as its base URL. Start offline. Keep the report as JSON. Explain new findings with exact anchor and context. Do not change content or call Jev without approval.

## Contributor agents
Read [AGENTS.md](../AGENTS.md). Runtime instructions above do not authorize source changes, credentials discovery, network access beyond the selected provider, or automated publishing.
