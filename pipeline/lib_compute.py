"""Analytics primitives for the Kisatori pipeline: the mistake engine and the
per-category derived tables (green splits, leg ranks, running position)."""
import math
import statistics as stats


def category_tables(runners):
    """Given a category's parsed runners (uniform nLegs), return derived tables.

    Returns dict with:
      nLegs, n, green[nLegs]            field-fastest per-leg split
      legRankOf[name][i], rankAtOf[name][i]
      winnerTimeSec, lastLegs[name]
    """
    n_legs = runners[0]["nLegs"]
    n = len(runners)
    green = [min(r["legSecs"][i] for r in runners) for i in range(n_legs)]
    leg_rank = {}
    rank_at = {}
    for r in runners:
        lr, ra = [], []
        for i in range(n_legs):
            mine = r["legSecs"][i]
            lr.append(1 + sum(1 for o in runners if o["legSecs"][i] < mine))
            minec = r["cumSecs"][i]
            ra.append(1 + sum(1 for o in runners if o["cumSecs"][i] < minec))
        leg_rank[r["name"]] = lr
        rank_at[r["name"]] = ra
    winner = min(r["finishSec"] for r in runners)
    last_legs = {r["name"]: r["legSecs"][-1] for r in runners}
    return {
        "nLegs": n_legs, "n": n, "green": green,
        "legRankOf": leg_rank, "rankAtOf": rank_at,
        "winnerTimeSec": winner, "lastLegs": last_legs,
    }


def mistake_engine(leg_secs, green):
    """Robust per-leg mistake detection for one runner.

    m = median of per-leg ratios (split/green); expected = m*green.
    A leg is a mistake when its residual (actual-expected) exceeds
    max(2*robust_sigma, 20% of expected). loss = max(0, residual).
    Returns (mRatio, expected[], residual[], loss[], mistake[]).
    """
    ratios = [s / g for s, g in zip(leg_secs, green)]
    m = stats.median(ratios)
    expected = [m * g for g in green]
    residual = [s - e for s, e in zip(leg_secs, expected)]
    med_r = stats.median(residual)
    mad = stats.median([abs(x - med_r) for x in residual])
    sigma = 1.4826 * mad
    loss, mistake = [], []
    for e, res in zip(expected, residual):
        thr = max(2 * sigma, 0.20 * e)
        loss.append(max(0.0, res))
        mistake.append(res > thr and res > 0)
    return m, expected, residual, loss, mistake


def percentile_from_rank(rank, n):
    """rank 1 -> 100, rank n -> 0. n==1 -> 100."""
    if n <= 1:
        return 100.0
    return round(100.0 * (n - rank) / (n - 1), 1)


def stdev(xs):
    return stats.pstdev(xs) if len(xs) > 1 else 0.0


def linfit_slope(ys):
    """Slope of ys vs index 0..k-1 (least squares). 0 if <2 points."""
    k = len(ys)
    if k < 2:
        return 0.0
    xs = list(range(k))
    mx = sum(xs) / k
    my = sum(ys) / k
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0
