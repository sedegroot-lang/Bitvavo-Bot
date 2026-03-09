"""Fetch icons from the CryptoIcons GitHub repo (RezaOptic/CryptoIcons).

This script downloads the repository archive, extracts it into a temporary
cache directory, then searches the tree for icon files matching coin symbols
(case-insensitive). When found, it copies PNG/WEBP/SVG files to `data/icons/{symbol}.png`.

If only SVGs are found and `cairosvg` is installed, the script will convert
SVG -> PNG automatically. Otherwise it reports which symbols need manual conversion.

Usage:
  .\.venv\Scripts\python.exe tools\prefetch_icons_repo.py

You can pass explicit symbols on the command line, e.g.
  .\.venv\Scripts\python.exe tools\prefetch_icons_repo.py LINK XRP NEAR

The script will also read `data/trade_log.json` to derive open trade symbols
if no args are provided.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, List

try:
    import requests
except Exception:
    print("Error: requests required. Install with: pip install requests")
    raise

try:
    import PIL.Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except Exception:
    CAIROSVG_AVAILABLE = False

GITHUB_ARCHIVE = "https://github.com/RezaOptic/CryptoIcons/archive/refs/heads/main.zip"
DATA_DIR = Path("data")
ICONS_DIR = DATA_DIR / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)
TRADE_LOG = DATA_DIR / "trade_log.json"


def load_open_symbols() -> List[str]:
    if not TRADE_LOG.exists():
        return []
    try:
        with TRADE_LOG.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    open_list = data.get("open") or []
    syms = []
    for it in open_list:
        if isinstance(it, dict) and it.get("market"):
            sym = str(it.get("market")).split("-")[0].upper()
            syms.append(sym)
    return syms


def symbols_from_args_or_trade_log() -> List[str]:
    args = [a.upper() for a in sys.argv[1:]]
    if args:
        return args
    return load_open_symbols()


def download_archive(dest: Path) -> Path:
    print("Downloading CryptoIcons archive...")
    resp = requests.get(GITHUB_ARCHIVE, stream=True, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def extract_archive(zip_path: Path, extract_to: Path) -> Path:
    print(f"Extracting archive to {extract_to}")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(path=extract_to)
    # The repo extracts into a directory like CryptoIcons-main
    for child in extract_to.iterdir():
        if child.is_dir():
            return child
    return extract_to


def find_icon_files(root: Path, symbol: str) -> List[Path]:
    # search for files containing the symbol name (case-insensitive)
    symbol_low = symbol.lower()
    matches = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if symbol_low in name:
            if name.endswith(('.png', '.webp', '.svg')):
                matches.append(p)
    return matches


def copy_or_convert(src: Path, dest_png: Path) -> bool:
    # If src is PNG or WEBP, copy and write as PNG (if webp, try PIL)
    if src.suffix.lower() in ('.png', '.webp'):
        if src.suffix.lower() == '.png':
            shutil.copyfile(src, dest_png)
            return True
        else:
            # webp -> png via PIL if available
            if PIL_AVAILABLE:
                try:
                    img = PIL.Image.open(src)
                    img.convert('RGBA').save(dest_png, format='PNG')
                    return True
                except Exception:
                    return False
            else:
                return False
    if src.suffix.lower() == '.svg':
        if CAIROSVG_AVAILABLE:
            try:
                cairosvg.svg2png(url=str(src), write_to=str(dest_png))
                return True
            except Exception:
                return False
        else:
            return False
    return False


def run(symbols: Iterable[str]) -> int:
    symbols = list(dict.fromkeys([s.upper() for s in symbols if s]))
    if not symbols:
        print("No symbols provided and no open trades found.")
        return 0

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        zip_path = td_path / "cryptoicons.zip"
        try:
            download_archive(zip_path)
        except Exception as exc:
            print(f"Failed to download archive: {exc}")
            return 2
        try:
            extracted = extract_archive(zip_path, td_path)
        except Exception as exc:
            print(f"Failed to extract archive: {exc}")
            return 3

        missing = []
        for sym in symbols:
            print(f"Looking for icons for: {sym}")
            found = find_icon_files(extracted, sym)
            if not found:
                print(f" - No icons found in repo for {sym}")
                missing.append(sym)
                continue
            # prefer png then webp then svg
            preferred = None
            for ext in ('.png', '.webp', '.svg'):
                for f in found:
                    if f.suffix.lower() == ext:
                        preferred = f
                        break
                if preferred:
                    break
            if not preferred:
                print(f" - Found files but none are supported for {sym}: {found}")
                missing.append(sym)
                continue
            dest = ICONS_DIR / f"{sym.lower()}.png"
            ok = copy_or_convert(preferred, dest)
            if ok:
                print(f" - Saved icon for {sym} -> {dest}")
            else:
                print(f" - Could not convert/copy {preferred} for {sym}.")
                missing.append(sym)

        if missing:
            print("\nSome symbols were not found or not converted:")
            for m in missing:
                print(f" - {m}")
            if not CAIROSVG_AVAILABLE:
                print("Install 'cairosvg' to enable SVG->PNG conversion: pip install cairosvg")
            if not PIL_AVAILABLE:
                print("Install 'Pillow' to enable WEBP->PNG conversion: pip install Pillow")

    return 0


def main() -> int:
    syms = symbols_from_args_or_trade_log()
    return run(syms)


if __name__ == '__main__':
    raise SystemExit(main())
