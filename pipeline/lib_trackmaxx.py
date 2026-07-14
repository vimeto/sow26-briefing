"""Fetch and parse trackmaxx.ch split results for a SOW26 stage.

Row model (list.ashx JSON, one row per participant in dataf):
- row[1]  rank, e.g. "12." (unranked rows use a non-numeric marker -> skipped)
- row[2]  displayed name
- several ";"-joined split fields at the tail. The LAST is cumulative seconds,
  the 2nd-last is per-leg seconds. Each is "N:v;v;v;..." where N = control count.
  Open courses (HS/HL/CS/CM/CL/CU) shift the fixed columns, so we locate the
  split fields by pattern (contains ';', starts "digits:digit"), never by index.
- mm:ss time fields (finish, behind) also start "digits:" but contain no ';',
  so they are naturally excluded.
"""
import json
import os
import re
import time
import unicodedata

import requests

from config import STAGE_RACE_UUID, TRACKMAXX_LIST, DATA, stage_categories

_SPLIT_RE = re.compile(r"^\d+:\d")
_RANK_RE = re.compile(r"^\d+\.$")
_TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def norm(s):
    """Lowercase + strip diacritics, for accent-insensitive name matching."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def fetch_stage(stage, out_dir=None, sleep=0.15):
    """Download every category's result JSON for a stage. Returns {cat: raw}."""
    out_dir = out_dir or os.path.join(DATA, "raw")
    os.makedirs(out_dir, exist_ok=True)
    race = STAGE_RACE_UUID[stage]
    cats = stage_categories(stage)
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://trackmaxx.ch/results/?race=sow26-{stage}",
    })
    raw = {}
    for name, cid in cats.items():
        url = (f"{TRACKMAXX_LIST}?mode=results&race={race}&c={cid}"
               f"&s=&f=&sk=0&ta=5000&filter=&filtervalue=")
        r = sess.get(url, timeout=30)
        r.raise_for_status()
        raw[name] = r.json()
        time.sleep(sleep)
    path = os.path.join(out_dir, f"stage{stage}_raw.json")
    with open(path, "w") as f:
        json.dump(raw, f)
    return raw


def load_raw(stage):
    with open(os.path.join(DATA, "raw", f"stage{stage}_raw.json")) as f:
        return json.load(f)


def _parse_split_field(field):
    toks = field.split(";")
    head = toks[0].split(":")
    n = int(head[0])
    vals = [int(head[1])] + [int(t) for t in toks[1:] if t != ""]
    return n, vals


def _time_to_sec(t):
    t = t.strip()
    if not _TIME_RE.match(t):
        return None
    parts = [int(p) for p in t.split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_category(raw_cat):
    """Parse one category's raw dict into a list of finisher records.

    Each record: {name, rank, finishSec, legSecs[], cumSecs[], nLegs}.
    nLegs includes the finish leg (control count + 1). Non-finishers, mispunches
    (non-monotonic cumulative), and rows failing the finish-time cross-check are
    dropped and counted in the returned stats.
    """
    rows = raw_cat.get("dataf", [])
    runners = []
    dropped = {"unranked": 0, "no_splits": 0, "bad_cum": 0, "time_mismatch": 0}
    for row in rows:
        rank_s = str(row[1])
        if not _RANK_RE.match(rank_s):
            dropped["unranked"] += 1
            continue
        name = str(row[2])
        data_fields = [x for x in row
                       if isinstance(x, str) and ";" in x and _SPLIT_RE.match(x)]
        if len(data_fields) < 2:
            dropped["no_splits"] += 1
            continue
        try:
            _, leg_vals = _parse_split_field(data_fields[-2])
            _, cum_vals = _parse_split_field(data_fields[-1])
        except (ValueError, IndexError):
            dropped["no_splits"] += 1
            continue
        # Real legs = leading strictly-increasing positive run of the cumulative
        # field (the fixed-width field is zero-padded past the finish).
        n_legs = 0
        prev = 0
        for v in cum_vals:
            if v > prev:
                n_legs += 1
                prev = v
            else:
                break
        if n_legs < 1 or len(leg_vals) < n_legs:
            dropped["bad_cum"] += 1
            continue
        legs = leg_vals[:n_legs]
        cums = cum_vals[:n_legs]
        if any(x <= 0 for x in legs) or sum(legs) != cums[-1]:
            dropped["bad_cum"] += 1
            continue
        finish = cums[-1]
        # Cross-check against displayed mm:ss time.
        tfields = [_time_to_sec(x) for x in row
                   if isinstance(x, str) and _TIME_RE.match(x.strip())]
        tfields = [t for t in tfields if t]
        if tfields:
            disp = min(tfields, key=lambda t: abs(t - finish))
            if abs(disp - finish) > 1:
                dropped["time_mismatch"] += 1
                continue
        rank = int(rank_s[:-1])
        runners.append({
            "name": name, "rank": rank, "finishSec": finish,
            "legSecs": legs, "cumSecs": cums, "nLegs": n_legs,
        })
    return runners, dropped


def parse_stage(stage, raw=None):
    """Parse every category of a stage. Returns {cat: {runners, dropped}}."""
    raw = raw or load_raw(stage)
    out = {}
    for cat, raw_cat in raw.items():
        runners, dropped = parse_category(raw_cat)
        out[cat] = {"runners": runners, "dropped": dropped}
    return out


def find_member_class(parsed_stage, member):
    """Locate (category, record) for a member across all categories in a stage.

    Matches when both name tokens (first + last, accent-folded) appear in the
    displayed name. Returns (cat, record) or (None, None).
    """
    first = norm(member["first"])
    last = norm(member["last"])
    hits = []
    for cat, blk in parsed_stage.items():
        for rec in blk["runners"]:
            n = norm(rec["name"])
            if first in n and last in n:
                hits.append((cat, rec))
    if not hits:
        return None, None
    return hits[0]
