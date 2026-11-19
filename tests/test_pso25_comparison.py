"""Check the 5-versus-25 comparison and the common physical settings."""
import unittest
from fopt5.design import ROOT


class BudgetComparisonTests(unittest.TestCase):
    def test_signed_delta_uses_pso_denominator_and_predeclared_tie(self):
        self.assertTrue((ROOT/"pso25/report.py").exists(), "Expected a score comparison that records the 5- and 25-call budgets")
        from pso25.report import compare_scores
        x=compare_scores(5,25,100.,125.,1.)
        self.assertEqual((x["llm_calls"],x["pso_calls"]),(5,25))
        self.assertEqual(x["winner"],"pso")
        self.assertEqual(x["llm_minus_pso_sm3"],-25.)
        self.assertAlmostEqual(x["llm_relative_to_pso"],-.2)
        self.assertEqual(compare_scores(5,5,100.,100.8,1.)["winner"],"tie")

    def test_changed_physics_blocks_comparison(self):
        self.assertTrue((ROOT/"pso25/report.py").exists(),"Verify that the arms share a simulator and base deck")
        from pso25.report import compatible
        from pso25.run import COMMON_FILES
        sig={"simulator":"JutulDarcy","threads":2,"julia_exe_sha256":"A","runtime_manifest_sha256":"B",
             "files":{k:"same" for k in COMMON_FILES}}
        compatible(sig,sig)
        with self.assertRaises(ValueError):
            compatible(sig,{**sig,"runtime_manifest_sha256":"different"})
        with self.assertRaises(ValueError):
            compatible(sig,{**sig,"files":{**sig["files"],"inputs/BASE.DATA":"other"}})
