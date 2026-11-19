"""Synchronous PSO using the shared design encoding, well-spacing repair, and velocity update."""
import math

import numpy as np

from fopt5.design import ROOT, read_json
from fopt5.pso import Particle, SHAPE, advance, position_to_plan, realized_position

PROTOCOL = read_json(ROOT / "pso25/protocol.json")
PARTICLES = PROTOCOL["particles"]
GENERATIONS = PROTOCOL["generations"]


class SynchronousSwarm:
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.particles = [
            Particle(self.rng.random(SHAPE), self.rng.uniform(-0.1, 0.1, SHAPE))
            for _ in range(PARTICLES)
        ]
        self.generation = 0
        self.awaiting_scores = False

    def propose_generation(self):
        if self.awaiting_scores or self.generation >= GENERATIONS:
            raise ValueError("Settle the preceding generation before requesting another one within the generation budget")
        if self.generation:
            winner = max(self.particles, key=lambda particle: particle.best_score)
            if winner.best is None:
                raise ValueError("No valid particle-swarm observations are available")
            # All particles in this generation use the same global best frozen at the end of the preceding generation.
            leader = winner.best.copy()
            for particle in self.particles:
                advance(particle, leader, self.rng)
        plans = []
        for particle in self.particles:
            plan = position_to_plan(particle.position)
            particle.position = realized_position(plan)
            plans.append(plan)
        self.generation += 1
        self.awaiting_scores = True
        return plans

    def observe(self, scores):
        if not self.awaiting_scores or len(scores) != PARTICLES:
            raise ValueError("Report all five scores for the same generation in particle order")
        if any(s is not None and not math.isfinite(s) for s in scores):
            raise ValueError("Cumulative oil must be finite or missing")
        for particle, score in zip(self.particles, scores):
            if score is not None and score > particle.best_score:
                particle.best_score = score
                particle.best = particle.position.copy()
        self.awaiting_scores = False
