"""Deterministic unit tests for the live paper-trading scanner (scanner.py).

These never touch the network: data.get_all_coins is stubbed to return no
coins (so no new signals/entries run) and scanner._fetch_all is stubbed to
return a fixed in-memory {symbol: [candle, ...]} map. A single open position is
seeded into a tmp ledger and scan() is driven against it.

Covers the two coupled correctness defects:
  * SL/TP must trigger on the intrabar low/high TOUCH and FILL at the
    threshold, not on (and at) the 15m close; stop wins when both are touched.
  * A held position whose fetch failed must be marked at its last-known mark,
    not faked flat at entry_price.
"""

import json
import os
import tempfile
import unittest

import data
import scanner


SYM = "FOOUSDT"


def _candle(o, h, l, c, v=1.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _seed_position(last_mark=100.0):
    return {
        "signal": "donchian_breakout",
        "entry_price": 100.0,
        "units": 1.0,
        "notional": 100.0,
        "stop_loss": 97.0,
        "take_profit": 105.0,
        "usdt_rate": 1.0,
        "opened_at": "2026-06-29T00:00:00+00:00",
        "last_mark": last_mark,
    }


class ScanExitTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="scanner-test-")
        self.ledger_path = os.path.join(self._tmpdir, "ledger.json")
        self.status_path = os.path.join(self._tmpdir, "STATUS.md")

        # Redirect ledger + status writes into the tmp dir.
        self._orig_ledger_path = scanner.LEDGER_PATH
        scanner.LEDGER_PATH = self.ledger_path
        self._orig_status_env = os.environ.get("STATUS_PATH")
        os.environ["STATUS_PATH"] = self.status_path

        # Stub the network layer: no coins discovered, no real klines fetched.
        self._orig_get_all_coins = data.get_all_coins
        self._orig_fetch_all = scanner._fetch_all
        data.get_all_coins = lambda **kw: []

    def tearDown(self):
        scanner.LEDGER_PATH = self._orig_ledger_path
        data.get_all_coins = self._orig_get_all_coins
        scanner._fetch_all = self._orig_fetch_all
        if self._orig_status_env is None:
            os.environ.pop("STATUS_PATH", None)
        else:
            os.environ["STATUS_PATH"] = self._orig_status_env

    def _write_ledger(self, position, cash=0.0):
        ledger = {
            "starting_cash": 100.0,
            "cash": cash,
            "positions": {SYM: position},
            "history": [],
            "events": [],
            "last_run_events": [],
            "runs": 0,
            "updated_at": None,
        }
        with open(self.ledger_path, "w") as f:
            json.dump(ledger, f)

    def _run(self, fake):
        scanner._fetch_all = lambda symbols: fake
        return scanner.scan()

    # (a) stop-loss touched by the low even though the close is back above it.
    def test_stop_loss_fills_at_threshold_not_close(self):
        self._write_ledger(_seed_position())
        ledger = self._run({SYM: [_candle(99, 100, 96, 99)]})
        self.assertNotIn(SYM, ledger["positions"])
        rec = ledger["history"][-1]
        self.assertEqual(rec["reason"], "stop-loss")
        # Fill at the SL threshold (97), NOT the close (99).
        self.assertEqual(rec["price"], 97.0)

    # (b) take-profit touched by the high even though the close is back below it.
    def test_take_profit_fills_at_threshold_not_close(self):
        self._write_ledger(_seed_position())
        ledger = self._run({SYM: [_candle(101, 106, 100, 101)]})
        self.assertNotIn(SYM, ledger["positions"])
        rec = ledger["history"][-1]
        self.assertEqual(rec["reason"], "take-profit")
        # Fill at the TP threshold (105), NOT the close (101).
        self.assertEqual(rec["price"], 105.0)

    # (c) a candle that straddles both must be treated as a stop-loss.
    def test_both_touched_is_stop_loss(self):
        self._write_ledger(_seed_position())
        ledger = self._run({SYM: [_candle(100, 106, 96, 100)]})
        self.assertNotIn(SYM, ledger["positions"])
        rec = ledger["history"][-1]
        self.assertEqual(rec["reason"], "stop-loss")
        self.assertEqual(rec["price"], 97.0)

    # (d) failed/empty fetch must mark at last-known mark, not fake-flat entry.
    def test_failed_fetch_marks_at_last_known_not_entry(self):
        self._write_ledger(_seed_position(last_mark=90.0))
        ledger = self._run({})  # no candle for SYM -> fetch "failed"
        # Position stays open (no candle to trigger SL/TP).
        self.assertIn(SYM, ledger["positions"])
        # Equity reflects the last-known mark (90), NOT entry_price (100).
        self.assertEqual(ledger["equity"], 90.0)
        self.assertNotEqual(ledger["equity"], 100.0)
        # STATUS.md should also show 90 in the current/mark column.
        with open(self.status_path) as f:
            status = f.read()
        self.assertIn("90", status)


class EvaluateExitHelperTests(unittest.TestCase):
    """Direct unit tests for the extracted pure helpers."""

    def test_evaluate_exit_stop(self):
        pos = {"stop_loss": 97.0, "take_profit": 105.0}
        self.assertEqual(scanner._evaluate_exit(pos, 100.0, 96.0), ("stop-loss", 97.0))

    def test_evaluate_exit_take(self):
        pos = {"stop_loss": 97.0, "take_profit": 105.0}
        self.assertEqual(scanner._evaluate_exit(pos, 106.0, 100.0), ("take-profit", 105.0))

    def test_evaluate_exit_both_is_stop(self):
        pos = {"stop_loss": 97.0, "take_profit": 105.0}
        self.assertEqual(scanner._evaluate_exit(pos, 106.0, 96.0), ("stop-loss", 97.0))

    def test_evaluate_exit_neither(self):
        pos = {"stop_loss": 97.0, "take_profit": 105.0}
        self.assertEqual(scanner._evaluate_exit(pos, 104.0, 98.0), (None, None))

    def test_mark_for_fresh(self):
        pos = {"entry_price": 100.0, "last_mark": 90.0}
        self.assertEqual(scanner._mark_for(pos, 88.0), 88.0)

    def test_mark_for_falls_back_to_last_mark(self):
        pos = {"entry_price": 100.0, "last_mark": 90.0}
        self.assertEqual(scanner._mark_for(pos, None), 90.0)

    def test_mark_for_last_resort_entry(self):
        pos = {"entry_price": 100.0}
        self.assertEqual(scanner._mark_for(pos, None), 100.0)


if __name__ == "__main__":
    unittest.main()
