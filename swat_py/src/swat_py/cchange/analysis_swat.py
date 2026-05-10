"""SWAT 2012 climate change output analysis.

Mirrors cchange_swat.R :: Swat.CChange.Rch.Analysis() and
Swat.CChange.Rch.Cha.Summary().
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd

from swat_py.config.env import EnvConfig
from swat_py.output.reader_swat import parse_output_rch, extract_rch_outtype
from swat_py.output.aggregator import add_date_parts


def analyse_cchange_rch(
    cfg: EnvConfig,
    out_types: List[str],
) -> None:
    """Extract daily/monthly time series for SWAT 2012 CC runs.

    Saves CSVs to ``SwatCcDir/Analysis/{model}/``.
    """
    syear_rcp_vals = (
        cfg.Syear_rcp if isinstance(cfg.Syear_rcp, list) else [cfg.Syear_rcp]
    )

    for outtype in out_types:
        outlets = cfg.OutletFlowIDs if outtype in ("flow", "flowd") else cfg.OutletWqIDs
        outlet_nms = cfg.OutletFlowNms if outtype in ("flow", "flowd") else cfg.OutletWqNms

        for outlet, outlet_nm in zip(outlets, outlet_nms):
            for mdl_nm in cfg.MdlNms:
                mdl_dir = Path(cfg.SwatCcDir) / "Output" / mdl_nm
                analysis_dir = Path(cfg.SwatCcDir) / "Analysis" / mdl_nm
                analysis_dir.mkdir(parents=True, exist_ok=True)

                for scn_nm in cfg.ScnNms:
                    if scn_nm == "historical":
                        syear = int(cfg.Syear_hist)
                    else:
                        syear = min(int(v) for v in syear_rcp_vals)

                    sdate = f"{syear}-01-01"
                    rch_path = mdl_dir / f"output-{scn_nm}.rch"
                    raw = parse_output_rch(rch_path, outlet, sdate)
                    if raw is None:
                        continue

                    typed = extract_rch_outtype(raw, outtype)
                    typed = add_date_parts(typed)

                    tag = f"{outtype}_{outlet}-{outlet_nm}"
                    typed.to_csv(
                        analysis_dir / f"output_{scn_nm}_{tag}-daily.csv",
                        index=False,
                    )

                    sim_col = _main_sim_col(outtype)
                    monthly = typed.groupby("yearmon")[sim_col].mean().reset_index()
                    monthly.to_csv(
                        analysis_dir / f"output_{scn_nm}_{tag}-monthly.csv",
                        index=False,
                    )


def _main_sim_col(outtype: str) -> str:
    return {
        "flow":  "flow_cms",
        "flowd": "flow_mm",
        "sed":   "Sed_ton",
        "sedc":  "Sed_mgl",
        "tn":    "TN_kg",
        "tnc":   "TN_mgl",
        "tp":    "TP_kg",
        "tpc":   "TP_mgl",
    }[outtype]
