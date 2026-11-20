"""Round 5: reduce pore volume along the existing injection connection to test water-arrival timing at P16."""

from datetime import datetime
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(1, str(ROOT.parent))
from compositional_tools import fields
from spatial_tools import native_fields, path_region
from field_edit import save_candidate

parent = fields(ROOT / "candidates/round4_connectivity")
indices, xyz, _ = native_fields()
sw0 = np.fromfile(ROOT / "runs/baseline_tuned/initial_ImmiscibleSaturation.bin")
volume = np.fromfile(ROOT / "runs/baseline_tuned/volumes.bin")
path = np.load(ROOT / "topology/paths.npz")["I12-W__P16"]
weight = path_region(xyz, path, horizontal_radius_m=180.0, vertical_radius_m=20.0)
safe = (sw0 < 0.99) & (parent["PORO"].ravel()[indices] * volume > 1e-3)
phi = parent["PORO"].copy()
phi.ravel()[indices] *= np.exp(np.log(0.5) * weight * safe)
rationale = {
    "decision_time": datetime.now().isoformat(),
    "objective": (
        "Full-period field and well oil and water rates. No additional terminal "
        "weighting; pressure and gas do not rank candidates."
    ),
    "parent_case": (
        "round4_connectivity: retain all permeability and initial composition values "
        "and edit only porosity in the same I12-W to P16 connection region."
    ),
    "observed_feedback": (
        "For P16 in round four the water-rate RMSE through day 1789 was 180.85 "
        "m3/day. The last rate was 240.12 against 461.68 observed; at day 1439 it was "
        "12.91 against 158.39. At day 1281 the rate was 1.46 against 4.97. The "
        "earlier excess water has diminished; do not reinstate the uniform "
        "bottom-water Kh enhancement."
    ),
    "spatial_evidence": (
        "diagnostics_round4_1789: Sw along the 11-node static path is approximately "
        "[.481,.647,.809,.492,.461,.413,.381,.331,.308,.334,.294]. The water front "
        "has advanced toward the producer. A static path is not a tracer streamline "
        "and cannot uniquely identify the source of water."
    ),
    "physical_hypothesis": (
        "Reduce hydrocarbon-bearing pore volume along the existing path with "
        "permeability held fixed. Test whether the front arrives earlier and the day "
        "1300 to 1800 water-rate match improves. Nonlinear field-wide responses may "
        "affect pressure and other wells. Use a complete forward run to measure the "
        "effect; the porosity multiplier alone gives no fitted score."
    ),
    "edit": {
        "path": "I12-W__P16",
        "horizontal_scale_m": 180.0,
        "vertical_scale_m": 20.0,
        "truncation_in_scales": 3.0,
        "central_porosity_multiplier_vs_round4": 0.5,
        "multiplier_application": "phi_new = phi_round4 * exp(log(0.5) * gaussian_path_weight * eligibility_mask)",
    },
    "porosity_eligibility_conditions": (
        "Only active cells with initial Sw < .99 and parent-cell pore volume > 1e-3 "
        "m3 are eligible. Pure-water regions and inactive cells retain their values. "
        "Written porosity satisfies 0 < phi < 1."
    ),
    "fixed_conditions": (
        "Retain all permeabilities, initial composition, initial "
        "pressure/Sw/temperature, EOS, SCAL, grid, completions, historical well "
        "controls, numerical settings and simulator source. The five component "
        "fractions remain nonnegative and sum to one in each cell."
    ),
    "pore_volume_parent_m3": float(np.sum(parent["PORO"].ravel()[indices] * volume)),
    "pore_volume_after_edit_m3": float(np.sum(phi.ravel()[indices] * volume)),
    "verification_requirements": (
        "Run from t0 for 516 reports over 2891 days. Compare rounds three and four "
        "and the formal baseline under the fixed full-period metric. Each run keeps "
        "the same fields throughout."
    ),
}
print(
    save_candidate(
        "round5_path_storage", {"PORO": phi}, rationale, parent="round4_connectivity"
    )
)
(ROOT / "round5_decision.json").write_text(
    json.dumps(rationale, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(rationale, ensure_ascii=False, indent=2))
