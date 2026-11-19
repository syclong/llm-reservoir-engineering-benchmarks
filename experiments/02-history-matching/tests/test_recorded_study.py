"""Checks for the bundled inputs and offline evidence replay."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class RecordedStudyTests(unittest.TestCase):
    def replay_module(self):
        self.assertTrue((ROOT / "reproduce.py").is_file(), "An offline replay entry point is required")
        import reproduce
        return reproduce

    def test_init_seeds_only_the_starting_model(self):
        replay = self.replay_module()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp) / "fresh"
            replay.seed_inputs(work)
            self.assertEqual((work / "baseline/MODEL.DATA").read_bytes(), (ROOT / "inputs/BASE.DATA").read_bytes())
            self.assertTrue((work / "schedule_history.csv").is_file())
            self.assertFalse((work / "proposal").exists())
            self.assertFalse((work / "baseline/flow_complete.json").exists())
            with self.assertRaises(ValueError):
                replay.seed_inputs(work)

    def test_both_scales_replay_with_no_external_process(self):
        replay = self.replay_module()
        with tempfile.TemporaryDirectory() as temp, patch("subprocess.run", side_effect=AssertionError("unexpected dispatch")):
            work = Path(temp) / "replay"
            audit = replay.verify(work)
            self.assertEqual((audit["accepted_proposals"],audit["native_summaries_checked"]), (1,2))
            self.assertAlmostEqual(audit["well_balanced_after_pp"],2.0345541664312337)
            self.assertAlmostEqual(audit["field_after_pp"],1.2573579557702155)
            self.assertEqual(audit["changed_active_cells"],54)
            recorded = (work / "prompt.txt").read_bytes()
            published = (ROOT / "prompts/single_step.txt").read_bytes()
            for payload, receipt in ((recorded, "evidence/recorded_prompt_receipt.json"),
                                     (published, "prompts/receipt.json")):
                self.assertEqual(replay.hm.sha(payload), replay.load(ROOT / receipt)["sha256"])
            marker = b"[BEGIN COMPLETE WORKING DATA]"
            self.assertEqual(recorded.split(marker, 1)[1], published.split(marker, 1)[1])
            self.assertEqual((work / "results/field_history_comparison.csv").read_bytes(),
                             (ROOT / "results/field_history_comparison.csv").read_bytes())
