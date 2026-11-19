"""Regression tests for the one-step, cell-based history matching benchmark."""
import csv
from datetime import date
import io
from pathlib import Path
import tempfile
import unittest


class HistoryMatchingTests(unittest.TestCase):
    def module(self):
        self.assertTrue((Path(__file__).resolve().parents[1]/"punq_history_match.py").is_file(), "The one-step harness is required")
        import punq_history_match as hm
        return hm

    def test_includes_are_inlined_in_place_and_region_data_are_absent(self):
        hm=self.module()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/"more.inc").write_text("PORO\n4*0.2 /\n",encoding="utf-8")
            (root/"inner.inc").write_text("INCLUDE 'more.inc' /\n",encoding="utf-8")
            p=root/"test.DATA"
            p.write_text("RUNSPEC\nTITLE\n FIPNUM tutorial\nDIMENS\n2 2 1 /\nREGDIMS\n45 1 1 45 /\nGRID\nINCLUDE\n 'inner.inc' /\nREGIONS\nFIPNUM\n4*2 /\nENDBOX\nSOLUTION\nEQUIL\n1 1 /\nSUMMARY\nROIP\n/\nWOPR\n/\nSCHEDULE\nEND\n",encoding="utf-8")
            expanded,_=hm.expand_deck(p)
            clean=hm.adapt_deck(expanded)
            self.assertNotRegex(clean,r"(?im)fip|^[ \t]*INCLUDE\b")
            self.assertIn("PORO\n4*0.2 /",clean)
            self.assertIn("EQUIL\n1 1 /",clean)

    def test_absolute_edits_keep_inactive_cells_and_untouched_values(self):
        hm=self.module()
        deck="DIMENS\n2 2 1 /\nACTNUM\n1 0 2*1 /\nPORO\n4*0.2 /\nPERMX\n5 0 10 20 /\nPERMY\n5 0 10 20 /\nPERMZ\n0.5 0 1 2 /\n"
        raw='{"edits":[{"i":[1,2],"j":[1,1],"k":[1,1],"porosity":0.24},{"i":[2,2],"j":[2,2],"k":[1,1],"permeability_mD":{"x":30,"y":35,"z":3}}]}'
        changed,info=hm.apply_edits(deck,raw)
        self.assertEqual(hm.grid_array(changed,"PORO"),[.24,.2,.2,.2])
        self.assertEqual(hm.grid_array(changed,"PERMX"),[5,0,10,30])
        self.assertEqual(hm.grid_array(changed,"PERMY"),[5,0,10,35])
        self.assertEqual(hm.grid_array(changed,"PERMZ"),[.5,0,1,3])
        self.assertEqual((info["porosity_cells_changed"],info["permeability_cells_changed"]),(1,1))
        import json
        for bad in ({"edits":[{"region":1,"porosity":.2}]}, {"edits":[dict(json.loads(raw)["edits"][0],i=[0,1])]}, {"edits":json.loads(raw)["edits"]*2}):
            with self.assertRaises(ValueError):
                hm.apply_edits(deck,json.dumps(bad))
        with self.assertRaises(ValueError):
            hm.apply_edits(deck,'{"edits":[],"edits":[]}')

    def test_alignment_and_well_balanced_watercut_score(self):
        hm=self.module()
        days=[date(1967,1,1),date(1967,2,1),date(1967,3,1)]
        obs=[(w,t,100.,0.) for w in ("A","B") for t in days[:2]]
        obs[-1]=("B",days[1],0.,0.)
        series={"wells":["A","B"],"origin":days[0],"time":[0.,7.,31.,59.],
                "oil":{"A":[0.,0.,90.,80.],"B":[0.,0.,50.,0.]},
                "water":{"A":[0.,0.,10.,20.],"B":[0.,0.,50.,0.]}}
        stats,rows=hm.score(obs,days,series)
        self.assertAlmostEqual(stats["watercut_rmse_pp"],100*((((.1**2+.2**2)/2)+.5**2)/2)**.5)
        self.assertEqual((stats["observed_flowing_pairs"],len(rows)),(3,4))
        self.assertEqual(rows[0]["interval_end"],"1967-02-01")
        series["time"]=[0.,7.,30.,59.]
        with self.assertRaises(ValueError): hm.score(obs,days,series)

if __name__=="__main__":
    unittest.main()
