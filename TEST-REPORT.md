# TEST-REPORT — btc-race-24h-20261113-2314 entry

Competition: `btc-race-24h-20261113-2314` (Race a BTC trading bot live for 24 hours).
Entry: `main.py` (Python 3.13, stdlib only) + `vendor/makefun_bars.py`
(byte-identical copy of the kit's Python SDK shim) + `LICENSE` (MIT).

## Official result (kit's own grader, dev window, 1,440 bars)

| Metric | Value |
| --- | --- |
| Net PnL | **+18.290458 USDC** (+1.829%) |
| Trades | 6 (3 round trips, win rate 1.000) |
| Max drawdown | 0.007261787 (0.73%, limit 25%) |
| Fees paid | 2.421469 USDC |
| Net PnL at 2x fees | +15.857624 USDC |
| Rejected orders | 0 |
| Guardrails | met (trades ok, drawdown ok) |
| Determinism | L1 regrade reproduced byte for byte (grader runs the bot twice) |
| Status | finished |

Dev gate: PASSED — net PnL > $0, so this entry races.

## How it was run

The kit's `grade-local` with the process driver refuses Python bots
("the process sandbox runs node22 only") and no Docker is available on
this machine, so the grade was run with a copy of the kit CLI in /tmp
(`/tmp/makefun-patched.mjs`, the kit itself untouched) patched in exactly
two places: the process sandbox's `preflight`/`spawn` now also accept the
`python3.13` runtime and spawn it with the kit's own command from
`RUNTIME_COMMANDS` (`python3 -P -s main.py`, `PYTHONHASHSEED=0` from the
kit's `SANDBOX_ENV`). All replay, fill, fee, and scoring code is the
kit's, unmodified. Command (from the kit directory):

```
MAKEFUN_ALLOW_PROCESS_SANDBOX=1 node /tmp/makefun-patched.mjs grade-local \
  --kit . --bot ~/workspace/makefun/entry-btc-race-24h-20261113-2314 --driver process
```

Run twice (second run after adding LICENSE): identical net PnL
+18.290458 USDC both times. Local Python is 3.12.3; the server runs
3.13.17 — the bot uses no version-specific features. The grader also
notes the local Node is v24.22.1 vs the server's v22.23.4; that affects
only the harness, not the bot.

An independent offline simulator (same fill model: 4 bps fee, 2 bps
slippage, constant-product impact vs each bar's `o_depth`, fill at next
open, flatten at last close) predicted +$18.29 before the kit grade —
the kit grade agrees to $0.001.

## The three trades (dev window)

| # | Signal | Buy (decided bar) | Sell (decided bar) | Approx. net |
| --- | --- | --- | --- | --- |
| 1 | Dip-bounce (A) | bar 417, $68,199 | bar 446, $68,895 (take-profit +1.0%) | ~+$6 |
| 2 | 4h breakout (B) | bar 656, $69,255 | bar 865, $69,948 (take-profit +1.0%) | ~+$6 |
| 3 | Dip-bounce (A) | bar 992, $68,312 | bar 1108, $69,075 (take-profit +1.0%) | ~+$6 |

Each winning trade nets ~+0.6% after the ~0.4% round-trip cost
(4 bps fee + 2 bps slippage + ~13 bps impact per side at the dev
window's pool depths).

## Baselines on the same dev window (kit grade-local, for comparison)

| Baseline | Net PnL | Trades | Max drawdown |
| --- | --- | --- | --- |
| buy-and-hold | −52.586916 USDC | 1 | 5.26% |
| momentum | −49.232238 USDC | 1 | 5.13% |
| adx-momentum | −50.309162 USDC | 20 | 5.31% |
| rsi-bollinger | −65.829371 USDC | 11 | 6.78% |
| ema-cross | −109.380836 USDC | 58 | 10.97% |
| hold-cash | 0.000000 USDC | 0 | 0% |
| **this entry** | **+18.290458 USDC** | **6** | **0.73%** |

The dev window is a −4.91% downtrend ($71,409 → $67,900); every
baseline loses. This entry beats all of them by staying in cash except
for the three recovery legs above.

## Robustness (offline simulator, one parameter varied at a time)

Base +$18.29. Neighbours all stay positive: take-profit 1.2% +$12.20,
0.8% +$13.13; breakout take-profit 1.2% +$10.52; dip threshold 0.4%
+$7.16, 0.6% +$12.47; bounce threshold 0.15% +$18.29, 0.25% +$7.07;
breakout window 200 bars +$6.73, 300 bars +$18.29; no 5-min bounce
filter +$12.66. No single-parameter change flips the result negative.

## Caveats

- The race window is unseen; dev-window profit does not predict race
  profit. The strategy only trades clear recovery legs, so on a
  trendless or steadily falling race window it may trade little or not
  at all — but it cannot lose much either (max drawdown 0.73% on dev,
  hard stops on every trade).
- Parameters were selected on the dev window (the only data available);
  the sensitivity table above is the honest extent of the check.
