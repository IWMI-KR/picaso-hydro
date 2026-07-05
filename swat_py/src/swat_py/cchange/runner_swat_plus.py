"""SWAT-Plus climate change scenario runner.

Mirrors cchange_swat_plus.R :: Swat.CChange.Run.Plus().
"""

from __future__ import annotations

from pathlib import Path

from swat_py.config.env import EnvConfig
from swat_py.io.station import load_station_csv
from swat_py.io.weather_swat_plus import write_all_weather_plus
from swat_py.io.config_swat_plus import write_time_sim, patch_print_prt
from swat_py.runner.executor import SwatExecutor
from swat_py.runner.file_manager import rename_outputs, setup_run_dir


def run_cchange_plus(
    cfg: EnvConfig,
    exe_name: str = "SWAT-Plus.exe",
) -> None:
    """Run SWAT-Plus for every GCM × scenario combination.

    Outer loop: MdlNms (GCM names)
    Inner loop: ScnNms (scenarios: historical, ssp126, ssp245, etc.)

    For each combination:
    1. Write weather inputs from ``CcDataDir/{model}/``
    2. Update time.sim + print.prt
    3. Run SWAT-Plus.exe
    4. Rename output to ``SwatCcDir/Output/{model}/channel_sd_day-{scn}.txt``
    """
    nyskip = int(cfg.CioNYSKIP)
    run_dir = Path(cfg.SwatRunDir)

    # Syear_rcp / Eyear_rcp may be a single value or list of period endpoints
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

            # cchange 전용 관측소 메타(climate_change.metadata_file, 예: stations-cchange.csv).
            # ids 미지정 시 파일 내 전체 관측소.
            stations = load_station_csv(
                Path(cfg.ObsDayDir) / cfg.CChangeStnFile,
                cfg.CChangeStnIDs,
            )
            write_all_weather_plus(
                stations=stations,
                wthr_dir=wthr_dir,
                out_dir=run_dir,
                fnamestr=scn_nm,
            )

            # Determine simulation period
            if scn_nm == "historical":
                syear = int(cfg.Syear_hist)
                eyear = int(cfg.Eyear_hist)
            else:
                syear = min(int(v) for v in syear_rcp_vals)
                eyear = max(int(v) for v in eyear_rcp_vals)

            nbyr = eyear - syear + 1 + nyskip
            iyr = syear - nyskip
            write_time_sim(run_dir, nbyr, iyr)
            patch_print_prt(run_dir, nbyr, iyr, nyskip)

            # Run SWAT-Plus
            SwatExecutor(run_dir, exe_name).run()

            # Rename outputs
            rename_outputs(
                run_dir=run_dir,
                out_dir=out_dir,
                output_types=cfg.OutputTypes,
                scenario_name=scn_nm,
                model="swat_plus",
            )
