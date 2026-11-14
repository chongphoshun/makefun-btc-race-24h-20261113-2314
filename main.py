"""BTC 24h race bot: dip-bounce + range-breakout, long only, Python stdlib only.

Strategy (single asset CBBTC, 1-minute bars, $1,000 start, max 1 position):
  Two independent entry signals, both full-size (100% of cash):

  A) Dip-bounce: the 30-minute return is below -0.5% (a real dip, not noise)
     AND the 10-minute return is above +0.2% (the bounce has started)
     AND the 5-minute return is above 0 (the bounce is still alive, not
     already fading). Buys the start of a recovery leg after a drop.
  B) Range breakout: the close breaks above the highest close of the prior
     240 minutes (4 hours). Buys a genuine 4-hour range breakout, e.g. a
     slow grind that finally clears its range, and rides it to the target.

  Exits (per entry, whole position):
  - Take profit at +1.0% over the entry close (both modes). A full round
    trip costs ~0.4% (4 bps fee + 2 bps slippage + ~13 bps impact per side
    at the pool depths seen in the dev window), so +1.0% clears costs with
    ~+0.6% net per winning trade.
  - Trailing stop 0.8% below the highest close since entry.
  - Hard stop 0.5% below the entry close (mode A).
  - Mode A only: while the trade is underwater, exit if the 10-minute
    return turns below -0.2% (the bounce failed; cut it fast). Once the
    trade is in profit this stall exit is switched off, so a slow grind is
    not cut short by 1-minute noise.
  - Mode B only: exit if the close falls below the lowest close of the
    prior 240 minutes (the breakout range broke down), and a hard stop
    0.8% below the entry close.

  Why this shape: the dev window is a -4.9% downtrend (buy-and-hold loses
  ~$52) with a few slow 1-2% recovery legs. Trend-following and plain
  mean-reversion baselines all lose money there. These two rules only
  trade the recovery legs: three round trips on the dev window, each
  exited at the +1.0% target, for +$18.29 net with 0.73% max drawdown.
  Every parameter was checked one-at-a-time around the chosen values:
  all neighbours stay positive (+$6.73 to +$18.29), so the result does
  not hang on a single tuned number.

Protocol: agent-fun/bars-replay/v1 via the kit's Python shim (vendored
byte-identical under vendor/). One reply per batch, deterministic: only
float arithmetic on the bar closes, no clock, no randomness, no I/O.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

# --- entry parameters ---
DIP_30M = -0.005      # mode A: 30-min return below this
BOUNCE_10M = 0.002    # mode A: 10-min return above this
BOUNCE_5M = 0.0       # mode A: 5-min return above this
BREAKOUT_BARS = 240   # mode B: highest close of the prior N bars

# --- exit parameters ---
TAKE_PROFIT = 0.010   # both modes: +1.0% over the entry close
TRAIL_STOP = 0.008    # both modes: 0.8% below the peak close since entry
HARD_STOP_A = 0.005   # mode A: 0.5% below the entry close
HARD_STOP_B = 0.008   # mode B: 0.8% below the entry close
STALL_10M = -0.002    # mode A, underwater only: 10-min return below this

MAX_SLIPPAGE_BPS = 200  # 2%: the largest 1-min move in the dev window is 66 bps


class Bot:
    def __init__(self):
        self.closes = []        # closes (float USD) in bar order, fresh bars only
        self.entry_close = None  # close of the bar the current position was decided on
        self.peak = None        # highest close since entry
        self.mode = None        # "A" (dip-bounce) or "B" (breakout)
        self.pending = None     # (entry_close, mode) of a buy sent, awaiting confirmation

    def _ret(self, bars_back):
        """Return over the last `bars_back` bars, or None without enough history."""
        n = len(self.closes)
        if n <= bars_back:
            return None
        now = self.closes[-1]
        then = self.closes[-1 - bars_back]
        return now / then - 1.0

    def _range(self, bars_back):
        """(highest, lowest) of the prior `bars_back` closes, excluding the current one."""
        window = self.closes[-1 - bars_back:-1]
        if len(window) < bars_back:
            return None
        return max(window), min(window)

    def on_batch(self, state, batch):
        fresh = any(b["symbol"] == SYMBOL for b in batch["bars"])
        if fresh:
            self.closes.append(float(state.close(SYMBOL)))
        if state.warming_up or not fresh:
            return []

        close = self.closes[-1]
        held = state.positions.get(SYMBOL)

        # Confirm a pending buy once the position actually appears; drop it
        # if the buy was rejected (no position on the next batch).
        if held is not None:
            if self.pending is not None:
                self.entry_close, self.mode = self.pending
                self.peak = close
                self.pending = None
            if self.entry_close is None:
                self.entry_close = close
                self.mode = "A"
                self.peak = close
        else:
            self.entry_close = None
            self.peak = None
            self.mode = None
            self.pending = None

        if held is None:
            return self._maybe_buy(state, close)

        # --- holding: exits ---
        if close > self.peak:
            self.peak = close
        entry = self.entry_close
        if close >= entry * (1.0 + TAKE_PROFIT):
            return self._sell(state)
        if close <= self.peak * (1.0 - TRAIL_STOP):
            return self._sell(state)
        if self.mode == "A":
            if close <= entry * (1.0 - HARD_STOP_A):
                return self._sell(state)
            if close < entry:
                r10 = self._ret(10)
                if r10 is not None and r10 < STALL_10M:
                    return self._sell(state)
        else:  # mode B
            if close <= entry * (1.0 - HARD_STOP_B):
                return self._sell(state)
            rng = self._range(BREAKOUT_BARS)
            if rng is not None and close < rng[1]:
                return self._sell(state)
        return []

    def _maybe_buy(self, state, close):
        r30 = self._ret(30)
        r10 = self._ret(10)
        r5 = self._ret(5)
        mode = None
        if (r30 is not None and r10 is not None and r5 is not None
                and r30 < DIP_30M and r10 > BOUNCE_10M and r5 > BOUNCE_5M):
            mode = "A"
        else:
            rng = self._range(BREAKOUT_BARS)
            if rng is not None and close > rng[0]:
                mode = "B"
        if mode is None:
            return []
        notional = min(state.cash, state.weight_room(SYMBOL))
        if notional < int(state.hello["fees"]["min_notional_quote_units"]):
            return []
        self.pending = (close, mode)
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": notional,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def _sell(self, state):
        held = state.positions.get(SYMBOL)
        if held is None:
            return []
        return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
