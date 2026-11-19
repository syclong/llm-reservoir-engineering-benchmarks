"""Regression checks for PSO budgets, simulator identity, and economic shut-in."""
import copy
from pathlib import Path
import tempfile
import unittest
import numpy as np

from fopt5.design import ROOT, dump, parse_plan, read_json, write
from fopt5.experiment import verify_backend
from fopt5.pso import propose, position_to_plan
from fopt5.__main__ import ARMS

class ParticleChecks(unittest.TestCase):
    def test_five_evaluations_and_replay(self):
        seen=[]
        for n,score in enumerate([100,90,120,80,130],1):
            p=propose(seen,20261118,n)
            self.assertEqual(parse_plan(dump(p)),p)
            self.assertEqual(propose(copy.deepcopy(seen),20261118,n),p)
            seen.append({"plan":p,"status":"ok","fopt_sm3":score})
        self.assertEqual(len({dump(r["plan"]) for r in seen}),5)
        self.assertEqual(ARMS,("pso","llm"))
        with self.assertRaises(ValueError):
            propose(seen,20261118,6)
        alt=copy.deepcopy(seen[:2])
        alt[1]["fopt_sm3"]=1_000
        self.assertNotEqual(propose(alt,20261118,3),seen[2]["plan"])

    def test_spacing_repair_and_backend_guard(self):
        plan=position_to_plan(np.zeros((4,7)))
        self.assertEqual(parse_plan(dump(plan)),plan)
        with tempfile.TemporaryDirectory() as d:
            write(Path(d)/"study.json",dump({"signature":{"simulator":"other"}}))
            with self.assertRaises(ValueError):
                verify_backend(d)


class FieldChecks(unittest.TestCase):
    def test_absolute_pressure_order_and_closure_audit(self):
        from fopt5.engine import extract
        import csv
        from itertools import chain
        plan=read_json(ROOT/"examples/output_format.json")
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            raw=root/"raw"
            raw.mkdir()
            grid=np.arange(1,3001)
            pv=np.full(3000,1000.0)
            p0=np.full(3000,260e5)
            so0=np.full(3000,.8)
            # The first substep has a small production rate. The oil produced equals the reduction in oil inventory at the final state.
            dt=36.5*86400
            oil_rate=1e-6
            water_rate=4e-6
            s1=so0-oil_rate*dt/pv.sum()
            pf=240e5+grid
            for name,p,so in (("initial",p0,so0),("final",pf,s1)):
                np.savetxt(raw/(name+".csv"),np.column_stack((grid,pv,p,so,1-so)),delimiter=",",
                           header="cell,PV_m3,PRESSURE_Pa,SOIL,SWAT",comments="")
            meta=['simulator="JutulDarcy"','version="0.4.1"','jutul="0.5.9"','report_steps=100',
                  'horizon_days=3650.0','[closure_day]','PROD1=36.5']
            for w,values in plan.items():
                meta.extend([f"[wells.{w}]",f"ijk={values[:2]+[1]}",f"bhp_bar={values[2:]}"])
            write(raw/"complete.toml","\n".join(meta))
            cols=["time_s","dt_s","FPR_Pa",*(f"{w}_{k}" for w in plan for k in ("qo_m3s","qw_m3s","bhp_Pa","open_bhp"))]
            rows=[]
            for i in range(1,101):
                flows={"INJ1":(0,oil_rate+water_rate if i==1 else 0,362.5e5,1),
                       "INJ2":(0,0,362.5e5,1),"PROD1":(-oil_rate,-water_rate,175e5,1) if i==1 else (0,0,175e5,0),
                       "PROD2":(0,0,175e5,1)}
                rows.append([i*dt,dt,250e5,*chain.from_iterable(flows[w] for w in plan)])
            def save_steps():
                with (raw/"steps.csv").open("w",encoding="utf-8",newline="") as stream:
                    dest=csv.writer(stream)
                    dest.writerow(cols)
                    dest.writerows(rows)
            save_steps()
            result=extract(raw,plan,root/"valid")
            self.assertAlmostEqual(result["fopt_sm3"],oil_rate*dt)
            feedback=(root/"valid/feedback.txt").read_text(encoding="utf-8")
            self.assertTrue(any(line.startswith("J=1 "+repr(float(pf[0]/1e5))+" ") for line in feedback.splitlines()))
            self.assertTrue(any(line.startswith("J=2 "+repr(float(pf[60]/1e5))+" ") for line in feedback.splitlines()))
            rows[1][cols.index("PROD1_open_bhp")]=1.0
            save_steps()
            with self.assertRaisesRegex(ValueError,"Economic shut-in"):
                extract(raw,plan,root/"invalid")
