# Kisatori data schema (SOW26)

All times are **integer seconds** unless noted. All JSON is UTF-8. Produced by
`pipeline/compute.py` from trackmaxx splits (+ optional Livelox terrain). Rerun a
stage with `pipeline/build_stage.sh <N>`.

Member ids: `vilhelm, viivi, sirra, mikko, alma, markus, eevert, venla`.
**Viivi did not run stage 1** — she is absent from `stage1.json` (`members`,
`overall`, run-in `group`) and her `overall` is never `rankable` (she also
switched class HS→HL). Any member can be missing from a stage; the UI must not
assume all 8 are present every stage.

Livelox-dependent fields are **null until the Livelox extraction lands** for that
stage×class. When null: `legs[].distM/upM/downM`, `members[].hillProfile`,
`categories[].courseLengthM/climbM`, the `makikuningas`/`alamakikuningas` awards
and `makikuningas2` badge are absent, and the affected `crops` are skipped.

---

## data/members.json
Array of `{id, first, last, trackmaxx, kid, clsByStage}`. `trackmaxx` is the
"Lastname Firstname" display string used to match rows. `kid` true for venla,
alma. `clsByStage` maps stage-number **string** → class (e.g. `{"1":"HAM",
"2":"HAM","3":"HAM"}`); a stage key is **absent** if the member did not run it
(Viivi has no `"1"`). Written by compute.py, so it stays in sync.

## data/stage{N}.json
Top level: `stage, members[], awards[], duels[], runInReport, categories, overall[], crops[], metsaradio`.

### members[] — one per family member who ran this stage
| field | meaning |
|---|---|
| `memberId`, `name`, `class` | id, first name, trackmaxx category (e.g. HAM) |
| `rank`, `of` | placing and finisher count in the category |
| `timeSec`, `behindSec` | finish time; seconds behind the category winner |
| `percentile` | 0–100, rank1→100, rankN→0 (higher = better) |
| `mRatio` | median of the runner's per-leg ratios (split/green); the runner's personal "par" pace vs the field, ≥1 |
| `cleanTimeSec` | `timeSec − mistakeLossSec` (mistake-free time) |
| `cleanRank` | counterfactual placing at `cleanTimeSec`, holding every rival's actual time fixed (for "jos-kone"); equals `rank` when `mistakeCount==0` |
| `mistakeLossSec` | seconds lost on mistake legs only (see engine below) |
| `mistakeCount` | number of mistake legs |
| `runIn` | `{sec, fieldPct}` — finish-chute (last leg) time; `fieldPct` 0–100 = % of the **whole stage field** (all classes pooled, shared chute) beaten on the run-in |
| `legs[]` | per-leg detail, ordered start→finish, length = control count + 1 |
| `rankAtByControl[]` | running position after each control (same values as `legs[].rankAt`) |
| `hillProfile` | `{up, down, flat}` uphill/downhill/flat leg performance, or **null** without Livelox climb (see below) |

### hillProfile — uphill / flat / downhill performance
`{up, down, flat}`; each class is `{pct, n}` or **null** when `n==0`, and the whole
object is **null** when the runner has no usable climb legs. A leg counts only when
`distM ≥ 100` and its climb data is non-null; it is classed by gradient
`(upM − downM)/distM`: **up** ≥ +0.06, **down** ≤ −0.06, else **flat**. `pct` is the
member's mean field-percentile on that class's legs, where a leg's percentile is
`100·(1 − (legRank − 1)/(finishers − 1))` (100 = fastest split in the category);
`n` = number of legs in the class.

### legs[] entry
| field | meaning | null? |
|---|---|---|
| `ctrl` | control label: Livelox code when available, else ordinal `"1".."N"`; finish leg = `"Maali"` (or Livelox finish code) | never |
| `legSec`, `cumSec` | leg split; cumulative time at that control | never |
| `legRank` | rank of this split within the category (1 = fastest), competition ranking | never |
| `greenSec` | fastest split in the category on this leg ("green") | never |
| `ratio` | `legSec / greenSec`, ≥1.0 | never |
| `lossSec` | `max(0, legSec − expected)`; time lost vs the runner's own par (integer) | never |
| `mistake` | boolean, this leg flagged a mistake | never |
| `rankAt` | running position at this control (1 + #runners ahead on cumulative) | never |
| `distM` | straight-line leg length (m), Livelox | **null** without Livelox |
| `upM`, `downM` | leg climb / descent (m, both positive magnitudes), DEM 25 m-smoothed, rounded to 5 m | **null** without Livelox |

**Mistake engine** (per runner): ratios = split/green; `m = median(ratios)`;
`expected = m·green`; `residual = split − expected`. A leg is a mistake when
`residual > max(2·robust_sigma, 0.20·expected)` where `robust_sigma = 1.4826·MAD`
of the residuals. `lossSec = max(0, residual)` is reported for **every** leg, but
`mistakeLossSec`/`mistakeCount` count only flagged legs.

### awards[] — one entry per award type, up to 8 (fewer if unearned)
`{id, titleFi, emoji, memberId, valueFi, evidence:{memberId, legIdx}}`. `valueFi`
is a short Finnish evidence string for display. `evidence.legIdx` indexes into
that member's `legs[]`. Ids: `kultakontrolli` (best control leg vs field, run-in
excluded), `sudenkuoppa` (biggest single loss), `tasatahti` (steadiest, lowest
ratio σ), `raketti` (most places gained in 2nd half), `vihreasormi` (most legs in
category top-10%), `sisu` (biggest in-race comeback), `makikuningas` (best pace on
a steep-up leg), `alamakikuningas` (best mean field-percentile on downhill legs;
winner needs ≥2 qualifying downhill legs, `evidence.legIdx` = their best downhill
leg). The last two are **only present when Livelox climb exists**. An award is
omitted if no valid evidence leg exists (e.g. nobody lost time → no `sudenkuoppa`).

### duels[] — `eevert-markus` (HE) and `venla-alma` (CM)
`{id, titleFi, class, memberA, memberB, cumDiff[], legsWonA, legsWonB,
totalDiffSec, decisiveLegIdx}`. `titleFi` is the duel's display name
(`Lankoduelli` for eevert-markus, `Kälyduelli` for venla-alma — brothers-/
sisters-in-law). `cumDiff[i] = A.cumSec[i] − B.cumSec[i]` (negative = A ahead),
one per control. `decisiveLegIdx` = leg with the biggest single-leg swing in the
gap. Omitted if either runner is missing that stage. Length = min of the two
runners' control counts.

### runInReport (pooled over ALL finishers in ALL classes — shared finish chute)
`{binStartSec[], counts[], xmaxSec, clippedCount, dayFastest:{sec,names[],count},
fieldMedianSec, poolSize, group[]}`. Histogram is 1-second bins `0..xmaxSec`
(`xmaxSec ≈ p99`); `counts` **includes** the `clippedCount` runners above `xmaxSec`
folded into the last bin, so `sum(counts) == poolSize`. `group[]` = family members
`{memberId, sec, fieldPct}` sorted fastest-first.

### categories — map class → `{finishers, winnerTimeSec, courseLengthM, climbM}`
Only classes the family runs. `courseLengthM`, `climbM` are **null** without Livelox.

### overall[] — cumulative standing through this stage, one per present member
`{memberId, rankable, stagesCounted[], cumTimeSec, rankAfter, of, cumBehindSec,
category}`. `rankable` is false when the member missed a stage or switched class;
then `rankAfter/of/cumBehindSec` are **null** (but `cumTimeSec` = sum of stages
run, or null if none). When rankable, the pool is runners who finished **every**
stage 1..N in that same category.

### crops[] — `{id, file, memberId, legLabel, kind, ctrlFrom, ctrlTo, pxFrom, pxTo, widthPx, heightPx}`
`kind ∈ {hero, villain, duelHE, duelCM}`; `file` is repo-relative (e.g.
`crops/s2_hero_viivi_L3.webp`), webp ≤150 KB. The image **already has the course
overprint drawn** — two ISOM-purple control circles (start triangle when
`ctrlFrom` is the start), the straight leg line between them, and purple code
labels — windowed to the leg (min ~350 m window so short legs don't over-zoom).
The UI does **not** need to annotate; if it wants to, `pxFrom`/`pxTo` are the two
controls' `[x, y]` pixel positions **within the saved image** and `widthPx`/
`heightPx` its dimensions. **`[]` until Livelox maps for the relevant class
exist** (stage 1 CM has no map, so stage 1 emits only villain + duelHE).

### metsaradio — `{paragraphsFi: []}`; written by the lead, left empty here.

---

## data/forecast.json
`{asOfStage: 3, members:{id:{p05,p25,p50,p75,p95, pTop10, pBetterThanCurrent,
trend, catSize}}}`. Monte Carlo (20 000 sims): each remaining stage's percentile
~ Normal(mean, sd) of the member's observed stage percentiles (sd floor 5pp);
final standing = mean percentile over 6 stages mapped to a rank in `catSize`.
`p05..p95` are **final overall rank** quantiles (lower = better). `pTop10` =
P(top-10% of the category). `pBetterThanCurrent` = P(final standing percentile >
current standing percentile); **null** if no current standing. `trend ∈
{nouseva, laskeva, tasainen}` from the slope of stage percentiles.

## data/badges.json
`{memberId:[{id, titleFi, emoji, stage, descFi}]}`, accumulating. Per-stage:
`puhdas` (0 mistakes), `comeback` (≥8 places gained in-race), `perheykkonen`
(best family placement that stage), `salamavauhti` (day's fastest run-in),
`reipas` (kid finished — kids only). Cross-stage (stage 3): `rautanaula` (all
stages finished), `kolmenputki` (3× top-30%), `makikuningas2` (2× hill award —
**Livelox-dependent, may be absent**). The same `id` can repeat with different
`stage`; group by `id`+`stage` in the UI.
