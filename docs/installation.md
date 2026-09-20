# Install AnchorLint

## Requirements
Python 3.11 or newer; macOS, Linux or Windows. No Node.js, browser, database or API key for deterministic audits. Build the website with its own framework before running AnchorLint.

## pip in an isolated environment
```sh
python -m venv .venv
```
Activate it:
- macOS/Linux: `source .venv/bin/activate`
- Windows PowerShell: `.venv\Scripts\Activate.ps1`

Then:
```sh
python -m pip install "https://github.com/prantikmedhi/anchorlint/archive/refs/heads/main.zip"
anchorlint --version
anchorlint --help
```

Some macOS/Linux installations name Python `python3`; substitute it when creating the environment. `python` inside the activated environment should resolve to that environment. If PowerShell blocks activation, invoke `.venv\Scripts\python.exe -m pip` directly instead of loosening a machine-wide execution policy.

## uv tool
If you already use [uv](https://docs.astral.sh/uv/), install an isolated command:
```sh
uv tool install "https://github.com/prantikmedhi/anchorlint/archive/refs/heads/main.zip"
anchorlint --help
```

No PyPI package publication is claimed. For pinned installs use a reviewed release tag or full commit in place of `main` in the archive URL. Repository archives include documentation and examples; wheel installations contain the executable library, not a copy of your website or fixture tree.

## First real audit
```sh
anchorlint audit ./dist --base-url https://your-site.example --format json --output audit.json
```
Choose your actual built output (`dist`, `out`, `_site`, etc.) and public origin. Exit 1 means findings reached the gate; exit 2 means input/operation/coverage failure. Neither should be discarded with an unconditional `|| true` in CI.

## Jev opt-in
Create/manage a key through the [official TypeSafe console](https://console.typesafe.ai/). Set TYPESAFE_API_KEY through your environment or secret manager; never paste it into a committed command or ask an agent to print it. The program does not load `.env` automatically.
```sh
anchorlint audit ./dist --base-url https://your-site.example --provider jev --max-links 25 --format html --output audit.html
```
See [Jev](jev.md) and [security](../SECURITY.md) before sharing nonpublic content.
