"""Install the CJK fonts chosen in `font_languages` into /data/fonts.

Fonts come from pinned URLs and are checked against sha256 (fonts.json).
Fonts of languages no longer selected are removed. Nothing here is fatal:
a failed download only means that language renders as boxes, so the app
still starts. Standard library only (runs with the system python3).
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_DIR = Path("/data/fonts")
OPTIONS = Path("/data/options.json")


def load_manifest(path: Path = HERE / "fonts.json") -> dict:
    return json.loads(Path(path).read_text())


def selected(options_path: Path, manifest: dict) -> list[str]:
    try:
        wanted = json.loads(Path(options_path).read_text()).get("font_languages") or []
    except (OSError, ValueError):
        return []
    out = []
    for lang in wanted:
        if lang in manifest["languages"] and lang not in out:
            out.append(lang)
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(entry: dict, font_dir: Path, fetch) -> bool:
    fd, tmp = tempfile.mkstemp(dir=font_dir, prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as out, fetch(entry["url"]) as src:
            while chunk := src.read(1 << 20):
                out.write(chunk)
        if _sha256(Path(tmp)) != entry["sha256"]:
            print(f"[fonts] checksum mismatch for {entry['file']}, discarded", file=sys.stderr)
            return False
        os.replace(tmp, font_dir / entry["file"])
        return True
    except OSError as e:
        print(f"[fonts] download failed for {entry['file']}: {e}", file=sys.stderr)
        return False
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def install(langs: list[str], font_dir: Path, manifest: dict, fetch) -> dict:
    font_dir = Path(font_dir)
    font_dir.mkdir(parents=True, exist_ok=True)
    wanted = [e for lang in langs for e in manifest["languages"][lang]]
    summary = {"installed": [], "kept": [], "removed": [], "failed": []}
    for entry in wanted:
        path = font_dir / entry["file"]
        if path.is_file() and _sha256(path) == entry["sha256"]:
            summary["kept"].append(entry["file"])
        elif _download(entry, font_dir, fetch):
            summary["installed"].append(entry["file"])
        else:
            summary["failed"].append(entry["file"])
    keep = {e["file"] for e in wanted}
    for path in sorted(font_dir.iterdir()):
        if path.name not in keep and path.is_file():
            path.unlink()
            summary["removed"].append(path.name)
    return summary


def main() -> int:
    manifest = load_manifest()
    langs = selected(OPTIONS, manifest)
    summary = install(langs, FONT_DIR, manifest, lambda url: urllib.request.urlopen(url, timeout=60))
    print(f"[fonts] languages={langs or 'none'} installed={summary['installed']} kept={len(summary['kept'])} "
          f"removed={summary['removed']} failed={summary['failed']}")
    if (summary["installed"] or summary["removed"]) and os.path.exists("/usr/bin/fc-cache"):
        subprocess.run(["fc-cache", "-f", str(FONT_DIR)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
