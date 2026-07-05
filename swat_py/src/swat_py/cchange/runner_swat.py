"""SWAT 2012 climate change scenario runner.

Mirrors cchange_swat.R :: Swat.CChange.Run().
"""

from __future__ import annotations

from pathlib import Path

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat import write_all_weather
from swat_py.io.config_swat import patch_file_cio
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir


def run_cchange(
    cfg: EnvConfig,
    exe_name: str = "SWAT2020.exe",
) -> None:
    """Run SWAT 2012 for every GCM × scenario combination."""
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)

    syear_rcp_vals = (
        cfg.Syear_rcp if isinstance(cfg.Syear_rcp, list) else [cfg.Syear_rcp]
    )
    eyear_rcp_vals = (
        cfg.Eyear_rcp if isinstance(cfg.Eyear_rcp, list) else [cfg.Eyear_rcp]
    )

    for mdl_nm in cfg.MdlNms:
        print(f"\n{mdl_nm} is running...")

        out_dir = Path(cfg.SwatCcDir) / "Output" / mdl_nm
        setup_run_dir(out_dir)

        for scn_nm in cfg.ScnNms:
            wthr_dir = Path(cfg.CcDataDir) / mdl_nm

            # cchange 전용 관측소 메타(climate_change.metadata_file). ids 미지정 시 전체.
            stations = load_station_csv(
                Path(cfg.ObsDayDir) / cfg.CChangeStnFile,
                cfg.CChangeStnIDs,
            )
            write_all_weather(
                stations=stations,
                wthr_dir=wthr_dir,
                out_dir=run_dir,
                fnamestr=scn_nm,
            )

            if scn_nm == "historical":
                syear = int(cfg.Syear_hist)
                eyear = int(cfg.Eyear_hist)
            else:
                syear = min(int(v) for v in syear_rcp_vals)
                eyear = max(int(v) for v in eyear_rcp_vals)

            nbyr = eyear - syear + 1 + nyskip
            iyr = syear - nyskip
            patch_file_cio(run_dir, nbyr, iyr, nyskip)

            SwatExecutor(run_dir, exe_name).run()

            ext_list = cfg.OutputTypes if cfg.OutputTypes else ["rch"]
            rename_outputs(
                run_dir=run_dir,
                out_dir=out_dir,
                output_types=ext_list,
                scenario_name=scn_nm,
                model="swat2012",
            )
