#!/usr/bin/env python3
"""Copy the published outputs from WORKING/ into the repo's data/ folder.

The build scripts write their results to WORKING/, which is not in the repo (it also holds
about 4 GB of raw source downloads). This copies the outputs worth publishing into D3/data/,
so they can be linked from the site and the README. Run it after any rebuild; it overwrites
the copies and reports anything missing.
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
W = ROOT / "WORKING"
OUT = ROOT / "D3/data"

FILES = {
    "join": [
        W / "JOIN/dam_species_matches.csv",
        W / "JOIN/dam_habitat_join.csv",
        W / "JOIN/join_summary.txt",
    ],
    "audit": [
        W / "JOIN/audit/join_gap_audit.csv",
        W / "JOIN/audit/join_gap_audit.txt",
        W / "JOIN/audit/nacc_crosscheck.csv",
        W / "JOIN/audit/nacc_crosscheck.txt",
        W / "JOIN/audit/nhd_channel_names.csv",
        W / "JOIN/audit/same_stream_sweep.csv",
        W / "JOIN/audit/same_stream_sweep.txt",
        W / "JOIN/audit/range_edge_sweep.csv",
        W / "JOIN/audit/range_edge_sweep.txt",
    ],
    "soncc": [
        W / "LAYERS/derived/soncc_coho_derived_fullres.gpkg",
        W / "LAYERS/derived/soncc_manifest.json",
        W / "LAYERS/derived/soncc_stage_accounting.csv",
        W / "LAYERS/derived/soncc_dam_checks.csv",
        W / "LAYERS/derived/soncc_boundary_dam_effect.csv",
        W / "SS_BASINS/boundary_basins.geojson",
        W / "SS_BASINS/boundary_basins_check.json",
    ],
    ".": [
        W / "PRESENCE_SOURCES_MANIFEST.json",
    ],
}

missing = []
for sub, srcs in FILES.items():
    dest = OUT / sub
    dest.mkdir(parents=True, exist_ok=True)
    for src in srcs:
        if not src.exists():
            missing.append(src)
            continue
        name = src.name.lower() if sub == "." else src.name
        shutil.copy2(src, dest / name)
        print(f"copied {src.relative_to(ROOT)} -> {(dest / name).relative_to(ROOT)}")

if missing:
    print("\nMISSING (not copied):")
    for m in missing:
        print("  ", m.relative_to(ROOT))
