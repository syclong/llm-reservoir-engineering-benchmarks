"""Run JutulDarcy in batch mode and verify the raw numerical output."""
import csv
import hashlib
import io
import os
from pathlib import Path
import subprocess
import time
import tomllib
import numpy as np
from .design import ROOT, WELLS, write


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Solver:
    """Reuse the Julia process and build a fresh reservoir case for every feasible proposal."""
    def __init__(self, config, study, timeout=900):
        self.config, self.study, self.timeout = config, Path(study), timeout
        self.proc = self.log = None

    def start(self):
        cfg = self.config
        # The numerical worker only inherits system, locale, and numerical runtime settings.
        system = {"PATH", "HOME", "USER", "USERNAME", "USERPROFILE", "SYSTEMROOT", "SYSTEMDRIVE",
                  "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA",
                  "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "LANG", "TZ", "HOMEDRIVE",
                  "HOMEPATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "JULIA_CPU_TARGET"}
        env = {name: value for name, value in os.environ.items()
               if name.upper() in system or name.upper().startswith(("LC_", "OMP_", "OPENBLAS_", "MSMPI_"))}
        env["JULIA_LOAD_PATH"] = "@"+os.pathsep+"@stdlib"
        if cfg["depot"]:
            env["JULIA_DEPOT_PATH"] = cfg["depot"]
        args = [cfg["exe"], "--startup-file=no", "-O1", f"--threads={cfg['threads']}",
                "--compiled-modules="+("yes" if cfg["compiled_modules"] else "no"),
                "--project="+str(cfg["project"]), str(ROOT/"solver/evaluate.jl"), "--worker"]
        self.log = (self.study/"julia.log").open("ab")
        try:
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log, env=env)
        except BaseException:
            self.log.close()
            raise

    def run(self, folder):
        folder = Path(folder).resolve()
        raw = folder/"jutul"
        if raw.exists() or (folder/"launched.txt").exists():
            raise ValueError("This round already has a solver dispatch record")
        if self.proc is None:
            self.start()
        names = [str(folder/"MODEL.DATA"), str(raw)]
        if any(any(c in v for c in "\t\r\n") for v in names):
            raise ValueError("Solver paths cannot contain tabs or line breaks")
        # Write the dispatch marker before sending the job, so an interruption cannot cause a duplicate evaluation.
        write(folder/"launched.txt", "JutulDarcy worker\n")
        self.proc.stdin.write(("\t".join(names)+"\n").encode("utf-8"))
        self.proc.stdin.flush()
        end = time.monotonic() + self.timeout
        while time.monotonic() < end:
            if (raw/"complete.toml").is_file():
                return
            if (raw/"error.txt").is_file():
                raise RuntimeError("Julia failed to solve this case. See jutul/error.txt in the round directory.")
            if self.proc.poll() is not None:
                raise RuntimeError("The Julia process exited early. See julia.log in the study directory.")
            time.sleep(0.25)
        self.close(kill=True)
        raise TimeoutError("The Julia simulation timed out")

    def close(self, kill=False):
        if self.proc is not None:
            try:
                if kill and self.proc.poll() is None:
                    self.proc.kill()
                self.proc.stdin.close()
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            finally:
                self.log.close()
                self.proc = None


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def field(raw, name):
    values = np.loadtxt(raw/name, delimiter=",", skiprows=1, ndmin=2)
    require(values.shape == (3000, 5) and np.isfinite(values).all(), "The grid field is incomplete or contains non-finite values")
    cell, pv, pressure, so, sw = values.T
    require(np.array_equal(cell,np.arange(1,3001)), "Grid indices or cell ordering are incorrect")
    require(np.all(pv > 0) and np.all(pressure > 0), "Invalid pore volume or absolute pressure")
    require(np.allclose(so+sw,1,rtol=0,atol=1e-7) and min(sw)>=-1e-7 and max(sw)<=1+1e-7,"Invalid oil or water saturation")
    return pv, pressure/1e5, so, sw


def extract(raw, plan, folder):
    """Integrate surface oil rates over accepted substeps and cross-check against the change in reservoir oil inventory."""
    raw, folder = Path(raw), Path(folder)
    with (raw/"complete.toml").open("rb") as handle:
        meta = tomllib.load(handle)
    require((meta["simulator"],meta["version"],meta["jutul"]) == ("JutulDarcy","0.4.1","0.5.9"),"Unexpected simulator or package version")
    require(meta["report_steps"]==100 and abs(meta["horizon_days"]-3650)<1e-7,"The simulation did not complete the ten-year horizon")
    pv, p0, s0, sw0 = field(raw,"initial.csv")
    pv1, p, so, sw = field(raw,"final.csv")
    require(np.array_equal(pv,pv1) and np.allclose(p0,260) and np.allclose(sw0,.2) and np.allclose(s0,.8),"Initial state or pore volumes differ from the shared case")
    series = np.genfromtxt(raw/"steps.csv", delimiter=",", names=True, ndmin=1)
    require(len(series)>0 and all(np.isfinite(series[n]).all() for n in series.dtype.names),"Accepted substep history is incomplete")
    sec, dt = series["time_s"],series["dt_s"]
    days = sec/86400
    require(min(dt)>0 and np.allclose(sec,np.cumsum(dt),rtol=0,atol=1e-5) and abs(days[-1]-3650)<1e-7,"The accepted substep timeline contains a gap")
    require(all(np.any(np.isclose(days,x,rtol=0,atol=1e-7)) for x in 36.5*np.arange(1,101)),"A scheduled report time is missing")
    require(set(meta["wells"])==set(WELLS) and set(meta["closure_day"]).issubset(WELLS[2:]),"Unexpected well names or closure records")
    qo_field, qw_field, qi_field = (np.zeros(len(dt)) for _ in range(3))
    well_cols = {}
    well_cums = []
    for w in WELLS:
        i,j,*targets = plan[w]
        declared = meta["wells"][w]
        require(declared["ijk"]==[i,j,1] and np.allclose(declared["bhp_bar"], targets,rtol=0,atol=1e-7),"Simulated completion or BHP schedule differs from the plan")
        qo, qw, bhp, opened = (series[w+"_"+k] for k in ("qo_m3s","qw_m3s","bhp_Pa","open_bhp"))
        inj = w.startswith("INJ")
        direction = 1 if inj else -1
        require(min(direction*qo)>=-1e-7 and min(direction*qw)>=-1e-7, "Unexpected well flow direction")
        period = np.minimum(4,np.floor((sec-dt+1e-4)/(730*86400)).astype(int))
        flow = abs(qo)+abs(qw)>1e-7
        require(np.all((opened==0)|(opened==1)) and np.all(opened[flow]==1), "Detected flow after well shut-in")
        require(np.allclose(bhp[flow]/1e5,np.asarray(targets)[period][flow],rtol=0,atol=.05), "BHP for a flowing well differs from its target")
        if inj:
            require(np.max(np.abs(qo))<1e-7,"A water injector has nonzero oil flow")
            qi_field += qw
            well_cols[w+"_WWIR"]=qw*86400
        else:
            oil, water = -qo, -qw
            liquid = oil+water
            cut = np.divide(water,liquid,out=np.zeros_like(oil),where=liquid>1e-14)
            crossings = np.flatnonzero((liquid>1e-14)&(cut>=.78))
            event=meta["closure_day"].get(w)
            require((event is not None)==bool(len(crossings)), "Economic shut-in event is inconsistent with the surface water cut")
            if event is not None:
                first=int(crossings[0])
                require(abs(days[first]-event)<1e-7 and np.all(opened[first+1:]==0) and not np.any(flow[first+1:]), "Economic shut-in did not persist for the rest of the simulation")
            opt=np.cumsum(oil*dt)
            well_cums.append(float(opt[-1]))
            qo_field+=oil
            qw_field+=water
            for key,v in (("WOPR",oil*86400),("WWPR",water*86400),("WOPT",opt),("WWCT",cut)):
                well_cols[w+"_"+key]=v
        well_cols[w+"_WBHP"]=bhp/1e5
    opt = np.cumsum(qo_field*dt)
    total = float(opt[-1])
    stock_loss = float(np.dot(pv,s0-so))
    injected, produced_water = float(np.dot(qi_field,dt)), float(np.dot(qw_field,dt))
    require(abs(sum(well_cums)-total)<max(.01,abs(total)*1e-10) and np.all(np.diff(opt)>=-1e-5),"Field cumulative oil or the sum of well production totals is inconsistent")
    require(abs(stock_loss-total)<max(2,abs(total)*2e-4),"Surface oil production differs from the change in reservoir oil inventory")
    require(abs(injected-produced_water-total)<max(2,abs(injected)*2e-4),"Field injection and production volumes do not balance")
    cols={"TIME":days,"FOPT":opt,"FOPR":qo_field*86400,"FWPR":qw_field*86400,"FWIR":qi_field*86400,"FPR":series["FPR_Pa"]/1e5,**well_cols}
    buffer=io.StringIO()
    writer=csv.writer(buffer,lineterminator="\n")
    writer.writerow(cols)
    for row in zip(*cols.values()):
        writer.writerow([repr(float(x)) for x in row])
    history=buffer.getvalue()
    write(folder/"history.csv",history)
    parts=["Surface rates are end-of-substep values for all accepted substeps. TIME is in days, rates in sm³/d, cumulative volumes in sm³, and absolute pressure in bar. Cumulative production starts at zero on day 0. FPR is weighted by hydrocarbon pore volume.",history]
    for name,values in (("PRESSURE",p),("SOIL",so),("SWAT",sw)):
        parts.append(name+" K=1. Rows run from J=1 to 50. Each row contains 60 values in order from I=1 to 60.")
        parts.extend("J="+str(j)+" "+" ".join(repr(float(v)) for v in row) for j,row in enumerate(values.reshape(50,60),1))
    write(folder/"feedback.txt","\n".join(parts)+"\n")
    return {"simulator":"JutulDarcy","version":meta["version"],"fopt_sm3":total,"sum_well_wopt_sm3":sum(well_cums),
            "inventory_loss_sm3":stock_loss,"injected_water_sm3":injected,"produced_water_sm3":produced_water,
            "closure_day":meta["closure_day"],"active_cells":3000,"final_day":float(days[-1]),"accepted_steps":len(dt),
            "raw_sha256":{name:file_sha(raw/name) for name in ("initial.csv","final.csv","steps.csv","complete.toml")}}
