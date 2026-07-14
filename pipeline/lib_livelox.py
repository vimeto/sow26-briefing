"""Load per-(stage,class) Livelox extraction files and crop map images.

The extraction files are produced by the livelox-climb agent into
data/livelox/s{N}_{CLASS}.json (+ data/livelox/maps/*). Everything here is
null-safe: if a file is missing or marked unavailable, callers get None and the
pipeline degrades (course/climb/crop fields become null).
"""
import json
import os

from config import DATA

LIVELOX_DIR = os.path.join(DATA, "livelox")


def load(stage, cls):
    """Return the livelox dict for (stage, class) if available, else None."""
    path = os.path.join(LIVELOX_DIR, f"s{stage}_{cls}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    if not d.get("available"):
        return None
    return d


def leg_terrain(ll, leg_idx):
    """(distM, upM, downM) for a leg index, or (None, None, None)."""
    if not ll:
        return None, None, None
    legs = ll.get("legs", [])
    if 0 <= leg_idx < len(legs):
        L = legs[leg_idx]
        return L.get("distM"), L.get("upM"), L.get("downM")
    return None, None, None


def control_codes(ll):
    """List of control codes start..finish, or None."""
    if not ll:
        return None
    return [c["code"] for c in ll.get("controls", [])]


def crop_leg(ll, leg_idx, out_path, pad_frac=0.25, min_pad_px=70,
             max_dim=1400, max_kb=150):
    """Crop the base map around a leg (control leg_idx -> leg_idx+1).

    Draws nothing. Returns (fromCode, toCode) on success or None if the map or
    transform is unavailable. Saves webp <= max_kb.
    """
    from PIL import Image

    if not ll or "map" not in ll:
        return None
    m = ll["map"]
    png = os.path.join(LIVELOX_DIR, m["pngPath"])
    if not os.path.exists(png):
        return None
    (a, b, c), (d, e, f) = m["lv95ToPixel"]
    ctrls = ll["controls"]
    if leg_idx + 1 >= len(ctrls):
        return None
    p0, p1 = ctrls[leg_idx], ctrls[leg_idx + 1]

    def to_px(pt):
        return (a * pt["E"] + b * pt["N"] + c, d * pt["E"] + e * pt["N"] + f)

    x0, y0 = to_px(p0)
    x1, y1 = to_px(p1)
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    padx = max((xmax - xmin) * pad_frac, min_pad_px)
    pady = max((ymax - ymin) * pad_frac, min_pad_px)
    L = int(max(0, xmin - padx))
    T = int(max(0, ymin - pady))
    R = int(min(m["width"], xmax + padx))
    B = int(min(m["height"], ymax + pady))
    if R - L < 10 or B - T < 10:
        return None
    img = Image.open(png).convert("RGB").crop((L, T, R, B))
    if max(img.size) > max_dim:
        scale = max_dim / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    q = 85
    while q >= 40:
        img.save(out_path, "WEBP", quality=q, method=6)
        if os.path.getsize(out_path) <= max_kb * 1024:
            break
        q -= 10
    return p0["code"], p1["code"]
