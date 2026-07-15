"""Post-compute validation. Exits non-zero on any hard failure.

Checks: member finish times vs trackmaxx displayed times (0 mismatches);
per-leg cumulative == sum of legs; percentiles in [0,100]; every award has a
real evidence leg; run-in histogram sums to pool size; known stage-2 benchmarks.
"""
import json
import os
import sys

import config
import lib_trackmaxx as T

DATA = config.DATA
fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def sec_of_displayed(row):
    import re
    tre = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
    out = []
    for x in row:
        if isinstance(x, str) and tre.match(x.strip()):
            p = [int(v) for v in x.strip().split(":")]
            out.append(p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2])
    return out


def main():
    members = config.load_members()
    # 1. Re-parse and confirm zero finish-time mismatches across all finishers.
    total_finishers = 0
    for stage in (1, 2, 3):
        P = T.parse_stage(stage)
        for cat, blk in P.items():
            for r in blk["runners"]:
                total_finishers += 1
                check(sum(r["legSecs"]) == r["cumSecs"][-1],
                      f"s{stage} {cat} {r['name']}: legs sum != cum")
                check(r["cumSecs"][-1] == r["finishSec"],
                      f"s{stage} {cat} {r['name']}: cum end != finish")
                disp = sec_of_displayed(next(
                    row for row in T.load_raw(stage)[cat]["dataf"]
                    if str(row[2]) == r["name"] and str(row[1]) == f"{r['rank']}."))
                check(any(abs(d - r["finishSec"]) <= 1 for d in disp),
                      f"s{stage} {cat} {r['name']}: no displayed time matches {r['finishSec']}")

    # 2. Per-stage JSON structural checks.
    for stage in (1, 2, 3):
        sj = json.load(open(os.path.join(DATA, f"stage{stage}.json")))
        for m in sj["members"]:
            check(0 <= m["percentile"] <= 100, f"s{stage} {m['memberId']} pct out of range")
            check(m["of"] >= m["rank"] >= 1, f"s{stage} {m['memberId']} rank/of bad")
            check(m["cleanTimeSec"] <= m["timeSec"], f"s{stage} {m['memberId']} clean>time")
            for lg in m["legs"]:
                check(lg["ratio"] >= 1.0 - 1e-9, f"s{stage} {m['memberId']} ratio<1")
                check(lg["legRank"] >= 1, f"s{stage} {m['memberId']} legRank<1")
        # awards evidence points at a real leg
            # hillProfile: null (no terrain) or buckets with pct in [0,100], n>=1
            hp = m.get("hillProfile")
            if hp is not None:
                for bk in ("up", "down", "flat"):
                    b = hp.get(bk)
                    if b is not None:
                        check(0 <= b["pct"] <= 100, f"s{stage} {m['memberId']} {bk}.pct range")
                        check(b["n"] >= 1, f"s{stage} {m['memberId']} {bk}.n<1")
        mrows = {m["memberId"]: m for m in sj["members"]}
        for a in sj["awards"]:
            mid = a["evidence"]["memberId"]
            li = a["evidence"]["legIdx"]
            check(mid in mrows and 0 <= li < len(mrows[mid]["legs"]),
                  f"s{stage} award {a['id']} bad evidence leg")
            if a["id"] == "alamakikuningas":
                hp = mrows[mid].get("hillProfile")
                check(hp and hp.get("down") and hp["down"]["n"] >= 2,
                      f"s{stage} alamakikuningas winner lacks >=2 downhill legs")
        # run-in histogram integrity
        ri = sj["runInReport"]
        check(sum(ri["counts"]) == ri["poolSize"],
              f"s{stage} runin counts sum {sum(ri['counts'])} != pool {ri['poolSize']}")
        for g in ri["group"]:
            check(0 <= g["fieldPct"] <= 100, f"s{stage} runin fieldPct range")

    # 3. Known stage-2 benchmarks.
    s2 = json.load(open(os.path.join(DATA, "stage2.json")))
    ri = s2["runInReport"]
    check(ri["fieldMedianSec"] == 31, f"s2 run-in median {ri['fieldMedianSec']} != 31")
    peak = max(range(len(ri["counts"])), key=lambda i: ri["counts"][i])
    check(ri["binStartSec"][peak] == 28 and ri["counts"][peak] == 120,
          f"s2 peak bin {ri['binStartSec'][peak]}s x{ri['counts'][peak]} != 28s x120")
    runin = {g["memberId"]: g["sec"] for g in ri["group"]}
    check(runin.get("vilhelm") == 18, f"s2 vilhelm run-in {runin.get('vilhelm')} != 18")
    check(runin.get("viivi") == 28, f"s2 viivi run-in {runin.get('viivi')} != 28")

    print(f"checked {total_finishers} finishers across 3 stages")
    if fails:
        print(f"FAIL: {len(fails)} issue(s):")
        for f in fails[:40]:
            print("  -", f)
        sys.exit(1)
    print("ALL VALIDATION CHECKS PASSED")


if __name__ == "__main__":
    main()
