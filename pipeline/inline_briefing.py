#!/usr/bin/env python3
"""Build-time injection for the briefing page: fresh teaser + stage chips.

Reads data/stage*.json; fills the KISATORI_TEASER block with the latest
stage's headline and adds a result chip to each completed stage's card.
Static fallbacks in src/index.html survive if no data exists.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

def fmt_pct(p: float) -> str:
    return f"top {max(1, round(100 - p))}%"

def main(src: str, dst: str) -> None:
    html = Path(src).read_text()
    stages = {}
    for p in sorted(DATA.glob("stage*.json")):
        n = int("".join(ch for ch in p.stem if ch.isdigit()))
        stages[n] = json.loads(p.read_text())

    if stages:
        latest_n = max(stages)
        s = stages[latest_n]
        group = (s.get("runInReport") or {}).get("group") or []
        members = {m["memberId"]: m for m in s.get("members", [])}
        bits = []
        if group:
            g0 = group[0]
            bits.append(f"maaliviivan mestari {members.get(g0['memberId'], {}).get('name', g0['memberId'])} ({g0['sec']} s)")
        best = max(s.get("members", []), key=lambda m: m.get("percentile") or 0, default=None)
        if best:
            bits.append(f"päivän kärki {best['name']} ({fmt_pct(best['percentile'])})")
        line = " · ".join(bits) or "Tulokset, palkinnot ja ennusteet"
        teaser = f'''
<a class="kisatori-teaser" href="kisatori/#e{latest_n}">
  <span class="kt-head"><span class="kt-live"></span>Kisatori · Etappi {latest_n} ✓</span>
  <span class="kt-line">{line} — koko analyysi, palkinnot ja ennusteet →</span>
</a>
'''
        html = re.sub(r"<!--KISATORI_TEASER_START-->.*?<!--KISATORI_TEASER_END-->",
                      "<!--KISATORI_TEASER_START-->" + teaser + "<!--KISATORI_TEASER_END-->",
                      html, flags=re.S)

    for n in stages:
        chip = f'<a class="kstage" href="kisatori/#e{n}">✓ Tulokset &amp; analyysi</a>'
        html = html.replace(f"<!--KISATORI_STAGE_{n}-->", f"<!--KISATORI_STAGE_{n}-->{chip}")

    Path(dst).write_text(html)
    print(f"briefing injected -> {dst} (stages with data: {sorted(stages)})")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
