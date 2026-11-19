"""Check synchronous updates, evaluation budgets, and duplicate dispatch protection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np

from fopt5.design import ROOT, dump, parse_plan, write
from fopt5.pso import Particle, SHAPE, advance, position_to_plan, realized_position


class SynchronousSwarmTests(unittest.TestCase):
    def swarm(self):
        self.assertTrue((ROOT/"pso25/swarm.py").is_file(), "The synchronous five-particle implementation is required")
        from pso25.swarm import SynchronousSwarm
        return SynchronousSwarm(20261118)

    def test_five_complete_batches_only(self):
        swarm=self.swarm()
        with self.assertRaises(ValueError):
            swarm.observe([1.0]*5)
        for generation in range(1,6):
            plans=swarm.propose_generation()
            self.assertEqual(swarm.generation,generation)
            self.assertEqual(len(plans),5)
            self.assertEqual([parse_plan(dump(p)) for p in plans],plans)
            with self.assertRaises(ValueError):
                swarm.propose_generation()
            with self.assertRaises(ValueError):
                swarm.observe([1.0]*4)
            swarm.observe([float(generation+n) for n in range(5)])
        with self.assertRaises(ValueError):
            swarm.propose_generation()

    def test_all_five_use_previous_generations_frozen_best(self):
        swarm=self.swarm()
        first=swarm.propose_generation()
        rng=np.random.default_rng(20261118)
        particles=[Particle(rng.random(SHAPE),rng.uniform(-.1,.1,SHAPE)) for _ in range(5)]
        for p,plan in zip(particles,first):
            self.assertEqual(position_to_plan(p.position),plan)
            p.position=realized_position(plan)
            p.best=p.position.copy()
        swarm.observe([5.,2.,8.,19.,3.])
        leader=particles[3].best.copy()
        expected=[]
        for p in particles:
            advance(p,leader,rng)
            expected.append(position_to_plan(p.position))
        self.assertEqual(swarm.propose_generation(),expected)

    def test_partial_dispatch_is_never_repeated(self):
        self.assertTrue((ROOT/"pso25/run.py").is_file(), "A scheduler with records keyed by evaluation ID is required")
        from pso25.run import evaluate
        plan=self.swarm().propose_generation()[0]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            write(root/"pso25/r01/launched.txt","submitted")
            solver=Mock()
            with self.assertRaisesRegex(RuntimeError,"already dispatched"):
                evaluate(root,1,1,plan,False,solver)
            solver.run.assert_not_called()
