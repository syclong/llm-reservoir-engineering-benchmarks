#!/usr/bin/env python3
"""Single-step PUNQ history matching. Python 3.10+ and OPM Flow 2026.04."""
import argparse
import contextlib
import csv
from datetime import date, datetime, timezone
import hashlib
import itertools
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import uuid

MODEL = "gpt-6-astra"
FLOW_IMAGE = "openporousmedia/opmreleases@sha256:db8865d7c80440513c8c73df7ed385a3b7d2e055a0ef95f7662ec06ef6a6b3a9"
CONTEXT_LIMIT, RESERVED = 1_000_000, 8704
PROPS = ("PORO", "PERMX", "PERMY", "PERMZ")
WELLS = ("PRO-1", "PRO-4", "PRO-5", "PRO-11", "PRO-12", "PRO-15", "PRO-20")
PREVIEW_MARK = "[PENDING BASELINE SIMULATION]"
EPS = 1e-8


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(text.encode("utf-8"))
        tmp = handle.name
    os.replace(tmp, path)


def as_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def csv_text(header, rows):
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def mask_comments(text):
    # Keep the positions of all characters, including quoted paths with dashes.
    pattern = r"""'(?:''|[^'\n])*'|"[^"\n]*"|--[^\n]*"""
    return re.sub(pattern, lambda m: " " * len(m[0]) if m[0].startswith("--") else m[0], text)


def expand_deck(main):
    main = Path(main).resolve()
    root = main.parent
    files = {}
    keyword = re.compile(r'''(?im)^[ \t]*INCLUDE\b\s*(?:'([^'\n]+)'|"([^"\n]+)")\s*/[ \t]*''')
    def visit(path, ancestors):
        path = path.resolve()
        require(path.is_relative_to(root) and path not in ancestors, "Invalid or circular INCLUDE")
        text = read(path)
        files[path.relative_to(root).as_posix()] = sha(path.read_bytes())
        pos, pieces = 0, []
        for m in keyword.finditer(mask_comments(text)):
            rel = (m[1] or m[2]).replace("\\", "/")
            if Path(rel).name.casefold()=="punq_s3n_fipnum.inc":
                # This tutorial's reporting-only include is outside the model's input.
                pieces.extend([text[pos:m.start()], "\n"])
                pos=m.end()
                continue
            local = path.parent / rel
            child = local if local.is_file() else root / rel
            pieces.extend([text[pos:m.start()], visit(child, ancestors + (path,)).rstrip("\n"), "\n"])
            pos = m.end()
        pieces.append(text[pos:])
        return "".join(pieces)
    deck = visit(main, ())
    require(not re.search(r"(?im)^[ \t]*INCLUDE\b", mask_comments(deck)), "Unresolved INCLUDE record")
    return deck, files


def array_body(deck, name):
    masked = mask_comments(deck)
    tags = list(re.finditer(r"(?im)^[ \t]*"+re.escape(name)+r"[ \t]*$", masked))
    require(len(tags) == 1, f"Expected exactly one {name} array")
    start = tags[0].end()
    stop = masked.find("/", start)
    require(stop >= 0, f"Unterminated {name} array")
    return start, stop, masked[start:stop]


def grid_array(deck, name):
    _, _, body = array_body(deck, name)
    result = []
    for item in body.split():
        n, sep, value = item.partition("*")
        count, literal = (int(n), value) if sep else (1, n)
        require(count > 0 and len(result) + count <= 2_000_000, f"Invalid repeat count in {name}")
        v = float(literal.replace("D", "E").replace("d", "e"))
        require(math.isfinite(v), f"Non-finite {name} value")
        result.extend([v] * count)
    return result


def section_span(deck, name, following):
    text = mask_comments(deck)
    left = re.search(r"(?im)^[ \t]*"+name+r"\b[^\n]*\n", text)
    require(left is not None, f"Missing {name} section")
    right = re.search(r"(?im)^[ \t]*"+following+r"\b[^\n]*$", text[left.end():])
    require(right is not None, f"Missing {following} section")
    return left.end(), left.end() + right.start()


def drop_array_record(text, name):
    masked = mask_comments(text)
    match = re.search(r"(?im)^[ \t]*"+re.escape(name)+r"[ \t]*$", masked)
    if match is None:
        return text
    stop = masked.find("/", match.end())
    require(stop >= 0, f"Unterminated {name} record")
    return text[:match.start()] + text[stop+1:]


def adapt_deck(expanded):
    # Only remove the grouping material and its output requests from this tutorial.
    text = re.sub(r"(?im)^([ \t]*(?:RUNSPEC|GRID|PROPS|REGIONS|SOLUTION|SUMMARY|SCHEDULE))[ \t]*=+[ \t]*$", r"\1", expanded)
    text, n = re.subn(r"(?im)^([ \t]*TITLE[ \t]*\n)[^\n]*", r"\1 PUNQ-S3 SINGLE-STEP HISTORY MATCH", text)
    require(n == 1, "Expected one title")
    text = drop_array_record(text, "REGDIMS")
    # The source uses both defaults implicitly. OPM needs these table counts explicitly.
    additions = "".join(name+"\n 1 /\n" for name in ("NUMRES","EQLDIMS")
                        if not re.search(r"(?im)^[ \t]*"+name+r"[ \t]*$", mask_comments(text)))
    if additions:
        text = re.sub(r"(?im)^([ \t]*RUNSPEC[ \t]*\n)", lambda m:m[0]+additions, text, count=1)
    a,b = section_span(text, "REGIONS", "SOLUTION")
    region = drop_array_record(text[a:b], "FIPNUM")
    region = re.sub(r"(?im)^[ \t]*ENDBOX[ \t]*$", "", region)
    require(not mask_comments(region).strip(), "Unexpected physical region keyword. Review this deck before adapting it.")
    text = text[:a] + "\n" + text[b:]
    a,b = section_span(text, "SUMMARY", "SCHEDULE")
    summary = re.sub(r"(?im)^[ \t]*(?:RGIPL|RGIP|ROIP|RWIP|RPR|ROE)[ \t]*\n[ \t]*/[ \t]*$", "", text[a:b])
    if re.search(r"(?im)^[ \t]*AQUCT[ \t]*$", mask_comments(text)):
        # Request cumulative influx of the two analytical aquifers as solver evidence.
        summary = summary.rstrip() + "\nAAQT\n 1 2 /\n\n"
    text = text[:a]+summary+text[b:]
    # Save the reservoir state at each report period, in addition to the summary histories.
    if not re.search(r"(?im)^[ \t]*RPTRST[ \t]*$", mask_comments(text)):
        text = re.sub(r"(?im)^([ \t]*SCHEDULE[ \t]*\n)", lambda m:m[0]+"\nRPTRST\n 'BASIC=2' /\n", text, count=1)
    require(not re.search(r"(?i)fip",text), "Unexpected region entry in the cell-indexed working deck")
    return text


def grid(deck):
    dims = grid_array(deck, "DIMENS")
    require(len(dims)==3 and all(v==int(v) and v>0 for v in dims), "Invalid grid dimensions")
    dims = tuple(map(int, dims))
    cells = math.prod(dims)
    mask = grid_array(deck, "ACTNUM")
    require(len(mask)==cells and all(x in (0.,1.) for x in mask), "Invalid activity array")
    arrays = {name:grid_array(deck,name) for name in PROPS}
    require(all(len(v)==cells for v in arrays.values()), "Rock array size differs from DIMENS")
    for i, active in enumerate(mask):
        if active:
            require(0<arrays["PORO"][i]<1 and all(arrays[k][i]>=0 for k in PROPS[1:]), "Invalid initial active-cell properties")
    return dims, mask, arrays


def strict_object(raw):
    def unique(pairs):
        obj={}
        for k,v in pairs:
            require(k not in obj, f"Duplicate JSON field {k}")
            obj[k]=v
        return obj
    def invalid(_):
        raise ValueError("Non-finite JSON number")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def numeric(value):
    require(type(value) in (int,float) and math.isfinite(value), "Expected a finite numeric value")
    return float(value)


def apply_edits(deck, raw):
    proposal=strict_object(raw)
    require(isinstance(proposal,dict) and set(proposal)=={"edits"}, "Expected a single edits list")
    edits=proposal["edits"]
    require(isinstance(edits,list) and edits, "Provide at least one edit")
    dims,active,props=grid(deck)
    used={"porosity":set(), "permeability_mD":set()}
    changed={key:set() for key in used}
    for patch in edits:
        axes={"i","j","k"}
        require(isinstance(patch,dict) and axes<=set(patch) and set(patch)<=axes|set(used), "Invalid edit coordinates or fields")
        require(bool(set(patch)&set(used)), "Every edit needs a property")
        ranges=[]
        for axis,limit in zip(("i","j","k"),dims):
            bounds=patch[axis]
            require(isinstance(bounds,list) and len(bounds)==2 and all(type(n) is int for n in bounds)
                    and 1<=bounds[0]<=bounds[1]<=limit, f"Invalid {axis} range")
            ranges.append(range(bounds[0]-1,bounds[1]))
        ids=[(k*dims[1]+j)*dims[0]+i for k,j,i in itertools.product(ranges[2],ranges[1],ranges[0])]
        cells={i for i in ids if active[i]}
        require(cells, "An edit does not select any active cells")
        for field in used:
            if field not in patch:
                continue
            require(used[field].isdisjoint(cells), f"Overlapping {field} assignments")
            used[field].update(cells)
            if field=="porosity":
                v=numeric(patch[field])
                require(0<v<1, "Porosity must be strictly between zero and one")
                values={"PORO":v}
            else:
                tensor=patch[field]
                require(isinstance(tensor,dict) and set(tensor)=={"x","y","z"}, "Specify all three permeability components")
                values={kw:numeric(tensor[axis]) for axis,kw in zip(("x","y","z"),PROPS[1:])}
                require(min(values.values())>=0, "Permeability must be nonnegative")
            for i in cells:
                if any(props[kw][i]!=v for kw,v in values.items()):
                    changed[field].add(i)
                for kw,v in values.items():
                    props[kw][i]=v
    require(all(changed.values()), "The proposal must change at least one active cell in each property family")
    spans=[]
    for name in PROPS:
        a,b,_=array_body(deck,name)
        vals=props[name]
        body="\n"+"\n".join(" ".join(repr(v) for v in vals[i:i+8]) for i in range(0,len(vals),8))+"\n"
        spans.append((a,b,body))
    result=deck
    for a,b,repl in sorted(spans,reverse=True):
        result=result[:a]+repl+result[b:]
    require(grid(result)[2]==props, "Rock fields did not round-trip")
    return result,{"boxes":len(edits),"porosity_cells_changed":len(changed["porosity"]),
                   "permeability_cells_changed":len(changed["permeability_mD"])}


def deck_date(s):
    months="JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    dd,mon,yy=s.upper().replace("'","").split()
    return date(int(yy),months.index(mon)+1,int(dd))


def period_dates(deck):
    text=mask_comments(deck)
    start=re.search(r"(?im)^[ \t]*START[ \t]*\n\s*([^/\n]+)\s*/",text)
    require(start is not None,"Missing START date")
    edges=[deck_date(start[1])]
    for block in re.finditer(r"(?im)^[ \t]*DATES[ \t]*\n(.*?)^[ \t]*/[ \t]*$",text,re.S):
        edges.extend(deck_date(d) for d in re.findall(r"(?im)^[ \t]*(\d+[ \t]+'?[A-Za-z]+'?[ \t]+\d{4})[ \t]*/",block[1]))
    require(len(edges)>1 and all(a<b for a,b in zip(edges,edges[1:])), "Invalid report calendar")
    return edges


def schedule_targets(deck, edges):
    """Read the oil/water history and whole-well shut periods directly from the schedule."""
    clean=mask_comments(deck)
    schedule=re.split(r"(?im)^[ \t]*SCHEDULE[ \t]*$",clean,maxsplit=1)[-1]
    tags=list(re.finditer(r"(?m)^[ \t]*([A-Z][A-Z0-9_]*)[ \t]*$",schedule))
    rates,opened,observed={}, {}, []
    interval=0
    for idx,tag in enumerate(tags):
        key=tag[1]
        block=schedule[tag.end():(tags[idx+1].start() if idx+1<len(tags) else len(schedule))]
        if key=="WCONHIST":
            for rec in re.finditer(r"(?im)^[ \t]*'([^']+)'[ \t]+([^ \t\n]+)[ \t]+([^ \t\n]+)[ \t]+([^/\n]+?)[ \t]*/",block):
                w,flag,mode=rec[1],rec[2].strip("'").upper(),rec[3].strip("'").upper()
                require(w in WELLS and flag in ("1*","OPEN","SHUT","STOP") and mode=="LRAT", "Unexpected well control in source schedule")
                nums=rec[4].split()
                oil,water=map(float,nums[:2])
                require(all(math.isfinite(v) and v>=0 for v in (oil,water)), "Invalid historical rates")
                rates[w]=(oil,water)
                opened[w]=flag in ("1*","OPEN")
        elif key=="WELOPEN":
            for rec in re.finditer(r"(?im)^[ \t]*'([^']+)'[ \t]+('[A-Z]+'|[A-Z]+)[ \t]*/",block):
                w,flag=rec[1],rec[2].strip("'").upper()
                require(w in WELLS and flag in ("SHUT","STOP","OPEN"), "Unexpected well-status record")
                opened[w]=flag=="OPEN"
        elif key=="DATES":
            for raw in re.findall(r"(?im)^[ \t]*(\d+[ \t]+'?[A-Za-z]+'?[ \t]+\d{4})[ \t]*/",block):
                require(interval<len(edges)-1 and deck_date(raw)==edges[interval+1],"Calendar/schedule mismatch")
                require(set(rates)==set(WELLS),"Missing initial well history")
                for w in WELLS:
                    observed.append((w,edges[interval],*(rates[w] if opened[w] else (0.,0.))))
                interval+=1
    require(interval==len(edges)-1,"Incomplete schedule history")
    return observed


def targets_table(obs,edges):
    ends=dict(zip(edges,edges[1:]))
    return csv_text(["interval_start","interval_end","start_day","end_day","well","WOPR_obs_sm3_d","WWPR_obs_sm3_d"],
                    ((d.isoformat(),ends[d].isoformat(),(d-edges[0]).days,(ends[d]-edges[0]).days,w,qo,qw)
                     for w,d,qo,qw in obs))


TASK = """Perform a single-step history match for the supplied oil-water-gas reservoir. The seven producers are controlled by total surface liquid rate. Compare the recorded oil and water rates in the production schedule with the actual simulated well production curves, identify mismatches, and submit ONE update to the reservoir rock fields. The evaluator will rebuild the deck from the same initial state and run OPM Flow once with your edits.

The objective is to minimize the well-balanced water-cut RMSE in percentage points. For each observed producing interval, water cut = surface water rate / (surface oil rate + surface water rate). For each well, average the squared differences between simulated and observed water cut over its observed flowing intervals. Average those well means equally, take the square root, and multiply by 100. If an observed well is flowing but its simulated total production is zero, that sample contributes 1.0 squared error. Observed shut-in intervals are excluded from this primary score. Oil-rate and water-rate RMSE on all matched rows are also reported separately in standard cubic meters per day. The schedule sets the total liquid rate.

The grid has 19 x 28 x 5 logical cells. Coordinates are one-based; I varies fastest, followed by J and then K. ACTNUM selects active cells. The DATA arrays PORO, PERMX, PERMY and PERMZ are the actual starting cell properties. A deck entry n*value denotes n consecutive copies. Geometry, activity, wells, completions, controls, aquifers, initial conditions, fluids, and relative permeability stay fixed. Locate each edit by its grid indices.

Return a single JSON object with an "edits" array. Each edit names inclusive ranges "i":[lo,hi], "j":[lo,hi], and "k":[lo,hi]. For a single cell use equal endpoints. An edit can assign "porosity" (an absolute fraction strictly between 0 and 1), "permeability_mD" (an object with absolute nonnegative "x", "y", and "z" values in mD), or both. Supply absolute cell values. Each edit must contain at least one active cell. Inactive cells and unspecified properties keep their original values. Assign each property family once per edited active cell. Include at least one effective porosity change and one effective permeability change across the full proposal. Choose the locations, extent and values yourself. The shape is {"edits":[{"i":[I1,I2],"j":[J1,J2],"k":[K1,K2],"porosity":PHI,"permeability_mD":{"x":KX,"y":KY,"z":KZ}}]}. Replace symbolic entries with numbers. Use plain JSON for the response.

The historical rates are supplied by the DATA schedule. During a completed baseline run the evaluator reads the WOPRH and WWPRH history vectors from OPM Flow and checks them against that schedule. The target table pairs each interval start with its end date and elapsed day. Compare the targets with computed surface WOPR and WWPR at the interval end. All saved summary series are inline, with their keyword, entity, and unit on the line above their values. TIME is in days from the start date. WOPR, WWPR and WGPR are forward surface rates in sm³/day. WBHP is simulated absolute pressure in bar. WOPRH and WWPRH repeat the entered oil and water targets over each control interval."""


def score(obs, edges, series):
    """Match every target to its own well and right report boundary, without interpolation."""
    times=series["time"]
    require(times and all(math.isfinite(t) for t in times) and all(a<=b for a,b in zip(times,times[1:])), "Invalid summary time axis")
    require(series["origin"]==edges[0] and abs(times[-1]-(edges[-1]-edges[0]).days)<=1e-4,"The simulation did not finish the original calendar")
    wells=series["wells"]
    require(len(set(wells))==len(wells),"Duplicate well names")
    require({(w,d) for w,d,_,_ in obs}==set(itertools.product(wells,edges[:-1]))
            and len(obs)==len(wells)*(len(edges)-1),"Incomplete or duplicate target rows")
    for phase in ("oil","water"):
        for w in wells:
            values=series[phase][w]
            require(len(values)==len(times) and all(math.isfinite(v) and v>=-EPS for v in values),"Invalid production curve")
    ends=dict(zip(edges,edges[1:]))
    endpoint={}
    for d in edges[1:]:
        day=(d-edges[0]).days
        hits=[i for i,t in enumerate(times) if abs(t-day)<=1e-4]
        require(bool(hits),f"Missing simulated report date {d}")
        for i in hits[1:]:
            require(all(series[p][w][i]==series[p][w][hits[0]] for w in wells for p in ("oil","water")),
                    f"Ambiguous simulation outputs at {d}")
        endpoint[d]=hits[-1]
    errors={w:[] for w in wells}
    osq,wsq,rows=[],[],[]
    for w,d,oil,water in obs:
        i=endpoint[ends[d]]
        so,sw=series["oil"][w][i],series["water"][w][i]
        ot,st=oil+water,so+sw
        ref=water/ot if ot>EPS else None
        fit=sw/st if st>EPS else None
        if ref is not None:
            errors[w].append((ref-fit)**2 if fit is not None else 1.0)
        osq.append((so-oil)**2)
        wsq.append((sw-water)**2)
        rows.append({"interval_start":d.isoformat(),"interval_end":ends[d].isoformat(),"well":w,
                     "oil_target":oil,"oil_sim":so,"water_target":water,"water_sim":sw,
                     "water_cut_target":ref,"water_cut_sim":fit})
    require(all(errors.values()),"A well has no flowing observation")
    means={w:math.fsum(v)/len(v) for w,v in errors.items()}
    stats={"watercut_rmse_pp":100*math.sqrt(math.fsum(means.values())/len(means)),
           "oil_rate_rmse_sm3_d":math.sqrt(math.fsum(osq)/len(osq)),
           "water_rate_rmse_sm3_d":math.sqrt(math.fsum(wsq)/len(wsq)),
           "observed_flowing_pairs":sum(map(len,errors.values())),"all_well_interval_pairs":len(obs),
           "per_well_watercut_rmse_pp":{w:100*math.sqrt(v) for w,v in means.items()}}
    return stats,rows


def assemble_prompt(deck, history_text, series=None, stats=None, *, task=TASK):
    parts=[task,"[BEGIN COMPLETE WORKING DATA]",deck.rstrip("\n"),"[END COMPLETE WORKING DATA]",
           "[BEGIN SEVEN-WELL OIL AND WATER HISTORY]",history_text.rstrip("\n"),"[END SEVEN-WELL HISTORY]",
           "[BEGIN ALL SAVED SIMULATION SUMMARY SERIES]"]
    if series is None:
        parts.extend([PREVIEW_MARK+" The prepare command inserts actual OPM time series here.",
                      "[END ALL SAVED SIMULATION SUMMARY SERIES]","[REVIEW COPY] A preview with a pending baseline is never submitted."])
    else:
        require(stats is not None,"Baseline score is required")
        parts.extend([summary_plain_text(series),"[END ALL SAVED SIMULATION SUMMARY SERIES]","[BASELINE FIT]",
                      f"Well-balanced water-cut RMSE: {stats['watercut_rmse_pp']:.12g} percentage points",
                      f"Oil-rate RMSE: {stats['oil_rate_rmse_sm3_d']:.12g} sm³/day",
                      f"Water-rate RMSE: {stats['water_rate_rmse_sm3_d']:.12g} sm³/day",
                      "Per-well water-cut RMSE (percentage points)\n"+"\n".join(f"{w}  {v:.12g}" for w,v in stats["per_well_watercut_rmse_pp"].items()),
                      "[END INPUT] Return your single JSON proposal now."])
    result="\n\n".join(parts)+"\n"
    require(re.search(r"(?i)fip",result) is None,"A grouping label was found in the model-facing text")
    require(len(result.encode("utf-8"))+RESERVED<=CONTEXT_LIMIT,"The full untruncated prompt exceeds the study budget")
    return result


def initialize(source, work):
    source=Path(source).expanduser().resolve()
    main=source/"PUNQ_S3N.DATA" if source.is_dir() else source
    original,files=expand_deck(main)
    deck=adapt_deck(original)
    dims,activity,_=grid(deck)
    require(dims==(19,28,5) and sum(activity)==1761,"Unexpected PUNQ grid dimensions or activity")
    edges=period_dates(deck)
    require(len(edges)==53 and edges[0]==date(1967,1,1) and edges[-1]==date(1983,7,1),"Unexpected PUNQ schedule")
    obs=schedule_targets(deck,edges)
    target=targets_table(obs,edges)
    original_controls=re.findall(r"(?im)^[ \t]*'(PRO-[0-9]+)'[ \t]+(?:1\*|'?OPEN'?)[ \t]+(LRAT|ORAT|WRAT|GRAT|BHP|RESV)\b",mask_comments(deck))
    require({m for _,m in original_controls}=={"LRAT"} and {w for w,_ in original_controls}==set(WELLS),"Unexpected historical well controls")
    require(all(re.search(r"(?im)^[ \t]*"+kw+r"[ \t]*$",mask_comments(deck)) for kw in ("AQUCT","AQUANCON","DRSDT","STONE1")),"Missing physical keyword")
    record={"id":"PUNQ_ONE_STEP_CELL_FIELDS_V1","model":MODEL,"shape":list(dims),"active_cells":int(sum(activity)),
            "wells":list(WELLS),"intervals":len(edges)-1,"history_rows":len(obs),"flowing_rows":sum(x+y>EPS for _,_,x,y in obs),
            "start":edges[0].isoformat(),"end":edges[-1].isoformat(),"deck_sha256":sha(deck.encode()),
            "targets_sha256":sha(target.encode()),"original_source_sha256":files,"history_source":"WCONHIST with WELOPEN, verified against OPM WOPRH/WWPRH at report endpoints",
            "objective":"well-balanced water-cut RMSE in percentage points",
            "baseline_and_candidate":"same initial state, deck controls, solver and numerical settings",
            "proposal_budget":1}
    work=Path(work)
    for rel,body in (("case.json",as_json(record)),("baseline/MODEL.DATA",deck),("schedule_history.csv",target)):
        path=work/rel
        if path.exists():
            require(path.read_bytes()==body.encode(),f"Frozen input differs at {rel}. Use a new study directory.")
        else:
            write(path,body)
    return deck,edges,obs,target


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()


def flow_settings(executable=None):
    if executable:
        found=shutil.which(str(executable))
        require(found, "Native Flow executable was not found")
        command=[str(Path(found).resolve())]
        descriptor={"engine":"OPM Flow","binary_sha256":file_hash(command[0])}
    else:
        docker=shutil.which("docker")
        require(docker,"Install Docker or supply --flow with a native OPM Flow executable")
        command=[docker,"run","--rm","--network","none","--entrypoint","/usr/bin/flow",FLOW_IMAGE]
        descriptor={"engine":"OPM Flow","docker_image":FLOW_IMAGE}
    version=subprocess.run([*command,"--version"],capture_output=True,check=True,timeout=600)
    message=version.stdout.decode("utf-8","replace").strip()
    require("flow" in message.lower(),"Unrecognized Flow version")
    descriptor.update(version=message,threads=1)
    return descriptor


def run_flow(case, executable=None, timeout=1800, expected=None):
    case=Path(case).resolve()
    deck=case/"MODEL.DATA"
    digest=file_hash(deck)
    stamp=case/"flow_complete.json"
    if stamp.is_file():
        rec=json.loads(read(stamp))
        require(rec["data_sha256"]==digest and rec["exit_code"]==0, "Existing run belongs to a different deck")
        if expected is not None: require(rec["solver"]==expected,"Baseline/candidate solver mismatch")
        for n,checksum in rec["output_sha256"].items():
            require(file_hash(case/"output"/n)==checksum, f"Raw output changed: {n}")
        return rec
    descriptor=flow_settings(executable)
    if expected is not None: require(descriptor==expected,"Baseline/candidate solver mismatch")
    output=case/"output"
    require(not output.exists(), "An output directory already exists without a completion receipt. Inspect the interrupted run.")
    run_id="punqhm-"+uuid.uuid4().hex[:16]
    started=utc()
    marker=case/"dispatched.json"
    with marker.open("x",encoding="utf-8") as f:
        f.write(as_json({"utc":started,"data_sha256":digest,"solver":descriptor,"job":run_id}))
    output.mkdir()
    env=dict(os.environ,OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1")
    if executable:
        args=[shutil.which(str(executable)),str(deck),"--output-dir="+str(output),"--threads-per-process=1"]
    else:
        require("," not in str(case),"The Docker mount path cannot contain a comma")
        args=[shutil.which("docker"),"run","--rm","--name",run_id,"--network","none",
              "--mount",f"type=bind,source={case},target=/case","--workdir","/case",
              "-e","OMP_NUM_THREADS=1","-e","OPENBLAS_NUM_THREADS=1","--entrypoint","/usr/bin/flow",FLOW_IMAGE,
              "MODEL.DATA","--output-dir=/case/output","--threads-per-process=1"]
    with (case/"flow.log").open("wb") as log:
        try:
            result=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,env=env,cwd=case,timeout=timeout)
        except subprocess.TimeoutExpired:
            if not executable:
                subprocess.run(["docker","stop",run_id],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            raise
    if result.returncode:
        raise RuntimeError(f"OPM Flow exited {result.returncode}. See {case / 'flow.log'}")
    for ext in ("SMSPEC","UNSMRY","EGRID","INIT","UNRST"):
        require((output/("MODEL."+ext)).is_file(), f"Missing Flow output MODEL.{ext}")
    rec={"solver":descriptor,"data_sha256":digest,"started_utc":started,"finished_utc":utc(),
         "exit_code":result.returncode,"output_sha256":{p.name:file_hash(p) for p in sorted(output.iterdir()) if p.is_file()}}
    write(stamp,as_json(rec))
    return rec


def ecl_records(path, selected=None):
    """Read Eclipse binary keyword arrays with either byte order."""
    with Path(path).open("rb") as f:
        first=f.read(4)
        require(len(first)==4,"Empty binary file")
        endian=">" if struct.unpack(">i",first)[0]==16 else "<"
        f.seek(0)
        def record():
            mark=f.read(4)
            if not mark: return None
            require(len(mark)==4,"Truncated Fortran marker")
            size=struct.unpack(endian+"i",mark)[0]
            require(0<=size<=500_000_000,"Invalid Fortran record length")
            data=f.read(size)
            require(len(data)==size and f.read(4)==mark,"Broken Fortran record")
            return data
        while (head:=record()) is not None:
            require(len(head)==16,"Invalid keyword header")
            key=head[:8].decode("ascii").strip()
            count=struct.unpack(endian+"i",head[8:12])[0]
            kind=head[12:16].decode("ascii")
            fmt={"INTE":"i","LOGI":"i","REAL":"f","DOUB":"d"}.get(kind)
            if fmt: width=struct.calcsize(endian+fmt)
            elif kind=="CHAR": width=8
            elif re.fullmatch(r"C\d{3}",kind): width=int(kind[1:])
            elif kind=="MESS": width=0
            else: raise ValueError(f"Unsupported binary type {kind}")
            require(count>=0 and (width or not count),"Invalid array count")
            left=count*width
            keep=selected is None or key in selected
            chunks=[]
            while left:
                block=record()
                require(block is not None and 0<len(block)<=left,"Partial binary data array")
                if keep: chunks.append(block)
                left-=len(block)
            if keep:
                data=b"".join(chunks)
                if fmt: vals=struct.unpack(endian+str(count)+fmt,data)
                elif width: vals=tuple(data[i:i+width].decode("ascii").strip() for i in range(0,len(data),width))
                else: vals=()
                yield key,kind,vals


def get_vectors(prefix):
    spec={k:v for k,_,v in ecl_records(prefix.with_suffix(".SMSPEC"))}
    keys=spec["KEYWORDS"]
    names=spec.get("WGNAMES",spec.get("NAMES"))
    units,nums=spec["UNITS"],spec["NUMS"]
    require(names is not None and len(keys)==len(names)==len(units)==len(nums),"Invalid summary specification")
    params=[(kind,v) for _,kind,v in ecl_records(prefix.with_suffix(".UNSMRY"),{"PARAMS"})]
    require(params and all(k in ("REAL","DOUB") and len(v)==len(keys) for k,v in params),"Invalid summary matrix")
    data=[v for _,v in params]
    require(all(math.isfinite(x) for row in data for x in row),"Non-finite summary value")
    code=".9g" if all(k=="REAL" for k,_ in params) else ".17g"
    fmt=lambda x:format(x,code)
    def column(kw,well=None,number=None,unit=None):
        loc=[i for i,k in enumerate(keys) if k==kw and (well is None or names[i]==well) and (number is None or nums[i]==number)]
        require(len(loc)==1,f"Missing or ambiguous summary vector {kw} {well or number or ''}")
        idx=loc[0]
        if unit: require(units[idx].upper() in unit,f"Unexpected unit for {kw}: {units[idx]}")
        return [row[idx] for row in data]
    origin=spec["STARTDAT"]
    series={"wells":list(WELLS),"origin":date(origin[2],origin[1],origin[0]),"time":column("TIME",unit={"DAYS","DAY"}),"format":fmt}
    for kw,field in (("WOPR","oil"),("WWPR","water"),("WGPR","gas"),("WBHP","bhp"),("WOPRH","oil_h"),("WWPRH","water_h")):
        series[field]={w:column(kw,w,unit={"BARSA","BARA","BAR"} if kw=="WBHP" else {"SM3/DAY","SM3/D"}) for w in WELLS}
    series["aquifer_cumulative"]={str(n):column("AAQT",number=n,unit={"SM3"})[-1] for n in (1,2)}
    series["total_oil_sm3"]=column("FOPT",unit={"SM3"})[-1]
    series["metadata"]=[(i+1,k,"" if n.startswith(":+") else n,int(num),u) for i,(k,n,num,u) in enumerate(zip(keys,names,nums,units))]
    series["data"]=data
    return series


def vector_label(meta):
    index,key,name,num,unit=meta
    ident=name if name else str(num) if num>0 else "FIELD"
    return f"C{index:03d} {key} {ident} [{unit or '1'}]"


def summary_plain_text(series):
    """Inline every numeric series, with precision sufficient to recover its stored values."""
    fmt=series["format"]
    lines=["TIME gives elapsed days. Each numbered series has one value for each saved time, in that order.",
           "Only the entered oil and water histories are scored. Other historical quantities can contain defaults or derived values."]
    for i,meta in enumerate(series["metadata"]):
        lines.extend([vector_label(meta)," ".join(fmt(row[i]) for row in series["data"])])
    return "\n".join(lines)


def historical_from_output(schedule,edges,s):
    times=s["time"]
    vals=[]
    max_abs=0.
    ends=dict(zip(edges,edges[1:]))
    for w,d,qo,qw in schedule:
        end=ends[d]
        hits=[i for i,t in enumerate(times) if abs(t-(end-edges[0]).days)<=1e-4]
        require(hits,f"No historical output at {end}")
        i=hits[-1]
        oil,water=s["oil_h"][w][i],s["water_h"][w][i]
        require(all((s["oil_h"][w][j],s["water_h"][w][j])==(oil,water) for j in hits),"Ambiguous historical endpoint")
        require(math.isclose(oil,qo,rel_tol=3e-6,abs_tol=1e-5) and math.isclose(water,qw,rel_tol=3e-6,abs_tol=1e-5),
                f"Native history and schedule differ at {w} for {d} through {end}")
        max_abs=max(max_abs,abs(oil-qo),abs(water-qw))
        vals.append((w,d,oil,water))
    return vals,max_abs


def target_plain_text(obs,edges):
    ends=dict(zip(edges,edges[1:]))
    by_well={w:[] for w in WELLS}
    for w,d,qo,qw in obs:
        by_well[w].append(f"{d.isoformat()}  {ends[d].isoformat()}  {(ends[d]-edges[0]).days}  {qo:.9g}  {qw:.9g}")
    parts=["Each row is one history interval. Oil and water are surface rates in sm³/day."]
    for w in WELLS:
        parts.append(w+"\ninterval_start  interval_end  end_day  WOPRH  WWPRH\n"+"\n".join(by_well[w]))
    return "\n\n".join(parts)


def verify_grid(prefix,deck,edges,out):
    import gzip
    dims,active,props=grid(deck)
    mesh={k:v for k,_,v in ecl_records(prefix.with_suffix(".EGRID"),{"GRIDHEAD","ACTNUM"})}
    require(tuple(mesh["GRIDHEAD"][1:4])==dims and tuple(active)==mesh["ACTNUM"],"Flow grid differs from the deck")
    ids=[i for i,v in enumerate(active) if v]
    init={k:v for k,_,v in ecl_records(prefix.with_suffix(".INIT"),set(PROPS))}
    require(set(init)==set(PROPS),"Missing rock property in INIT")
    for name in PROPS:
        v=init[name]
        if len(v)==len(active): v=[v[i] for i in ids]
        require(len(v)==len(ids) and all(math.isclose(x,props[name][i],rel_tol=2e-6,abs_tol=1e-7) for x,i in zip(v,ids)),
                f"Flow did not read the requested {name} field")
    coords=[(i%dims[0]+1,(i//dims[0])%dims[1]+1,i//(dims[0]*dims[1])+1) for i in ids]
    count=0
    current=None
    header=["report","elapsed_days","date","I","J","K","PRESSURE_bar","SWAT","SGAS","SOIL_derived","RS"]
    temp=out/"reservoir_states.csv.gz.tmp"
    def emit(state,writer):
        ix=state["SEQNUM"][0]
        require(ix==count and 0<=ix<len(edges),"Unexpected restart sequence")
        elapsed=state["DOUBHEAD"][0]
        require(abs(elapsed-(edges[ix]-edges[0]).days)<1e-5,"Restart time mismatch")
        ih=state["INTEHEAD"]
        require(tuple(ih[8:12])==(*dims,len(ids)) and date(ih[66],ih[65],ih[64])==edges[ix],"Restart header mismatch")
        fields=[state[k] for k in ("PRESSURE","SWAT","SGAS","RS")]
        require(all(len(v)==len(ids) for v in fields),"Incomplete cell state")
        final=[]
        for cell,(pressure,sw,sg,rs) in zip(coords,zip(*fields)):
            so=1-sw-sg
            require(all(math.isfinite(x) for x in (pressure,sw,sg,rs)) and pressure>0 and min(sw,sg,so)>=-1e-4 and max(sw,sg,so)<=1.0001,
                    "Nonphysical restart pressure or saturations")
            row=[ix,elapsed,edges[ix].isoformat(),*cell,pressure,sw,sg,so,rs]
            writer.writerow(row)
            if ix==len(edges)-1: final.append(row)
        return final
    with (temp.open("wb") as destination,
          gzip.GzipFile(filename="",mode="wb",fileobj=destination,mtime=0) as packed,
          io.TextIOWrapper(packed,encoding="utf-8",newline="") as f):
        writer=csv.writer(f,lineterminator="\n")
        writer.writerow(header)
        for key,_,vals in ecl_records(prefix.with_suffix(".UNRST"),{"SEQNUM","DOUBHEAD","INTEHEAD","PRESSURE","SWAT","SGAS","RS"}):
            if key=="SEQNUM":
                if current is not None:
                    emit(current,writer)
                    count+=1
                current={}
            require(current is not None,"Restart data before first sequence")
            current[key]=vals
        require(current is not None,"Empty restart file")
        final=emit(current,writer)
        count+=1
    require(count==len(edges) and len(final)==len(ids),"Incomplete restart history")
    os.replace(temp,out/"reservoir_states.csv.gz")
    write(out/"final_cells.csv",csv_text(header,final))
    return {"grid":list(dims),"active_cells":len(ids),"restart_snapshots":count,"state_rows":len(ids)*count,
            "initial_and_final_dates":[edges[0].isoformat(),edges[-1].isoformat()],"solver_read_rock_fields":list(PROPS)}


def matrices_and_curves(case, deck, edges, schedule):
    case=Path(case)
    prefix=case/"output/MODEL"
    s=get_vectors(prefix)
    hist,err=historical_from_output(schedule,edges,s)
    stats,pairs=score(hist,edges,s)
    require(all(v>0 for v in s["aquifer_cumulative"].values()),"Expected positive cumulative influx from both aquifers in this case")
    qc=verify_grid(prefix,deck,edges,case)
    qc.update(summary_times=len(s["time"]),summary_vectors=len(s["metadata"]),first_output_day=s["time"][0],
              final_day=s["time"][-1],history_schedule_max_abs_sm3_d=err,
              aquifer_cumulative_influx_sm3=s["aquifer_cumulative"],final_field_oil_sm3=s["total_oil_sm3"])
    write(case/"qc.json",as_json(qc))
    write(case/"fit.json",as_json(stats))
    write(case/"history_oil_water.csv",targets_table(hist,edges))
    write(case/"well_curves_all_times.csv",csv_text(["time_days","well","WOPR_sm3_d","WWPR_sm3_d","WGPR_sm3_d","WBHP_bar","WOPRH_sm3_d","WWPRH_sm3_d"],
          ([s["format"](t),w,*[s["format"](s[p][w][i]) for p in ("oil","water","gas","bhp","oil_h","water_h")]]
           for i,t in enumerate(s["time"]) for w in WELLS)))
    write(case/"matched_history.csv",csv_text(list(pairs[0]),(tuple(row.values()) for row in pairs)))
    write(case/"summary_channels.csv",csv_text(["index","keyword","entity","number","unit"],s["metadata"]))
    write(case/"summary_full.csv",csv_text([vector_label(v) for v in s["metadata"]],([s["format"](x) for x in row] for row in s["data"])))
    return s,hist,stats,qc


@contextlib.contextmanager
def study_lock(work):
    work.mkdir(parents=True,exist_ok=True)
    with (work/".study.lock").open("a+b") as f:
        if f.seek(0,2)==0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def load_inputs(source, work):
    if source is not None:
        return initialize(source,work)
    require((work/"case.json").is_file(),"Supply --source with the tutorial directory on the first invocation")
    record=json.loads(read(work/"case.json"))
    deck=read(work/"baseline/MODEL.DATA")
    require(sha(deck.encode())==record["deck_sha256"],"Baseline deck hash mismatch")
    edges=period_dates(deck)
    schedule=schedule_targets(deck,edges)
    targets=targets_table(schedule,edges)
    require(sha(targets.encode())==record["targets_sha256"] and read(work/"schedule_history.csv")==targets,"Frozen schedule history mismatch")
    return deck,edges,schedule,targets


def prepare(work, deck, edges, schedule, executable, timeout, audit_only=False):
    case=work/"baseline"
    if audit_only:
        require((case/"flow_complete.json").is_file(),"No complete baseline available for audit")
    receipt=run_flow(case,executable,timeout)
    series,hist,stats,qc=matrices_and_curves(case,deck,edges,schedule)
    real=assemble_prompt(deck,target_plain_text(hist,edges),series,stats)
    note={"model":MODEL,"input_messages":1,"tools":[],"attachments":[],"sha256":sha(real.encode("utf-8")),
          "utf8_bytes":len(real.encode("utf-8")),"context_window":CONTEXT_LIMIT,"reserved":RESERVED,
          "data_sha256":receipt["data_sha256"],"history_source":"OPM WOPRH/WWPRH from DATA schedule",
          "history_pairs":len(hist),"summary_channels":qc["summary_vectors"],"values_per_channel":qc["summary_times"]}
    if (work/"proposal/intent.json").exists():
        require((work/"prompt.txt").read_bytes()==real.encode("utf-8") and
                json.loads(read(work/"prompt_receipt.json"))==note,"Prompt changed after proposal dispatch")
    write(work/"prompt.txt",real)
    write(work/"prompt_receipt.json",as_json(note))
    return {"solver":receipt["solver"],"history":hist,"fit":stats,"prompt_sha256":note["sha256"]}


def collect_proposal(work, baseline, manual=None):
    folder=work/"proposal"
    folder.mkdir(exist_ok=True)
    intent=folder/"intent.json"
    rawfile=folder/"response.txt"
    payload=(work/"prompt.txt").read_bytes()
    require(sha(payload)==baseline["prompt_sha256"] and PREVIEW_MARK.encode() not in payload,"Expected the full verified baseline prompt")
    if rawfile.exists():
        raw=rawfile.read_bytes().decode("utf-8-sig")
        if manual is not None:
            require(Path(manual).read_bytes().decode("utf-8-sig")==raw,"The registered one-step response cannot be replaced")
        saved=json.loads(read(intent))
        require(saved["prompt_sha256"]==sha(payload) and saved["model"]==MODEL,"Proposal registration mismatch")
        verify_delivered_reply(folder,raw,sha(payload))
        return raw
    if manual is None:
        require(not intent.exists(),"A request was already dispatched. Use only its original response if recovering.")
        client=shutil.which("llm")
        require(client is not None,"The llm command must be available, or use submit with the original reply")
    else:
        raw=Path(manual).read_bytes().decode("utf-8-sig")
    if not intent.exists():
        with intent.open("x",encoding="utf-8") as stream:
            stream.write(as_json({"utc":utc(),"model":MODEL,"prompt_sha256":sha(payload),
                                  "mode":"manual" if manual is not None else "single_text","tools":[],"attachments":[]}))
    else:
        require(json.loads(read(intent))["prompt_sha256"]==sha(payload),"Original request used a different prompt")
    if manual is None:
        # The model receives bytes on stdin. It gets no file paths, tool definitions, or prior conversation.
        with tempfile.TemporaryDirectory(prefix="punq-single-message-") as temp:
            try:
                result=subprocess.run([client,"prompt","--model",MODEL,"--no-stream","--no-log"],
                                      input=payload,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                      cwd=temp,shell=False,timeout=1200,check=False,
                                      env=dict(os.environ,PYTHONUTF8="1",PYTHONIOENCODING="utf-8"))
            except subprocess.TimeoutExpired:
                raise RuntimeError("Model transport timed out; the prompt intent is preserved.") from None
        require(result.returncode==0,f"Model command exited with code {result.returncode}")
        raw=result.stdout.decode("utf-8-sig")
    write(rawfile,raw)
    verify_delivered_reply(folder,raw,sha(payload))
    return raw


def verify_delivered_reply(folder,raw,prompt_hash):
    evidence={"prompt_sha256":prompt_hash,"response_sha256":sha(raw.encode("utf-8")),"model":MODEL}
    receipt=folder/"reply_receipt.json"
    if receipt.exists():
        require(json.loads(read(receipt))==evidence,"Previously delivered model text changed")
    else:
        write(receipt,as_json(evidence))


def evaluate_candidate(work,deck,edges,schedule,baseline,raw,executable,timeout):
    try:
        new,edits=apply_edits(deck,raw)
    except (ValueError,TypeError,OverflowError) as exc:
        write(work/"proposal/invalid.json",as_json({"status":"invalid","error":str(exc),"simulator_calls":0,"response_sha256":sha(raw.encode())}))
        raise
    case=work/"candidate"
    p=case/"MODEL.DATA"
    if p.is_file():
        require(p.read_bytes()==new.encode("utf-8"),"The candidate was already created from a different proposal")
    else:
        write(p,new)
    write(case/"edits_applied.json",as_json(edits))
    run_flow(case,executable,timeout,expected=baseline["solver"])
    series,hist,_,qc=matrices_and_curves(case,new,edges,schedule)
    require(hist==baseline["history"],"The candidate does not have identical historical targets")
    after,_=score(baseline["history"],edges,series)
    before=baseline["fit"]
    j0,j1=before["watercut_rmse_pp"],after["watercut_rmse_pp"]
    report={"baseline":before,"candidate":after,"reduction_pp":j0-j1,
            "relative_reduction_pct":100*(j0-j1)/j0 if j0>0 else None,
            "improved":j1<j0,"changed":edits,"candidate_data_sha256":sha(new.encode()),
            "response_sha256":sha(raw.encode()),"prompt_sha256":baseline["prompt_sha256"],
            "history_checks_passed":True,"candidate_report_snapshots":qc["restart_snapshots"]}
    write(work/"comparison.json",as_json(report))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("preview","prepare","audit","run","submit"))
    parser.add_argument("--source",type=Path,help="Source tutorial directory or its PUNQ_S3N.DATA file")
    parser.add_argument("--work",type=Path,default=Path("study"))
    parser.add_argument("--flow",help="Optional native OPM Flow executable. Default: pinned Docker image.")
    parser.add_argument("--timeout",type=int,default=1800,help="Maximum seconds per flow solve")
    parser.add_argument("--response",type=Path,help="Original one-step JSON response, for submit")
    args=parser.parse_args()
    require(args.timeout>0,"A positive simulator timeout is required")
    require((args.command=="submit")==bool(args.response),"Only submit takes a --response file and it is required")
    work=args.work.resolve()
    with study_lock(work):
        deck,edges,schedule,_=load_inputs(args.source,work)
        if args.command=="preview":
            if (work/"baseline/flow_complete.json").is_file():
                prepare(work,deck,edges,schedule,args.flow,args.timeout,audit_only=True)
                print(work/"prompt.txt")
            else:
                write(work/"prompt_preview.txt",assemble_prompt(deck,target_plain_text(schedule,edges)))
                print(work/"prompt_preview.txt")
            return
        baseline=prepare(work,deck,edges,schedule,args.flow,args.timeout,audit_only=args.command=="audit")
        if args.command in ("prepare","audit"):
            print(as_json({"baseline":baseline["fit"],"prompt":str(work/"prompt.txt")}))
            return
        raw=collect_proposal(work,baseline,args.response)
        outcome=evaluate_candidate(work,deck,edges,schedule,baseline,raw,args.flow,args.timeout)
        print(as_json(outcome))


if __name__=="__main__":
    main()
