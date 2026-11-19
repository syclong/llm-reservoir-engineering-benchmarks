"""Compute a deck-derived static reference without using region numbers or simulator output."""
from itertools import combinations
from statistics import mean

from deck import Grid, expand, numbers, records


def extrema(grid, keyword, cells):
    if not cells:
        return None
    values = [grid.a[keyword][c] for c in cells]
    return [min(values), max(values)]


def static_reference(text):
    grid = Grid(text)
    active_layers = [{c for c in grid.active if grid.ijk(c)[2] == k} for k in range(1, grid.nz + 1)]
    dx, dy = grid.spacing()
    active_top = active_layers[0]
    crest = min(map(grid.top, active_top))
    crests = [grid.ijk(c)[:2] for c in sorted(active_top) if abs(grid.top(c) - crest) < 1e-5]
    i, j = crests[0]
    arms = [[grid.cell(a, j, 1) for a in r] for r in (range(1, i), range(i + 1, grid.nx + 1))]
    arms += [[grid.cell(i, b, 1) for b in r] for r in (range(1, j), range(j + 1, grid.ny + 1))]
    reliefs = [max(grid.top(c) for c in arm if c in active_top) - crest for arm in arms]
    structure = "central_high" if min(reliefs) > 1.0 else "other"

    layers, layer_labels = [], []
    for k, cells in enumerate(active_layers, 1):
        sand = cells & grid.sand
        labels, sizes = grid.components(sand)
        layer_labels.append(labels)
        rocks = {name: {kw: extrema(grid, kw, sub) for kw in ("PORO", "PERMX", "PERMY", "PERMZ")}
                 for name, sub in (("reservoir_quality", sand), ("other_active", cells - sand))}
        layers.append(dict(k=k, role="reservoir" if sand else "barrier", active_cells=len(cells),
                           high_perm_cells=len(sand), high_perm_bodies=len(sizes), body_sizes=sorted(sizes, reverse=True),
                           mean_thickness_m=mean(grid.thickness(c) for c in cells),
                           sand_footprint_km2=len(sand) * dx * dy / 1e6, properties=rocks))

    vertical = []
    for k, cells in enumerate(active_layers[:-1], 1):
        candidates = sum(c + grid.plane in active_layers[k] for c in cells)
        connected = sum((n - c) == grid.plane and c in cells for c, n in grid.edges)
        vertical.append(dict(k=[k, k + 1], formation_link=connected > 0, active_faces=candidates, open_faces=connected))

    wells, completions = grid.read_wells()
    all_labels, _ = grid.components(grid.active)
    pairs = []
    for left, right in combinations(wells, 2):
        same = []
        for k, labels in enumerate(layer_labels, 1):
            a = grid.cell(*left["ij"], k)
            b = grid.cell(*right["ij"], k)
            same.append(a in labels and b in labels and labels[a] == labels[b])
        roots = [{all_labels[c] for c in completions[w["name"]]} for w in (left, right)]
        pairs.append(dict(wells=[left["name"], right["name"]], same_body_by_k=same,
                          open_completion_link=bool(roots[0] & roots[1])))

    equilibrate = expand(records(grid.kw["EQUIL"])[0])
    aquifer = {"AQUCT", "AQUFETP", "AQUFET", "AQUFLUX", "AQUNUM", "AQUANCON"}
    return dict(grid=dict(dims=[grid.nx, grid.ny, grid.nz], active_by_k=list(map(len, active_layers)),
                          dx_m=dx, dy_m=dy, active_total=len(grid.active), logical_total=grid.size),
                geology=dict(structure=structure, crest_ij=crests[0], tied_crest_ij=crests,
                             crest_top_m=crest, active_top_range_m=[crest, max(map(grid.top, active_top))],
                             flank_relief_m=reliefs),
                fluids=dict(phases=[p.lower() for p in ("OIL", "WATER", "GAS") if p in grid.kw],
                            dissolved_gas="DISGAS" in grid.kw, datum_depth_m=float(equilibrate[0]),
                            datum_pressure_bar=float(equilibrate[1]), owc_m=float(equilibrate[2]),
                            goc_m=float(equilibrate[4]), aquifer_specified=bool(aquifer & grid.kw.keys())),
                layers=layers, vertical=vertical, wells=wells, pairs=pairs,
                schedule_days=sum(numbers(grid.kw["TSTEP"])))
