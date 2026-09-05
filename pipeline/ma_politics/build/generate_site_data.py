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


def _vintage_year_range(vintage: str) -> tuple[int, int | None]:
    """Parses "2001-2010" -> (2001, 2010), "2022-present" -> (2022, None)
    (open-ended). Used to find which primary years belong to a vintage
    directly from the vintage label already on hand, rather than needing a
    year->vintage lookup table — see discover_primary_years' own docstring
    for why primary years can't be discovered the same way discover_years
    finds general-election ones."""
    start_s, end_s = vintage.split("-")
    return int(start_s), None if end_s == "present" else int(end_s)


def discover_primary_years(chamber: str, vintage: str, derived_dir: Path) -> list[int]:
    """Which years have {chamber}_{year}_primary.parquet on disk and fall
    within this vintage's own year range. Unlike discover_years, this
    doesn't require a same-year lean file to exist first — a real, live
    situation this project hit directly: primary results for a given year
    can be fetched and matched to districts well before that year's
    Governor/President baseline race is (own_tide needs the baseline;
    a primary's own vote totals don't), so gating primary discovery on
    the lean file's existence would silently hide primary data that's
    already sitting on disk."""
    start, end = _vintage_year_range(vintage)
    pattern = re.compile(rf"^{re.escape(chamber)}_(\d{{4}})_primary\.parquet$")
    years = []
    for p in derived_dir.glob(f"{chamber}_*_primary.parquet"):
        m = pattern.match(p.name)
        if not m:
            continue
        y = int(m.group(1))
        if start <= y and (end is None or y <= end):
            years.append(y)
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
            # war_resolved, incumbency_adjustment, expected_share_resolved
            # and the rest of apply_war's fields are added afterward, once
            # is_incumbent (also set later, in build_district_records) and
            # the globally-fit model are both available — not present yet
            # on the dict this function returns.
        }
        for _, row in district_war.sort_values("votes", ascending=False).iterrows()
    ]


def _primary_candidate_list(primary_race: pd.DataFrame) -> list[dict]:
    """primary_race: every row of one primary election_id (build_district_
    records groups by that before calling this, since a district/party/year
    can have two — a regular primary and a special one, see derived_metrics'
    own compute_primary_results docstring). is_incumbent/incumbent_terms are
    added afterward, once the district's own general-election winner
    history is available; primary_war/primary_expected_share once
    fit_primary_war_model's fit is."""
    return [
        {
            "name": row["candidate_name"],
            "slug": candidate_slug(row["candidate_slug"]),
            "party": _clean_str(row["party"]),
            "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
            "winner": bool(row["winner"]),
            "actual_primary_share": round(float(row["actual_primary_share"]), 4) if pd.notna(row["actual_primary_share"]) else None,
        }
        for _, row in primary_race.sort_values("votes", ascending=False).iterrows()
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


def compute_national_approval_by_year(approval_dir: Path) -> dict[int, float]:
    """The sitting president's own job-approval rating near that year's
    Election Day, re-expressed as a *Democratic* share (mirroring
    compute_statewide_tide_by_year's own convention, so both feed
    fit_war_model's own_* sign-flip the same way): `approving/100` when the
    president is a Democrat, `1 - approving/100` when a Republican. This is
    a genuinely different signal from own_tide above — tide is
    Massachusetts' own statewide baseline-race result, approval is the
    *national* political environment, sourced independently (see
    fetch.presidential_approval) rather than derived from anything
    apportioned down from a MA race. Missing entirely (file not present)
    returns an empty dict rather than raising — fit_war_model already
    treats any year absent from tide_by_year as "skip this row," the same
    graceful-degradation this reuses rather than special-casing."""
    path = approval_dir / "approval_by_year.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    result = {}
    for _, row in df.iterrows():
        approving = row["approving"] / 100
        result[int(row["year"])] = approving if row["president_party"] == "Democratic" else 1 - approving
    return result


def _is_incumbent_dummy(terms: int) -> float:
    """A single incumbent/non-incumbent dummy, not one term per consecutive-
    term bucket (1st/2nd/3rd-or-later) — an earlier version of this fit
    split those out, but their posterior means landed close enough together
    (this site's data doesn't show a strong "sophomore surge" or later-term
    fade) that the extra three parameters weren't earning their keep over
    one shared incumbency effect."""
    return 1.0 if terms >= 1 else 0.0


# Weakly informative, regularizing priors for every coefficient
# fit_war_model fits, in the coefficient's own native units (a candidate's
# own-party share of the two-party vote, same scale as the response).
# Independent of the noise variance (semi-conjugate, not the classic
# prior-scaled-by-sigma^2 convention) specifically so each prior can be
# set directly from substantive belief about vote-share regressions
# rather than through an assumed sigma. `intercept`/`own_lean`/`own_tide`
# are centered on the theoretically-expected values (a generic candidate
# splits the vote evenly; lean alone should track actual share about 1:1
# if it were a perfect predictor; no prior sign on tide's residual effect
# once lean is already in the model). `incumbent` gets a modest,
# positive-leaning prior (grounded in the same incumbency-advantage
# literature methodology.md already cites, not fit from this project's
# own preliminary numbers) with real shrinkage (sd 0.08). `log_raised`'s
# prior is scaled for a variable that itself spans roughly log($1k) to
# log($1M) (~7-14).
# `hispanic_pct` and `voting_age_pct` are proportions like `bachelors_pct`,
# so they share its prior. `income_10k` is median household income in
# $10,000 units (so a district going from $70k to $170k median income is
# a 10-unit swing) — its prior is scaled down from `bachelors_pct`'s the
# same way `log_raised` was scaled down from `own_lean`'s: a $10k step is
# a much finer-grained unit than a full 0-to-1 population share, so the
# same substantive belief ("this shouldn't move vote share by double-digit
# points on its own") implies a much smaller per-unit coefficient.
#
# The `_x_dem` terms are Democratic-specific deltas layered on top of the
# shared coefficient above them (own_lean, own_tide, and incumbent),
# plus a plain `is_dem` delta on the intercept — see
# fit_war_model's own docstring for why: a real, found-live asymmetry
# (Democratic candidates' residuals average +5.3 points, Republicans'
# -5.3, from the same shared-coefficient model these priors used to
# describe alone) that the own-party sign-flip alone doesn't absorb. Each
# delta's prior is centered at 0 with half its main effect's prior SD —
# start from "assume the two parties behave the same way" and require the
# data to pull a specific term away from that, rather than either forcing
# strict pooling (the old design) or fitting two fully separate models
# with no shared information at all.
#
# Deliberately no interaction with *tide* for any predictor (a demographic
# field × tide, e.g., to ask "does this district trait change how much it
# swings with the national mood"): an interaction with tide is only as
# identified as the number of distinct tide values in the fit, i.e.
# distinct election years, and every term here still has too few to trust
# one — demographics only covers the current vintage's 2 elections (2022,
# 2024); even finance's log_raised, with a real 12 years of backfill, has
# no specific hypothesis motivating one yet. An earlier version of this
# project fit `bachelors_pct_x_tide` anyway (on exactly those 2 years),
# which turned out to be a cherry-picked, thinly-identified special case
# rather than a principled choice. If a term earns a tide interaction in
# the future, the honest bar is a predictor with enough distinct years to
# show real variation in the interaction itself (a rule of thumb: 4+), not
# just "we thought to try it." The party interactions above are a
# different case — every term here has real variation across two parties
# and a real, already-observed asymmetry motivating them, not a
# speculative test.
_COEFFICIENT_PRIORS: dict[str, tuple[float, float]] = {
    "intercept": (0.5, 0.2),
    "is_dem": (0.0, 0.1),
    "own_lean": (1.0, 0.4),
    "own_lean_x_dem": (0.0, 0.2),
    "own_tide": (0.0, 0.4),
    "own_tide_x_dem": (0.0, 0.2),
    # national_approval is own_tide's national-level counterpart (see
    # compute_national_approval_by_year's own docstring for the distinction)
    # and shares its prior for exactly that reason — no `_x_dem` delta yet,
    # unlike own_tide: that term exists because a real, already-observed
    # asymmetry motivated it (see this dict's own top comment on the
    # `_x_dem` terms generally); national_approval hasn't been examined for
    # one yet, so it stays a single shared term until it has.
    "national_approval": (0.0, 0.4),
    "incumbent": (0.05, 0.08),
    "incumbent_x_dem": (0.0, 0.04),
    # A race-level term (true for both candidates in an open race, unlike
    # incumbency, which is specific to one candidate) — folded into the
    # Baseline/intercept component on district/candidate attribution
    # charts rather than given its own bar, since it isn't really "this
    # candidate's own" advantage or disadvantage the way lean/tide/
    # incumbency/demographics/fundraising all are. No informative prior
    # (no literature this project already cites gives a specific magnitude
    # the way incumbency's does), so centered at 0 with a moderate SD.
    "open_seat": (0.0, 0.1),
    "bachelors_pct": (0.0, 0.3),
    "hispanic_pct": (0.0, 0.3),
    "voting_age_pct": (0.0, 0.3),
    "income_10k": (0.0, 0.02),
    # median_age_10 is median age in decades (so 35 -> 45 is a 1-unit
    # swing) — its own dedicated, narrower prior rather than sharing
    # income_10k's: a 10-year age swing is a much bigger share of this
    # state's real district-to-district range (roughly 2 decades) than a
    # $10k income swing is of that variable's own range (roughly 8 such
    # units), so the same "shouldn't move vote share by double digits on
    # its own" belief implies a slightly wider allowance per unit here.
    "median_age_10": (0.0, 0.03),
    # homeownership_pct/white_pct are 0-1 population shares like
    # bachelors_pct/hispanic_pct/voting_age_pct, so they share that prior.
    "homeownership_pct": (0.0, 0.3),
    "white_pct": (0.0, 0.3),
    # Replaces log_raised: own_raised / (own_raised + opponent_raised),
    # this candidate's own share of the two-party OCPF-matched total for
    # that specific race (not just their own raw dollar total, which
    # couldn't tell a $50k candidate facing a $20k opponent apart from one
    # facing a $500k opponent). A 0-1 share like the population-style
    # covariates above, so it shares their prior rather than log_raised's
    # much narrower one (that one was scaled for a variable spanning
    # roughly log($1k) to log($1M), a unit this share doesn't have).
    "fundraising_share": (0.0, 0.3),
    # fit_primary_war_model's own, much smaller model — prefixed rather
    # than reusing "incumbent"/"log_raised" outright, since a primary's
    # incumbency effect and fundraising effect are fit on a genuinely
    # different electorate (intra-party, not two-party) and aren't
    # expected to share a magnitude with the general model's own terms;
    # see that function's own docstring for the full formula and why.
    # `primary_incumbent`'s prior mean is deliberately much larger than
    # the general model's own "incumbent" (0.05) — incumbents winning
    # primaries by wide margins (60-40, 70-30) is a well-known pattern in
    # the incumbency-advantage literature this project's methodology page
    # already cites, not a project-specific guess — with a wide sd since
    # this project hasn't fit that magnitude itself before now.
    "primary_intercept": (0.0, 0.1),
    "primary_incumbent": (0.15, 0.15),
    "primary_incumbent_x_tide": (0.0, 0.2),
    "primary_incumbent_x_lean": (0.0, 0.2),
    "primary_log_raised": (0.0, 0.02),
    # fit_us_house_war_model's own, separate fit for MA's U.S. House
    # delegation (9-10 large districts, not 160 small ones) — prefixed
    # "ush_" rather than sharing the general model's own "own_lean"/
    # "own_tide"/"incumbent" keys, since the two are deliberately never
    # pooled (a real, direct user choice: a separate fit for U.S. House,
    # not folded into the state legislative model) even though they're
    # the same *kind* of quantity, so the priors are set identically to
    # the general model's own core terms (no demographics/finance
    # extensions here — no congressional-district demographics crosswalk
    # and no FEC data fetched this round, both documented gaps on the
    # methodology page rather than silently absent. ush_national_approval/
    # ush_open_seat, unlike demographics/fundraising, depend on neither
    # blocked data source (national approval is a national-level series,
    # not congressional-district-specific; open-seat status comes straight
    # out of PD43+'s own election results, already fetched) — included
    # here for the same reason they're in the general model.
    "ush_intercept": (0.5, 0.2),
    "ush_is_dem": (0.0, 0.1),
    "ush_own_lean": (1.0, 0.4),
    "ush_own_lean_x_dem": (0.0, 0.2),
    "ush_own_tide": (0.0, 0.4),
    "ush_own_tide_x_dem": (0.0, 0.2),
    "ush_national_approval": (0.0, 0.4),
    "ush_incumbent": (0.05, 0.08),
    "ush_incumbent_x_dem": (0.0, 0.04),
    "ush_open_seat": (0.0, 0.1),
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
    pipeline run — deliberately not OLS/plain least squares. The one model
    this function is used for (see fit_war_model below) has several terms
    OLS handles badly: own_lean and own_tide, though now derived from
    different sources (structural district lean vs. per-year statewide
    tide), remain correlated with the party-interaction and incumbency
    terms built from them; incumbents are a minority of races; and
    the demographics/finance extension terms are informed by samples small
    enough (a couple hundred rows, one covering just a handful of election
    years) that an unconstrained least-squares estimate would be little
    more than noise dressed up as a coefficient. A weakly
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


_GENERAL_EXTENSION_COVARIATES = (
    "bachelors_pct",
    "hispanic_pct",
    "voting_age_pct",
    "income_10k",
    "median_age_10",
    "homeownership_pct",
    "white_pct",
    "fundraising_share",
    "open_seat",
)


def _opponent(entry: dict, slug: str) -> dict | None:
    """The other major-party candidate in this same year's race, if any —
    used both for fundraising_share below (needs both sides' OCPF totals)
    and anywhere else a race needs to reason about "the candidate this one
    is actually running against." Every contested entry fit_war_model/
    apply_war process has exactly one Democrat and one Republican (that's
    what "contested" means here — see compute_war's own is_uncontested
    definition), so this never has to disambiguate among multiple
    same-party opponents."""
    return next(
        (o for o in entry["candidates"] if o["party"] in ("Democratic", "Republican") and o["slug"] != slug),
        None,
    )


def _fundraising_share(finance_by_slug: dict, entry: dict, c: dict) -> float | None:
    """This candidate's own share of the two-party OCPF-matched total for
    this specific race — own_raised / (own_raised + opponent_raised) —
    rather than log_raised's own raw dollar total, which couldn't tell a
    $50k candidate facing a $20k opponent apart from one facing a $500k
    opponent even though those are very different competitive positions.
    None whenever either side's OCPF match is missing (a real, structural
    tradeoff versus log_raised, which only ever needed *this* candidate's
    own match): a share needs both numbers, not just one."""
    opponent = _opponent(entry, c["slug"])
    if opponent is None:
        return None
    own_finance = finance_by_slug.get(c["slug"], {}).get("by_year", {}).get(entry["year"])
    opp_finance = finance_by_slug.get(opponent["slug"], {}).get("by_year", {}).get(entry["year"])
    own_raised = own_finance["total_raised"] if own_finance else None
    opp_raised = opp_finance["total_raised"] if opp_finance else None
    if own_raised is None or opp_raised is None or (own_raised + opp_raised) <= 0:
        return None
    return own_raised / (own_raised + opp_raised)


def fit_war_model(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    approval_by_year: dict[int, float],
    current_vintage: str,
    finance_by_slug: dict,
) -> dict:
    """The one regression this site's WAR is built on. Fit once, across the
    full 2002-2024 backfill, on every contested major-party candidate-race:

        own_share ~ intercept + is_dem
                     + own_lean          + own_lean_x_dem
                     + own_tide          + own_tide_x_dem
                     + national_approval
                     + incumbent         + incumbent_x_dem
                     + open_seat
                     + bachelors_pct + hispanic_pct + voting_age_pct + income_10k
                     + median_age_10 + homeownership_pct + white_pct
                     + fundraising_share

    `incumbent` is a single dummy (any candidate who won their district's
    immediately preceding election, whatever their consecutive-term
    count), not three separate 1st/2nd/3rd-or-later-term buckets — an
    earlier version of this fit split those out, but their posterior
    means landed close enough together (no real "sophomore surge" or
    later-term fade in this data) that the extra parameters weren't
    earning their keep; see _is_incumbent_dummy's own docstring.

    "own_*" means the value is already flipped to that candidate's own
    party's perspective (own_lean = lean for a Democrat, 1 - lean for a
    Republican; same for tide and national_approval) — the same symmetry
    compute_war() already uses, so one pooled fit covers both parties'
    *shared* behavior. The `_x_dem` terms then let a Democrat's fitted
    relationship to lean/tide/incumbency differ from a Republican's, on
    top of that shared baseline — see _COEFFICIENT_PRIORS' own comment for
    why: a real, found-live asymmetry (this fit's own residuals, without
    these terms, averaged +5.3 points for Democrats and -5.3 for
    Republicans) that the sign-flip symmetry alone doesn't absorb, since it
    only guarantees the *pooled* mean residual is zero, not the within-
    party one. `national_approval` has no `_x_dem` delta of its own yet —
    it hasn't been examined for a similar asymmetry the way own_tide has,
    so it stays a single shared term until it is (see _COEFFICIENT_PRIORS'
    own comment).

    own_lean comes from each district's own *structural* lean
    (build_district_records' lean_dem_share_structural — the average
    across every year on record for that district within its vintage), not
    that specific year's own apportioned result. own_tide
    (compute_statewide_tide_by_year) is the statewide, unapportioned
    two-party share on that year's baseline race — Massachusetts' own
    mood. national_approval (compute_national_approval_by_year) is a
    genuinely different signal from own_tide: the sitting president's own
    approval rating near that year's Election Day, sourced independently
    (not derived from any MA race) — the *national* environment, distinct
    from the state's own. Splitting a district's long-run partisan
    baseline from the current cycle's state and national mood this way is
    closer to the Gelman & King "normal vote" framing this project's own
    methodology page already cites than a single per-year lean was.

    `open_seat` is 1.0 when neither candidate in the race held the seat
    before (entry["is_open_seat"]), 0.0 otherwise, mean-filled like the
    demographics/finance covariates below when unknown (a vintage's first
    tracked year, where incumbency can't be determined at all — see
    build_district_records' own incumbency docstring). Unlike every other
    term here, it describes the *race*, not a specific candidate — both
    contestants in an open race get the same value — so its fitted
    contribution is folded into the Baseline/intercept component on
    attribution charts (apply_war) rather than given its own bar, the same
    way a primary's fair_share and intercept are already combined into one
    "Baseline" bar there.

    Demographics (bachelors_pct/hispanic_pct/voting_age_pct/income_10k/
    median_age_10/homeownership_pct/white_pct) and campaign finance
    (fundraising_share) are folded into this same fit as ordinary terms,
    not separate models. Each is centered on its own mean *among the rows
    that actually have it*, and a row missing it gets the mean itself (so
    its centered value is exactly 0) rather than a raw zero or a separate
    indicator dummy — for a linear fit, a row contributing 0 to a term's
    own deviation-from-mean genuinely carries no information about that
    term's coefficient, while its lean/tide/incumbency values still fully
    inform the shared core terms. `fundraising_share` is this candidate's
    own share of the two-party OCPF-matched total for that specific race
    (own_raised / (own_raised + opponent_raised)) — see _fundraising_share's
    own docstring for why this needs both sides matched, not just one.

    Fit via _bayesian_linear_regression (Gibbs sampling, weakly informative
    priors — see its docstring and _COEFFICIENT_PRIORS'), pooled across
    both chambers, both parties (via the sign-flip plus the party-delta
    terms above), and every vintage — this is the only regression this
    site fits for WAR, so every candidate-race that can inform any of its
    terms does."""
    rows = []
    for vintage, records in district_records_by_vintage.items():
        for d in records:
            covariates = _demographic_covariates(d.get("demographics")) if vintage == current_vintage else {}
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                tide = tide_by_year.get(entry["year"])
                approval = approval_by_year.get(entry["year"])
                if tide is None or approval is None:
                    continue
                open_seat_raw = entry.get("is_open_seat")
                open_seat = None if open_seat_raw is None else (1.0 if open_seat_raw else 0.0)
                for c in entry["candidates"]:
                    if c["war"] is None or c["party"] not in ("Democratic", "Republican"):
                        continue
                    is_dem = c["party"] == "Democratic"
                    dem_flag = 1.0 if is_dem else 0.0
                    own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                    own_tide = tide if is_dem else 1 - tide
                    own_approval = approval if is_dem else 1 - approval
                    row = {
                        "own_share": c["actual_two_party_share"],
                        "is_dem": dem_flag,
                        "own_lean": own_lean,
                        "own_lean_x_dem": own_lean * dem_flag,
                        "own_tide": own_tide,
                        "own_tide_x_dem": own_tide * dem_flag,
                        "national_approval": own_approval,
                        "open_seat": open_seat,
                        "bachelors_pct": covariates.get("bachelors_pct"),
                        "hispanic_pct": covariates.get("hispanic_pct"),
                        "voting_age_pct": covariates.get("voting_age_pct"),
                        "income_10k": covariates.get("income_10k"),
                        "median_age_10": covariates.get("median_age_10"),
                        "homeownership_pct": covariates.get("homeownership_pct"),
                        "white_pct": covariates.get("white_pct"),
                        "fundraising_share": _fundraising_share(finance_by_slug, entry, c),
                    }
                    is_incumbent = _is_incumbent_dummy(c.get("incumbent_terms", 0))
                    row["incumbent"] = is_incumbent
                    row["incumbent_x_dem"] = is_incumbent * dem_flag
                    rows.append(row)

    df = pd.DataFrame(rows)

    # Each extension covariate is centered on its own mean among rows
    # that actually have it, then missing rows are filled with that same
    # mean — so their centered value is exactly 0 and they don't move the
    # fitted coefficient, while every row's lean/tide/approval/incumbency
    # values still inform the shared core terms (see this function's own
    # docstring). reference_values is exported so apply_war can reuse the
    # exact same centering when computing each race's own component.
    reference_values = {}
    for col in _GENERAL_EXTENSION_COVARIATES:
        real = df[col].dropna()
        reference_values[col] = float(real.mean()) if len(real) else 0.0
        df[f"n_{col}"] = int(real.count())
        df[col] = df[col].fillna(reference_values[col]) - reference_values[col]

    feature_names = [
        "intercept",
        "is_dem",
        "own_lean",
        "own_lean_x_dem",
        "own_tide",
        "own_tide_x_dem",
        "national_approval",
        "incumbent",
        "incumbent_x_dem",
        "open_seat",
        "bachelors_pct",
        "hispanic_pct",
        "voting_age_pct",
        "income_10k",
        "median_age_10",
        "homeownership_pct",
        "white_pct",
        "fundraising_share",
    ]
    x = np.column_stack([np.ones(len(df))] + [df[name].to_numpy() for name in feature_names[1:]])
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["reference_values"] = reference_values
    fit["n_incumbent"] = int(df["incumbent"].sum())
    fit["n_non_incumbent"] = int(len(df) - df["incumbent"].sum())
    fit["n_open_seat"] = int(df["n_open_seat"].iloc[0])
    fit["n_demographics"] = int(df["n_bachelors_pct"].iloc[0])
    fit["n_finance"] = int(df["n_fundraising_share"].iloc[0])
    return fit


def apply_war(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    approval_by_year: dict[int, float],
    current_vintage: str,
    finance_by_slug: dict,
    fit: dict,
) -> None:
    """Applies fit_war_model's posterior-mean coefficients to every
    candidate-race across every vintage — one model, one number per race.
    Sets war_resolved/expected_share_resolved plus each decomposed
    component — intercept (which also absorbs open_seat's contribution,
    since that term describes the race rather than this specific
    candidate — see fit_war_model's own docstring), lean, tide, national
    approval, incumbency, and (wherever this specific race's own data
    supports them) demographics and/or fundraising, which can both apply
    to the same race at once.

    Mutates candidate dicts inside district_records_by_vintage in place;
    must run after fit_war_model, and before write_district_files/
    write_seat_files/build_candidate_records (build_candidate_records
    copies these fields onto each race, so it needs to run after this,
    not before)."""
    coefs = fit["coefficients"]
    ref = fit["reference_values"]
    b0, b0_sd = coefs["intercept"]["posterior_mean"], coefs["intercept"]["posterior_sd"]
    b_dem, b_dem_sd = coefs["is_dem"]["posterior_mean"], coefs["is_dem"]["posterior_sd"]
    b_lean, b_lean_sd = coefs["own_lean"]["posterior_mean"], coefs["own_lean"]["posterior_sd"]
    b_lean_dem, b_lean_dem_sd = coefs["own_lean_x_dem"]["posterior_mean"], coefs["own_lean_x_dem"]["posterior_sd"]
    b_tide, b_tide_sd = coefs["own_tide"]["posterior_mean"], coefs["own_tide"]["posterior_sd"]
    b_tide_dem, b_tide_dem_sd = coefs["own_tide_x_dem"]["posterior_mean"], coefs["own_tide_x_dem"]["posterior_sd"]
    b_approval, b_approval_sd = coefs["national_approval"]["posterior_mean"], coefs["national_approval"]["posterior_sd"]
    b_inc, b_inc_sd = coefs["incumbent"]["posterior_mean"], coefs["incumbent"]["posterior_sd"]
    b_inc_dem, b_inc_dem_sd = coefs["incumbent_x_dem"]["posterior_mean"], coefs["incumbent_x_dem"]["posterior_sd"]
    b_open, b_open_sd = coefs["open_seat"]["posterior_mean"], coefs["open_seat"]["posterior_sd"]
    b_fund, b_fund_sd = coefs["fundraising_share"]["posterior_mean"], coefs["fundraising_share"]["posterior_sd"]
    sigma = fit["posterior_sigma_mean"]

    for vintage, records in district_records_by_vintage.items():
        for d in records:
            covariates = _demographic_covariates(d.get("demographics")) if vintage == current_vintage else {}
            has_bachelors = "bachelors_pct" in covariates
            has_full_demographics = all(k in covariates for k in _DEMOGRAPHICS_FULL_COVARIATES)
            demographics_tier = "full" if has_full_demographics else "core" if has_bachelors else None

            for entry in d["results_by_year"]:
                tide = tide_by_year.get(entry["year"])
                approval = approval_by_year.get(entry["year"])
                open_seat_raw = entry.get("is_open_seat")
                open_seat_centered = (
                    (1.0 if open_seat_raw else 0.0) if open_seat_raw is not None else ref["open_seat"]
                ) - ref["open_seat"]
                open_seat_component = b_open * open_seat_centered
                open_seat_component_sd = abs(open_seat_centered) * b_open_sd

                for c in entry["candidates"]:
                    if c["war"] is None or tide is None or approval is None or c["party"] not in ("Democratic", "Republican"):
                        c.update(
                            intercept_component=None,
                            intercept_component_sd=None,
                            lean_component=None,
                            lean_component_sd=None,
                            tide_component=None,
                            tide_component_sd=None,
                            approval_component=None,
                            approval_component_sd=None,
                            incumbency_adjustment=None,
                            incumbency_adjustment_sd=None,
                            demographics_component=None,
                            demographics_component_sd=None,
                            fundraising_component=None,
                            fundraising_component_sd=None,
                            demographics_tier=None,
                            expected_share_resolved=None,
                            war_resolved=None,
                            war_resolved_sd=None,
                            war_factors=None,
                        )
                        continue

                    is_dem = c["party"] == "Democratic"
                    dem_flag = 1.0 if is_dem else 0.0
                    own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                    own_tide = tide if is_dem else 1 - tide
                    own_approval = approval if is_dem else 1 - approval
                    is_incumbent = _is_incumbent_dummy(c.get("incumbent_terms", 0))

                    intercept_component = b0 + b_dem * dem_flag + open_seat_component
                    intercept_component_sd = (
                        b0_sd**2 + (dem_flag * b_dem_sd) ** 2 + open_seat_component_sd**2
                    ) ** 0.5
                    lean_component = (b_lean + b_lean_dem * dem_flag) * own_lean
                    lean_component_sd = abs(own_lean) * (b_lean_sd**2 + (dem_flag * b_lean_dem_sd) ** 2) ** 0.5
                    tide_component = (b_tide + b_tide_dem * dem_flag) * own_tide
                    tide_component_sd = abs(own_tide) * (b_tide_sd**2 + (dem_flag * b_tide_dem_sd) ** 2) ** 0.5
                    approval_component = b_approval * own_approval
                    approval_component_sd = abs(own_approval) * b_approval_sd
                    incumbency_component = (b_inc + b_inc_dem * dem_flag) * is_incumbent
                    incumbency_component_sd = (
                        (b_inc_sd**2 + (dem_flag * b_inc_dem_sd) ** 2) ** 0.5 if is_incumbent else 0.0
                    )

                    if has_bachelors:
                        demo_terms = [("bachelors_pct", covariates["bachelors_pct"])]
                        if has_full_demographics:
                            demo_terms += [
                                ("hispanic_pct", covariates["hispanic_pct"]),
                                ("voting_age_pct", covariates["voting_age_pct"]),
                                ("income_10k", covariates["income_10k"]),
                                ("median_age_10", covariates["median_age_10"]),
                                ("homeownership_pct", covariates["homeownership_pct"]),
                                ("white_pct", covariates["white_pct"]),
                            ]
                        demographics_component = sum(
                            coefs[name]["posterior_mean"] * (value - ref[name]) for name, value in demo_terms
                        )
                        demographics_component_sd = (
                            sum((coefs[name]["posterior_sd"] * (value - ref[name])) ** 2 for name, value in demo_terms)
                            ** 0.5
                        )
                    else:
                        demographics_component = None
                        demographics_component_sd = None

                    fundraising_share = _fundraising_share(finance_by_slug, entry, c)
                    if fundraising_share is not None:
                        fundraising_component = b_fund * (fundraising_share - ref["fundraising_share"])
                        fundraising_component_sd = abs(fundraising_share - ref["fundraising_share"]) * b_fund_sd
                    else:
                        fundraising_component = None
                        fundraising_component_sd = None

                    expected = (
                        intercept_component
                        + lean_component
                        + tide_component
                        + approval_component
                        + incumbency_component
                        + (demographics_component or 0.0)
                        + (fundraising_component or 0.0)
                    )

                    factors = ["District lean", "Statewide tide", "National presidential approval", "Incumbency"]
                    if demographics_component is not None:
                        factors.append(
                            "District demographics (bachelor's degree %, Hispanic/Latino %, voting-age %, income, "
                            "median age, homeownership %, white %)"
                            if has_full_demographics
                            else "District demographics (bachelor's degree %)"
                        )
                    if fundraising_component is not None:
                        factors.append("Relative campaign fundraising")

                    c.update(
                        intercept_component=round(intercept_component, 4),
                        intercept_component_sd=round(intercept_component_sd, 4),
                        lean_component=round(lean_component, 4),
                        lean_component_sd=round(lean_component_sd, 4),
                        tide_component=round(tide_component, 4),
                        tide_component_sd=round(tide_component_sd, 4),
                        approval_component=round(approval_component, 4),
                        approval_component_sd=round(approval_component_sd, 4),
                        incumbency_adjustment=round(incumbency_component, 4),
                        incumbency_adjustment_sd=round(incumbency_component_sd, 4),
                        demographics_component=round(demographics_component, 4) if demographics_component is not None else None,
                        demographics_component_sd=(
                            round(demographics_component_sd, 4) if demographics_component_sd is not None else None
                        ),
                        fundraising_component=round(fundraising_component, 4) if fundraising_component is not None else None,
                        fundraising_component_sd=(
                            round(fundraising_component_sd, 4) if fundraising_component_sd is not None else None
                        ),
                        demographics_tier=demographics_tier,
                        expected_share_resolved=round(expected, 4),
                        war_resolved=(
                            None if entry["is_uncontested"] else round(c["actual_two_party_share"] - expected, 4)
                        ),
                        war_resolved_sd=None if entry["is_uncontested"] else round(sigma, 4),
                        war_factors=factors,
                    )


def fit_us_house_war_model(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    approval_by_year: dict[int, float],
) -> dict:
    """MA's U.S. House delegation gets its own, separate regression from
    the state House/Senate model above — a direct user choice, not a
    default: 9-10 large congressional districts covering the whole state
    is a genuinely different population from 160+40 small state-
    legislative ones (different district sizes, different candidate pool,
    different fundraising scale), and pooling the two into one fit would
    let 1,500+ state-legislative rows dominate a coefficient meant to
    describe a completely different kind of race. `district_records_by_
    vintage` here must contain ONLY chamber="us-house" records — callers
    keep this fit's input strictly separate from the state model's own
    (never merge the two before both fits have run; see main()'s own
    ordering) — otherwise a district lean/tide computed for a
    congressional district would leak into the state fit's own training
    sample and vice versa.

        own_share ~ ush_intercept + ush_is_dem
                     + ush_own_lean          + ush_own_lean_x_dem
                     + ush_own_tide          + ush_own_tide_x_dem
                     + ush_national_approval
                     + ush_incumbent         + ush_incumbent_x_dem
                     + ush_open_seat

    Same core-term shape and own-party sign-flip convention as
    fit_war_model (see its own docstring for what "own_*" means and why
    the `_x_dem` terms exist), including national_approval and open_seat
    (neither depends on the two data sources this model still lacks —
    national approval is a national-level series, not congressional-
    district-specific, and open-seat status comes straight out of PD43+'s
    own already-fetched results) — but still no demographics or
    fundraising extension: MA's congressional districts have no
    demographics crosswalk built (Census PL 94-171/ACS matching here would
    need its own new district roster, not done this round) and campaign
    finance for federal candidates lives at the FEC, not OCPF (this site's
    only campaign-finance source, which covers state filers only) — both
    real, documented gaps (see methodology.md), not silent omissions."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            if d["chamber"] != "us-house":
                continue
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                tide = tide_by_year.get(entry["year"])
                approval = approval_by_year.get(entry["year"])
                if tide is None or approval is None:
                    continue
                open_seat_raw = entry.get("is_open_seat")
                open_seat = None if open_seat_raw is None else (1.0 if open_seat_raw else 0.0)
                for c in entry["candidates"]:
                    if c["war"] is None or c["party"] not in ("Democratic", "Republican"):
                        continue
                    is_dem = c["party"] == "Democratic"
                    dem_flag = 1.0 if is_dem else 0.0
                    own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                    own_tide = tide if is_dem else 1 - tide
                    own_approval = approval if is_dem else 1 - approval
                    is_incumbent = _is_incumbent_dummy(c.get("incumbent_terms", 0))
                    rows.append(
                        {
                            "own_share": c["actual_two_party_share"],
                            "is_dem": dem_flag,
                            "own_lean": own_lean,
                            "own_lean_x_dem": own_lean * dem_flag,
                            "own_tide": own_tide,
                            "own_tide_x_dem": own_tide * dem_flag,
                            "national_approval": own_approval,
                            "incumbent": is_incumbent,
                            "incumbent_x_dem": is_incumbent * dem_flag,
                            "open_seat": open_seat,
                        }
                    )

    df = pd.DataFrame(rows)

    reference_values = {}
    real = df["open_seat"].dropna()
    reference_values["open_seat"] = float(real.mean()) if len(real) else 0.0
    df["n_open_seat"] = int(real.count())
    df["open_seat"] = df["open_seat"].fillna(reference_values["open_seat"]) - reference_values["open_seat"]

    feature_names = [
        "ush_intercept",
        "ush_is_dem",
        "ush_own_lean",
        "ush_own_lean_x_dem",
        "ush_own_tide",
        "ush_own_tide_x_dem",
        "ush_national_approval",
        "ush_incumbent",
        "ush_incumbent_x_dem",
        "ush_open_seat",
    ]
    raw_cols = [
        "is_dem",
        "own_lean",
        "own_lean_x_dem",
        "own_tide",
        "own_tide_x_dem",
        "national_approval",
        "incumbent",
        "incumbent_x_dem",
        "open_seat",
    ]
    x = np.column_stack([np.ones(len(df))] + [df[name].to_numpy() for name in raw_cols])
    fit = _bayesian_linear_regression(x, df["own_share"].to_numpy(), feature_names)
    fit["reference_values"] = reference_values
    fit["n_incumbent"] = int(df["incumbent"].sum())
    fit["n_non_incumbent"] = int(len(df) - df["incumbent"].sum())
    fit["n_open_seat"] = int(df["n_open_seat"].iloc[0])
    return fit


def apply_us_house_war(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    approval_by_year: dict[int, float],
    fit: dict,
) -> None:
    """apply_war's counterpart for fit_us_house_war_model — same
    intercept(+open-seat)/lean/tide/approval/incumbency decomposition, no
    demographics/fundraising branches (see fit_us_house_war_model's own
    docstring for why). Sets the same war_resolved/expected_share_resolved/
    war_factors field names as apply_war, not a distinctly-prefixed set,
    since a congressional district/seat/candidate page reuses the exact
    same district/seat/candidate.html templates as a state one and those
    templates read those field names directly — only ever called on
    records already filtered to chamber="us-house" (see this function's
    own caller in main())."""
    coefs = fit["coefficients"]
    ref = fit["reference_values"]
    b0, b0_sd = coefs["ush_intercept"]["posterior_mean"], coefs["ush_intercept"]["posterior_sd"]
    b_dem, b_dem_sd = coefs["ush_is_dem"]["posterior_mean"], coefs["ush_is_dem"]["posterior_sd"]
    b_lean, b_lean_sd = coefs["ush_own_lean"]["posterior_mean"], coefs["ush_own_lean"]["posterior_sd"]
    b_lean_dem, b_lean_dem_sd = coefs["ush_own_lean_x_dem"]["posterior_mean"], coefs["ush_own_lean_x_dem"]["posterior_sd"]
    b_tide, b_tide_sd = coefs["ush_own_tide"]["posterior_mean"], coefs["ush_own_tide"]["posterior_sd"]
    b_tide_dem, b_tide_dem_sd = coefs["ush_own_tide_x_dem"]["posterior_mean"], coefs["ush_own_tide_x_dem"]["posterior_sd"]
    b_approval, b_approval_sd = (
        coefs["ush_national_approval"]["posterior_mean"],
        coefs["ush_national_approval"]["posterior_sd"],
    )
    b_inc, b_inc_sd = coefs["ush_incumbent"]["posterior_mean"], coefs["ush_incumbent"]["posterior_sd"]
    b_inc_dem, b_inc_dem_sd = coefs["ush_incumbent_x_dem"]["posterior_mean"], coefs["ush_incumbent_x_dem"]["posterior_sd"]
    b_open, b_open_sd = coefs["ush_open_seat"]["posterior_mean"], coefs["ush_open_seat"]["posterior_sd"]
    sigma = fit["posterior_sigma_mean"]

    for records in district_records_by_vintage.values():
        for d in records:
            if d["chamber"] != "us-house":
                continue
            for entry in d["results_by_year"]:
                tide = tide_by_year.get(entry["year"])
                approval = approval_by_year.get(entry["year"])
                open_seat_raw = entry.get("is_open_seat")
                open_seat_centered = (
                    (1.0 if open_seat_raw else 0.0) if open_seat_raw is not None else ref["open_seat"]
                ) - ref["open_seat"]
                open_seat_component = b_open * open_seat_centered
                open_seat_component_sd = abs(open_seat_centered) * b_open_sd

                for c in entry["candidates"]:
                    if c["war"] is None or tide is None or approval is None or c["party"] not in ("Democratic", "Republican"):
                        c.update(
                            intercept_component=None,
                            intercept_component_sd=None,
                            lean_component=None,
                            lean_component_sd=None,
                            tide_component=None,
                            tide_component_sd=None,
                            approval_component=None,
                            approval_component_sd=None,
                            incumbency_adjustment=None,
                            incumbency_adjustment_sd=None,
                            demographics_component=None,
                            demographics_component_sd=None,
                            fundraising_component=None,
                            fundraising_component_sd=None,
                            demographics_tier=None,
                            expected_share_resolved=None,
                            war_resolved=None,
                            war_resolved_sd=None,
                            war_factors=None,
                        )
                        continue

                    is_dem = c["party"] == "Democratic"
                    dem_flag = 1.0 if is_dem else 0.0
                    own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                    own_tide = tide if is_dem else 1 - tide
                    own_approval = approval if is_dem else 1 - approval
                    is_incumbent = _is_incumbent_dummy(c.get("incumbent_terms", 0))

                    intercept_component = b0 + b_dem * dem_flag + open_seat_component
                    intercept_component_sd = (
                        b0_sd**2 + (dem_flag * b_dem_sd) ** 2 + open_seat_component_sd**2
                    ) ** 0.5
                    lean_component = (b_lean + b_lean_dem * dem_flag) * own_lean
                    lean_component_sd = abs(own_lean) * (b_lean_sd**2 + (dem_flag * b_lean_dem_sd) ** 2) ** 0.5
                    tide_component = (b_tide + b_tide_dem * dem_flag) * own_tide
                    tide_component_sd = abs(own_tide) * (b_tide_sd**2 + (dem_flag * b_tide_dem_sd) ** 2) ** 0.5
                    approval_component = b_approval * own_approval
                    approval_component_sd = abs(own_approval) * b_approval_sd
                    incumbency_component = (b_inc + b_inc_dem * dem_flag) * is_incumbent
                    incumbency_component_sd = (
                        (b_inc_sd**2 + (dem_flag * b_inc_dem_sd) ** 2) ** 0.5 if is_incumbent else 0.0
                    )

                    expected = (
                        intercept_component + lean_component + tide_component + approval_component + incumbency_component
                    )

                    c.update(
                        intercept_component=round(intercept_component, 4),
                        intercept_component_sd=round(intercept_component_sd, 4),
                        lean_component=round(lean_component, 4),
                        lean_component_sd=round(lean_component_sd, 4),
                        tide_component=round(tide_component, 4),
                        tide_component_sd=round(tide_component_sd, 4),
                        approval_component=round(approval_component, 4),
                        approval_component_sd=round(approval_component_sd, 4),
                        incumbency_adjustment=round(incumbency_component, 4),
                        incumbency_adjustment_sd=round(incumbency_component_sd, 4),
                        demographics_component=None,
                        demographics_component_sd=None,
                        fundraising_component=None,
                        fundraising_component_sd=None,
                        demographics_tier=None,
                        expected_share_resolved=round(expected, 4),
                        war_resolved=(
                            None if entry["is_uncontested"] else round(c["actual_two_party_share"] - expected, 4)
                        ),
                        war_resolved_sd=None if entry["is_uncontested"] else round(sigma, 4),
                        war_factors=["District lean", "Statewide tide", "National presidential approval", "Incumbency"],
                    )


def build_war_fit_sample(district_records_by_vintage: dict[str, list[dict]]) -> list[dict]:
    """Every contested major-party candidate-race's actual vs. this
    site's one fitted model's expected share, party, and year — the same
    population fit_war_model trained its core terms on (must be called
    after apply_war, so expected_share_resolved is populated). Exists
    purely for the methodology page's "actual vs. expected" scatter and
    Democratic-vs-Republican residual histogram, which need a full sample
    to plot rather than the summary statistics war_model.yml already
    carries — written to site/_data/war_fit_sample.yml so the page can
    embed it directly via Jekyll's site.data, the same pattern already
    used for the fitted coefficients themselves."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for entry in d["results_by_year"]:
                if entry["is_uncontested"]:
                    continue
                for c in entry["candidates"]:
                    if c.get("expected_share_resolved") is None or c["party"] not in ("Democratic", "Republican"):
                        continue
                    rows.append(
                        {
                            "actual": c["actual_two_party_share"],
                            "expected": c["expected_share_resolved"],
                            "party": c["party"],
                            "year": entry["year"],
                        }
                    )
    return rows


def fit_primary_war_model(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    finance_by_slug: dict,
) -> dict:
    """A second, much smaller regression alongside fit_war_model — a
    primary needs its own model, not more rows in the general one, because
    a primary is a genuinely different contest: intra-party (2+ candidates
    of the *same* party, no two-party split) rather than inter-party, so
    there's no district lean/statewide tide baseline the way a general has
    on its own. Fit across every contested major-party primary this site
    has (2002-2026, specials included — unlike a general's district
    records, which never carry special-election rows at all, per
    derived_metrics.compute_war's own docstring, this one is being built
    from scratch with specials in scope from the start):

        excess_share ~ primary_intercept
                        + primary_incumbent
                        + primary_incumbent_x_tide
                        + primary_incumbent_x_lean
                        + primary_log_raised

    `excess_share` is actual_primary_share minus fair_share (1 /
    n_candidates) — a primary's own field size sets its "no-information"
    baseline the way 50% does for a two-candidate general, so the response
    here is the deviation *from* that baseline rather than raw share
    directly, which would otherwise need a separate intercept per field
    size to mean the same thing. `primary_incumbent` is a single dummy
    (the district's own sitting officeholder as of that primary — see
    build_district_records' own primaries-block docstring for exactly how
    "as of" is resolved), not further split by term count the way an
    earlier version of fit_war_model's own incumbency term briefly was,
    for the same reason: this project doesn't have enough contested-
    primary rows to support that many parameters. `own_tide`/`own_lean`
    reuse fit_war_model's own-party sign-flip convention (own_lean =
    lean_dem_share_structural for a Democratic primary, 1 - it for a
    Republican one; same for tide) so one pooled fit covers both parties'
    primaries — but neither appears as its own main effect here, only
    interacted with incumbency: there's no a priori reason a *non*-
    incumbent's share of their own party's primary electorate should track
    the district's general-election partisanship, but a real question
    worth asking is whether an incumbent's primary strength scales with
    how safe their seat is (own_lean) or with the political mood their
    own party is riding that cycle (own_tide) — that's what those two
    interaction terms exist to test, not to assert.

    A primary race with no tide value for its year (this project's 2026
    data right now — see discover_primary_years) is skipped entirely: the
    fit needs own_tide for every row, not just the ones with an incumbent,
    since dropping it would silently shrink the sample by exactly however
    many non-incumbent rows happen to fall in an undated year, which is a
    real bias risk for a sample already this size-constrained rather than
    a defensible simplification."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for p in d["primaries"]:
                if not p["is_contested"] or p["party"] not in ("Democratic", "Republican"):
                    continue
                tide = tide_by_year.get(p["year"])
                if tide is None:
                    continue
                is_dem = p["party"] == "Democratic"
                own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                own_tide = tide if is_dem else 1 - tide
                fair_share = 1.0 / p["n_candidates"]
                for c in p["candidates"]:
                    inc = 1.0 if c["is_incumbent"] else 0.0
                    finance = finance_by_slug.get(c["slug"], {}).get("by_year", {}).get(p["year"])
                    raised = finance["total_raised"] if finance else None
                    rows.append(
                        {
                            "excess_share": c["actual_primary_share"] - fair_share,
                            "primary_incumbent": inc,
                            "primary_incumbent_x_tide": inc * own_tide,
                            "primary_incumbent_x_lean": inc * own_lean,
                            "primary_log_raised": float(np.log1p(raised)) if raised is not None else None,
                        }
                    )

    df = pd.DataFrame(rows)

    # Same mean-centering/mean-fill convention as fit_war_model's own
    # extension covariates — see that function's own docstring for why.
    reference_values = {}
    real = df["primary_log_raised"].dropna()
    reference_values["log_raised"] = float(real.mean()) if len(real) else 0.0
    n_finance = int(real.count())
    # .astype(float) guards against the all-None edge case (no OCPF data at
    # all, e.g. a partial local run) — a column with zero real values
    # infers as pandas object dtype even after fillna, which np.linalg.
    # lstsq below can't cast; a column with at least one real value never
    # hits this, since pandas infers float64 from the start.
    df["primary_log_raised"] = (
        df["primary_log_raised"].fillna(reference_values["log_raised"]).astype(float) - reference_values["log_raised"]
    )

    feature_names = [
        "primary_intercept",
        "primary_incumbent",
        "primary_incumbent_x_tide",
        "primary_incumbent_x_lean",
        "primary_log_raised",
    ]
    x = np.column_stack([np.ones(len(df))] + [df[name].to_numpy() for name in feature_names[1:]])
    fit = _bayesian_linear_regression(x, df["excess_share"].to_numpy(), feature_names)
    fit["reference_values"] = reference_values
    fit["n_incumbent"] = int(df["primary_incumbent"].sum())
    fit["n_non_incumbent"] = int(len(df) - df["primary_incumbent"].sum())
    fit["n_finance"] = n_finance
    return fit


def apply_primary_war(
    district_records_by_vintage: dict[str, list[dict]],
    tide_by_year: dict[int, float],
    finance_by_slug: dict,
    fit: dict,
) -> None:
    """Applies fit_primary_war_model's posterior-mean coefficients to every
    primary candidate across every vintage, mutating d["primaries"] in
    place — must run after fit_primary_war_model, and before
    build_candidate_records (which copies these fields onto each
    candidate's own race entries).

    Sets primary_war/primary_expected_share (the primary-specific
    counterparts to apply_war's war_resolved/expected_share_resolved,
    kept as distinct field names since the two aren't on the same scale —
    a primary's "expected share" is relative to an N-candidate field, a
    general's to a two-party baseline) plus a decomposed
    primary_baseline_component (fair_share + the fitted intercept, shown
    as one combined bar rather than two on the attribution chart — see
    the candidate-page template for why), primary_incumbency_component,
    and, wherever a matched OCPF total supports it,
    primary_fundraising_component.

    Each candidate's raw prediction (fair_share + intercept + their own
    incumbency/fundraising terms) is computed first, then every candidate
    in that race is rescaled by one shared factor so the race's own
    expected shares sum to exactly 1 — asked for directly, after an
    uncontested incumbent's raw prediction was found live to read as high
    as 132% (e.g. William N. Brownsberger, whose 132%-in-2018 case is what
    prompted this), which is right but easy to misread as a data error: a
    single candidate's own "expected share of this specific race's vote"
    should top out at 100% by definition, whatever the raw model implies
    about how strong an incumbent they are. Rescaling (not clamping) keeps
    the relative signal intact — a candidate the raw model favors more
    still ends up with a higher normalized share than one it favors less
    — and the same shared factor is applied to every component
    (baseline/incumbency/fundraising, and their SDs), so they still sum
    exactly to the normalized expected share. The underlying regression
    itself (fit_primary_war_model, and every coefficient shown on the
    methodology page) is unchanged — only this application step, turning
    those coefficients into one race's own predicted split, changed.

    Skipped (falls back to the unnormalized raw values, same as before
    this rescaling existed) only when some candidate in the race has no
    raw prediction at all — an incumbent running in a year with no tide
    data yet (2026, currently) — since a race missing one participant's
    prediction has nothing valid to rescale against."""
    coefs = fit["coefficients"]
    ref = fit["reference_values"]
    b0, b0_sd = coefs["primary_intercept"]["posterior_mean"], coefs["primary_intercept"]["posterior_sd"]
    b_inc, b_inc_sd = coefs["primary_incumbent"]["posterior_mean"], coefs["primary_incumbent"]["posterior_sd"]
    b_inc_tide, b_inc_tide_sd = (
        coefs["primary_incumbent_x_tide"]["posterior_mean"],
        coefs["primary_incumbent_x_tide"]["posterior_sd"],
    )
    b_inc_lean, b_inc_lean_sd = (
        coefs["primary_incumbent_x_lean"]["posterior_mean"],
        coefs["primary_incumbent_x_lean"]["posterior_sd"],
    )
    b_fin, b_fin_sd = coefs["primary_log_raised"]["posterior_mean"], coefs["primary_log_raised"]["posterior_sd"]
    sigma = fit["posterior_sigma_mean"]

    for records in district_records_by_vintage.values():
        for d in records:
            for p in d["primaries"]:
                if p["party"] not in ("Democratic", "Republican"):
                    for c in p["candidates"]:
                        c.update(
                            fair_share=None,
                            primary_baseline_component=None,
                            primary_baseline_component_sd=None,
                            primary_incumbency_component=None,
                            primary_incumbency_component_sd=None,
                            primary_fundraising_component=None,
                            primary_fundraising_component_sd=None,
                            primary_expected_share=None,
                            primary_war=None,
                            primary_war_sd=None,
                            primary_war_factors=None,
                        )
                    continue

                is_dem = p["party"] == "Democratic"
                own_lean = d["lean_dem_share_structural"] if is_dem else 1 - d["lean_dem_share_structural"]
                tide = tide_by_year.get(p["year"])
                own_tide = tide if (tide is None or is_dem) else 1 - tide
                fair_share = 1.0 / p["n_candidates"]
                baseline_component = fair_share + b0

                # Pass 1: each candidate's own raw (unrescaled) prediction.
                raw_by_slug: dict[str, dict | None] = {}
                for c in p["candidates"]:
                    inc = 1.0 if c["is_incumbent"] else 0.0
                    if c["is_incumbent"] and own_tide is None:
                        # Can't compute this specific incumbent's own
                        # tide-interacted contribution — see this
                        # function's own docstring / fit_primary_war_
                        # model's for why a missing tide isn't worked
                        # around rather than left null.
                        raw_by_slug[c["slug"]] = None
                        continue

                    own_tide_for_calc = own_tide if own_tide is not None else 0.0
                    incumbency_component = (b_inc + b_inc_tide * own_tide_for_calc + b_inc_lean * own_lean) * inc
                    incumbency_component_sd = (
                        (b_inc_sd**2 + (own_tide_for_calc * b_inc_tide_sd) ** 2 + (own_lean * b_inc_lean_sd) ** 2) ** 0.5
                        if inc
                        else 0.0
                    )

                    finance = finance_by_slug.get(c["slug"], {}).get("by_year", {}).get(p["year"])
                    raised = finance["total_raised"] if finance else None
                    if raised is not None:
                        log_raised = float(np.log1p(raised))
                        fundraising_component = b_fin * (log_raised - ref["log_raised"])
                        fundraising_component_sd = abs(log_raised - ref["log_raised"]) * b_fin_sd
                    else:
                        fundraising_component = None
                        fundraising_component_sd = None

                    expected = baseline_component + incumbency_component + (fundraising_component or 0.0)
                    raw_by_slug[c["slug"]] = dict(
                        baseline=baseline_component,
                        incumbency=incumbency_component,
                        incumbency_sd=incumbency_component_sd,
                        fundraising=fundraising_component,
                        fundraising_sd=fundraising_component_sd,
                        expected=expected,
                        inc=inc,
                    )

                # Pass 2: one shared rescale factor per race — see this
                # function's own docstring for why (and when skipped).
                any_missing = any(v is None for v in raw_by_slug.values())
                total_raw = None if any_missing else sum(v["expected"] for v in raw_by_slug.values())
                factor = 1.0 if (any_missing or not total_raw) else 1.0 / total_raw

                for c in p["candidates"]:
                    r = raw_by_slug[c["slug"]]
                    if r is None:
                        c.update(
                            fair_share=round(fair_share, 4),
                            primary_baseline_component=None,
                            primary_baseline_component_sd=None,
                            primary_incumbency_component=None,
                            primary_incumbency_component_sd=None,
                            primary_fundraising_component=None,
                            primary_fundraising_component_sd=None,
                            primary_expected_share=None,
                            primary_war=None,
                            primary_war_sd=None,
                            primary_war_factors=None,
                        )
                        continue

                    fundraising_component = r["fundraising"] * factor if r["fundraising"] is not None else None
                    fundraising_component_sd = (
                        r["fundraising_sd"] * factor if r["fundraising_sd"] is not None else None
                    )
                    expected = r["expected"] * factor

                    factors = ["Equal share among candidates"]
                    if r["inc"]:
                        factors.append("Incumbency (interacted with statewide tide and district lean)")
                    if fundraising_component is not None:
                        factors.append("Campaign fundraising")

                    c.update(
                        fair_share=round(fair_share, 4),
                        primary_baseline_component=round(r["baseline"] * factor, 4),
                        primary_baseline_component_sd=round(b0_sd * factor, 4),
                        primary_incumbency_component=round(r["incumbency"] * factor, 4),
                        primary_incumbency_component_sd=round(r["incumbency_sd"] * factor, 4),
                        primary_fundraising_component=(
                            round(fundraising_component, 4) if fundraising_component is not None else None
                        ),
                        primary_fundraising_component_sd=(
                            round(fundraising_component_sd, 4) if fundraising_component_sd is not None else None
                        ),
                        primary_expected_share=round(expected, 4),
                        primary_war=(
                            None if not p["is_contested"] else round(c["actual_primary_share"] - expected, 4)
                        ),
                        primary_war_sd=None if not p["is_contested"] else round(sigma, 4),
                        primary_war_factors=factors,
                    )


def build_primary_war_fit_sample(district_records_by_vintage: dict[str, list[dict]]) -> list[dict]:
    """Every contested major-party primary candidate's actual vs. this
    site's fitted primary model's expected share, for the methodology
    page's own diagnostic chart — same role build_war_fit_sample plays for
    the general model."""
    rows = []
    for records in district_records_by_vintage.values():
        for d in records:
            for p in d["primaries"]:
                if not p["is_contested"] or p["party"] not in ("Democratic", "Republican"):
                    continue
                for c in p["candidates"]:
                    if c.get("primary_expected_share") is None:
                        continue
                    rows.append(
                        {
                            "actual": c["actual_primary_share"],
                            "expected": c["primary_expected_share"],
                            "party": c["party"],
                            "year": p["year"],
                            "is_special": p["is_special"],
                        }
                    )
    return rows


_DEMOGRAPHICS_CORE_COVARIATES = ("bachelors_pct",)
_DEMOGRAPHICS_FULL_COVARIATES = (
    "bachelors_pct",
    "hispanic_pct",
    "voting_age_pct",
    "income_10k",
    "median_age_10",
    "homeownership_pct",
    "white_pct",
)


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
    years). `income_10k` is median household income in $10,000 units.

    `median_age_10`/`homeownership_pct`/`white_pct` are all ACS-only (median
    age needs no separate denominator; homeownership and race both pair a
    numerator and denominator from the *same* ACS table) — so, unlike
    hispanic_pct/voting_age_pct, they ride along with bachelors_pct/
    income_10k on whichever tier a district's ACS match already supports,
    rather than adding a third core/full split of their own. `median_age_10`
    is median age in decades (so a district going from 35 to 45 is a 1-unit
    swing, the same "divide a real-world unit down to a comparably-sized
    step" scaling `income_10k` already uses); `homeownership_pct`/
    `white_pct` are 0-1 population shares like `bachelors_pct`."""
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
    if demographics.get("median_age") is not None:
        covariates["median_age_10"] = demographics["median_age"] / 10
    if demographics.get("occupied_housing_units") and demographics.get("owner_occupied_housing_units") is not None:
        covariates["homeownership_pct"] = demographics["owner_occupied_housing_units"] / demographics["occupied_housing_units"]
    if demographics.get("total_population_race") and demographics.get("white_alone_not_hispanic_population") is not None:
        covariates["white_pct"] = demographics["white_alone_not_hispanic_population"] / demographics["total_population_race"]
    return covariates


def build_district_records(chamber: str, vintage: str, derived_dir: Path) -> list[dict]:
    years = discover_years(chamber, vintage, derived_dir)
    if not years:
        return []

    lean_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{vintage}_{y}_lean.parquet") for y in years}
    war_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{y}_war.parquet") for y in years}
    # Discovered independently of `years` above — see discover_primary_years'
    # own docstring for why a primary year doesn't need a same-year lean
    # file to exist first.
    primary_years = discover_primary_years(chamber, vintage, derived_dir)
    primary_by_year = {y: pd.read_parquet(derived_dir / f"{chamber}_{y}_primary.parquet") for y in primary_years}

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
        # winner_terms_after_year[Y] = (winner slug, consecutive terms
        # completed) immediately after year Y's own race — i.e. counting
        # the term they just won, unlike the pre-race incumbent_terms
        # above. Feeds the primary incumbency lookup below: a primary
        # happens before that same year's general, so what matters there
        # is how many terms the *most recent prior* general's winner has
        # completed as of now, not how many they'd served walking in.
        terms_served = 0
        current_winner_slug = None
        winner_terms_after_year: dict[int, tuple[str, int] | None] = {}
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
            winner_terms_after_year[entry["year"]] = (
                (current_winner_slug, terms_served) if current_winner_slug is not None else None
            )

        # Primary results — a separate list, not folded into results_by_year
        # above, since a primary year doesn't always line up 1:1 with a
        # general year (this project's own 2026 data has primaries with no
        # same-year general yet — see discover_primary_years) and a single
        # (year, party) can itself hold two races, a regular primary and a
        # special one (grouped by election_id below, not just year+party,
        # for exactly that reason — see derived_metrics.compute_primary_
        # results' own docstring). is_incumbent for a primary candidate
        # looks up the most recent *general*-election winner strictly
        # before that primary's own year (a primary happens before that
        # same year's general, so that year's own general result — even if
        # one exists — isn't known yet at primary time), and how many terms
        # they've completed as of now (winner_terms_after_year, not the
        # pre-race incumbent_terms above — a candidate who just won their
        # first general has completed 1 term by the time the next primary
        # rolls around, not 0).
        primaries = []
        for y in primary_years:
            district_primary = primary_by_year[y][primary_by_year[y]["district_name"] == district_name]
            if district_primary.empty:
                continue
            prior_general_year = max((gy for gy in winner_terms_after_year if gy < y), default=None)
            incumbent_slug, incumbent_terms_at_primary = (
                winner_terms_after_year.get(prior_general_year) or (None, 0)
                if prior_general_year is not None
                else (None, 0)
            )
            for election_id, race in district_primary.groupby("election_id", sort=False):
                candidates = _primary_candidate_list(race)
                for c in candidates:
                    c["is_incumbent"] = incumbent_slug is not None and c["slug"] == incumbent_slug
                    c["incumbent_terms"] = incumbent_terms_at_primary if c["is_incumbent"] else 0
                primaries.append(
                    {
                        "year": y,
                        "party": race["party"].iloc[0],
                        "is_special": bool(race["is_special"].iloc[0]),
                        "n_candidates": int(race["n_candidates"].iloc[0]),
                        "is_contested": bool(race["is_contested"].iloc[0]),
                        "candidates": candidates,
                    }
                )
        primaries.sort(key=lambda p: (-p["year"], p["is_special"], p["party"]))

        latest = results_by_year[0]
        # This district's *structural* lean — the plain average of
        # lean_dem_share across every year on record for it within this
        # vintage — feeds fit_war_model's own_lean term below, kept
        # distinct from the per-year lean_dem_share above (which stays
        # the "most recent election" figure district pages already show,
        # and which the trend chart still plots year by year). Per-year
        # lean and statewide tide are both derived from the *same* year's
        # baseline race, just at different geographic granularity — highly
        # correlated, which the regression used to have to regularize its
        # way around. Averaging lean across years instead makes it track
        # a district's long-run partisan baseline ("normal vote," in the
        # Gelman & King framing this site's own methodology page already
        # cites) while tide alone carries the year-to-year national/state
        # swing — the two are no longer measuring near-overlapping things.
        # A district with only one year on record so far has a degenerate
        # one-value "average" (itself), same as before; it refines as more
        # years backfill in, like every other multi-year derived stat here.
        lean_structural = round(
            sum(ry["lean_dem_share"] for ry in results_by_year) / len(results_by_year), 4
        )
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
                "lean_dem_share_structural": lean_structural,
                "competitiveness": latest["competitiveness"],
                "competitiveness_label": latest["competitiveness_label"],
                "party_favored": latest["party_favored"],
                "results_by_year": results_by_year,
                "primaries": primaries,
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


def build_vintage_chain_index(
    district_records_by_vintage: dict[str, list[dict]],
    lineage: pd.DataFrame,
    current_vintage: str,
) -> dict[tuple[str, str, str], list[dict]]:
    """For every (chamber, vintage, district_name) across every vintage,
    the full lineage chain that node belongs to, oldest vintage first —
    a vintage-picker dropdown's own data source, on both district and seat
    pages (asked for directly, after noticing a district/seat page had no
    way to jump straight to another era of the same area without going
    through a seat page's "Before redistricting" list first).

    Built by walking seat_lineage both backward (predecessor: same best-
    area-overlap rule build_seat_records' own `history` list already uses
    — the old district that contributed the most area to this one) and
    forward (successor: the same rule mirrored — of this district's own
    area, which single later district absorbed the most of it, reusing
    `pct_of_old_area` rather than a new column, since it's already exactly
    "share of the OLD district's own area" from either direction) from
    that node. Chain identity doesn't depend on which node you start
    from, so every member of one lineage family gets the identical list.

    Each entry's `url` points at the seat page for the current vintage
    (this site's canonical current-vintage URL) or the district page for
    any other vintage — and is None if that specific (chamber, vintage,
    district_name) never actually got built this run (a lineage row can
    exist for a district/chamber combination this run didn't backfill)."""
    exists = {
        (r["chamber"], vintage, r["district_name"])
        for vintage, recs in district_records_by_vintage.items()
        for r in recs
    }

    def predecessor(chamber: str, vintage: str, name: str) -> tuple[str, str] | None:
        rows = lineage[
            (lineage["chamber"] == chamber)
            & (lineage["new_vintage"] == vintage)
            & (lineage["new_district_name"] == name)
        ]
        if rows.empty:
            return None
        best = rows.sort_values("pct_of_old_area", ascending=False).iloc[0]
        return (best["old_vintage"], best["old_district_name"])

    def successor(chamber: str, vintage: str, name: str) -> tuple[str, str] | None:
        rows = lineage[
            (lineage["chamber"] == chamber)
            & (lineage["old_vintage"] == vintage)
            & (lineage["old_district_name"] == name)
        ]
        if rows.empty:
            return None
        best = rows.sort_values("pct_of_old_area", ascending=False).iloc[0]
        return (best["new_vintage"], best["new_district_name"])

    index: dict[tuple[str, str, str], list[dict]] = {}
    for vintage, recs in district_records_by_vintage.items():
        for r in recs:
            chamber, name = r["chamber"], r["district_name"]
            key = (chamber, vintage, name)
            if key in index:
                continue

            chain = [(vintage, name)]
            seen_vintages = {vintage}
            cur_v, cur_n = vintage, name
            while True:
                prev = predecessor(chamber, cur_v, cur_n)
                if prev is None or prev[0] in seen_vintages:
                    break
                chain.insert(0, prev)
                seen_vintages.add(prev[0])
                cur_v, cur_n = prev

            cur_v, cur_n = vintage, name
            while True:
                nxt = successor(chamber, cur_v, cur_n)
                if nxt is None or nxt[0] in seen_vintages:
                    break
                chain.append(nxt)
                seen_vintages.add(nxt[0])
                cur_v, cur_n = nxt

            options = [
                {
                    "vintage": v,
                    "district_name": n,
                    "url": (
                        (seat_url(chamber, n) if v == current_vintage else district_url(chamber, n, v))
                        if (chamber, v, n) in exists
                        else None
                    ),
                }
                for v, n in chain
            ]
            for v, n in chain:
                index[(chamber, v, n)] = options

    return index


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

    # Each vintage's own first tracked election year — used to flag
    # is_redistricting_year below (see the field's own comment). Computed
    # from this run's actual data, not hardcoded, so it stays correct
    # however far the backfill's covered range changes.
    vintage_start_year = {
        vintage: min(entry["year"] for d in records for entry in d["results_by_year"])
        for vintage, records in district_records_by_vintage.items()
        if records
    }

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
                            "intercept_component": c.get("intercept_component"),
                            "intercept_component_sd": c.get("intercept_component_sd"),
                            "lean_component": c.get("lean_component"),
                            "lean_component_sd": c.get("lean_component_sd"),
                            "tide_component": c.get("tide_component"),
                            "tide_component_sd": c.get("tide_component_sd"),
                            "approval_component": c.get("approval_component"),
                            "approval_component_sd": c.get("approval_component_sd"),
                            "incumbency_adjustment": c.get("incumbency_adjustment"),
                            "incumbency_adjustment_sd": c.get("incumbency_adjustment_sd"),
                            "demographics_component": c.get("demographics_component"),
                            "demographics_component_sd": c.get("demographics_component_sd"),
                            "fundraising_component": c.get("fundraising_component"),
                            "fundraising_component_sd": c.get("fundraising_component_sd"),
                            "demographics_tier": c.get("demographics_tier"),
                            "expected_share_resolved": c.get("expected_share_resolved"),
                            "war_resolved": c.get("war_resolved"),
                            "war_resolved_sd": c.get("war_resolved_sd"),
                            "war_factors": c.get("war_factors"),
                            "is_uncontested": entry["is_uncontested"],
                            "is_incumbent": c["is_incumbent"],
                            "incumbent_terms": c.get("incumbent_terms", 0),
                            # True for a race that's the first election under
                            # its vintage's maps — the year every candidate's
                            # incumbent_terms resets to 0 regardless of real-
                            # world tenure (see apply_war/build_district_
                            # records' incumbency docstrings and the
                            # methodology page's "Incumbency and open seats"
                            # section for why incumbency deliberately isn't
                            # chased across a redistricting boundary). Surfaced
                            # so candidate.html's year-spanning charts can mark
                            # these years, since a single candidate's chart
                            # can cross a boundary a single district/seat
                            # page's chart never does.
                            "is_redistricting_year": entry["year"] == vintage_start_year.get(vintage),
                            "stage": "general",
                            "is_special": False,  # generals never carry this — see derived_metrics.compute_war
                        }
                    )
                    prev = latest_info.get(c["slug"])
                    if prev is None or entry["year"] > prev[0]:
                        latest_info[c["slug"]] = (entry["year"], c["name"], c["party"])

            # Primary races — same candidate-race dict shape where the two
            # stages share a concept (chamber/year/district/party/votes/
            # winner/is_redistricting_year), primary-specific fields
            # (actual_primary_share, primary_war, ...) named distinctly
            # from their general counterparts rather than overloaded onto
            # the same keys, since they're not on the same scale (a
            # primary's expected share is relative to its own field size,
            # a general's to a two-party baseline) — see apply_primary_
            # war's own docstring. `latest_info` (this candidate's current
            # display name/party) intentionally isn't updated from primary
            # rows: a candidate's most recent GENERAL appearance is judged
            # the more representative "latest," and a primary-only
            # candidate's name/party still comes from here regardless,
            # via the fallback below.
            for p in d["primaries"]:
                for c in p["candidates"]:
                    races_by_slug.setdefault(c["slug"], []).append(
                        {
                            "chamber": d["chamber"],
                            "year": p["year"],
                            "vintage": vintage,
                            "district_name": d["district_name"],
                            "district_url": district_url(d["chamber"], d["district_name"], vintage),
                            "party": c["party"],
                            "votes": c["votes"],
                            "winner": c["winner"],
                            "actual_primary_share": c.get("actual_primary_share"),
                            "fair_share": c.get("fair_share"),
                            "n_candidates": p["n_candidates"],
                            "primary_baseline_component": c.get("primary_baseline_component"),
                            "primary_baseline_component_sd": c.get("primary_baseline_component_sd"),
                            "primary_incumbency_component": c.get("primary_incumbency_component"),
                            "primary_incumbency_component_sd": c.get("primary_incumbency_component_sd"),
                            "primary_fundraising_component": c.get("primary_fundraising_component"),
                            "primary_fundraising_component_sd": c.get("primary_fundraising_component_sd"),
                            "primary_expected_share": c.get("primary_expected_share"),
                            "primary_war": c.get("primary_war"),
                            "primary_war_sd": c.get("primary_war_sd"),
                            "primary_war_factors": c.get("primary_war_factors"),
                            "is_uncontested": not p["is_contested"],
                            "is_incumbent": c["is_incumbent"],
                            "incumbent_terms": c.get("incumbent_terms", 0),
                            "is_redistricting_year": p["year"] == vintage_start_year.get(vintage),
                            "stage": "primary",
                            "is_special": p["is_special"],
                        }
                    )
                    if c["slug"] not in latest_info:
                        latest_info[c["slug"]] = (p["year"], c["name"], c["party"])

    records = []
    for slug, races in races_by_slug.items():
        # Newest year first; within a tied year, general before primary
        # (chronologically correct — a primary always precedes that same
        # year's general) rather than relying on insertion order, which
        # happened to already match but isn't a contract worth depending on.
        races_sorted = sorted(
            races, key=lambda r: (-r["year"], r["chamber"], 0 if r["stage"] == "general" else 1)
        )
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


def _statewide_candidate_list(race_results: pd.DataFrame, share_col: str) -> list[dict]:
    """race_results: every fetch.pd43 result row for one election_id. Shares
    are each candidate's fraction of votes among *named* candidates only
    (excludes write-ins/blanks, same "which votes count" convention
    compute_war/compute_primary_results already use elsewhere), not a
    two-party share — a Senate general can carry a real third-party
    candidate on the ballot (e.g. a Libertarian in 2002/2020), unlike this
    site's two-party-only House/Senate WAR framing."""
    total = float(race_results["votes"].fillna(0).sum())
    return [
        {
            "name": row["candidate_name"],
            "slug": candidate_slug(row["candidate_slug"]),
            "party": _clean_str(row["party"]),
            "votes": int(row["votes"]) if pd.notna(row["votes"]) else None,
            "winner": bool(row["winner"]),
            share_col: round(float(row["votes"]) / total, 4) if pd.notna(row["votes"]) and total else None,
        }
        for _, row in race_results.sort_values("votes", ascending=False, na_position="last").iterrows()
    ]


def build_us_senate_records(pd43_dir: Path) -> dict | None:
    """MA's U.S. Senate election history — deliberately NOT run through the
    district/seat/WAR machinery every other chamber on this site uses: a
    statewide, single-seat, staggered-6-year-term office has no meaningful
    "replacement level" the way a multi-seat chamber does (there's no
    second Massachusetts to compare a Senate result against, and "WAR
    relative to what this seat 'should' produce" collapses to "how did
    this specific race's winner do in this specific race," which isn't a
    real baseline) — a direct, explicit user choice: a simpler results-
    over-time page instead of forcing this office through the district/
    seat/candidate template trio. No campaign-finance section either, same
    reason as fit_us_house_war_model's own docstring (OCPF doesn't cover
    federal filers; an FEC fetcher is a real, documented future addition,
    not attempted this round).

    Returns None (nothing to write) if fetch.pd43 was never run for
    us-senate at all — same "skip gracefully, don't crash" convention the
    rest of this module uses for genuinely optional inputs."""
    races_path = pd43_dir / "us-senate_races.parquet"
    results_path = pd43_dir / "us-senate_results.parquet"
    if not (races_path.exists() and results_path.exists()):
        return None
    races = pd.read_parquet(races_path)
    results = pd.read_parquet(results_path)
    if not len(races):
        return None

    generals = []
    for _, race in races[races["stage"] == "general"].sort_values("year", ascending=False).iterrows():
        race_results = results[results["election_id"] == race["election_id"]]
        generals.append(
            {
                "year": int(race["year"]),
                "is_special": bool(race["is_special"]),
                "candidates": _statewide_candidate_list(race_results, "vote_share"),
            }
        )

    primaries = []
    for _, race in races[races["stage"] == "primary"].sort_values(
        ["year", "party"], ascending=[False, True]
    ).iterrows():
        race_results = results[results["election_id"] == race["election_id"]]
        primaries.append(
            {
                "year": int(race["year"]),
                "party": race["party"],
                "is_special": bool(race["is_special"]),
                "candidates": _statewide_candidate_list(race_results, "primary_vote_share"),
            }
        )

    return {"generals": generals, "primaries": primaries}


@click.command()
@click.option("--chamber", type=click.Choice(["house", "senate", "both"]), default="both")
@click.option(
    "--us-house/--no-us-house",
    default=True,
    help="Also build U.S. House district/seat/candidate pages, fit via their own separate model (fit_us_house_war_model) — see its own docstring for why it's never pooled with the state chamber(s) above.",
)
@click.option(
    "--us-senate/--no-us-senate",
    default=True,
    help="Also build a simple U.S. Senate results-over-time page (no districts, no WAR model — see build_us_senate_records' own docstring).",
)
@click.option(
    "--pd43-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/pd43"),
    help="Raw fetch.pd43 output, for build_us_senate_records (which reads us-senate_races/results directly, not via derived_metrics/crosswalks — there's no district to apportion into).",
)
@click.option(
    "--us-senate-data-out",
    type=click.Path(path_type=Path),
    default=Path("site/_data/us_senate.yml"),
)
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
    "--approval-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/presidential_approval"),
    help="Presidential approval-by-year data from fetch.presidential_approval, for the national_approval term",
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
    help="Where to write war_model.yml/war_fit_sample.yml — the fitted regression posteriors and sample, for the methodology page to read via site.data.war_model etc.",
)
@click.option("--seats-out-dir", type=click.Path(path_type=Path), default=Path("site/_seats"))
@click.option("--districts-out-dir", type=click.Path(path_type=Path), default=Path("site/_districts"))
@click.option("--candidates-out-dir", type=click.Path(path_type=Path), default=Path("site/_candidates"))
@click.option("--towns-out-dir", type=click.Path(path_type=Path), default=Path("site/_towns"))
@click.option("--parties-out-dir", type=click.Path(path_type=Path), default=Path("site/_parties"))
@click.option(
    "--boundaries-dir",
    type=click.Path(path_type=Path),
    default=Path("data/raw/boundaries"),
    help="District boundary geometry (fetch.district_boundaries/fetch.congressional_boundaries output), for the combined statewide-map GeoJSON below.",
)
@click.option(
    "--geo-out-dir",
    type=click.Path(path_type=Path),
    default=Path("site/assets/data/geo"),
    help="Where to (re)write the combined <chamber>-<vintage>-all.geojson files site/map/ reads — written here, after apply_war/apply_us_house_war, so they carry real fitted winner_war/winner_*_component values; see publish_district_geo.write_combined_from_records' own docstring.",
)
@click.option("-v", "--verbose", is_flag=True)
def main(
    chamber: str,
    us_house: bool,
    us_senate: bool,
    pd43_dir: Path,
    us_senate_data_out: Path,
    current_vintage: str,
    vintages: str,
    derived_dir: Path,
    crosswalks_dir: Path,
    baseline_dir: Path,
    ocpf_dir: Path,
    approval_dir: Path,
    demographics_dir: Path,
    site_data_dir: Path,
    seats_out_dir: Path,
    districts_out_dir: Path,
    candidates_out_dir: Path,
    towns_out_dir: Path,
    parties_out_dir: Path,
    boundaries_dir: Path,
    geo_out_dir: Path,
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

    # Kept in a fully separate dict from district_records_by_vintage above
    # until after both the state and U.S. House models have been fit and
    # applied (see fit_us_house_war_model's own docstring for why the two
    # are never pooled) — merged into the same dict only afterward, so
    # every downstream consumer that doesn't care about the model split
    # (write_district_files, build_seat_records, build_candidate_records,
    # town/party records) sees one combined roster without needing its own
    # chamber-specific logic.
    ush_district_records_by_vintage: dict[str, list[dict]] = {}
    if us_house:
        for vintage in vintage_list:
            ush_district_records_by_vintage[vintage] = build_district_records("us-house", vintage, derived_dir)

    # Census demographics (PL 94-171 + ACS) only exist for the current
    # vintage — see demographics_match.py's docstring — so only those
    # records get enriched; other vintages' district pages simply have no
    # demographics section. Enriched before fit_war_model, which needs it
    # already attached.
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
    approval_by_year = compute_national_approval_by_year(approval_dir)

    # fit_war_model needs finance_by_slug (for its log_raised term) before it
    # can run, and campaign-finance matching needs a candidate_records
    # structure to match against OCPF — so build a preliminary
    # candidate_records here purely for that slug/district/chamber/year
    # lookup. It's rebuilt again below, after apply_war, so the final
    # candidate race dicts pick up the fitted WAR fields too.
    preliminary_candidate_records = build_candidate_records(district_records_by_vintage)
    finance_by_slug: dict = {}
    if (ocpf_dir / "filers.parquet").exists():
        finance_by_slug = campaign_finance_match.load_and_match(preliminary_candidate_records, ocpf_dir)
    else:
        logger.warning("No OCPF data at %s — candidate pages will have no campaign-finance section", ocpf_dir)

    war_fit = fit_war_model(district_records_by_vintage, tide_by_year, approval_by_year, current_vintage, finance_by_slug)
    logger.info(
        "WAR model fit: n=%d, R²=%s, own_lean=%+.3f (x_dem %+.3f), own_tide=%+.3f (x_dem %+.3f), "
        "national_approval=%+.3f, incumbent=%+.3f (x_dem %+.3f), open_seat=%+.3f, "
        "n_demographics=%d, n_finance=%d, n_open_seat=%d",
        war_fit["n"],
        war_fit["r_squared"],
        war_fit["coefficients"]["own_lean"]["posterior_mean"],
        war_fit["coefficients"]["own_lean_x_dem"]["posterior_mean"],
        war_fit["coefficients"]["own_tide"]["posterior_mean"],
        war_fit["coefficients"]["own_tide_x_dem"]["posterior_mean"],
        war_fit["coefficients"]["national_approval"]["posterior_mean"],
        war_fit["coefficients"]["incumbent"]["posterior_mean"],
        war_fit["coefficients"]["incumbent_x_dem"]["posterior_mean"],
        war_fit["coefficients"]["open_seat"]["posterior_mean"],
        war_fit["n_demographics"],
        war_fit["n_finance"],
        war_fit["n_open_seat"],
    )
    (site_data_dir / "war_model.yml").write_text(yaml.safe_dump(war_fit, sort_keys=False))

    apply_war(district_records_by_vintage, tide_by_year, approval_by_year, current_vintage, finance_by_slug, war_fit)

    fit_sample = build_war_fit_sample(district_records_by_vintage)
    (site_data_dir / "war_fit_sample.yml").write_text(yaml.safe_dump(fit_sample, sort_keys=False))
    logger.info("Wrote %d rows to %s", len(fit_sample), site_data_dir / "war_fit_sample.yml")

    primary_war_fit = fit_primary_war_model(district_records_by_vintage, tide_by_year, finance_by_slug)
    logger.info(
        "Primary WAR model fit: n=%d, R²=%s, incumbent=%+.3f, incumbent_x_tide=%+.3f, incumbent_x_lean=%+.3f, "
        "n_incumbent=%d, n_finance=%d",
        primary_war_fit["n"],
        primary_war_fit["r_squared"],
        primary_war_fit["coefficients"]["primary_incumbent"]["posterior_mean"],
        primary_war_fit["coefficients"]["primary_incumbent_x_tide"]["posterior_mean"],
        primary_war_fit["coefficients"]["primary_incumbent_x_lean"]["posterior_mean"],
        primary_war_fit["n_incumbent"],
        primary_war_fit["n_finance"],
    )
    (site_data_dir / "primary_war_model.yml").write_text(yaml.safe_dump(primary_war_fit, sort_keys=False))

    apply_primary_war(district_records_by_vintage, tide_by_year, finance_by_slug, primary_war_fit)

    primary_fit_sample = build_primary_war_fit_sample(district_records_by_vintage)
    (site_data_dir / "primary_war_fit_sample.yml").write_text(yaml.safe_dump(primary_fit_sample, sort_keys=False))
    logger.info("Wrote %d rows to %s", len(primary_fit_sample), site_data_dir / "primary_war_fit_sample.yml")

    # U.S. House's own separate fit — see fit_us_house_war_model's own
    # docstring for why this never touches district_records_by_vintage
    # (the state model's own training data) above. No primary model for
    # U.S. House this round (a documented gap, methodology.md) — primary
    # candidates on a congressional district page still show their raw
    # actual_primary_share/fair_share, just no fitted primary_war overlay.
    if us_house and any(ush_district_records_by_vintage.values()):
        us_house_war_fit = fit_us_house_war_model(ush_district_records_by_vintage, tide_by_year, approval_by_year)
        logger.info(
            "U.S. House WAR model fit: n=%d, R²=%s, own_lean=%+.3f (x_dem %+.3f), own_tide=%+.3f (x_dem %+.3f), "
            "national_approval=%+.3f, incumbent=%+.3f (x_dem %+.3f), open_seat=%+.3f",
            us_house_war_fit["n"],
            us_house_war_fit["r_squared"],
            us_house_war_fit["coefficients"]["ush_own_lean"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_own_lean_x_dem"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_own_tide"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_own_tide_x_dem"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_national_approval"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_incumbent"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_incumbent_x_dem"]["posterior_mean"],
            us_house_war_fit["coefficients"]["ush_open_seat"]["posterior_mean"],
        )
        (site_data_dir / "us_house_war_model.yml").write_text(yaml.safe_dump(us_house_war_fit, sort_keys=False))

        apply_us_house_war(ush_district_records_by_vintage, tide_by_year, approval_by_year, us_house_war_fit)

        us_house_fit_sample = build_war_fit_sample(ush_district_records_by_vintage)
        (site_data_dir / "us_house_war_fit_sample.yml").write_text(yaml.safe_dump(us_house_fit_sample, sort_keys=False))
        logger.info("Wrote %d rows to %s", len(us_house_fit_sample), site_data_dir / "us_house_war_fit_sample.yml")

        # Merged in only now that both models are done fitting/applying —
        # every downstream step from here on (lineage/vintage chains,
        # district/seat/candidate files, town/party rollups) treats
        # U.S. House exactly like any other chamber.
        for vintage, recs in ush_district_records_by_vintage.items():
            district_records_by_vintage.setdefault(vintage, []).extend(recs)
        chambers = [*chambers, "us-house"]

    lineage = pd.read_parquet(crosswalks_dir / "seat_lineage.parquet")
    vintage_chain_index = build_vintage_chain_index(district_records_by_vintage, lineage, current_vintage)
    for recs in district_records_by_vintage.values():
        for r in recs:
            r["vintage_options"] = vintage_chain_index.get((r["chamber"], r["vintage"], r["district_name"]), [])

    all_district_records = [r for recs in district_records_by_vintage.values() for r in recs]
    write_district_files(all_district_records, districts_out_dir)

    seat_records = build_seat_records(district_records_by_vintage, current_vintage, lineage)
    write_seat_files(seat_records, seats_out_dir)

    # Rebuilt now that apply_war has populated every district record's WAR
    # fields, so this final candidate_records correctly inherits them via
    # its usual copy-from-district-dict pattern.
    candidate_records = build_candidate_records(district_records_by_vintage)
    for candidate in candidate_records:
        if candidate["slug"] in finance_by_slug:
            candidate["ocpf_finance"] = finance_by_slug[candidate["slug"]]
    write_candidate_files(candidate_records, candidates_out_dir)

    town_records = build_town_records(chambers, current_vintage, crosswalks_dir, seat_records)
    write_town_files(town_records, towns_out_dir)

    party_records = build_party_records(seat_records)
    write_party_files(party_records, parties_out_dir)

    # Combined statewide-map GeoJSON (site/map/), written from these same
    # already-resolved records rather than by a separate publish_district_
    # geo.py CLI invocation, specifically so its winner_war/winner_*_
    # component fields reflect the real fitted WAR model(s) above instead
    # of the nulls a standalone rebuild (which has no reason to also wire
    # up tide/OCPF/demographics itself) would produce — see
    # write_combined_from_records' own docstring. Deferred (function-body)
    # import: publish_district_geo imports build_district_records/
    # district_slug/district_url from this module at its own top level, so
    # importing it back at this module's top level would be a circular
    # import; by the time main() actually runs, both modules are already
    # fully loaded, so this works fine.
    from ma_politics.build.publish_district_geo import write_combined_from_records

    records_by_chamber_vintage: dict[tuple[str, str], list[dict]] = {}
    for vintage, recs in district_records_by_vintage.items():
        for r in recs:
            records_by_chamber_vintage.setdefault((r["chamber"], vintage), []).append(r)
    for (c, vintage), recs in records_by_chamber_vintage.items():
        n = write_combined_from_records(c, vintage, boundaries_dir, recs, geo_out_dir)
        logger.info("Wrote combined map (%d districts) for %s %s to %s", n, c, vintage, geo_out_dir)

    if us_senate:
        us_senate_records = build_us_senate_records(pd43_dir)
        if us_senate_records is None:
            logger.warning("No U.S. Senate data at %s — skipping /us-senate/ page data", pd43_dir)
        else:
            us_senate_data_out.parent.mkdir(parents=True, exist_ok=True)
            us_senate_data_out.write_text(yaml.safe_dump(us_senate_records, sort_keys=False))
            logger.info(
                "Wrote %d U.S. Senate general(s) + %d primary race(s) to %s",
                len(us_senate_records["generals"]),
                len(us_senate_records["primaries"]),
                us_senate_data_out,
            )


if __name__ == "__main__":
    main()
