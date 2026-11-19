"""Asynchronous two-particle PSO. Replay its trajectory from the seed and this arm's own observations."""
from dataclasses import dataclass
import math
import numpy as np
from .design import WELLS, dump, parse_plan

N_PARTICLES = 2
INERTIA = 0.7298
COGNITIVE = 1.49618
SOCIAL = 1.49618
SPEED_LIMIT = 0.25
SHAPE = (4, 7)


@dataclass
class Particle:
    position: np.ndarray
    velocity: np.ndarray
    best: np.ndarray | None = None
    best_score: float = -math.inf


def position_to_plan(position):
    """Map normalized coordinates to grid cells and bar. Resolve spacing conflicts at the nearest feasible cell."""
    plan = {}
    placed = []
    for w, row in zip(WELLS, position):
        i = min(60, 1+int(row[0]*60))
        j = min(50, 1+int(row[1]*50))
        def feasible(cell):
            return all(32**2*((cell[0]-x)**2+(cell[1]-y)**2) >= 250**2 for x,y in placed)
        if not feasible((i,j)):
            cells = ((x,y) for x in range(1,61) for y in range(1,51))
            i,j = min(filter(feasible,cells),key=lambda xy:((xy[0]-i)**2+(xy[1]-j)**2,xy))
        placed.append((i,j))
        low,high=(275,450) if w.startswith("INJ") else (100,250)
        pressures=np.round(low+(high-low)*row[2:],2).tolist()
        plan[w]=[i,j,*pressures]
    return parse_plan(dump(plan))


def realized_position(plan):
    result=np.empty(SHAPE)
    for n,w in enumerate(WELLS):
        i,j,*p=plan[w]
        low,high=(275,450) if w.startswith("INJ") else (100,250)
        result[n,:2]=[(i-.5)/60,(j-.5)/50]
        result[n,2:]=(np.asarray(p)-low)/(high-low)
    return result


def advance(particle, leader, rng):
    personal=particle.position if particle.best is None else particle.best
    velocity=(INERTIA*particle.velocity
              + COGNITIVE*rng.random(SHAPE)*(personal-particle.position)
              + SOCIAL*rng.random(SHAPE)*(leader-particle.position))
    velocity=np.clip(velocity,-SPEED_LIMIT,SPEED_LIMIT)
    next_position=particle.position+velocity
    outside=(next_position<0)|(next_position>1)
    # The speed bound permits at most one boundary crossing per step. Reflect both position and velocity.
    particle.position=np.where(next_position<0,-next_position,np.where(next_position>1,2-next_position,next_position))
    particle.velocity=np.where(outside,-velocity,velocity)


def propose(history,seed,round_no):
    if round_no!=len(history)+1 or not (1<=round_no<=5):
        raise ValueError("The particle-swarm round does not match the number of observations")
    rng=np.random.default_rng(seed)
    swarm=[Particle(rng.random(SHAPE),rng.uniform(-.1,.1,SHAPE)) for _ in range(N_PARTICLES)]
    for step in range(round_no):
        particle=swarm[step%N_PARTICLES]
        if step>=N_PARTICLES:
            best=max(swarm,key=lambda p:p.best_score)
            leader=best.best if best.best is not None else particle.position
            advance(particle,leader,rng)
        plan=position_to_plan(particle.position)
        particle.position=realized_position(plan)
        if step==round_no-1:
            return plan
        row=history[step]
        if row.get("plan")!=plan:
            raise ValueError("The saved proposal differs from the fixed-seed particle trajectory")
        if row["status"]=="ok" and row["fopt_sm3"]>particle.best_score:
            particle.best_score=row["fopt_sm3"]
            particle.best=particle.position.copy()
