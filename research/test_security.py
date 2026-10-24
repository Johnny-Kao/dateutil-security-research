"""Assertions for bounded dateutil #1094 research. Never targets remote services."""
import unittest

from validate import MAX_COUNT, isolated_case, local_http_case, rule_text, validate_rule_text


class BoundedReproductionTest(unittest.TestCase):
    def test_accept_only_finite_rule_text(self):
        self.assertEqual(
            validate_rule_text(rule_text(MAX_COUNT, True)),
            rule_text(MAX_COUNT, True),
        )
        bad = (
            "RRULE:FREQ=MINUTELY",
            "DTSTART:20250101T000000\nRRULE:FREQ=SECONDLY;COUNT=1",
            "DTSTART:20250101T000000\nRRULE:FREQ=MINUTELY;COUNT=300001",
            "DTSTART:20250101T000000\nRRULE:FREQ=MINUTELY;COUNT=20"
            "\nEXRULE:FREQ=MINUTELY;COUNT=19",
            "DTSTART:20250101T000000\nRRULE:FREQ=MINUTELY",
        )
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_rule_text(value)

    def test_finite_resource_case(self):
        normal = isolated_case("normal", 10_000)
        excluded = isolated_case("excluded", 10_000)
        self.assertIsNotNone(normal["next_event"])
        self.assertIsNone(excluded["next_event"])
        self.assertLess(excluded["cpu_s"], 12)

    def test_http_ingress_and_delayed_second_request(self):
        result = local_http_case(MAX_COUNT)
        self.assertEqual(result["excluded_request"]["http_status"], 200)
        self.assertIsNone(result["excluded_request"]["next_event"])
        self.assertIsNotNone(result["benign_request_behind_excluded"]["next_event"])
        self.assertIn("rrule_text", result["ingress"])
        # Head-of-line blocking is recorded by the benchmark, but not asserted
        # in CI: contention and scheduler jitter vary by runner.


if __name__ == "__main__":
    unittest.main()
