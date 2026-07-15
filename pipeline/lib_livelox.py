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


PURPLE = (166, 38, 170)  # ISOM course-overprint magenta (#A626AA)


def _load_font(size):
    """A legible sans-serif TrueType at the requested px size, else PIL default."""
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def crop_leg(ll, leg_idx, out_path, pad_frac=0.28, min_window_m=350,
             max_dim=1400, max_kb=150):
    """Crop the base map around a leg (control leg_idx -> leg_idx+1) and draw the
    course overprint so it reads like a real orienteering map extract.

    Draws two ISOM-purple control circles (60 m diameter; a start triangle when
    ctrlFrom is the start), a straight line between their edges, and small purple
    code labels. Rendered at 2x and downscaled for anti-aliasing.

    Returns a dict {fromCode, toCode, pxFrom, pxTo, widthPx, heightPx} on success
    (pixel coords are of the two controls within the saved image), or None if the
    map/transform is unavailable. Saves webp <= max_kb.
    """
    import math

    from PIL import Image, ImageDraw

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

    # Scale of the affine: LV95 units are metres, so |det|^0.5 is pixels/metre.
    det = abs(a * e - b * d)
    px_per_m = math.sqrt(det) if det > 0 else 1.0
    min_window_px = min_window_m * px_per_m

    # Window: leg bounding box + proportional padding, but never smaller than
    # min_window_px so short legs don't over-zoom. Centre on the leg midpoint.
    xmin, xmax = sorted((x0, x1))
    ymin, ymax = sorted((y0, y1))
    win_w = max((xmax - xmin) * (1 + 2 * pad_frac), min_window_px)
    win_h = max((ymax - ymin) * (1 + 2 * pad_frac), min_window_px)
    cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
    W, H = m["width"], m["height"]
    win_w, win_h = min(win_w, W), min(win_h, H)
    L, R = cx - win_w / 2.0, cx + win_w / 2.0
    Tp, B = cy - win_h / 2.0, cy + win_h / 2.0
    # Slide (don't shrink) back inside the map so both controls stay visible.
    if L < 0:
        R -= L; L = 0.0
    if R > W:
        L -= (R - W); R = float(W)
    if Tp < 0:
        B -= Tp; Tp = 0.0
    if B > H:
        Tp -= (B - H); B = float(H)
    L, Tp = max(0.0, L), max(0.0, Tp)
    L, Tp, R, B = int(L), int(Tp), int(math.ceil(R)), int(math.ceil(B))
    if R - L < 10 or B - Tp < 10:
        return None

    base = Image.open(png).convert("RGB").crop((L, Tp, R, B))
    cw, ch = base.size
    # Final downscale factor to honour max_dim (kept separate from the 2x AA pass).
    fscale = min(1.0, max_dim / max(cw, ch))

    ss = 2  # supersample for anti-aliasing
    big = base.resize((cw * ss, ch * ss), Image.LANCZOS)
    dr = ImageDraw.Draw(big, "RGBA")

    def cpix(x, y):  # map pixel -> supersampled crop pixel
        return ((x - L) * ss, (y - Tp) * ss)

    sx0, sy0 = cpix(x0, y0)
    sx1, sy1 = cpix(x1, y1)
    r_circle = 30.0 * px_per_m * ss          # 60 m diameter -> 30 m radius
    stroke = max(2, int(round(5 * px_per_m * fscale * ss)))
    line_col = PURPLE + (235,)

    # Direction along the leg (for edge-to-edge line + label offset side).
    dx, dy = sx1 - sx0, sy1 - sy0
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    px_, py_ = -uy, ux  # unit perpendicular

    # Connecting line between the marker edges (not through them).
    lx0, ly0 = sx0 + ux * r_circle, sy0 + uy * r_circle
    lx1, ly1 = sx1 - ux * r_circle, sy1 - uy * r_circle
    if (lx1 - lx0) * ux + (ly1 - ly0) * uy > 0:  # only if a gap remains
        dr.line([(lx0, ly0), (lx1, ly1)], fill=line_col, width=stroke)

    def draw_circle(cxp, cyp):
        dr.ellipse([cxp - r_circle, cyp - r_circle, cxp + r_circle, cyp + r_circle],
                   outline=line_col, width=stroke)

    def draw_triangle(cxp, cyp):
        # ISOM start triangle: one vertex points toward the first control.
        rr = r_circle * 1.15
        verts = []
        for k in range(3):
            ang = math.atan2(uy, ux) + k * (2 * math.pi / 3)
            verts.append((cxp + rr * math.cos(ang), cyp + rr * math.sin(ang)))
        dr.line(verts + [verts[0]], fill=line_col, width=stroke, joint="curve")

    if p0.get("type") == 0:
        draw_triangle(sx0, sy0)
    else:
        draw_circle(sx0, sy0)
    draw_circle(sx1, sy1)

    # Code labels, offset perpendicular to the leg, away from the line.
    font = _load_font(max(18, int(round(22 * ss * max(fscale, 0.5)))))

    def draw_label(cxp, cyp, code, side):
        off = r_circle + 6 * ss
        lx, ly = cxp + px_ * off * side, cyp + py_ * off * side
        tb = dr.textbbox((0, 0), str(code), font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        dr.text((lx - tw / 2, ly - th / 2), str(code), font=font,
                fill=PURPLE + (255,))

    draw_label(sx0, sy0, p0["code"], 1)
    draw_label(sx1, sy1, p1["code"], -1)

    # Down to final size (2x AA collapse + max_dim clamp).
    fw, fh = max(1, int(round(cw * fscale))), max(1, int(round(ch * fscale)))
    img = big.resize((fw, fh), Image.LANCZOS)

    q = 85
    while q >= 40:
        img.save(out_path, "WEBP", quality=q, method=6)
        if os.path.getsize(out_path) <= max_kb * 1024:
            break
        q -= 10

    def fpix(x, y):
        return [round((x - L) * fscale, 1), round((y - Tp) * fscale, 1)]

    return {
        "fromCode": p0["code"], "toCode": p1["code"],
        "pxFrom": fpix(x0, y0), "pxTo": fpix(x1, y1),
        "widthPx": fw, "heightPx": fh,
    }
