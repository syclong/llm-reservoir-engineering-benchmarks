"""Read the self-contained, Cartesian-pillar corner-point case used in experiment 03."""
from functools import cached_property
from math import dist
import re
import shlex
from statistics import mean

KEYWORD = re.compile(r"^[A-Z][A-Z0-9_]{0,11}[ \t]*$", re.MULTILINE)
REPORT_ONLY = {"REGDIMS", "FIPNUM", "RPR"}
CELL_ARRAYS = ("ACTNUM", "PORO", "PERMX", "PERMY", "PERMZ", "MULTX", "MULTY", "MULTZ")


def normalize(text):
    return "\n".join(line.split("--", 1)[0].rstrip() for line in text.splitlines()).strip() + "\n"


def blocks(text):
    matches = list(KEYWORD.finditer(text))
    result = {}
    for index, match in enumerate(matches):
        keyword = match.group().strip()
        if keyword in result:
            raise ValueError(f"Repeated keyword {keyword} is outside this case reader")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[keyword] = text[match.end():end].strip()
    return result


def blind(text):
    cleaned = normalize(text)
    original = blocks(cleaned)
    if "INCLUDE" in original or not REPORT_ONLY <= original.keys():
        raise ValueError("Expected the self-contained source deck with its regional diagnostics")
    pieces = []
    for keyword, body in original.items():
        if keyword in REPORT_ONLY:
            continue
        pieces.append(keyword)
        if keyword == "TITLE":
            pieces.append(" Case A")
        elif body:
            pieces.append(body)
    result = "\n".join(pieces) + "\n"
    retained = blocks(result)
    for keyword, body in original.items():
        if keyword not in REPORT_ONLY | {"TITLE"} and retained.get(keyword) != body:
            raise ValueError(f"Numerical or operational record changed in {keyword}")
    return result


def expand(tokens):
    values = []
    for token in tokens:
        count, star, value = token.partition("*")
        if star:
            values.extend([value or None] * int(count or 1))
        else:
            values.append(token)
    return values


def records(body):
    return [shlex.split(item) for item in body.split("/") if item.strip()]


def numbers(body):
    return [float(token) for token in expand(body.replace("/", " ").split())]


class Grid:
    def __init__(self, text):
        self.kw = blocks(normalize(text))
        self.nx, self.ny, self.nz = map(int, numbers(self.kw["DIMENS"]))
        self.size = self.nx * self.ny * self.nz
        self.plane = self.nx * self.ny
        self.a = {name: numbers(self.kw[name]) for name in CELL_ARRAYS}
        if any(len(vals) != self.size for vals in self.a.values()):
            raise ValueError("Cell array length disagrees with DIMENS")
        self.zcorn = numbers(self.kw["ZCORN"])
        self.coord = numbers(self.kw["COORD"])
        if len(self.zcorn) != 8 * self.size or len(self.coord) != 6 * (self.nx + 1) * (self.ny + 1):
            raise ValueError("Corner-point geometry dimensions disagree")
        self.active = {c for c, a in enumerate(self.a["ACTNUM"]) if a > 0}
        self.sand = {c for c in self.active if min(self.a["PERMX"][c], self.a["PERMY"][c]) >= 1.0}

    def cell(self, i, j, k):
        if not (1 <= i <= self.nx and 1 <= j <= self.ny and 1 <= k <= self.nz):
            raise ValueError("Out-of-grid I,J,K")
        return (k - 1) * self.plane + (j - 1) * self.nx + i - 1

    def ijk(self, cell):
        k, within = divmod(cell, self.plane)
        j, i = divmod(within, self.nx)
        return i + 1, j + 1, k + 1

    def corners(self, cell, bottom=False):
        i, j, k = (v - 1 for v in self.ijk(cell))
        offset = ((2 * k + int(bottom)) * (2 * self.ny) + 2 * j) * (2 * self.nx) + 2 * i
        return [self.zcorn[offset + dj * 2 * self.nx + di] for dj in (0, 1) for di in (0, 1)]

    def top(self, cell):
        return mean(self.corners(cell))

    def thickness(self, cell):
        return mean(self.corners(cell, True)) - self.top(cell)

    def spacing(self):
        def point(i, j):
            s = 6 * (j * (self.nx + 1) + i)
            return self.coord[s:s + 2]
        x = [dist(point(i, j), point(i + 1, j)) for j in range(self.ny + 1) for i in range(self.nx)]
        y = [dist(point(i, j), point(i, j + 1)) for j in range(self.ny) for i in range(self.nx + 1)]
        if max(x) - min(x) > 1e-6 or max(y) - min(y) > 1e-6:
            raise ValueError("This protocol expects uniform plan-view spacing")
        return mean(x), mean(y)

    @cached_property
    def edges(self):
        result = []
        for c in sorted(self.active):
            i, j, k = self.ijk(c)
            neighbors = (("X", self.nx - i, 1), ("Y", self.ny - j, self.nx), ("Z", self.nz - k, self.plane))
            for axis, remaining, stride in neighbors:
                n = c + stride
                if not remaining or n not in self.active:
                    continue
                perm = self.a["PERM" + axis]
                if self.a["MULT" + axis][c] > 0 and min(perm[c], perm[n]) > 0:
                    result.append((c, n))
        return result

    def components(self, cells):
        adjacency = {c: [] for c in cells}
        for c, n in self.edges:
            if c in cells and n in cells:
                adjacency[c].append(n)
                adjacency[n].append(c)
        labels = {}
        sizes = []
        for seed in sorted(cells):
            if seed in labels:
                continue
            label = len(sizes)
            stack = [seed]
            labels[seed] = label
            count = 0
            while stack:
                c = stack.pop()
                count += 1
                for n in adjacency[c]:
                    if n not in labels:
                        labels[n] = label
                        stack.append(n)
            sizes.append(count)
        return labels, sizes

    def read_wells(self):
        specs = {r[0]: r for r in records(self.kw["WELSPECS"])}
        controls = {r[0]: expand(r) for r in records(self.kw["WCONPROD"])}
        completions = {name: [] for name in specs}
        for name, i, j, top, base, state, *_ in records(self.kw["COMPDAT"]):
            if state == "OPEN":
                for k in range(int(top), int(base) + 1):
                    c = self.cell(int(i), int(j), k)
                    if c not in self.active:
                        raise ValueError("An OPEN completion is inactive")
                    completions[name].append(c)
        result = []
        for name, r in specs.items():
            control = controls[name]
            if control[1:3] != ["OPEN", "ORAT"]:
                raise ValueError("Expected the case's fixed oil-rate producer controls")
            result.append(dict(name=name, ij=list(map(int, r[2:4])), open_k=sorted({self.ijk(c)[2] for c in completions[name]}),
                               control=control[2], oil_target_sm3_d=float(control[3]), bhp_limit_bar=float(control[8]),
                               allow_wellbore_crossflow=(expand(r)[9].upper() == "YES")))
        return result, completions
