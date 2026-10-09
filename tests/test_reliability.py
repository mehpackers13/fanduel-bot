import unittest, tempfile, json, datetime
from pathlib import Path
from unittest.mock import patch, Mock
from time_utils import parse_timestamp, last_completed_scan
from safe_state import atomic_json

class CommonTests(unittest.TestCase):
    def test_eastern_offsets(self):
        self.assertEqual(parse_timestamp("2026-01-15 10:00 ET").hour, 15)
        self.assertEqual(parse_timestamp("2026-07-15 10:00 ET").hour, 14)
        self.assertEqual(parse_timestamp("2026-07-15T10:00:00-04:00").hour, 14)
    def test_no_scan_from_failure_or_start(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bot.log"
            p.write_text("[2026-07-15 10:00 ET] Starting scan\n[2026-07-15 10:01 ET] scan failed\n")
            self.assertIsNone(last_completed_scan(p))
            p.write_text("[2026-07-15 10:02 ET] Scan complete\n")
            self.assertEqual(parse_timestamp(last_completed_scan(p)).hour,14)
    def test_failed_json_write_preserves_state(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.json";atomic_json(p,{"valid":1})
            with self.assertRaises(ValueError):atomic_json(p,{"bad":float("nan")})
            self.assertEqual(json.loads(p.read_text()),{"valid":1})

import outcomes, generate_data
class ReportingTests(unittest.TestCase):
    def test_empty_subset_not_replaced(self):
        with patch.object(outcomes,"completed_bets",side_effect=AssertionError("Must not load other rows")):
            self.assertEqual(outcomes.win_rate([]),0)
            self.assertEqual(outcomes.roi([]),0)
    def test_push_is_not_loss(self):
        self.assertEqual(outcomes.win_rate([{"outcome":"W"},{"outcome":"P"}]),100)
    def test_percentage_probability_for_historical_pl(self):
        rows=[{"outcome":"W","suggested_bet":"10","implied_prob":"50","profit_loss":""}]
        self.assertEqual(generate_data.calc_unit_total(rows),1)
