"""Emit Jekyll-consumable content from the interim derived-metrics data:
Markdown-with-YAML-frontmatter files (districts/seats/candidates/towns/
parties) into site/_*, per docs/PLAN.md §5/§7 — a collection of front-
matter files rendered by a single Liquid template per type, rather than a
separate Python/Node HTML generator, since Jekyll (via GitHub Actions, not
the Pages-native build) handles this natively.

Two-tier district/seat model (matches docs/PLAN.md §7's original design,
completed here for the multi-year backfill):

- **District** (`/district/...`): one page per (chamber, district_name,
  vintage), accumulating every election year available for that vintage
  (a vintage spans several cycles, e.g. 2022-present covers both 2022 and
  2024). District *identity* is scoped to one vintage because boundaries
  and even names can change across redistricting — a "4th Middlesex" in
  one vintage isn't guaranteed to be the same geography as a same-named
  district in another.
- **Seat** (`/seat/...`): the *current*-vintage's district record, plus a
  `history` list walking backward through build.crosswalks' seat_lineage
  (best-area-overlap predecessor, however many vintage hops back that
  goes) to the districts it evolved from. This is the "persistent" view a
  user browsing by district naturally wants — "who represents this area
  today, and what was here before" — without needing to already know
  which vintage's naming a prior election used.

Both are driven by discovering *which* years' data actually exist on disk
(via each vintage's `{chamber}_{vintage}_{year}_lean.parquet` files) rather
than a hardcoded year list — running the pipeline for more years and
re-running this script is enough to pick them up, no code change needed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import click
import numpy as np
import pandas as pd
import yaml

from ma_politics.build import campaign_finance_match, demographics_match
from ma_politics.util.names import normalize_town_name

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _clean_str(value) -> str | None:
    """PD43+ occasionally has no parseable party for a candidate (e.g. a
    losing write-in whose detail page carries no recognized party class —
    a real, pre-existing data gap, not a fetch bug; see fetch.pd43). pandas
    represents that as float NaN even in an otherwise-string column, and
    yaml.safe_dump renders float NaN as the YAML literal `.nan`, which
    Ruby's JSON generator (Jekyll's `jsonify` filter) then rejects outright
    ("NaN not allowed in JSON") — found by running an actual `jekyll
    build`, not caught by the Python side alone. Coerce to a real Python
    None so it serializes as YAML null / JSON null instead."""
    return None if pd.isna(value) else value


def candidate_slug(pd43_slug: str) -> str:
    """PD43+'s own candidate slug (e.g. "Paul-W-Mark", from their
    /candidates/view/ URLs) lowercased for consistency with this site's
    other (all-lowercase) slugs. Used as the candidate's durable identity
    instead of re-deriving one from their name, which risks collisions
    between different candidates with similar names."""
    return pd43_slug.lower()


def district_slug(chamber: str, district_name: str, vintage: str) -> str:
    return f"{chamber}-{slugify(district_name)}-{slugify(vintage)}"


def district_url(chamber: str, district_name: str, vintage: str) -> str:
    return f"/district/{district_slug(chamber, district_name, vintage)}/"


def seat_url(chamber: str, district_name: str) -> str:
    return f"/seat/{chamber}-{slugify(district_name)}/"


def discover_years(chamber: str, vintage: str, derived_dir: Path) -> list[int]:
    """Which election years actually have derived-metrics output for this
    (chamber, vintage) — from the lean file's own name, which is year-
    scoped (see build.derived_metrics: lean is recomputed against a
    different statewide baseline race every cycle, so a vintage spanning
    several years needs one lean file per year)."""
    pattern = re.compile(rf"^{re.escape(chamber)}_{re.escape(vintage)}_(\d{{4}})_lean\.parquet$")
    years = []
    for p in derived_dir.glob(f"{chamber}_{vintage}_*_lean.parquet"):
        m = pattern.match(p.name)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _candidate_list(district_war: pd.DataFrame) -> list[dict]:
    return [
        {
            "name": row["candidate_name"],
            "slug": candidate_slug(row["candidate_slug"]),
            "party": _clean_str(row["party"]),
            "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
            "winner": bool(row["winner"]),
            "actual_two_party_share": (
                round(float(row["actual_two_party_share"]), 4) if pd.notna(row["actual_two_party_share"]) else None
            ),
            "war": round(float(row["war"]), 4) if pd.notna(row["war"]) else None,
            # war_v2, incumbency_adjustment, expected_two_party_share(_v2)
            # are added afterward by apply_war_v2, once is_incumbent (also
            # set later, in build_district_records) and the globally-fit
            # incumbency effect are both available — not present yet on
            # the dict this function returns.
        }
        for _, row in district_war.sort_values("votes", ascending=False).iterrows()
    ]


def _baseline_office_for_year(year: int) -> str:
    """MA governor and president elections alternate on a fixed 4-year
    cycle covering every even year this site backfills (2002-2024):
    year % 4 == 2 -> governor (2002, 2006, ..., 2022), == 0 -> president
    (2004, 2008, ..., 2024) — the same convention build.derived_metrics'
    own --baseline-office CLI flag is invoked with per year, restated here
    as a rule rather than re-reading it from anywhere, since nothing
    downstream of the fetch actually records which office was used."""
    return "governor" if year % 4 == 2 else "president"


def compute_statewide_tide_by_year(baseline_dir: Path) -> dict[int, float]:
    """The *unapportioned* statewide two-party Democratic share on each
    year's baseline race (Governor/President) — a genuinely different
    number from lean_dem_share, which is that same race's result
    apportioned down to one district by town-area overlap. Gelman & King's
    normal-vote-plus-national-tide decomposition (already cited in
    methodology.md) separates a district's long-run partisanship from a
    given year's overall national/state mood; lean_dem_share alone
    conflates the two, since it's already specific to one race in one
    year. This is the piece that lets a regression tell them apart.

    Summed from the baseline race's *town-level* results, not read
    directly off `{office}_results.parquet`'s own vote totals — found by
    checking real output before trusting it: that results table reliably
    carries candidate name/party for every year, but its `votes` column is
    NaN for the statewide total in several older years (2002-2014), a
    real, pre-existing gap in what PD43+'s race-detail page exposes for
    the fetcher to capture, not a bug in this fetch. The town-level CSV
    export doesn't have that gap, so this sums across every town instead —
    reusing derived_metrics.resolve_candidate_column to handle the same
    "/" vs "and" joint-ticket naming inconsistency documented there,
    narrowed to columns with real data for this specific election_id for
    the same reason that function's own docstring requires it (an
    unfiltered search over every year's columns can silently match a
    same-named column from a different year)."""
    from ma_politics.build.derived_metrics import resolve_candidate_column

    tide_by_year: dict[int, float] = {}
    for office in ("governor", "president"):
        races_path = baseline_dir / f"{office}_races.parquet"
        results_path = baseline_dir / f"{office}_results.parquet"
        town_path = baseline_dir / f"{office}_town_results.parquet"
        if not (races_path.exists() and results_path.exists() and town_path.exists()):
            continue
        races = pd.read_parquet(races_path)
        results = pd.read_parquet(results_path)
        town_results = pd.read_parquet(town_path)
        general = races[races["stage"] == "general"]
        for _, race in general.iterrows():
            year = int(race["year"])
            if _baseline_office_for_year(year) != office:
                continue
            election_id = race["election_id"]
            race_results = results[results["election_id"] == election_id]
            dem_rows = race_results[race_results["party"] == "Democratic"]
            rep_rows = race_results[race_results["party"] == "Republican"]
            if dem_rows.empty or rep_rows.empty:
                logger.warning("No Democratic/Republican candidate found for %s %d — skipping tide", office, year)
                continue
            dem_name = dem_rows.iloc[0]["candidate_name"]
            rep_name = rep_rows.iloc[0]["candidate_name"]
            town = town_results[town_results["election_id"] == election_id]
            town_columns = [c for c in town.columns if c not in ("election_id", "town") and town[c].fillna(0).sum() > 0]
            try:
                dem_col = resolve_candidate_column(dem_name, town_columns)
                rep_col = resolve_candidate_column(rep_name, town_columns)
            except ValueError:
                logger.warning("Could not resolve %s/%s town-result columns for %s %d", dem_name, rep_name, office, year)
                continue
            dem = float(town[dem_col].fillna(0).sum())
            rep = float(town[rep_col].fillna(0).sum())
            two_party = dem + rep
            if two_party > 0:
                tide_by_year[year] = dem / two_party
    return tide_by_year


INCUMBENT_TERM_BUCKETS = ("incumbent_1", "incumbent_2", "incumbent_3plus")


def _incumbent_term_dummies(terms: int) -> dict[str, float]:
    return {
        "incumbent_1": 1.0 if terms == 1 else 0.0,
        "incumbent_2": 1.0 if terms == 2 else 0.0,
        "incumbent_3plus": 1.0 if terms >= 3 else 0.0,
    }


# Weakly informative, regularizing priors for every coefficient this
# module fits, in the coefficient's own native units (a Democratic share
# of the two-party vote, same scale as the response). Independent of the
# noise variance (semi-conjugate, not the classic prior-scaled-by-sigma^2
# convention) specifically so each prior can be set directly from
# substantive belief about vote-share regressions rather than through an
# assumed sigma. `intercept`/`own_lean`/`own_tide` are centered on the
# theoretically-expected values (a generic candidate splits the vote
# evenly; lean alone should track actual share about 1:1 if it were a
# perfect predictor; no prior sign on tide's residual effect once lean is
# already in the model). The incumbency buckets share one modest,
# positive-leaning prior (grounded in the same incumbency-advantage
# literature methodology.md already cites, not fit from this project's
# own preliminary numbers) with real shrinkage (sd 0.08) — useful given
# how unevenly sized the three buckets are (far fewer 3+-term incumbents
# than 1-term ones). `log_raised`'s prior is scaled for a variable that
# itself spans roughly log($1k) to log($1M) (~7-14). `hispanic_pct` and
# `voting_age_pct` are proportions like `bachelors_pct`, so they share its
# prior. `income_10k` is median household income in $10,000 units (so a
# district going from $70k to $170k median income is a 10-unit swing) —
# its prior is scaled down from `bachelors_pct`'s the same way `log_raised`
# was scaled down from `own_lean`'s: a $10k step is a much finer-grained
# unit than a full 0-to-1 population share, so the same substantive belief
# ("this shouldn't move vote share by double-digit points on its own")
# implies a much smaller per-unit coefficient.
#
# Deliberately no interaction terms (e.g. a demographic field × tide, to
# ask "does this district trait change how much it swings with the
# national mood"): an interaction with tide is only as identified as the
# number of distinct tide values in the fit, i.e. distinct election
# years, and every term here still has too few to trust one — demographics
# only covers the current vintage's 2 elections (2022, 2024); even
# finance's log_raised, with a real 12 years of backfill, has no specific
# hypothesis motivating one yet. An earlier version of this project fit
# `bachelors_pct_x_tide` anyway (on exactly those 2 years), which turned
# out to be a cherry-picked, thinly-identified special case rather than a
# principled choice — chosen because "diploma divide" is the term the
# realignment literature discusses, not because the data supported it
# better than, say, testing every continuous covariate the same way. If a
# term earns an interaction in the future, the honest bar is a predictor
# with enough distinct years to show real variation in the interaction
# itself (a rule of thumb: 4+), not just "we thought to try it."
_COEFFICIENT_PRIORS: dict[str, tuple[float, float]] = {
    "intercept": (0.5, 0.2),
    "own_lean": (1.0, 0.4),
    "own_tide": (0.0, 0.4),
    "incumbent_1": (0.05, 0.08),
    "incumbent_2": (0.05, 0.08),
    "incumbent_3plus": (0.05, 0.08),
    "bachelors_pct": (0.0, 0.3),
    "hispanic_pct": (0.0, 0.3),
    "voting_age_pct": (0.0, 0.3),
    "income_10k": (0.0, 0.02),
    "log_raised": (0.0, 0.02),
}


def _bayesian_linear_regression(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: list[str],
    prior_sigma_shape: float = 3.0,
    prior_sigma_scale: float = 0.03,
    n_samples: int = 4000,
    n_burnin: int = 1000,
    seed: int = 0,
) -> dict:
    """Bayesian linear regression via Gibbs sampling, fit fresh on every
    pipeline run — deliberately not OLS/plain least squares. Every model
    this function is used for (see fit_war_v2_core and the two
    fit_war_v3_* diagnostics below) has at least one term OLS handles
    badly: own_lean and own_tide come from the same underlying baseline
    race just apportioned differently, so they're correlated; the
    incumbency buckets are unevenly sized; and the v3 extensions fit on
    samples small enough (a couple hundred rows, one covering just two
    election years) that an unconstrained least-squares estimate would be
    little more than noise dressed up as a coefficient. A weakly
    informative Gaussian prior on each coefficient (`_COEFFICIENT_PRIORS`)
    regularizes exactly those cases — it pulls a coefficient toward its
    prior in proportion to how little the data actually constrains it —
    and the model reports a full posterior (mean, SD, 95% credible
    interval from the actual sampled draws), not just a point estimate.

    No PyMC/Stan dependency (this pipeline deliberately keeps a small,
    curated dependency list — see pyproject.toml): a linear-Gaussian
    model's Gibbs sampler has closed-form conditionals for both blocks
    (beta | sigma^2 is multivariate normal; sigma^2 | beta is inverse-
    gamma), so a plain numpy implementation is exact MCMC, not an
    approximation of one, and fast enough — a few thousand iterations over
    at most a few thousand rows and under ten parameters — to run inline
    on every build rather than needing to be precomputed offline.

    A known simplification, not fixed here: the likelihood is Gaussian on
    a proportion bounded in [0, 1] (a Beta or logit-normal likelihood
    would respect that boundary properly), which is fine for races that
    aren't hugging 0% or 100% but is an approximation worth naming, same
    spirit as this project's other documented simplifications."""
    rng = np.random.default_rng(seed)
    n, k = X.shape
    prior_mean = np.array([_COEFFICIENT_PRIORS[name][0] for name in feature_names])
    prior_sd = np.array([_COEFFICIENT_PRIORS[name][1] for name in feature_names])
    v0_inv = np.diag(1.0 / (prior_sd**2))
    xtx = X.T @ X
    xty = X.T @ y

    beta = np.linalg.lstsq(X, y, rcond=None)[0]  # start the chain near the least-squares fit
    sigma2 = float(np.var(y - X @ beta))

    beta_samples = np.empty((n_samples, k))
    sigma_samples = np.empty(n_samples)
    for i in range(n_samples + n_burnin):
        vn_inv = v0_inv + xtx / sigma2
        vn = np.linalg.inv(vn_inv)
        mn = vn @ (v0_inv @ prior_mean + xty / sigma2)
        beta = rng.multivariate_normal(mn, vn)

        resid = y - X @ beta
        shape_n = prior_sigma_shape + n / 2
        scale_n = prior_sigma_scale + 0.5 * float(resid @ resid)
        sigma2 = 1.0 / rng.gamma(shape_n, 1.0 / scale_n)

        if i >= n_burnin:
            j = i - n_burnin
            beta_samples[j] = beta
            sigma_samples[j] = np.sqrt(sigma2)

    posterior_mean = beta_samples.mean(axis=0)
    fitted = X @ posterior_mean
    resid = y - fitted
    rss = float(np.sum(resid**2))
    tss = float(np.sum((y - y.mean()) ** 2))

    # Standardized ("beta weight") coefficients, alongside the native-unit
    # ones above: each posterior draw scaled by that predictor's own SD in
    # the actual fitted sample (population SD, not sample SD — this is a
    # descriptive rescaling of the sample the model saw, not itself a
    # further inference), turning "share points per unit of own_lean" and
    # "share points per log-dollar of fundraising" into one common
    # unit — "share points per 1 SD of this predictor" — genuinely
    # comparable across continuous slopes (own_lean, log_raised) and 0/1
    # incumbency dummies alike. The intercept has no such rescaling (its
    # "predictor" is a constant column of 1s, SD 0) and is left out
    # entirely (None) rather than reported as a misleading zero.
    predictor_sd = X.std(axis=0, ddof=0)

    coefficients = {}
    for idx, name in enumerate(feature_names):
        draws = beta_samples[:, idx]
        is_intercept = name == "intercept"
        sd = float(predictor_sd[idx])
        standardized = None if is_intercept else draws * sd
        coefficients[name] = {
            "prior_mean": round(float(prior_mean[idx]), 4),
            "prior_sd": round(float(prior_sd[idx]), 4),
            "posterior_mean": round(float(draws.mean()), 4),
            "posterior_sd": round(float(draws.std()), 4),
            "ci_95_low": round(float(np.percentile(draws, 2.5)), 4),
            "ci_95_high": round(float(np.percentile(draws, 97.5)), 4),
            "predictor_sd": None if is_intercept else round(sd, 4),
            "standardized_mean": None if is_intercept else round(float(standardized.mean()), 4),
            "standardized_sd": None if is_intercept else round(float(standardized.std()), 4),
            "standardized_ci_95_low": None if is_intercept else round(float(np.percentile(standardized, 2.5)), 4),
            "standardized_ci_95_high": None if is_intercept else round(float(np.percentile(standardized, 97.5)), 4),
        }

    return {
        "n": n,
        "r_squared": round(1 - rss / tss, 4) if tss > 0 else None,
        "posterior_sigma_mean": round(float(sigma_samples.mean()), 4),
        "coefficients": coefficients,
    }


def fit_war_v2_core(district_records_by_vintage: dict[str, list[dict]], tide_by_year: dict[int, float]) -> dict:
    """WAR v2's expected-share model, upgraded from a single incumbency
    coefficient to a real Bayesian multiple regression — same
    "fundamentals" idea Split Ticket and the Gelman & King literature use
    (see methodology.md), fit as this project's own weighting rather than
    copied from theirs:

        own_party_share ~ intercept + own_lean + own_tide
                           + incumbent_1term + incumbent_2term + incumbent_3plus_term

    "own_party_*" means the value is already flipped to that candidate's
    own party's perspective (own_lean = lean_dem_share for a Democrat,
    1 - lean_dem_share for a Republican; same for tide) — the same
    symmetry compute_war() already uses, so one pooled fit covers both
    parties instead of needing two.

    own_tide (compute_statewide_tide_by_year) is the statewide,
    unapportioned two-party share on that year's baseline race — distinct
    from own_lean, which is that same race apportioned down to this one
    district. Including both lets the fit separate a district's own
    persistent partisanship from a given cycle's overall national/state
    mood, instead of lean alone conflating them.

    Incumbency is three dummies (1 / 2 / 3+ consecutive terms already
    served — see build_district_records' incumbent_terms) against a
    non-incumbent baseline, rather than v1's single binary term, so the
    fit can show whether a second or third term brings a bigger or
    smaller edge than the first instead of assuming they're identical.

    Fit via _bayesian_linear_regression (Gibbs sampling, weakly
    informative priors — see its docstring), pooled across House and
    Senate for the same reason the previous single-coefficient version
    was: both chambers land close enough on the underlying incumbency
    effect that a separate fit isn't justified by the data. Contested
    major-party races only, across the full 2002-2024 backfill —
    uncontested races are excluded, per the methodology page's WAR v1
    limitation (a mechanical 100% share isn't a clean training signal)."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                tide = tide_by_year.get(entry["year"])
                if tide is None:
                    continue
                for c in entry["candidates"]:
                    if c["war"] is None or c["party"] not in ("Democratic", "Republican"):
                        continue
                    is_dem = c["party"] == "Democratic"
                    own_lean = entry["lean_dem_share"] if is_dem else 1 - entry["lean_dem_share"]
                    own_tide = tide if is_dem else 1 - tide
                    row = {"own_share": c["actual_two_party_share"], "own_lean": own_lean, "own_tide": own_tide}
                    row.update(_incumbent_term_dummies(c.get("incumbent_terms", 0)))
                    rows.append(row)

    df = pd.DataFrame(rows)
    feature_names = ["intercept", "own_lean", "own_tide", *INCUMBENT_TERM_BUCKETS]
    x = np.column_stack(
        [np.ones(len(df)), df["own_lean"].to_numpy(), df["own_tide"].to_numpy()]
        + [df[b].to_numpy() for b in INCUMBENT_TERM_BUCKETS]
    )
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["n_incumbent_1"] = int(df["incumbent_1"].sum())
    fit["n_incumbent_2"] = int(df["incumbent_2"].sum())
    fit["n_incumbent_3plus"] = int(df["incumbent_3plus"].sum())
    fit["n_non_incumbent"] = int(
        len(df) - df["incumbent_1"].sum() - df["incumbent_2"].sum() - df["incumbent_3plus"].sum()
    )
    return fit


def apply_war_v2(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    fit: dict,
) -> None:
    """Second pass over already-built district records (mutates candidate
    dicts in place): applies fit_war_v2_core's posterior-mean coefficients
    (the Bayes-optimal point estimate under squared-error loss) to every
    candidate-race, major and minor party alike (war_v2 stays None for
    non-major-party candidates, same as v1). Decomposes the fitted
    expected share into its own regression terms — intercept, lean
    component, tide component, incumbency adjustment, each already in
    this candidate's own-party perspective and summing exactly to
    expected_two_party_share_v2 — rather than just the final number, so
    the district/seat page attribution chart can show what the actual
    fitted model attributes the expected share to, not a hand-picked
    approximation of it.

    war_v2 itself is left null for an uncontested race: an unopposed
    candidate's ~100% actual share isn't a meaningful comparison to the
    model's expectation (it's mechanically inflated, not earned against
    real competition — same reasoning already documented for WAR v1's own
    uncontested-race limitation). expected_two_party_share_v2 and every
    *_component stay defined regardless, since none of them depend on the
    actual outcome — they're this project's "baseline expectation" metric,
    the number that's still meaningful when WAR itself isn't."""
    coefs = fit["coefficients"]
    b0 = coefs["intercept"]["posterior_mean"]
    b_lean = coefs["own_lean"]["posterior_mean"]
    b_tide = coefs["own_tide"]["posterior_mean"]
    b_terms = {b: coefs[b]["posterior_mean"] for b in INCUMBENT_TERM_BUCKETS}

    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                tide = tide_by_year.get(entry["year"])
                for c in entry["candidates"]:
                    if c["war"] is None or tide is None:
                        c.update(
                            own_lean=None,
                            own_tide=None,
                            war_v2=None,
                            war_v2_sd=None,
                            incumbency_adjustment=None,
                            incumbency_adjustment_sd=None,
                            intercept_component=None,
                            intercept_component_sd=None,
                            lean_component=None,
                            lean_component_sd=None,
                            tide_component=None,
                            tide_component_sd=None,
                            expected_two_party_share=None,
                            expected_two_party_share_v2=None,
                        )
                        continue
                    is_dem = c["party"] == "Democratic"
                    own_lean = entry["lean_dem_share"] if is_dem else 1 - entry["lean_dem_share"]
                    own_tide = tide if is_dem else 1 - tide
                    dummies = _incumbent_term_dummies(c.get("incumbent_terms", 0))
                    incumbency_component = sum(b_terms[b] * dummies[b] for b in INCUMBENT_TERM_BUCKETS)
                    lean_component = b_lean * own_lean
                    tide_component = b_tide * own_tide
                    expected_v2 = b0 + lean_component + tide_component + incumbency_component
                    expected_v1 = round(c["actual_two_party_share"] - c["war"], 4)
                    # Approximate per-component uncertainty via the delta
                    # method: component_sd ~= |covariate| * coefficient's own
                    # posterior_sd. A known simplification (same spirit as
                    # this module's other documented ones) — it treats each
                    # coefficient's posterior as independent of the others,
                    # ignoring their actual posterior covariance, rather than
                    # propagating a full joint posterior (which would need
                    # exporting thousands of raw draws per race, a much
                    # heavier lift for a diagnostic uncertainty band). The
                    # active incumbency bucket (if any) contributes its own
                    # coefficient's posterior_sd directly, since exactly one
                    # dummy is 1 at a time. war_v2_sd reuses the fit's
                    # residual noise SD (posterior_sigma_mean) as a constant
                    # proxy for "how much of WAR v2 itself is typical
                    # unexplained variation," not a delta-method quantity —
                    # a different but equally honest way to report how much
                    # the leftover residual should be trusted.
                    active_bucket = next((b for b in INCUMBENT_TERM_BUCKETS if dummies[b] == 1.0), None)
                    incumbency_component_sd = coefs[active_bucket]["posterior_sd"] if active_bucket else 0.0
                    c.update(
                        own_lean=round(own_lean, 4),
                        own_tide=round(own_tide, 4),
                        war_v2=(
                            None if entry["is_uncontested"]
                            else round(c["actual_two_party_share"] - expected_v2, 4)
                        ),
                        war_v2_sd=None if entry["is_uncontested"] else round(fit["posterior_sigma_mean"], 4),
                        incumbency_adjustment=round(incumbency_component, 4),
                        incumbency_adjustment_sd=round(incumbency_component_sd, 4),
                        intercept_component=round(b0, 4),
                        intercept_component_sd=coefs["intercept"]["posterior_sd"],
                        lean_component=round(lean_component, 4),
                        lean_component_sd=round(abs(own_lean) * coefs["own_lean"]["posterior_sd"], 4),
                        tide_component=round(tide_component, 4),
                        tide_component_sd=round(abs(own_tide) * coefs["own_tide"]["posterior_sd"], 4),
                        expected_two_party_share=expected_v1,
                        expected_two_party_share_v2=round(expected_v2, 4),
                    )


def build_war_v2_fit_sample(district_records_by_vintage: dict[str, list[dict]]) -> list[dict]:
    """Every contested major-party candidate-race's actual vs. WAR v2
    expected share, party, and year — the exact same rows fit_war_v2_core
    trained on (must be called after apply_war_v2, so
    expected_two_party_share_v2 is populated). Exists purely for the
    methodology page's "actual vs. expected" scatter chart, which needs a
    full sample to plot rather than the summary statistics war_v2.yml
    already carries — written to site/_data/war_v2_fit_sample.yml so the
    page can embed it directly via Jekyll's site.data, the same pattern
    already used for the fitted coefficients themselves."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                for c in entry["candidates"]:
                    if c.get("war_v2") is None:
                        continue
                    rows.append(
                        {
                            "actual": c["actual_two_party_share"],
                            "expected": c["expected_two_party_share_v2"],
                            "party": c["party"],
                            "year": entry["year"],
                        }
                    )
    return rows


_DEMOGRAPHICS_CORE_COVARIATES = ("bachelors_pct",)
_DEMOGRAPHICS_FULL_COVARIATES = ("bachelors_pct", "hispanic_pct", "voting_age_pct", "income_10k")


def _demographic_covariates(demographics: dict | None) -> dict[str, float]:
    """Computes whatever demographic covariates a district's own Census
    match actually supports — never all-or-nothing the way the original
    single-tier version of this fit was, which silently dropped a district
    entirely if it was missing even one field. Real, live gap this closes:
    15 of 200 current-vintage districts (all Senate seats) have a PL 94-171
    name-matching failure (see demographics_match.py) but DO have ACS
    income/education data — those districts can still support
    `bachelors_pct` (falling back to ACS's own `total_population_acs` as
    the denominator when PL 94-171's `total_population` is missing) even
    though `hispanic_pct`/`voting_age_pct` can't be computed for them
    (both need PL 94-171's population specifically — its own numerator and
    denominator have to come from the same table, not mixed across ACS and
    PL 94-171, which use different survey methodologies and reference
    years). `income_10k` is median household income in $10,000 units."""
    if not demographics:
        return {}
    covariates: dict[str, float] = {}
    pop = demographics.get("total_population") or demographics.get("total_population_acs")
    if pop and demographics.get("bachelors_degree_count") is not None:
        covariates["bachelors_pct"] = demographics["bachelors_degree_count"] / pop
    pl_pop = demographics.get("total_population")
    if pl_pop:
        if demographics.get("hispanic_or_latino_population") is not None:
            covariates["hispanic_pct"] = demographics["hispanic_or_latino_population"] / pl_pop
        if demographics.get("voting_age_population") is not None:
            covariates["voting_age_pct"] = demographics["voting_age_population"] / pl_pop
    if demographics.get("median_household_income") is not None:
        covariates["income_10k"] = demographics["median_household_income"] / 10000
    return covariates


def _build_demographics_rows(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    current_vintage: str,
    required_covariates: tuple[str, ...],
) -> list[dict]:
    """Shared row-builder for both demographics fit tiers below — only
    difference between the core and full fits is which covariates a
    district needs to have to contribute a row at all."""
    rows = []
    for d in district_records_by_vintage.get(current_vintage, []):
        covariates = _demographic_covariates(d.get("demographics"))
        if not all(k in covariates for k in required_covariates):
            continue
        for entry in d["results_by_year"]:
            if entry["is_uncontested"]:
                continue
            tide = tide_by_year.get(entry["year"])
            if tide is None:
                continue
            for c in entry["candidates"]:
                if c["war"] is None or c["party"] not in ("Democratic", "Republican"):
                    continue
                is_dem = c["party"] == "Democratic"
                own_lean = entry["lean_dem_share"] if is_dem else 1 - entry["lean_dem_share"]
                own_tide = tide if is_dem else 1 - tide
                row = {
                    "own_share": c["actual_two_party_share"],
                    "own_lean": own_lean,
                    "own_tide": own_tide,
                    "bachelors_pct": covariates["bachelors_pct"],
                    "year": entry["year"],
                }
                if "hispanic_pct" in required_covariates:
                    row["hispanic_pct"] = covariates["hispanic_pct"]
                    row["voting_age_pct"] = covariates["voting_age_pct"]
                    row["income_10k"] = covariates["income_10k"]
                row.update(_incumbent_term_dummies(c.get("incumbent_terms", 0)))
                rows.append(row)
    return rows


def fit_war_v3_demographics_core(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    current_vintage: str,
) -> dict | None:
    """A diagnostic extension of the WAR v2 core model (fit_war_v2_core),
    adding district demographics. Deliberately NOT threaded into every
    candidate's war_v2 field the way the core model is: demographics
    (Census PL 94-171/ACS, see demographics_match.py) only exist for the
    current, 2022-present redistricting vintage, which as of this backfill
    has exactly two election years on record (2022, 2024) — not remotely
    enough to also fit an interaction with tide (see the module-level
    comment above _COEFFICIENT_PRIORS for why this deliberately doesn't
    try), so this stays a main-effects-only fit until more cycles land.

    This is the "core" tier — bachelor's-degree-or-higher share of
    population alone, the "diploma divide" variable most associated with
    recent-era partisan realignment in the real political-science
    literature — used both as its own labeled diagnostic and as the
    fallback fit for districts whose PL 94-171 match failed (see
    _demographic_covariates), so apply_war_v3_demographics can still give
    them *something* rather than nothing. See fit_war_v3_demographics_full
    for the richer tier. Returns None if too few districts qualify."""
    rows = _build_demographics_rows(district_records_by_vintage, tide_by_year, current_vintage, _DEMOGRAPHICS_CORE_COVARIATES)
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows)
    feature_names = ["intercept", "own_lean", "own_tide", *INCUMBENT_TERM_BUCKETS, "bachelors_pct"]
    x = np.column_stack(
        [np.ones(len(df)), df["own_lean"].to_numpy(), df["own_tide"].to_numpy()]
        + [df[b].to_numpy() for b in INCUMBENT_TERM_BUCKETS]
        + [df["bachelors_pct"].to_numpy()]
    )
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["n_distinct_years"] = int(df["year"].nunique())
    return fit


def fit_war_v3_demographics_full(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    current_vintage: str,
) -> dict | None:
    """The richer tier of the demographics diagnostic: fit_war_v3_demographics_core's
    bachelors_pct terms plus Hispanic-or-Latino population share, voting-age
    population share, and median household income (in $10,000 units) —
    the remaining Census fields this project already fetches (see
    fetch.demographics) but had never threaded into WAR v3, even though
    Hispanic/Latino population and income are both already surfaced in the
    site's own Demographics section. Restricted to districts with a real
    PL 94-171 match (hispanic_pct/voting_age_pct need it, see
    _demographic_covariates) — a strictly narrower sample than the core
    tier's, which is exactly why apply_war_v3_demographics falls back to
    the core fit rather than this one for districts that don't qualify,
    instead of leaving them out of WAR v3 entirely. Returns None if too
    few districts qualify."""
    rows = _build_demographics_rows(district_records_by_vintage, tide_by_year, current_vintage, _DEMOGRAPHICS_FULL_COVARIATES)
    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows)
    feature_names = [
        "intercept",
        "own_lean",
        "own_tide",
        *INCUMBENT_TERM_BUCKETS,
        "bachelors_pct",
        "hispanic_pct",
        "voting_age_pct",
        "income_10k",
    ]
    x = np.column_stack(
        [np.ones(len(df)), df["own_lean"].to_numpy(), df["own_tide"].to_numpy()]
        + [df[b].to_numpy() for b in INCUMBENT_TERM_BUCKETS]
        + [
            df["bachelors_pct"].to_numpy(),
            df["hispanic_pct"].to_numpy(),
            df["voting_age_pct"].to_numpy(),
            df["income_10k"].to_numpy(),
        ]
    )
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["n_distinct_years"] = int(df["year"].nunique())
    # income_10k has the same issue as log_raised below: no meaningful
    # $0-income baseline, so it's centered on this fit's own mean rather
    # than compared to zero.
    fit["reference_values"] = {"income_10k": float(df["income_10k"].mean())}
    return fit


def fit_war_v3_finance(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    finance_by_slug: dict[str, dict],
) -> dict | None:
    """A second diagnostic extension of the WAR v2 core model, adding
    campaign finance — a candidate's own OCPF total raised that cycle,
    log-transformed (fundraising totals are heavily right-skewed: a few
    candidates raise vastly more than most). OCPF's bulk export now
    covers the full 2002-2024 range this project backfills elsewhere (see
    fetch.campaign_finance) — no longer restricted to a single year — so
    own_tide is back in the model, the same as the core fit above: with
    real cross-year variation, it's no longer collinear with the
    intercept the way it was when this was fit on 2022 alone. Restricted
    to candidate-races campaign_finance_match actually matched to an OCPF
    filer (a best-effort name/district/chamber match, not every candidate
    — see its own docstring). Still reported as a methodology-page
    diagnostic only, not threaded into every candidate's WAR the way v2
    is: even with the full backfill, only a fraction of candidate-races
    have a confident OCPF match, so folding it into the site's main WAR
    number would still leave most races undefined."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                tide = tide_by_year.get(entry["year"])
                if tide is None:
                    continue
                for c in entry["candidates"]:
                    if c["war"] is None or c["party"] not in ("Democratic", "Republican"):
                        continue
                    finance = finance_by_slug.get(c["slug"])
                    raised = finance["by_year"].get(entry["year"], {}).get("total_raised") if finance else None
                    if raised is None:
                        continue
                    is_dem = c["party"] == "Democratic"
                    own_lean = entry["lean_dem_share"] if is_dem else 1 - entry["lean_dem_share"]
                    own_tide = tide if is_dem else 1 - tide
                    row = {
                        "own_share": c["actual_two_party_share"],
                        "own_lean": own_lean,
                        "own_tide": own_tide,
                        "log_raised": float(np.log1p(raised)),
                        "year": entry["year"],
                    }
                    row.update(_incumbent_term_dummies(c.get("incumbent_terms", 0)))
                    rows.append(row)

    if len(rows) < 20:
        return None
    df = pd.DataFrame(rows)
    feature_names = ["intercept", "own_lean", "own_tide", *INCUMBENT_TERM_BUCKETS, "log_raised"]
    x = np.column_stack(
        [np.ones(len(df)), df["own_lean"].to_numpy(), df["own_tide"].to_numpy()]
        + [df[b].to_numpy() for b in INCUMBENT_TERM_BUCKETS]
        + [df["log_raised"].to_numpy()]
    )
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["n_distinct_years"] = int(df["year"].nunique())
    # log_raised has no natural zero-effect anchor the way a lean/tide/
    # population-share fraction does (0 log-dollars raised isn't a real
    # candidate) — its attribution-chart contribution is centered on this
    # fitted sample's own mean, not the raw value, so the fundraising bar
    # reads as "how this candidate's fundraising compares to a typical
    # candidate's" rather than an arbitrary distance from an impossible
    # $0 baseline. See apply_war_v3_finance for where this gets used.
    fit["reference_values"] = {"log_raised": float(df["log_raised"].mean())}
    return fit


def apply_war_v3_demographics(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    current_vintage: str,
    core_fit: dict | None,
    full_fit: dict | None,
) -> None:
    """Mirrors apply_war_v2, but for the two-tier demographics diagnostic
    (fit_war_v3_demographics_core/_full) — mutates the SAME current-vintage
    candidate dicts apply_war_v2 already updated, adding a distinctly-
    suffixed (`*_v3_demographics`) set of fields alongside v2's own
    intercept_component/lean_component/tide_component/incumbency_adjustment,
    rather than overwriting them: these models fit different coefficients
    (their own_lean/own_tide/incumbency terms come from smaller, current-
    vintage-only samples), so v2's original components need to survive
    untouched for the district/seat page's existing attribution chart.
    Scoped to district/seat pages only: demographics is a district-level
    attribute, not a per-candidate one, so this deliberately isn't
    threaded into candidate pages the way the finance diagnostic below is.

    Graceful per-district fallback, not all-or-nothing: each district
    picks whichever tier its own Census match actually supports —
    `full_fit` (bachelors_pct + hispanic_pct + voting_age_pct + income_10k)
    when all four are available, else `core_fit` (bachelors_pct alone)
    when at least that is, else no WAR v3 at all for that district (same
    as before this tiering existed). The chosen tier's name is recorded in
    `demographics_tier` ("full"/"core"/None) so pages can say which model
    actually applied rather than leaving it invisible. All of a tier's
    added terms are combined into one "demographics_component" (not one
    stacked-bar segment per term) so the attribution chart's palette still
    only needs a single extra color regardless of which tier ran.

    war_v3_demographics itself is null for an uncontested race (a
    mechanically-inflated ~100% actual share isn't a meaningful gap from
    expectation — same reasoning as WAR v1/v2's documented uncontested
    limitation) — but expected_two_party_share_v3_demographics and every
    *_component stay defined regardless, since they don't depend on the
    actual outcome at all: they're this project's "baseline expectation"
    metric, the one still meaningful when WAR itself isn't."""

    def _tier_coefs(fit: dict) -> dict:
        coefs = fit["coefficients"]
        return {
            "b0": coefs["intercept"]["posterior_mean"],
            "b0_sd": coefs["intercept"]["posterior_sd"],
            "b_lean": coefs["own_lean"]["posterior_mean"],
            "b_lean_sd": coefs["own_lean"]["posterior_sd"],
            "b_tide": coefs["own_tide"]["posterior_mean"],
            "b_tide_sd": coefs["own_tide"]["posterior_sd"],
            "b_terms": {b: coefs[b]["posterior_mean"] for b in INCUMBENT_TERM_BUCKETS},
            "b_terms_sd": {b: coefs[b]["posterior_sd"] for b in INCUMBENT_TERM_BUCKETS},
            "coefs": coefs,
            "sigma": fit["posterior_sigma_mean"],
            "reference_values": fit.get("reference_values", {}),
        }

    core = _tier_coefs(core_fit) if core_fit else None
    full = _tier_coefs(full_fit) if full_fit else None

    for d in district_records_by_vintage.get(current_vintage, []):
        covariates = _demographic_covariates(d.get("demographics"))
        if full and all(k in covariates for k in _DEMOGRAPHICS_FULL_COVARIATES):
            tier, tc = "full", full
        elif core and "bachelors_pct" in covariates:
            tier, tc = "core", core
        else:
            tier, tc = None, None

        for entry in d["results_by_year"]:
            tide = tide_by_year.get(entry["year"])
            for c in entry["candidates"]:
                if c["war"] is None or tide is None or tc is None or c["party"] not in ("Democratic", "Republican"):
                    c.update(
                        demographics_tier=None,
                        intercept_component_v3_demographics=None,
                        intercept_component_v3_demographics_sd=None,
                        lean_component_v3_demographics=None,
                        lean_component_v3_demographics_sd=None,
                        tide_component_v3_demographics=None,
                        tide_component_v3_demographics_sd=None,
                        incumbency_adjustment_v3_demographics=None,
                        incumbency_adjustment_v3_demographics_sd=None,
                        demographics_component=None,
                        demographics_component_sd=None,
                        expected_two_party_share_v3_demographics=None,
                        war_v3_demographics=None,
                        war_v3_demographics_sd=None,
                    )
                    continue
                is_dem = c["party"] == "Democratic"
                own_lean = entry["lean_dem_share"] if is_dem else 1 - entry["lean_dem_share"]
                own_tide = tide if is_dem else 1 - tide
                dummies = _incumbent_term_dummies(c.get("incumbent_terms", 0))
                incumbency_component = sum(tc["b_terms"][b] * dummies[b] for b in INCUMBENT_TERM_BUCKETS)
                lean_component = tc["b_lean"] * own_lean
                tide_component = tc["b_tide"] * own_tide
                tide_component_sd = abs(own_tide) * tc["b_tide_sd"]

                # Every term this tier actually fits, combined into one
                # "demographics_component" plus its delta-method SD summed
                # in quadrature across all contributing terms (same
                # independence approximation used elsewhere in this
                # module). income_10k (full tier only) has no natural
                # zero-income baseline the way a population share does, so
                # — same as log_raised in apply_war_v3_finance below —
                # it's centered on this fit's own mean, with the removed
                # constant folded into the baseline/intercept instead of
                # left in the demographics bar.
                coefs = tc["coefs"]
                demo_terms = [(covariates["bachelors_pct"], 0.0, "bachelors_pct")]
                if tier == "full":
                    demo_terms.append((covariates["hispanic_pct"], 0.0, "hispanic_pct"))
                    demo_terms.append((covariates["voting_age_pct"], 0.0, "voting_age_pct"))
                    income_ref = tc["reference_values"]["income_10k"]
                    demo_terms.append((covariates["income_10k"], income_ref, "income_10k"))
                demographics_component = sum(coefs[name]["posterior_mean"] * (value - ref) for value, ref, name in demo_terms)
                demographics_component_sd = sum(
                    (coefs[name]["posterior_sd"] * (value - ref)) ** 2 for value, ref, name in demo_terms
                ) ** 0.5

                intercept_effective = tc["b0"]
                if tier == "full":
                    intercept_effective += coefs["income_10k"]["posterior_mean"] * income_ref

                expected = intercept_effective + lean_component + tide_component + incumbency_component + demographics_component
                active_bucket = next((b for b in INCUMBENT_TERM_BUCKETS if dummies[b] == 1.0), None)
                incumbency_component_sd = tc["b_terms_sd"][active_bucket] if active_bucket else 0.0
                c.update(
                    demographics_tier=tier,
                    intercept_component_v3_demographics=round(intercept_effective, 4),
                    intercept_component_v3_demographics_sd=round(tc["b0_sd"], 4),
                    lean_component_v3_demographics=round(lean_component, 4),
                    lean_component_v3_demographics_sd=round(abs(own_lean) * tc["b_lean_sd"], 4),
                    tide_component_v3_demographics=round(tide_component, 4),
                    tide_component_v3_demographics_sd=round(tide_component_sd, 4),
                    incumbency_adjustment_v3_demographics=round(incumbency_component, 4),
                    incumbency_adjustment_v3_demographics_sd=round(incumbency_component_sd, 4),
                    demographics_component=round(demographics_component, 4),
                    demographics_component_sd=round(demographics_component_sd, 4),
                    expected_two_party_share_v3_demographics=round(expected, 4),
                    war_v3_demographics=(
                        None if entry["is_uncontested"] else round(c["actual_two_party_share"] - expected, 4)
                    ),
                    war_v3_demographics_sd=None if entry["is_uncontested"] else round(tc["sigma"], 4),
                )


def apply_war_v3_finance(candidate_records: list[dict], finance_by_slug: dict, fit: dict) -> None:
    """Mirrors apply_war_v2, but for the campaign-finance diagnostic
    (fit_war_v3_finance) — operates on the already-built candidate_records
    (each race's own_lean/own_tide/incumbent_terms, threaded through from
    apply_war_v2's own additions to the district records above), not the
    district records directly, since fundraising is a per-candidate
    observable rather than a district one. Only sets real values for a
    race where this candidate actually has an OCPF-matched total for that
    specific year; every other race gets explicit Nones (same "missing
    over wrong" pattern as apply_war_v2), so candidate.html can check one
    field to decide whether to show the finance-aware attribution view.

    war_v3_finance itself is left null for an uncontested race, same
    reasoning and same fields-that-stay-defined pattern as apply_war_v2's
    own uncontested handling — expected_two_party_share_v3_finance is
    this candidate's "baseline expectation" for that race regardless of
    whether the race itself was ever contested."""
    coefs = fit["coefficients"]
    # log_raised has no natural zero-effect baseline the way lean/tide's
    # 0-1 fractions do (a candidate who raised $0 isn't a meaningful
    # reference point), so its attribution-chart contribution is centered
    # on this fit's own mean instead of the raw log-dollar value — the
    # removed constant (b_raised * log_raised_ref) is folded into the
    # baseline/intercept below, so the fundraising bar reads as "how this
    # candidate's fundraising compares to a typical matched candidate's,"
    # not an arbitrary distance from an impossible $0 baseline. See
    # fit_war_v3_finance for where reference_values comes from.
    log_raised_ref = fit["reference_values"]["log_raised"]
    b0 = coefs["intercept"]["posterior_mean"] + coefs["log_raised"]["posterior_mean"] * log_raised_ref
    b_lean = coefs["own_lean"]["posterior_mean"]
    b_tide = coefs["own_tide"]["posterior_mean"]
    b_terms = {b: coefs[b]["posterior_mean"] for b in INCUMBENT_TERM_BUCKETS}
    b_raised = coefs["log_raised"]["posterior_mean"]

    for candidate in candidate_records:
        finance = finance_by_slug.get(candidate["slug"])
        for race in candidate["races"]:
            raised = finance["by_year"].get(race["year"], {}).get("total_raised") if finance else None
            if (
                raised is None
                or race.get("own_lean") is None
                or race.get("own_tide") is None
                or race["party"] not in ("Democratic", "Republican")
            ):
                race.update(
                    fundraising_component=None,
                    fundraising_component_sd=None,
                    intercept_component_v3_finance=None,
                    intercept_component_v3_finance_sd=None,
                    lean_component_v3_finance=None,
                    lean_component_v3_finance_sd=None,
                    tide_component_v3_finance=None,
                    tide_component_v3_finance_sd=None,
                    incumbency_adjustment_v3_finance=None,
                    incumbency_adjustment_v3_finance_sd=None,
                    expected_two_party_share_v3_finance=None,
                    war_v3_finance=None,
                    war_v3_finance_sd=None,
                )
                continue
            log_raised = float(np.log1p(raised))
            dummies = _incumbent_term_dummies(race.get("incumbent_terms", 0))
            incumbency_component = sum(b_terms[b] * dummies[b] for b in INCUMBENT_TERM_BUCKETS)
            lean_component = b_lean * race["own_lean"]
            tide_component = b_tide * race["own_tide"]
            fundraising_component = b_raised * (log_raised - log_raised_ref)
            expected = b0 + lean_component + tide_component + incumbency_component + fundraising_component
            active_bucket = next((b for b in INCUMBENT_TERM_BUCKETS if dummies[b] == 1.0), None)
            incumbency_component_sd = coefs[active_bucket]["posterior_sd"] if active_bucket else 0.0
            race.update(
                fundraising_component=round(fundraising_component, 4),
                fundraising_component_sd=round(abs(log_raised - log_raised_ref) * coefs["log_raised"]["posterior_sd"], 4),
                intercept_component_v3_finance=round(b0, 4),
                intercept_component_v3_finance_sd=coefs["intercept"]["posterior_sd"],
                lean_component_v3_finance=round(lean_component, 4),
                lean_component_v3_finance_sd=round(abs(race["own_lean"]) * coefs["own_lean"]["posterior_sd"], 4),
                tide_component_v3_finance=round(tide_component, 4),
                tide_component_v3_finance_sd=round(abs(race["own_tide"]) * coefs["own_tide"]["posterior_sd"], 4),
                incumbency_adjustment_v3_finance=round(incumbency_component, 4),
                incumbency_adjustment_v3_finance_sd=round(incumbency_component_sd, 4),
                expected_two_party_share_v3_finance=round(expected, 4),
                war_v3_finance=(
                    None if race["is_uncontested"]
                    else round(race["actual_two_party_share"] - expected, 4)
                ),
                war_v3_finance_sd=None if race["is_uncontested"] else round(fit["posterior_sigma_mean"], 4),
            )


_WAR_FACTOR_LABELS = {
    "core": ["District lean", "Statewide tide", "Incumbency"],
    "demographics_core": ["District lean", "Statewide tide", "Incumbency", "District demographics (bachelor's degree %)"],
    "demographics_full": [
        "District lean", "Statewide tide", "Incumbency",
        "District demographics (bachelor's degree %, Hispanic/Latino %, voting-age %, median income)",
    ],
    "finance": ["District lean", "Statewide tide", "Incumbency", "Campaign fundraising"],
}


def apply_resolved_war_district(district_records_by_vintage: dict[str, list[dict]]) -> None:
    """The single, user-facing WAR number this site now shows on district,
    seat, chamber, and party pages, instead of separate v1/v2/v3 columns:
    always the richest model this specific district's own Census match
    supports (the full demographics tier, else the bachelors_pct-only core
    demographics tier, else the plain core regression) — never the raw v1
    baseline (kept internally as `war` for other computations —
    is_incumbent, open-seat detection, etc. — but no longer surfaced to
    readers, since it's mechanically inflated for uncontested races and
    superseded by v2 everywhere it has data to be). Must run after
    apply_war_v2 and apply_war_v3_demographics, and before any of this
    vintage's district/seat files are written — those write functions
    serialize these same dicts immediately, not lazily, so mutating them
    afterward would never reach the files.

    `war_factors` is a plain-language list of what actually went into that
    specific number (no "v2"/"v3"/"core"/"full" jargon), attached to the
    WAR figure itself so a reader can see, right where they see the
    number, whether it reflects local demographics or not, without needing
    to trace which internal model tier produced it. See
    apply_resolved_war_candidate for the equivalent on candidate pages."""
    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                for c in entry["candidates"]:
                    tier = c.get("demographics_tier")
                    if c["war"] is None:
                        c.update(war_resolved=None, war_resolved_sd=None, expected_share_resolved=None, war_model=None, war_factors=None)
                        continue
                    if tier in ("full", "core"):
                        war_model = "demographics_full" if tier == "full" else "demographics_core"
                        war_resolved, war_resolved_sd = c["war_v3_demographics"], c["war_v3_demographics_sd"]
                        expected_share_resolved = c["expected_two_party_share_v3_demographics"]
                    else:
                        war_model = "core"
                        war_resolved, war_resolved_sd = c.get("war_v2"), c.get("war_v2_sd")
                        expected_share_resolved = c.get("expected_two_party_share_v2")
                    c.update(
                        war_resolved=war_resolved,
                        war_resolved_sd=war_resolved_sd,
                        expected_share_resolved=expected_share_resolved,
                        war_model=war_model,
                        war_factors=_WAR_FACTOR_LABELS[war_model],
                    )


def apply_resolved_war_candidate(candidate_records: list[dict]) -> None:
    """Candidate-page counterpart to apply_resolved_war_district: resolves
    to the finance-extended model for any specific race-year with a
    matched OCPF total, falling back to the core model for the rest of
    that same candidate's races — "prefer sophisticated, drop back only
    where the data requires it," same direction as the district-level
    resolution but keyed by year instead of by district. Must run after
    apply_war_v2 and apply_war_v3_finance, and before write_candidate_files."""
    for candidate in candidate_records:
        for race in candidate["races"]:
            if race.get("war") is None:
                race.update(war_resolved=None, war_resolved_sd=None, expected_share_resolved=None, war_model=None, war_factors=None)
                continue
            has_finance = race.get("fundraising_component") is not None
            if has_finance:
                war_model = "finance"
                war_resolved, war_resolved_sd = race["war_v3_finance"], race["war_v3_finance_sd"]
                expected_share_resolved = race["expected_two_party_share_v3_finance"]
            else:
                war_model = "core"
                war_resolved, war_resolved_sd = race.get("war_v2"), race.get("war_v2_sd")
                expected_share_resolved = race.get("expected_two_party_share_v2")
            race.update(
                war_resolved=war_resolved,
                war_resolved_sd=war_resolved_sd,
                expected_share_resolved=expected_share_resolved,
                war_model=war_model,
                war_factors=_WAR_FACTOR_LABELS[war_model],
            )


def build_district_records(chamber: str, vintage: str, derived_dir: Path) -> list[dict]:
    years = discover_years(chamber, vintage, derived_dir)
    if not years:
        return []

    lean_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{vintage}_{y}_lean.parquet") for y in years}
    war_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{y}_war.parquet") for y in years}

    # Union across years, not just the latest: a district still belongs on
    # this vintage's roster even if only an earlier year has been backfilled
    # so far (e.g. a partial/in-progress backfill run).
    roster = (
        pd.concat([lean_by_year[y][["district_id", "district_name"]] for y in years], ignore_index=True)
        .drop_duplicates("district_name")
    )

    records = []
    for _, row in roster.iterrows():
        district_name = row["district_name"]
        results_by_year = []
        for y in sorted(years, reverse=True):
            lean_rows = lean_by_year[y][lean_by_year[y]["district_name"] == district_name]
            if lean_rows.empty:
                continue
            lean_row = lean_rows.iloc[0]
            district_war = war_by_year[y][war_by_year[y]["district_name"] == district_name]
            is_uncontested = bool(district_war["is_uncontested"].iloc[0]) if len(district_war) else None
            turnout_ratio = (
                round(float(district_war["turnout_ratio"].iloc[0]), 4)
                if len(district_war) and pd.notna(district_war["turnout_ratio"].iloc[0])
                else None
            )
            results_by_year.append(
                {
                    "year": y,
                    "lean_dem_share": round(float(lean_row["lean_dem_share"]), 4),
                    "competitiveness": lean_row["competitiveness"],
                    "competitiveness_label": lean_row["competitiveness_label"],
                    "party_favored": lean_row["party_favored"],
                    "is_uncontested": is_uncontested,
                    "turnout_ratio": turnout_ratio,
                    "candidates": _candidate_list(district_war),
                }
            )
        if not results_by_year:
            continue

        # Incumbency, scoped to *within this vintage only* — not chased
        # across a redistricting boundary via seat_lineage, since a
        # lineage match is an area-overlap best-guess, not a guarantee the
        # same electorate (or even district name) carried over; claiming
        # someone is "the incumbent" off that guess would overstate what's
        # actually known. results_by_year is sorted descending by year, so
        # the entry one index later is the immediately preceding election
        # for this same district — an open seat (or the first year on
        # record for this vintage) leaves is_incumbent False rather than
        # guessing, and is_open_seat stays None (unknown) rather than
        # implying a confirmed open seat, when there's no prior-year data
        # to check against at all.
        for i, entry in enumerate(results_by_year):
            prev_winner_slug = None
            if i + 1 < len(results_by_year):
                prev_winner = next((c for c in results_by_year[i + 1]["candidates"] if c["winner"]), None)
                prev_winner_slug = prev_winner["slug"] if prev_winner else None
            for c in entry["candidates"]:
                c["is_incumbent"] = prev_winner_slug is not None and c["slug"] == prev_winner_slug
            entry["is_open_seat"] = (
                None if prev_winner_slug is None else not any(c["is_incumbent"] for c in entry["candidates"])
            )

        # Consecutive incumbency terms already served BEFORE this race —
        # a richer signal than the plain is_incumbent boolean above (which
        # this doesn't replace; every existing "(incumbent)" badge still
        # reads that), feeding WAR v2's regression below. Walked oldest-
        # to-newest (results_by_year is newest-first) so a run of same-
        # slug wins accumulates naturally; resets whenever the winner
        # changes, or a year has no recorded winner at all (treated as an
        # unknown break in the chain rather than guessed through).
        terms_served = 0
        current_winner_slug = None
        for entry in reversed(results_by_year):
            for c in entry["candidates"]:
                c["incumbent_terms"] = terms_served if c["is_incumbent"] else 0
            winner = next((c for c in entry["candidates"] if c["winner"]), None)
            if winner is not None and winner["slug"] == current_winner_slug:
                terms_served += 1
            elif winner is not None:
                current_winner_slug = winner["slug"]
                terms_served = 1
            else:
                current_winner_slug = None
                terms_served = 0

        latest = results_by_year[0]
        records.append(
            {
                "chamber": chamber,
                "vintage": vintage,
                "district_id": row["district_id"],
                "district_name": district_name,
                # Same slug this record's own page file uses (write_district_files
                # below) — also what publish_district_geo.py names this
                # district's map GeoJSON file, so the district page can
                # build that file's URL directly instead of re-deriving the
                # slug in Liquid and risking it drift from either producer.
                "geo_slug": district_slug(chamber, district_name, vintage),
                "years": [ry["year"] for ry in results_by_year],
                "lean_dem_share": latest["lean_dem_share"],
                "competitiveness": latest["competitiveness"],
                "competitiveness_label": latest["competitiveness_label"],
                "party_favored": latest["party_favored"],
                "results_by_year": results_by_year,
            }
        )
    return records


def write_district_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = district_slug(record["chamber"], record["district_name"], record["vintage"])
        front_matter = {
            **record,
            "title": f"{record['district_name']} ({record['vintage']})",
            "layout": "district",
        }
        path = out_dir / f"{slug}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d district pages to %s", len(records), out_dir)


def build_seat_records(
    district_records_by_vintage: dict[str, list[dict]],
    current_vintage: str,
    lineage: pd.DataFrame,
) -> list[dict]:
    """The current vintage's district records, each with a `history` list
    walking backward through seat_lineage's best-area-overlap predecessor —
    however many vintage hops that chain reaches (currently up to two:
    2022-present -> 2012-2020 -> 2001-2010), not hardcoded to a fixed
    depth, so this keeps working if another vintage is added later."""
    by_key = {
        (r["chamber"], vintage, r["district_name"]): r
        for vintage, recs in district_records_by_vintage.items()
        for r in recs
    }

    records = []
    for d in district_records_by_vintage.get(current_vintage, []):
        chamber = d["chamber"]
        vintage, district_name = current_vintage, d["district_name"]
        history = []
        seen_vintages = {current_vintage}
        while True:
            preds = lineage[
                (lineage["chamber"] == chamber)
                & (lineage["new_vintage"] == vintage)
                & (lineage["new_district_name"] == district_name)
            ]
            if preds.empty:
                break
            best = preds.sort_values("pct_of_old_area", ascending=False).iloc[0]
            prev_vintage, prev_name = best["old_vintage"], best["old_district_name"]
            if prev_vintage in seen_vintages:
                break  # guard against any lineage cycle in the data
            prev_record = by_key.get((chamber, prev_vintage, prev_name))
            history.append(
                {
                    "vintage": prev_vintage,
                    "district_name": prev_name,
                    "url": district_url(chamber, prev_name, prev_vintage) if prev_record else None,
                    "overlap_pct": round(float(best["pct_of_old_area"]), 4),
                }
            )
            seen_vintages.add(prev_vintage)
            vintage, district_name = prev_vintage, prev_name
        records.append({**d, "history": history})
    return records


def write_seat_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        slug = f"{record['chamber']}-{slugify(record['district_name'])}"
        front_matter = {**record, "title": record["district_name"], "layout": "seat"}
        path = out_dir / f"{slug}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d seat pages to %s", len(records), out_dir)


def build_candidate_records(district_records_by_vintage: dict[str, list[dict]]) -> list[dict]:
    """One record per candidate_slug, with every race they ran across every
    vintage/year/chamber this run has data for — built from the already-
    assembled district records (which carry is_incumbent and turnout_ratio,
    computed once there) rather than re-reading raw WAR parquet, so a
    candidate's own race history can't drift from what the district page
    for that same race shows. All years at once, not one CLI invocation
    per year, specifically so a candidate who ran in multiple election
    cycles gets one merged record instead of each year's run silently
    overwriting the last."""
    races_by_slug: dict[str, list[dict]] = {}
    latest_info: dict[str, tuple[int, str, str | None]] = {}  # slug -> (year, name, party)

    for vintage, records in district_records_by_vintage.items():
        for d in records:
            for entry in d["results_by_year"]:
                for c in entry["candidates"]:
                    races_by_slug.setdefault(c["slug"], []).append(
                        {
                            "chamber": d["chamber"],
                            "year": entry["year"],
                            "vintage": vintage,
                            "district_name": d["district_name"],
                            # Precomputed here (not reconstructed via Liquid's
                            # slugify filter in candidate.html) so this link
                            # can't drift from the district page's own actual
                            # filename the way a prior bug in this project did
                            # for a similarly-reconstructed candidate link.
                            "district_url": district_url(d["chamber"], d["district_name"], vintage),
                            "party": c["party"],
                            "votes": c["votes"],
                            "winner": c["winner"],
                            "actual_two_party_share": c["actual_two_party_share"],
                            "war": c["war"],
                            "own_lean": c.get("own_lean"),
                            "own_tide": c.get("own_tide"),
                            "war_v2": c.get("war_v2"),
                            "war_v2_sd": c.get("war_v2_sd"),
                            "incumbency_adjustment": c.get("incumbency_adjustment"),
                            "incumbency_adjustment_sd": c.get("incumbency_adjustment_sd"),
                            "intercept_component": c.get("intercept_component"),
                            "intercept_component_sd": c.get("intercept_component_sd"),
                            "lean_component": c.get("lean_component"),
                            "lean_component_sd": c.get("lean_component_sd"),
                            "tide_component": c.get("tide_component"),
                            "tide_component_sd": c.get("tide_component_sd"),
                            "expected_two_party_share": c.get("expected_two_party_share"),
                            "expected_two_party_share_v2": c.get("expected_two_party_share_v2"),
                            "is_uncontested": entry["is_uncontested"],
                            "is_incumbent": c["is_incumbent"],
                            "incumbent_terms": c.get("incumbent_terms", 0),
                        }
                    )
                    prev = latest_info.get(c["slug"])
                    if prev is None or entry["year"] > prev[0]:
                        latest_info[c["slug"]] = (entry["year"], c["name"], c["party"])

    records = []
    for slug, races in races_by_slug.items():
        races_sorted = sorted(races, key=lambda r: (r["year"], r["chamber"]), reverse=True)
        _, name, party = latest_info[slug]
        records.append({"slug": slug, "name": name, "party": party, "races": races_sorted})
    return records


def write_candidate_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "candidate"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d candidate pages to %s", len(records), out_dir)


def build_town_records(chambers: list[str], vintage: str, crosswalks_dir: Path, seat_records: list[dict]) -> list[dict]:
    """One record per town, listing every district (in any given chamber)
    that overlaps it — a town routinely splits across multiple districts,
    especially in denser areas (Boston alone spans 16 House districts in
    the 2022 vintage). Joined against the already-built seat_records
    (current vintage, most recent year's winner) for each district's
    current lean/representative rather than re-deriving from raw parquet,
    since that's already computed and correct."""
    overlap = pd.read_parquet(crosswalks_dir / "town_district_overlap.parquet")
    overlap = overlap[overlap["vintage"] == vintage]
    overlap = overlap[overlap["chamber"].isin(chambers)]
    # TIGER's one non-municipality placeholder row (water/unassigned area,
    # see fetch.towns) — not a real town, exclude.
    overlap = overlap[overlap["town"] != "County subdivisions not defined"]

    seat_by_key = {(s["chamber"], s["district_name"]): s for s in seat_records}

    records = []
    for raw_town, group in overlap.groupby("town"):
        # TIGER's NAME field inconsistently suffixes some municipalities
        # with "Town"/"City" (e.g. "Agawam Town") — same normalization
        # derived_metrics.py applies before joining town-level votes,
        # reused here so page titles/URLs read as "Agawam", not "Agawam Town".
        town = normalize_town_name(raw_town)
        districts = []
        for _, row in group.sort_values("pct_of_town", ascending=False).iterrows():
            seat = seat_by_key.get((row["chamber"], row["district_name"]))
            latest = seat["results_by_year"][0] if seat and seat["results_by_year"] else None
            winner = next((c for c in latest["candidates"] if c["winner"]), None) if latest else None
            districts.append(
                {
                    "chamber": row["chamber"],
                    "district_name": row["district_name"],
                    "url": seat_url(row["chamber"], row["district_name"]),
                    "pct_of_town": round(float(row["pct_of_town"]), 4),
                    "lean_dem_share": seat["lean_dem_share"] if seat else None,
                    "competitiveness_label": seat["competitiveness_label"] if seat else None,
                    "current_rep": winner["name"] if winner else None,
                    "current_rep_party": winner["party"] if winner else None,
                }
            )
        records.append({"name": town, "slug": slugify(town), "districts": districts})
    return records


def write_town_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "town"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d town pages to %s", len(records), out_dir)


def build_party_records(seat_records: list[dict]) -> list[dict]:
    """One record per party that currently holds at least one seat (most
    recent year of the current vintage), with every seat they hold and
    each winner's WAR — a natural "who's overperforming for this party"
    view. Built from seat_records' winners rather than a separate query,
    since "holds this seat" is exactly "is this seat's most recent
    winner"."""
    parties: dict[str, list[dict]] = {}
    for seat in seat_records:
        latest = seat["results_by_year"][0] if seat["results_by_year"] else None
        winner = next((c for c in latest["candidates"] if c["winner"]), None) if latest else None
        if not winner or not winner["party"]:
            continue
        parties.setdefault(winner["party"], []).append(
            {
                "chamber": seat["chamber"],
                "district_name": seat["district_name"],
                "url": seat_url(seat["chamber"], seat["district_name"]),
                "winner_name": winner["name"],
                "winner_slug": winner["slug"],
                "war_resolved": winner.get("war_resolved"),
                "war_factors": winner.get("war_factors"),
            }
        )

    records = []
    for party, seats_held in parties.items():
        # Highest WAR (biggest overperformance) first; null-WAR (uncontested
        # or minor-party winner) entries sort last, not scattered by the
        # coincidence of comparing None to a float.
        seats_held_sorted = sorted(seats_held, key=lambda s: (s["war_resolved"] is None, -(s["war_resolved"] or 0)))
        by_chamber = {}
        for s in seats_held:
            by_chamber[s["chamber"]] = by_chamber.get(s["chamber"], 0) + 1
        records.append(
            {
                "name": party,
                "slug": slugify(party),
                "seat_count": len(seats_held),
                "seat_count_by_chamber": by_chamber,
                "seats_held": seats_held_sorted,
            }
        )
    return records


def write_party_files(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        front_matter = {**record, "title": record["name"], "layout": "party"}
        path = out_dir / f"{record['slug']}.md"
        path.write_text(f"---\n{yaml.safe_dump(front_matter, sort_keys=False)}---\n")
    logger.info("Wrote %d party pages to %s", len(records), out_dir)


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option("--current-vintage", default="2022-present", help="Vintage whose districts become /seat/ pages")
@click.option(
    "--vintages",
    default="2001-2010,2012-2020,2022-present",
    help="Comma-separated list of all vintages to build /district/ pages for",
)
@click.option("--derived-dir", type=click.Path(path_type=Path), default=Path("data/interim/derived_metrics"))
@click.option("--crosswalks-dir", type=click.Path(path_type=Path), default=Path("data/interim/crosswalks"))
@click.option(
    "--baseline-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/pd43_statewide"),
    help="Statewide Governor/President race data from fetch.pd43, for WAR v2's statewide-tide term",
)
@click.option(
    "--ocpf-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/ocpf"),
    help="Campaign finance data from fetch.campaign_finance; skipped (with a warning) if missing",
)
@click.option(
    "--demographics-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/demographics"),
    help="Census PL 94-171/ACS data from fetch.demographics; only covers the current vintage, skipped if missing",
)
@click.option(
    "--site-data-dir",
    type=click.Path(path_type=Path),
    default=Path("site/_data"),
    help="Where to write war_v2.yml/war_v3_demographics.yml/war_v3_finance.yml — the fitted regression posteriors, for the methodology page to read via site.data.war_v2 etc.",
)
@click.option("--seats-out-dir", type=click.Path(path_type=Path), default=Path("site/_seats"))
@click.option("--districts-out-dir", type=click.Path(path_type=Path), default=Path("site/_districts"))
@click.option("--candidates-out-dir", type=click.Path(path_type=Path), default=Path("site/_candidates"))
@click.option("--towns-out-dir", type=click.Path(path_type=Path), default=Path("site/_towns"))
@click.option("--parties-out-dir", type=click.Path(path_type=Path), default=Path("site/_parties"))
@click.option("-v", "--verbose", is_flag=True)
def main(
    chamber: str,
    current_vintage: str,
    vintages: str,
    derived_dir: Path,
    crosswalks_dir: Path,
    baseline_dir: Path,
    ocpf_dir: Path,
    demographics_dir: Path,
    site_data_dir: Path,
    seats_out_dir: Path,
    districts_out_dir: Path,
    candidates_out_dir: Path,
    towns_out_dir: Path,
    parties_out_dir: Path,
    verbose: bool,
):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    chambers = ["house", "senate"] if chamber == "both" else [chamber]
    vintage_list = [v.strip() for v in vintages.split(",") if v.strip()]

    district_records_by_vintage: dict[str, list[dict]] = {}
    for vintage in vintage_list:
        recs = []
        for c in chambers:
            recs.extend(build_district_records(c, vintage, derived_dir))
        district_records_by_vintage[vintage] = recs

    # Census demographics (PL 94-171 + ACS) only exist for the current
    # vintage — see demographics_match.py's docstring — so only those
    # records get enriched; other vintages' district pages simply have no
    # demographics section. Enriched before any of the WAR fitting below,
    # since fit_war_v3_demographics needs it already attached.
    if current_vintage in district_records_by_vintage:
        for c in chambers:
            chamber_records = [d for d in district_records_by_vintage[current_vintage] if d["chamber"] == c]
            demographics_by_name = demographics_match.load_demographics(
                c, demographics_dir, [d["district_name"] for d in chamber_records]
            )
            for d in chamber_records:
                if d["district_name"] in demographics_by_name:
                    d["demographics"] = demographics_by_name[d["district_name"]]

    site_data_dir.mkdir(parents=True, exist_ok=True)
    tide_by_year = compute_statewide_tide_by_year(baseline_dir)

    # WAR v2: fit the core fundamentals regression once, globally, across
    # every vintage's data (it needs the whole pooled sample, not one
    # district's worth), then apply its posterior-mean coefficients as a
    # second pass over the records just built.
    war_v2_fit = fit_war_v2_core(district_records_by_vintage, tide_by_year)
    apply_war_v2(district_records_by_vintage, tide_by_year, war_v2_fit)
    logger.info(
        "WAR v2 core fit: n=%d, R²=%s, own_lean=%+.3f, own_tide=%+.3f, incumbent_1=%+.3f, incumbent_2=%+.3f, incumbent_3plus=%+.3f",
        war_v2_fit["n"],
        war_v2_fit["r_squared"],
        war_v2_fit["coefficients"]["own_lean"]["posterior_mean"],
        war_v2_fit["coefficients"]["own_tide"]["posterior_mean"],
        war_v2_fit["coefficients"]["incumbent_1"]["posterior_mean"],
        war_v2_fit["coefficients"]["incumbent_2"]["posterior_mean"],
        war_v2_fit["coefficients"]["incumbent_3plus"]["posterior_mean"],
    )
    (site_data_dir / "war_v2.yml").write_text(yaml.safe_dump(war_v2_fit, sort_keys=False))

    fit_sample = build_war_v2_fit_sample(district_records_by_vintage)
    (site_data_dir / "war_v2_fit_sample.yml").write_text(yaml.safe_dump(fit_sample, sort_keys=False))
    logger.info("Wrote %d rows to %s", len(fit_sample), site_data_dir / "war_v2_fit_sample.yml")

    # WAR v3: two diagnostic extensions of the core model, reported on the
    # methodology page only (see each function's docstring for why they
    # aren't threaded into every candidate's WAR the way v2 is — real
    # coverage limits, not an oversight). Demographics is itself two
    # tiers — core (bachelors_pct alone) and full (+ hispanic_pct,
    # voting_age_pct, income_10k) — so a district whose PL 94-171 match
    # failed but has ACS data still gets the core tier rather than nothing.
    war_v3_demographics_core_fit = fit_war_v3_demographics_core(district_records_by_vintage, tide_by_year, current_vintage)
    war_v3_demographics_full_fit = fit_war_v3_demographics_full(district_records_by_vintage, tide_by_year, current_vintage)
    if war_v3_demographics_core_fit is not None:
        logger.info(
            "WAR v3 demographics (core) diagnostic: n=%d, R²=%s, bachelors_pct=%+.3f",
            war_v3_demographics_core_fit["n"],
            war_v3_demographics_core_fit["r_squared"],
            war_v3_demographics_core_fit["coefficients"]["bachelors_pct"]["posterior_mean"],
        )
    else:
        logger.warning("Not enough current-vintage demographics-matched races to fit the WAR v3 demographics (core) diagnostic")
    if war_v3_demographics_full_fit is not None:
        logger.info(
            "WAR v3 demographics (full) diagnostic: n=%d, R²=%s, hispanic_pct=%+.3f, voting_age_pct=%+.3f, income_10k=%+.4f",
            war_v3_demographics_full_fit["n"],
            war_v3_demographics_full_fit["r_squared"],
            war_v3_demographics_full_fit["coefficients"]["hispanic_pct"]["posterior_mean"],
            war_v3_demographics_full_fit["coefficients"]["voting_age_pct"]["posterior_mean"],
            war_v3_demographics_full_fit["coefficients"]["income_10k"]["posterior_mean"],
        )
    else:
        logger.warning("Not enough fully-Census-matched districts to fit the WAR v3 demographics (full) diagnostic")
    if war_v3_demographics_core_fit is not None or war_v3_demographics_full_fit is not None:
        (site_data_dir / "war_v3_demographics.yml").write_text(
            yaml.safe_dump({"core": war_v3_demographics_core_fit, "full": war_v3_demographics_full_fit}, sort_keys=False)
        )
        apply_war_v3_demographics(
            district_records_by_vintage, tide_by_year, current_vintage, war_v3_demographics_core_fit, war_v3_demographics_full_fit
        )
    apply_resolved_war_district(district_records_by_vintage)

    all_district_records = [r for recs in district_records_by_vintage.values() for r in recs]
    write_district_files(all_district_records, districts_out_dir)

    lineage = pd.read_parquet(crosswalks_dir / "seat_lineage.parquet")
    seat_records = build_seat_records(district_records_by_vintage, current_vintage, lineage)
    write_seat_files(seat_records, seats_out_dir)

    candidate_records = build_candidate_records(district_records_by_vintage)
    if (ocpf_dir / "filers.parquet").exists():
        finance_by_slug = campaign_finance_match.load_and_match(candidate_records, ocpf_dir)
        for candidate in candidate_records:
            if candidate["slug"] in finance_by_slug:
                candidate["ocpf_finance"] = finance_by_slug[candidate["slug"]]

        war_v3_finance_fit = fit_war_v3_finance(district_records_by_vintage, tide_by_year, finance_by_slug)
        if war_v3_finance_fit is not None:
            logger.info(
                "WAR v3 finance diagnostic: n=%d, R²=%s, log_raised=%+.4f, years=%d",
                war_v3_finance_fit["n"],
                war_v3_finance_fit["r_squared"],
                war_v3_finance_fit["coefficients"]["log_raised"]["posterior_mean"],
                war_v3_finance_fit["n_distinct_years"],
            )
            (site_data_dir / "war_v3_finance.yml").write_text(yaml.safe_dump(war_v3_finance_fit, sort_keys=False))
            apply_war_v3_finance(candidate_records, finance_by_slug, war_v3_finance_fit)
        else:
            logger.warning("Not enough finance-matched races to fit the WAR v3 finance diagnostic")
    else:
        logger.warning("No OCPF data at %s — candidate pages will have no campaign-finance section", ocpf_dir)
    apply_resolved_war_candidate(candidate_records)
    write_candidate_files(candidate_records, candidates_out_dir)

    town_records = build_town_records(chambers, current_vintage, crosswalks_dir, seat_records)
    write_town_files(town_records, towns_out_dir)

    party_records = build_party_records(seat_records)
    write_party_files(party_records, parties_out_dir)


if __name__ == "__main__":
    main()
