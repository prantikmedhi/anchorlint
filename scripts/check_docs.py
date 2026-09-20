"""Check local Markdown references. Never follows network links or symlinks."""
from pathlib import Path
import re
import sys
import json
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlsplit


def check(root: Path) -> list[str]:
    errors = []
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if any(part in {"build", "dist", "node_modules", "__pycache__"} for part in path.relative_to(root).parts):
            continue
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for match in re.finditer(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", text):
            target = urlsplit(match.group(1).strip("<>"))
            if target.scheme or target.netloc or not target.path:
                continue
            dest = (path.parent / unquote(target.path)).resolve()
            if not dest.is_relative_to(root.resolve()) or not dest.exists():
                errors.append(f"{path.relative_to(root)}: missing or escaping link {match.group(1)}")
    site = root / "site"
    if site.is_dir():
        canonicals, titles = set(), set()
        for path in sorted(site.glob("*.html")):
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
            title = soup.title.get_text(strip=True) if soup.title else ""
            if not title or title in titles:
                errors.append(f"{path.name}: missing or duplicate title")
            titles.add(title)
            description = soup.find("meta", attrs={"name": "description"})
            canonical = soup.find("link", rel="canonical")
            if not description or not description.get("content"):
                errors.append(f"{path.name}: missing description")
            if not canonical or not canonical.get("href", "").startswith("https://prantikmedhi.github.io/anchorlint/"):
                errors.append(f"{path.name}: missing or invalid canonical")
            else:
                robots = soup.find("meta", attrs={"name": "robots"})
                if not robots or "noindex" not in robots.get("content", "").lower().split(","):
                    canonicals.add(canonical["href"])
            if len(soup.find_all("h1")) != 1 or not soup.find("main"):
                errors.append(f"{path.name}: expected one h1 and a main landmark")
            structured = soup.find("script", type="application/ld+json")
            try:
                data = json.loads(structured.string) if structured else {}
                if data.get("@type") != "SoftwareSourceCode" or data.get("aggregateRating"):
                    raise ValueError("invalid project schema")
            except (ValueError, TypeError):
                errors.append(f"{path.name}: missing or invalid SoftwareSourceCode JSON-LD")
            for tag in soup.find_all(["a", "link", "img", "script"]):
                href = tag.get("href") or tag.get("src")
                if not href:
                    continue
                target = urlsplit(href)
                if target.scheme or target.netloc or not target.path:
                    continue
                dest = (path.parent / unquote(target.path)).resolve()
                if not dest.is_relative_to(site.resolve()) or not dest.exists():
                    errors.append(f"{path.name}: missing site asset/link {href}")
        try:
            locs = {node.text for node in ET.parse(site / "sitemap.xml").iter() if node.tag.endswith("}loc")}
            if locs != canonicals:
                errors.append("sitemap.xml: canonical URL set mismatch")
        except (OSError, ET.ParseError):
            errors.append("sitemap.xml: absent or invalid")
        for required in ("robots.txt", "llms.txt"):
            if not (site / required).is_file():
                errors.append(f"site/{required}: missing")
    return errors


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    errors = check(root)
    for error in errors:
        print(error)
    if not errors:
        print("Documentation references OK")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
