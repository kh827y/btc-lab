# ABSORB-001 — price response to executed spot selling (frozen before any forward outcome)

Version `ABSORB-001-descriptive-v1`. Decisions D1/D3. **Descriptive study, not confirmation.** No fitted forecast, no trading rule, no tuning. Implementation: `research_absorb.py`. Reports: `data/research/absorb_v1/absorb_preflight.json`, then `absorb_outcomes.json`. One run of each; originals are never overwritten.

## Question

When BTC falls over a week, does the cost of delaying a purchase by seven days differ between declines that came with *more* net taker selling than a decline of that size usually involves (price moved little per unit sold) and declines that came with *less* (price fell on little selling)?

The study measures **price response to executed flow on one venue**. It does not identify who absorbed the selling or whether the buyers persist. A weak response to heavy selling is equally compatible with resting spot bids, arbitrageurs buying spot against leveraged perpetual longs, support from venues not sampled, or noise. The word "absorption" is used only in that limited sense.

## Prior exposure (registered before freeze)

- Exploratory probe, 27 Nov 2026 (Fable, research report): Binance BTCUSDT daily klines 2017-08-17..2026-11-26, same-day statistics only — yearly correlation of return with taker imbalance (0.37–0.65 from 2018), yearly mean imbalance, yearly slope, imbalance autocorrelation, and dispersion/volume inside the zero-fee window. No forward return was computed.
- FLOW-001 used the same venue's daily taker flow for 2017–2023 against 28-day outcomes (no incremental value).
- BUY-001, DD-001, RISK-001, TREND-001/002 exposed 2018–2023 BTC price outcomes. The development period is therefore not pristine; nothing here is a holdout test.
- Design choices informed by the probe: regime-adaptive scaling, the fee-regime exclusion, and treating 2017 only as warm-up history.

## Data

Local verified Binance BTCUSDT spot one-minute archives from `download_minutes.bat` (`data/binance_1m`), each ZIP re-checked against its recorded SHA-256. Fields: open, low, close, quote volume, taker-buy quote volume. **Only bars before 2024-01-01 00:00 UTC are loaded**; 2024+ is not read, counted or scored. Opening 2024+ would need a separate owner decision and registry entry. USDT prices throughout; no venue mixing. Derivatives data are deliberately not used (see Scope).

## Definitions (all point-in-time)

1. **Hour.** Valid only with all 60 accepted minutes and positive quote volume; gaps are never filled. Return `r = ln(close/open)` within the hour; signed flow `q = 2·takerBuyQuote − quoteVolume` (USDT). Both refer to exactly the same interval.
2. **Scaling.** For hour h, over the 672 hours strictly before h (≥538 valid): `σ` = root-mean-square of `r`, `s` = standard deviation of `q`. `ρ = r/σ`, `φ = q/s`. *Rationale:* 28 days is long enough for stable scales and short enough to adapt to regime shifts; scaling flow by its own recent dispersion rather than by volume survives fee-driven churn (the probe showed imbalance dispersion falling to a quarter while volume doubled).
3. **Weekly state** at cutoff c = Sunday 00:00 UTC (Saturday close, the lab's weekly convention), from the 168 hours before c (≥160 valid): `R = Σρ/√n`, `F = Σφ/√n`. Summing standardized hours gives unit-scale variables comparable across years; `√n` keeps weeks with a few missing hours comparable.
4. **Reference** at c: the previous 104 weekly cutoffs with valid (R, F), at least 52. Two years so that thresholds are not set by a single regime.
5. **Down week:** `R ≤` 33rd percentile of reference R (a decline that is large relative to prevailing volatility).
6. **Excess flow:** fit `F = a + g·R` on the reference weeks; `E = F − (a + g·R)`. E is the part of net taker flow not explained by the price move. It is uncorrelated with R in the reference weeks by construction, which is what makes the comparison price-controlled; Stage A reports whether that holds out of sample and Stage B checks the resulting balance directly. Terciles of reference residuals: `heavy` (E ≤ P33: more net selling than typical for this move), `typical`, `light` (E ≥ P67).
7. **Groups:** `D-heavy`, `D-typical`, `D-light` in Down weeks; `N-heavy`, `N-typical`, `N-light` otherwise.
8. **Fee-regime exclusion.** Binance zero-fee BTC trading started 2022-07-08 14:00 UTC and ended for BTCUSDT 2023-03-22 00:00 UTC. Weeks with a cutoff less than 840 hours (week + scaling window) after either boundary are excluded, because their scales mix two fee regimes.
9. **Origins.** Every classified weekly cutoff whose outcome window ends before 2024-01-01. Entry at Monday 00:00 UTC open (c + 24 h). Outcome windows of consecutive origins never overlap, so each origin is a distinct executable decision.
10. **Covariates:** R, `log σ` at c, and depth = log distance of the last close from the trailing 365-day closing high.

## Stage A — measurement validity (no forward outcomes)

Hard gates, each chosen because failing it makes the measure meaningless rather than merely weak:

- **Sign.** Correlation of ρ with φ (hourly) and of R with F (weekly) is positive in every complete calendar year from 2018. If the sign flips, "flow not explained by price" has no stable meaning.
- **Coverage.** From the first classified week, excluding fee-transition weeks: ≥95% of weeks classified overall and ≥90% in each complete year (the FLOW-001 convention). Outages cluster in stress, so heavy data loss would select the sample.

Reported without pass/fail: hourly/daily/weekly correlations and slopes by year; yearly mean and SD of R and F; out-of-sample correlation of E with R (a value above 0.3 in absolute terms is flagged as a weak price control); a placebo correlation of R with flow four weeks earlier; flow–return statistics before, during and after the zero-fee window. No R² floor is imposed: explanatory power is described, not gated.

## Stage B — sample adequacy and balance (no forward outcomes)

- Counts by group and year; largest single-year share.
- **Balance** between D-heavy and D-light: standardized mean differences (SMD) of R, log σ and depth. Any |SMD| > 0.25 (the conventional matching flag) makes the covariate-adjusted estimate the headline in Stage C. With about 30 weeks per group an SMD of this size often arises by chance, so this is a reporting rule, not a test; both estimates are always shown.
- **Minimum detectable difference**, stated before outcomes: `2.487·√(1/n₁+1/n₂)` in σ-units (two-sided 10%, 80% power, assuming a standardized outcome SD near 1), converted with the median weekly volatility. A planning figure.
- **Floor:** outcomes stay closed if either primary group has fewer than 10 origins or spans fewer than 3 calendar years — below that a mean difference of weekly BTC returns is noise in one regime. This is the only sample-size barrier; anything above it is reported with its detectable difference rather than blocked.

`outcomes_permitted` = both Stage A gates and the floor.

## Stage C — forward outcomes (one locked run)

Runs only with the SHA-256 of the reviewed preflight, an unchanged data manifest and identical recomputed origins.

- **Primary:** mean of `wait7 = ln(open[entry+7d] / open[entry])` in D-heavy minus D-light. Positive `wait7` means waiting a week cost more. For a fixed tranche, "buy now" versus "buy in 7 days" differ at any later date exactly by this ratio.
- **Uncertainty:** percentile 90% interval from a circular moving-block bootstrap over the chronological sequence of weekly origins (block 4 weeks, matching the scaling memory; 10,000 resamples; fixed seed), with a 13-week block as sensitivity.
- **Adjusted estimate:** group coefficient from OLS of `wait7` on group, R, log σ and depth within the two groups; same bootstrap. This is covariate adjustment of a descriptive contrast, not a forecasting model.
- **Price-only benchmark:** mean `wait7` for all, Down and not-Down origins. Flow adds information only through the within-Down contrast.
- **Also reported:** D-heavy/D-typical/D-light dose-response; N-heavy versus N-light (heavy selling while price is not falling); for the primary groups, volatility-standardized `wait7`, 7-day maximum adverse excursion, realized-to-trailing volatility ratio, 28-day wait cost, and next-week flow F (does selling continue?); entry at the cutoff instead of 24 h later; the six other weekday clocks.

## Reading the result

The report states whether the interval excludes zero and which absolute differences (1%, 3%, 5%) it rules out. No single "useful effect" is imposed: the owner's threshold is unspecified, and BUY-001's 1% reference is far below what this history can resolve.

- Interval excludes zero: a descriptive candidate for prospective tracking. No rule, no confirmation claim.
- Interval includes zero and rules out 3%: no large timing difference for this contrast.
- Interval includes zero but does not rule out 3%: **unresolved**, not negative.

**Closure scope.** Whatever the result, it closes only this contrast — Binance spot, 7-day excess-flow tercile within standardized down weeks, 7-day wait cost, 2018–2023. It does not close the broader mechanism: other venues, horizons, forced-selling events, risk outcomes, derivatives context and prospective evidence remain open. No historical variants of this study (other windows, thresholds, percentiles) will be run after seeing outcomes.

## Scope decisions

- **No derivatives context here.** Separating spot bids from arbitrage absorption needs perpetual premium/funding and open interest. Funding and basis are prices of leverage; open interest is a quantity; they can diverge and should be read separately. That belongs to a follow-up on its own data, not to this single-source study.
- **No 2024+ data, no new downloads, no paid calls, no language model.**

## Amendments

None. Any change after the freeze commit is listed here with date, reason and whether outcomes had been opened.
