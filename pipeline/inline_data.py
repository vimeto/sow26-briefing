#!/usr/bin/env python3
"""Inject data/*.json + crop images into src/kisatori.html.

The page contains a placeholder line:
    <script id="kisatori-data">window.KISATORI_DATA=null</script>
which is replaced with the full payload. Crop file paths referenced in
stage JSONs (crops[].file, relative to data/) become data: URIs under
payload.cropData[file].
"""
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

def main(src: str, dst: str) -> None:
    payload = {"stages": {}, "cropData": {}}
    for p in sorted(DATA.glob("stage*.json")):
        n = int("".join(ch for ch in p.stem if ch.isdigit()))
        payload["stages"][str(n)] = json.loads(p.read_text())
    for name in ("members", "forecast", "badges"):
        p = DATA / f"{name}.json"
        payload[name] = json.loads(p.read_text()) if p.exists() else None
    for stage in payload["stages"].values():
        for crop in stage.get("crops") or []:
            f = crop.get("file")
            fp = DATA / f
            if f and fp.exists() and f not in payload["cropData"]:
                mime = "image/webp" if f.endswith(".webp") else "image/png"
                b64 = base64.b64encode(fp.read_bytes()).decode()
                payload["cropData"][f] = f"data:{mime};base64,{b64}"

    html = Path(src).read_text()
    placeholder = '<script id="kisatori-data">window.KISATORI_DATA=null</script>'
    if placeholder not in html:
        sys.exit("FAIL: kisatori-data placeholder not found in " + src)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/")  # keep </script> safe inside the tag
    html = html.replace(
        placeholder,
        f'<script id="kisatori-data">window.KISATORI_DATA={blob}</script>',
    )
    Path(dst).write_text(html)
    size_mb = len(html) / 1e6
    print(f"inlined payload -> {dst} ({size_mb:.1f} MB)")
    if size_mb > 12:
        print("WARN: page is getting heavy; consider smaller crops")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
