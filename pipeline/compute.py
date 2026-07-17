"""Compute Kisatori stage/forecast/badges JSON from parsed trackmaxx results
plus optional Livelox terrain. Run: python compute.py [--stages 1 2 3]

Writes data/stage{N}.json, data/forecast.json, data/badges.json, data/crops/*,
and (re)writes data/SCHEMA.md.
"""
import argparse
import json
import math
import os

import numpy as np

import config
import lib_trackmaxx as T
import lib_compute as C
import lib_livelox as LL

STAGES = [1, 2, 3, 4, 5]
FAMILY_CATS = ["HAM", "HS", "HL", "D45", "H60", "CM", "HE"]

AWARD_META = {
    "kultakontrolli": ("Kultakontrolli", "🥇"),
    "sudenkuoppa": ("Sudenkuoppa", "🕳️"),
    "tasatahti": ("Tasatahti", "⏱️"),
    "raketti": ("Raketti", "🚀"),
    "vihreasormi": ("Vihreä sormi", "🌿"),
    "sisu": ("Sisu", "💪"),
    "makikuningas": ("Mäkikuningas", "⛰️"),
    "alamakikuningas": ("Alamäkikuningas/-kuningatar", "⛷️"),
}

# Gradient (up−down)/dist threshold separating uphill/flat/downhill legs, and the
# minimum leg length (m) for a leg to carry meaningful terrain signal.
HILL_GRAD_THR = 0.06
HILL_MIN_DIST_M = 100


def fmt_mmss(s):
    s = int(round(s))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def leg_hill_class(lg):
    """UP / DOWN / FLAT for a leg, or None when it lacks usable terrain data
    (missing climb, or too short to read a gradient from)."""
    dm, um, dn = lg.get("distM"), lg.get("upM"), lg.get("downM")
    if dm is None or um is None or dn is None or dm < HILL_MIN_DIST_M:
        return None
    grad = (um - dn) / dm
    if grad >= HILL_GRAD_THR:
        return "up"
    if grad <= -HILL_GRAD_THR:
        return "down"
    return "flat"


def hill_profile(legs, n_cat):
    """Per-class mean field-percentile on the runner's uphill/flat/downhill legs.

    Each qualifying leg contributes 100*(1 − (legRank−1)/(n_cat−1)) — the % of the
    category beaten on that split (100 = fastest). Classes with no qualifying leg
    are null; the whole profile is None when the runner has no usable climb legs.
    """
    buckets = {"up": [], "down": [], "flat": []}
    for lg in legs:
        cls = leg_hill_class(lg)
        if cls is None:
            continue
        pct = 100.0 if n_cat <= 1 else 100.0 * (1 - (lg["legRank"] - 1) / (n_cat - 1))
        buckets[cls].append(pct)
    if not any(buckets.values()):
        return None
    return {k: ({"pct": round(sum(v) / len(v), 1), "n": len(v)} if v else None)
            for k, v in buckets.items()}


# --------------------------------------------------------------------------
# Per-stage assembly
# --------------------------------------------------------------------------
def build_stage(stage, parsed, members):
    """Return (stage_json_dict, member_ctx) for one stage.

    member_ctx[id] carries per-member computed legs/stats for cross-stage use
    (awards, duels, overall, forecast, badges).
    """
    # Pooled run-in (shared finish chute across all categories this stage).
    pooled_last = []
    for cat, blk in parsed.items():
        for r in blk["runners"]:
            pooled_last.append((r["legSecs"][-1], r["name"], cat))
    pooled_vals = sorted(v for v, _, _ in pooled_last)
    npool = len(pooled_vals)

    def field_pct(v):
        if npool <= 1:
            return 100.0
        slower = sum(1 for x in pooled_vals if x > v)
        return round(100.0 * slower / (npool - 1), 1)

    # Cache category tables for family categories present.
    tables = {}
    for cat in parsed:
        runners = parsed[cat]["runners"]
        if runners:
            tables[cat] = C.category_tables(runners)

    member_ctx = {}
    member_rows = []
    for mb in members:
        cat, rec = T.find_member_class(parsed, mb)
        if not rec:
            member_ctx[mb["id"]] = None
            continue
        tbl = tables[cat]
        ll = LL.load(stage, cat)
        codes = LL.control_codes(ll)
        n_legs = rec["nLegs"]
        m_ratio, expected, residual, loss, mistake = C.mistake_engine(
            rec["legSecs"], tbl["green"])
        lr = tbl["legRankOf"][rec["name"]]
        ra = tbl["rankAtOf"][rec["name"]]
        n_cat = tbl["n"]
        top10_thr = max(1, math.ceil(0.10 * n_cat))
        legs = []
        for i in range(n_legs):
            dist_m, up_m, down_m = LL.leg_terrain(ll, i)
            if codes and i + 1 < len(codes):
                ctrl = codes[i + 1]
            else:
                ctrl = "Maali" if i == n_legs - 1 else str(i + 1)
            legs.append({
                "ctrl": ctrl,
                "legSec": rec["legSecs"][i],
                "cumSec": rec["cumSecs"][i],
                "legRank": lr[i],
                "greenSec": tbl["green"][i],
                "ratio": round(rec["legSecs"][i] / tbl["green"][i], 3),
                "lossSec": int(round(loss[i])),
                "mistake": bool(mistake[i]),
                "rankAt": ra[i],
                "distM": dist_m, "upM": up_m, "downM": down_m,
            })
        mistake_loss = int(round(sum(loss[i] for i in range(n_legs) if mistake[i])))
        mistake_count = sum(1 for x in mistake if x)
        last_leg = rec["legSecs"][-1]
        rank = rec["rank"]
        clean_time = rec["finishSec"] - mistake_loss
        # Counterfactual "clean race" placing: where the member would rank if
        # they had run mistake-free, holding every rival's actual time fixed.
        clean_rank = 1 + sum(1 for o in parsed[cat]["runners"]
                             if o["finishSec"] < clean_time)
        row = {
            "memberId": mb["id"], "name": mb["first"], "class": cat,
            "rank": rank, "of": n_cat,
            "timeSec": rec["finishSec"],
            "behindSec": rec["finishSec"] - tbl["winnerTimeSec"],
            "percentile": C.percentile_from_rank(rank, n_cat),
            "mRatio": round(m_ratio, 3),
            "cleanTimeSec": clean_time,
            "cleanRank": clean_rank,
            "mistakeLossSec": mistake_loss,
            "mistakeCount": mistake_count,
            "runIn": {"sec": last_leg, "fieldPct": field_pct(last_leg)},
            "legs": legs,
            "rankAtByControl": ra,
            "hillProfile": hill_profile(legs, n_cat),
        }
        member_rows.append(row)
        member_ctx[mb["id"]] = {
            "cat": cat, "row": row, "rec": rec, "legs": legs,
            "ratios": [lg["ratio"] for lg in legs],
            "rankAt": ra, "top10Legs": sum(1 for x in lr if x <= top10_thr),
            "n_cat": n_cat, "hasClimb": ll is not None,
        }

    awards = build_awards(member_ctx)
    duels = build_duels(parsed, members)
    runin = build_runin(pooled_last, pooled_vals, member_ctx)
    member_cats = {c["cat"] for c in member_ctx.values() if c}
    cats = build_categories(stage, parsed, tables, member_cats)

    stage_json = {
        "stage": stage,
        "members": member_rows,
        "awards": awards,
        "duels": duels,
        "runInReport": runin,
        "categories": cats,
        "crops": [],  # filled by add_crops after awards/duels known
        "metsaradio": {"paragraphsFi": []},
    }
    return stage_json, member_ctx


def build_awards(ctx):
    present = {k: v for k, v in ctx.items() if v}
    awards = []
    if not present:
        return awards

    def emit(aid, mid, leg_idx, value):
        title, emoji = AWARD_META[aid]
        awards.append({
            "id": aid, "titleFi": title, "emoji": emoji, "memberId": mid,
            "valueFi": value, "evidence": {"memberId": mid, "legIdx": leg_idx},
        })

    # kultakontrolli: lowest single-leg ratio across the family, excluding the
    # finish run-in (a sprint, celebrated separately in runInReport).
    best = None
    for mid, c in present.items():
        for i, lg in enumerate(c["legs"][:-1]):
            if best is None or lg["ratio"] < best[2]:
                best = (mid, i, lg["ratio"], lg)
    if best:
        mid, i, ratio, lg = best
        emit("kultakontrolli", mid, i,
             f"{lg['ctrl']}: {lg['legRank']}. koko sarjassa ({ratio*100:.0f} %)")

    # sudenkuoppa: biggest single loss
    worst = None
    for mid, c in present.items():
        for i, lg in enumerate(c["legs"]):
            if worst is None or lg["lossSec"] > worst[2]:
                worst = (mid, i, lg["lossSec"], lg)
    if worst and worst[2] > 0:
        mid, i, lossv, lg = worst
        emit("sudenkuoppa", mid, i, f"{lg['ctrl']}: −{fmt_mmss(lossv)} hukkaan")

    # tasatahti: lowest ratio variance (steadiest)
    steady = min(present.items(), key=lambda kv: C.stdev(kv[1]["ratios"]))
    mid, c = steady
    emit("tasatahti", mid, 0, f"tasaisin vauhti (σ {C.stdev(c['ratios']):.2f})")

    # raketti: most rank gained in 2nd half (rankAt at mid minus final rank)
    def rank_gain_2nd(c):
        ra = c["rankAt"]
        mid_i = len(ra) // 2
        return ra[mid_i] - ra[-1]
    rk = max(present.items(), key=lambda kv: rank_gain_2nd(kv[1]))
    mid, c = rk
    g = rank_gain_2nd(c)
    if g > 0:
        emit("raketti", mid, len(c["legs"]) // 2, f"+{g} sijaa loppupuoliskolla")

    # vihreasormi: most legs in field top-10%
    vg = max(present.items(), key=lambda kv: kv[1]["top10Legs"])
    mid, c = vg
    if c["top10Legs"] > 0:
        emit("vihreasormi", mid, 0, f"{c['top10Legs']} osuutta sarjan top-10 %:ssa")

    # sisu: biggest comeback (worst rankAt minus final rank)
    def comeback(c):
        return max(c["rankAt"]) - c["rankAt"][-1]
    sc = max(present.items(), key=lambda kv: comeback(kv[1]))
    mid, c = sc
    cb = comeback(c)
    if cb > 0:
        worst_i = c["rankAt"].index(max(c["rankAt"]))
        emit("sisu", mid, worst_i, f"noususija {max(c['rankAt'])}. → {c['rankAt'][-1]}.")

    # makikuningas: best pace on genuinely steep-up terrain. Anchor to the
    # steepest up-leg anyone in the family ran, then reward the best ratio among
    # legs at least 60% as steep (floor 20 m) so the award means a real hill.
    climb_legs = [(mid, i, lg) for mid, c in present.items() if c["hasClimb"]
                  for i, lg in enumerate(c["legs"]) if lg["upM"] is not None]
    if climb_legs:
        u_max = max(lg["upM"] for _, _, lg in climb_legs)
        thr_up = max(20, 0.6 * u_max)
        pool = [x for x in climb_legs if x[2]["upM"] >= thr_up]
        if pool:
            mid, i, lg = min(pool, key=lambda x: x[2]["ratio"])
            emit("makikuningas", mid, i,
                 f"{lg['ctrl']}: {lg['upM']} m nousua, {lg['ratio']*100:.0f} % vauhti")

    # alamakikuningas: best mean field-percentile on downhill legs (>= 2 legs).
    def best_down_leg_idx(c):
        best = None
        for i, lg in enumerate(c["legs"]):
            if leg_hill_class(lg) == "down" and (
                    best is None or lg["legRank"] < c["legs"][best]["legRank"]):
                best = i
        return best

    down_pool = []
    for mid, c in present.items():
        hp = c["row"].get("hillProfile")
        if hp and hp.get("down") and hp["down"]["n"] >= 2:
            down_pool.append((mid, c, hp["down"]))
    if down_pool:
        mid, c, dn = max(down_pool, key=lambda x: x[2]["pct"])
        leg_i = best_down_leg_idx(c)
        if leg_i is not None:
            top = max(1, round(100 - dn["pct"]))
            emit("alamakikuningas", mid, leg_i,
                 f"alamäissä kentän top {top} % ({dn['n']} osuutta)")
    return awards


def build_duels(parsed, members):
    # Family relation drives the duel's display title: Eevert & Markus are
    # brothers-in-law (lanko), Venla & Alma sisters-in-law (käly).
    pairs = [("eevert", "markus", "HE", "Lankoduelli"),
             ("venla", "alma", "CM", "Kälyduelli")]
    mby = {m["id"]: m for m in members}
    duels = []
    for aid, bid, hint, title in pairs:
        pa = find_rec(parsed, mby[aid])
        pb = find_rec(parsed, mby[bid])
        if not pa or not pb:
            continue
        (ca, ra), (cb, rb) = pa, pb
        if ca != cb:
            continue
        k = min(ra["nLegs"], rb["nLegs"])
        cum_diff = [ra["cumSecs"][i] - rb["cumSecs"][i] for i in range(k)]
        legs_a = sum(1 for i in range(k) if ra["legSecs"][i] < rb["legSecs"][i])
        legs_b = sum(1 for i in range(k) if rb["legSecs"][i] < ra["legSecs"][i])
        # decisive leg = biggest single-leg swing in the gap
        swings = [abs(cum_diff[0])] + [abs(cum_diff[i] - cum_diff[i - 1])
                                       for i in range(1, k)]
        decisive = int(max(range(k), key=lambda i: swings[i]))
        duels.append({
            "id": f"{aid}-{bid}", "titleFi": title,
            "class": ca, "memberA": aid, "memberB": bid,
            "cumDiff": cum_diff, "legsWonA": legs_a, "legsWonB": legs_b,
            "totalDiffSec": cum_diff[-1], "decisiveLegIdx": decisive,
        })
    return duels


def find_rec(parsed, member):
    cat, rec = T.find_member_class(parsed, member)
    if rec:
        return cat, rec
    return None


def build_runin(pooled_last, pooled_vals, ctx):
    npool = len(pooled_vals)
    arr = np.array(pooled_vals)
    xmax = int(math.ceil(np.percentile(arr, 99)))
    bins = list(range(0, xmax + 1))
    counts = [0] * len(bins)
    clipped = 0
    for v in pooled_vals:
        if v > xmax:
            clipped += 1
            counts[-1] += 1
        else:
            counts[min(int(v), xmax)] += 1
    fastest = pooled_vals[0]
    fastest_names = sorted({nm for v, nm, _ in pooled_last if v == fastest})
    group = []
    for mid, c in ctx.items():
        if not c:
            continue
        group.append({
            "memberId": mid,
            "sec": c["row"]["runIn"]["sec"],
            "fieldPct": c["row"]["runIn"]["fieldPct"],
        })
    group.sort(key=lambda g: g["sec"])
    return {
        "binStartSec": bins, "counts": counts,
        "xmaxSec": xmax, "clippedCount": clipped,
        "dayFastest": {"sec": fastest, "names": fastest_names,
                       "count": len(fastest_names)},
        "fieldMedianSec": int(round(float(np.median(arr)))),
        "poolSize": npool,
        "group": group,
    }


def build_categories(stage, parsed, tables, member_cats):
    out = {}
    for cat in member_cats:
        if cat not in tables:
            continue
        tbl = tables[cat]
        ll = LL.load(stage, cat)
        out[cat] = {
            "finishers": tbl["n"],
            "winnerTimeSec": tbl["winnerTimeSec"],
            "courseLengthM": ll["courseLengthM"] if ll else None,
            "climbM": ll["climbM"] if ll else None,
        }
    return out


# --------------------------------------------------------------------------
# Cross-stage: overall standings
# --------------------------------------------------------------------------
def build_overall(parsed_by_stage, through_k, member, member_cat_by_stage):
    stages = [s for s in STAGES if s <= through_k]
    cats = [member_cat_by_stage.get(s) for s in stages]
    if any(c is None for c in cats) or len(set(cats)) != 1:
        # Not rankable (missed a stage or switched category).
        run = [s for s in stages if member_cat_by_stage.get(s)]
        cum = 0
        for s in run:
            _, rec = T.find_member_class(parsed_by_stage[s], member)
            cum += rec["finishSec"]
        return {"rankable": False, "stagesCounted": run,
                "cumTimeSec": cum if run else None,
                "rankAfter": None, "of": None, "cumBehindSec": None,
                "category": member_cat_by_stage.get(stages[-1])}
    cat = cats[0]
    per_stage = []
    for s in stages:
        d = {r["name"]: r["finishSec"] for r in parsed_by_stage[s][cat]["runners"]}
        per_stage.append(d)
    common = set(per_stage[0])
    for d in per_stage[1:]:
        common &= set(d)
    cum = {nm: sum(d[nm] for d in per_stage) for nm in common}
    mname = None
    _, rec = T.find_member_class(parsed_by_stage[stages[-1]], member)
    mname = rec["name"]
    if mname not in cum:
        return {"rankable": False, "stagesCounted": stages,
                "cumTimeSec": None, "rankAfter": None, "of": None,
                "cumBehindSec": None, "category": cat}
    ranking = sorted(cum.values())
    my = cum[mname]
    rank_after = 1 + sum(1 for v in cum.values() if v < my)
    return {"rankable": True, "stagesCounted": stages, "cumTimeSec": my,
            "rankAfter": rank_after, "of": len(cum),
            "cumBehindSec": my - ranking[0], "category": cat}


# --------------------------------------------------------------------------
# Crops
# --------------------------------------------------------------------------
def add_crops(stage, stage_json, ctx):
    crops = []
    todo = []
    crops_dir = os.path.join(config.DATA, "crops")
    os.makedirs(crops_dir, exist_ok=True)

    def do_crop(kind, mid, leg_idx, cls):
        ll = LL.load(stage, cls)
        if not ll or "map" not in ll:
            todo.append(f"crop {kind}: no livelox map for stage {stage} {cls}")
            return
        fn = f"s{stage}_{kind}_{mid}_L{leg_idx}.webp"
        res = LL.crop_leg(ll, leg_idx, os.path.join(crops_dir, fn))
        if not res:
            todo.append(f"crop {kind}: crop failed for stage {stage} {cls} leg {leg_idx}")
            return
        crops.append({
            "id": f"{kind}", "file": f"crops/{fn}", "memberId": mid,
            "legLabel": f"{res['fromCode']}→{res['toCode']}", "kind": kind,
            "ctrlFrom": res["fromCode"], "ctrlTo": res["toCode"],
            "pxFrom": res["pxFrom"], "pxTo": res["pxTo"],
            "widthPx": res["widthPx"], "heightPx": res["heightPx"],
        })

    by_id = {a["id"]: a for a in stage_json["awards"]}
    if "kultakontrolli" in by_id:
        a = by_id["kultakontrolli"]
        mid = a["memberId"]
        do_crop("hero", mid, a["evidence"]["legIdx"], ctx[mid]["cat"])
    if "sudenkuoppa" in by_id:
        a = by_id["sudenkuoppa"]
        mid = a["memberId"]
        do_crop("villain", mid, a["evidence"]["legIdx"], ctx[mid]["cat"])
    for d in stage_json["duels"]:
        kind = "duelHE" if d["class"] == "HE" else "duelCM"
        do_crop(kind, d["memberA"], d["decisiveLegIdx"], d["class"])
    stage_json["crops"] = crops
    return todo


# --------------------------------------------------------------------------
# Forecast (Monte Carlo)
# --------------------------------------------------------------------------
def build_forecast(member_pcts, member_current_pct, member_catsize, n_sims=20000):
    """Monte Carlo final overall standing.

    Each remaining stage's percentile ~ Normal(mean, sd) of the member's
    observed stage percentiles (sd floored at 5pp). Final standing = mean
    percentile over all 6 stages, mapped to a rank in the category. Rank
    quantiles are for display; pBetterThanCurrent is computed on the coherent
    percentile scale (final mean percentile vs the member's current standing
    percentile), avoiding pool-size mismatches.
    """
    rng = np.random.default_rng(20260714)
    out = {}
    for mid, pcts in member_pcts.items():
        if not pcts:
            continue
        mean = float(np.mean(pcts))
        sd = max(float(np.std(pcts)) if len(pcts) > 1 else 5.0, 5.0)
        n = max(2, member_catsize.get(mid, 50))
        cur_pct = member_current_pct.get(mid)
        n_rem = 6 - len(STAGES)
        future = np.clip(rng.normal(mean, sd, size=(n_sims, n_rem)), 0, 100)
        avg6 = (sum(pcts) + future.sum(axis=1)) / (len(pcts) + n_rem)
        finals = np.round((100 - avg6) / 100 * (n - 1)).astype(int) + 1
        top10_n = max(1, math.ceil(0.10 * n))
        slope = C.linfit_slope(pcts)
        trend = "nouseva" if slope > 2 else "laskeva" if slope < -2 else "tasainen"
        out[mid] = {
            "p05": int(np.percentile(finals, 5)),
            "p25": int(np.percentile(finals, 25)),
            "p50": int(np.percentile(finals, 50)),
            "p75": int(np.percentile(finals, 75)),
            "p95": int(np.percentile(finals, 95)),
            "pTop10": round(float(np.mean(finals <= top10_n)), 3),
            "pBetterThanCurrent": (round(float(np.mean(avg6 > cur_pct)), 3)
                                   if cur_pct is not None else None),
            "trend": trend,
            "catSize": n,
        }
    return out


# --------------------------------------------------------------------------
# Badges
# --------------------------------------------------------------------------
def build_badges(stage_ctx, stage_jsons, members, awards_by_stage):
    kids = {m["id"] for m in members if m["kid"]}
    badges = {m["id"]: [] for m in members}

    def add(mid, bid, title, emoji, stage, desc):
        badges[mid].append({"id": bid, "titleFi": title, "emoji": emoji,
                            "stage": stage, "descFi": desc})

    # Per-stage badges
    hill_wins = {m["id"]: 0 for m in members}
    for stage in STAGES:
        ctx = stage_ctx[stage]
        sj = stage_jsons[stage]
        # best family placement this stage (highest percentile)
        present = [(mid, c) for mid, c in ctx.items() if c]
        if present:
            champ = max(present, key=lambda kv: kv[1]["row"]["percentile"])
            add(champ[0], "perheykkonen", "Perheykkönen", "👑", stage,
                f"perheen paras sijoitus etapilla {stage}")
        # day's fastest run-in
        fastest_names = set(sj["runInReport"]["dayFastest"]["names"])
        for mid, c in present:
            if c["rec"]["name"] in fastest_names:
                add(mid, "salamavauhti", "Salamavauhti", "⚡", stage,
                    "päivän nopein loppusuora")
        for mid, c in present:
            row = c["row"]
            if row["mistakeCount"] == 0:
                add(mid, "puhdas", "Puhdas suoritus", "✨", stage,
                    f"nolla virhettä etapilla {stage}")
            comeback = max(c["rankAt"]) - c["rankAt"][-1]
            if comeback >= 8:
                add(mid, "comeback", "Takaa-ajaja", "📈", stage,
                    f"nousi {comeback} sijaa kesken etapin")
            if mid in kids:
                add(mid, "reipas", "Reipas retkeilijä", "🐿️", stage,
                    f"maaliin asti etapilla {stage}")
        for a in awards_by_stage[stage]:
            if a["id"] == "makikuningas":
                hill_wins[a["memberId"]] += 1

    # Cross-stage badges
    for m in members:
        mid = m["id"]
        pcts = [stage_ctx[s][mid]["row"]["percentile"]
                for s in STAGES if stage_ctx[s].get(mid)]
        finished_all = all(stage_ctx[s].get(mid) for s in STAGES)
        if finished_all:
            add(mid, "rautanaula", "Rautanaula", "🔩", 3, "kaikki etapit maaliin")
        if len(pcts) >= 3 and all(p >= 70 for p in pcts):
            add(mid, "kolmenputki", "Kolmen putki", "🔥", 3,
                "kolme etappia top-30 %:ssa")
        if hill_wins[mid] >= 2:
            add(mid, "makikuningas2", "Mäkikuningas ×2", "⛰️", 3,
                "kaksi mäkivoittoa")
    return badges


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(stages):
    members = config.load_members()
    parsed_by_stage = {s: T.parse_stage(s) for s in STAGES}

    stage_jsons, stage_ctx, awards_by_stage = {}, {}, {}
    member_cat_by_stage = {m["id"]: {} for m in members}
    todo_all = []

    for s in STAGES:
        sj, ctx = build_stage(s, parsed_by_stage[s], members)
        stage_jsons[s] = sj
        stage_ctx[s] = ctx
        awards_by_stage[s] = sj["awards"]
        for mid, c in ctx.items():
            if c:
                member_cat_by_stage[mid][s] = c["cat"]

    # Overall (through each stage) + crops.
    for s in STAGES:
        overall = []
        for m in members:
            if not stage_ctx[s].get(m["id"]):
                continue
            ov = build_overall(parsed_by_stage, s, m, member_cat_by_stage[m["id"]])
            ov["memberId"] = m["id"]
            overall.append(ov)
        stage_jsons[s]["overall"] = overall
        todo_all += add_crops(s, stage_jsons[s], stage_ctx[s])

    # Write per-stage files (only the requested stages).
    # Metsäradio paragraphs are hand-written after compute — carry them over.
    for s in stages:
        path = os.path.join(config.DATA, f"stage{s}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    old = json.load(f)
                if old.get("metsaradio", {}).get("paragraphsFi"):
                    stage_jsons[s]["metsaradio"] = old["metsaradio"]
            except (json.JSONDecodeError, OSError):
                pass
        with open(path, "w") as f:
            json.dump(stage_jsons[s], f, ensure_ascii=False, indent=1)

    # Forecast (uses all 3 stages).
    member_pcts, member_current_pct, member_catsize = {}, {}, {}
    for m in members:
        mid = m["id"]
        pcts = [stage_ctx[s][mid]["row"]["percentile"]
                for s in STAGES if stage_ctx[s].get(mid)]
        member_pcts[mid] = pcts
        last = max((s for s in STAGES if stage_ctx[s].get(mid)), default=None)
        # Current standing as a percentile (coherent across pool sizes): from
        # the overall ranking if rankable, else the latest stage percentile.
        ov = build_overall(parsed_by_stage, STAGES[-1], m, member_cat_by_stage[mid])
        if ov.get("rankable"):
            member_current_pct[mid] = C.percentile_from_rank(ov["rankAfter"], ov["of"])
        elif last:
            member_current_pct[mid] = stage_ctx[last][mid]["row"]["percentile"]
        else:
            member_current_pct[mid] = None
        member_catsize[mid] = stage_ctx[last][mid]["n_cat"] if last else 50
    forecast = {"asOfStage": STAGES[-1],
                "members": build_forecast(member_pcts, member_current_pct, member_catsize)}
    with open(os.path.join(config.DATA, "forecast.json"), "w") as f:
        json.dump(forecast, f, ensure_ascii=False, indent=1)

    # Badges.
    badges = build_badges(stage_ctx, stage_jsons, members, awards_by_stage)
    with open(os.path.join(config.DATA, "badges.json"), "w") as f:
        json.dump(badges, f, ensure_ascii=False, indent=1)

    # Enrich the members roster with clsByStage (class per stage, string keys;
    # a stage key is absent if the member did not run it). Additive; the base
    # input fields are preserved so re-runs stay idempotent.
    for m in members:
        m["clsByStage"] = {str(s): c for s, c in
                           sorted(member_cat_by_stage[m["id"]].items())}
    with open(os.path.join(config.DATA, "members.json"), "w") as f:
        json.dump(members, f, ensure_ascii=False, indent=1)

    if todo_all:
        print("TODO / missing:")
        for t in sorted(set(todo_all)):
            print("  -", t)
    return stage_jsons, todo_all


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="*", type=int, default=STAGES)
    a = ap.parse_args()
    main(a.stages)
    print("done:", a.stages)
