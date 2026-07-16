#!/usr/bin/env python3
"""Fetch Livelox course geometry + base map for one stage.

Usage: .venv/bin/python fetch_livelox.py <stage>

For each class in livelox_ids.json classIds[<stage>]:
  ClassInfo POST -> classBlobUrl -> blob JSON -> data/livelox/s{N}_{CLS}.json
  (controls in LV95, per-leg dist/up/down via swisstopo DEM profile) and the
  base map PNG + LV95->pixel affine into data/livelox/maps/.
Classes whose blob is missing get {"available": false} like s1 CM.
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data", "livelox")
MAPS = os.path.join(OUT, "maps")

CLASSINFO = "https://www.livelox.com/Data/ClassInfo"


def http_get(url, binary=False, retries=4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read() if binary else r.read().decode("utf-8")
        except Exception as e:
            last = e
            time.sleep(1.0 + i)
    raise last


def class_blob_url(class_id):
    body = json.dumps({"eventId": None, "classIds": [class_id], "courseIds": [],
                       "relayLegs": [], "relayLegGroupIds": []}).encode()
    req = urllib.request.Request(CLASSINFO, data=body, headers={
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return (d.get("general") or {}).get("classBlobUrl")


def dem_profile(coords, nb):
    geom = json.dumps({"type": "LineString",
                       "coordinates": [[round(x, 2), round(y, 2)] for x, y in coords]})
    params = urllib.parse.urlencode({"geom": geom, "sr": "2056",
                                     "nb_points": str(nb), "distinct_points": "true"})
    url = "https://api3.geo.admin.ch/rest/services/profile.json?" + params
    last = None
    for i in range(5):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            time.sleep(1.2 + i)
    raise last


def leg_updown(cum, alt, d0, d1, step=25.0):
    if d1 - d0 < 1:
        return 0.0, 0.0
    xs = np.append(np.arange(d0, d1, step), d1)
    a = np.interp(xs, cum, alt)
    dd = np.diff(a)
    return float(dd[dd > 0].sum()), float(-dd[dd < 0].sum())


def pick_image(mapobj):
    imgs = [im for im in mapobj.get("images", []) if not im.get("isThumbnail", False)]
    if not imgs:
        imgs = mapobj.get("images", [])
    return max(imgs, key=lambda im: im.get("width", 0) * im.get("height", 0))


def process(stage, cls, cid):
    fname = os.path.join(OUT, f"s{stage}_{cls}.json")
    blob_url = class_blob_url(cid)
    if not blob_url:
        json.dump({"stage": stage, "class": cls, "available": False},
                  open(fname, "w"), indent=2)
        return f"s{stage}_{cls}: UNAVAILABLE (no class blob)"
    d = json.loads(http_get(blob_url))
    courses = d.get("courses") or []
    if not courses or not courses[0].get("controls"):
        json.dump({"stage": stage, "class": cls, "available": False},
                  open(fname, "w"), indent=2)
        return f"s{stage}_{cls}: UNAVAILABLE (no courses in blob)"
    co = courses[0]
    img = pick_image(d["map"])
    a, b, c = img["projection"]["matrix"][0]
    dd_, e, f = img["projection"]["matrix"][1]
    W, H = img["width"], img["height"]
    controls = []
    for i, cc in enumerate(co["controls"]):
        k = cc["control"]
        controls.append({"idx": i, "code": k.get("code"), "type": k.get("type"),
                         "E": round(k["projectedPosition"]["x"], 2),
                         "N": round(k["projectedPosition"]["y"], 2)})
    E0, N0 = controls[0]["E"], controls[0]["N"]
    px, py = a * E0 + b * N0 + c, dd_ * E0 + e * N0 + f
    inbounds = (0 <= px <= W) and (0 <= py <= H)
    png_rel = f"maps/s{stage}_{cls}.png"
    open(os.path.join(OUT, png_rel), "wb").write(http_get(img["url"], binary=True))
    pts = [(x["E"], x["N"]) for x in controls]
    seg = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
           for i in range(len(pts) - 1)]
    cumctrl = [0.0]
    for s in seg:
        cumctrl.append(cumctrl[-1] + s)
    nb = int(min(4900, max(200, round(cumctrl[-1] / 10))))
    prof = dem_profile(pts, nb)
    cum = np.array([p["dist"] for p in prof])
    alt = np.array([p["alts"]["DTM2"] for p in prof])
    legs = []
    tot_up = tot_dn = 0
    for i in range(len(pts) - 1):
        up, dn = leg_updown(cum, alt, cumctrl[i], cumctrl[i + 1])
        up_r, dn_r = int(round(up / 5) * 5), int(round(dn / 5) * 5)
        legs.append({"idx": i, "fromCode": controls[i]["code"],
                     "toCode": controls[i + 1]["code"],
                     "distM": int(round(seg[i])), "upM": up_r, "downM": dn_r})
        tot_up += up_r
        tot_dn += dn_r
    json.dump({
        "stage": stage, "class": cls, "classId": cid, "available": True,
        "courseLengthM": int(round(co["length"])) if co.get("length") is not None else None,
        "climbM": int(round(co["climb"])) if co.get("climb") is not None else None,
        "controls": controls, "legs": legs,
        "map": {"pngPath": png_rel, "width": W, "height": H,
                "lv95ToPixel": [[a, b, c], [dd_, e, f]]},
    }, open(fname, "w"), indent=2)
    flag = "" if inbounds else " *** CONTROL OUT OF MAP BOUNDS"
    return (f"s{stage}_{cls}: len={co.get('length')} climb={co.get('climb')} "
            f"ctrls={len(controls)} demUp={tot_up} demDn={tot_dn}{flag}")


def main():
    stage = int(sys.argv[1])
    os.makedirs(MAPS, exist_ok=True)
    with open(os.path.join(HERE, "livelox_ids.json")) as fh:
        ids = json.load(fh)["classIds"][str(stage)]
    for cls, cid in ids.items():
        try:
            print(process(stage, cls, cid))
        except Exception as ex:
            print(f"s{stage}_{cls}: ERROR {ex}")
        time.sleep(0.3)


if __name__ == "__main__":
    main()
