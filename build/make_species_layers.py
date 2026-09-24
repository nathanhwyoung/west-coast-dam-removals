"""Phase 1, item 1: split NMFS critical habitat into one file per species.

Source: DOCS/DAM_DATA/NOAA/NMFS_WCR_ESA_Critical_Habitat_20230717.gdb
Vintage verified current 2026-09-08: the published geodatabase and the live
service are both still 20230717. NMFS has issued no update since July 2023, and
there is still no SONCC coho layer (see PROCESS.md stage 5).

Two source layers, and both are needed:

  All_WCR_critical_habitat_line_20230717   82,286 features, the stream network
  All_WCR_critical_habitat_poly_20230717    1,776 features, mostly marine

The polygon layer is *mostly* irrelevant here (bocaccio, yelloweye rockfish,
Steller sea lion, humpback and killer whales, black abalone, leatherback turtle)
but it carries 390 features for four of our species: green sturgeon 237, Chinook
136, chum 9, sockeye 8. Those are the estuarine and bay portions of the
designations, and green sturgeon in particular is largely estuarine. Taking only
the line layer would silently drop them.

Simplification is DISPLAY ONLY, per standing rule 10. The joins in Phase 3 must
run against the full-resolution source, never these files.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GDB = (ROOT / "_OLD/DOCS/DAM_DATA/NOAA/NMFS_WCR_ESA_Critical_Habitat_20230717.gdb"
            / "NMFS_WCR_ESA_Critical_Habitat_20230717.gdb")
LINE_LAYER = "All_WCR_critical_habitat_line_20230717"
POLY_LAYER = "All_WCR_critical_habitat_poly_20230717"
OUT = ROOT / "WORKING/LAYERS/nmfs"

# ~0.0003 degrees is about 33 m. Measured 2026-09-08: this takes the whole West
# Coast network from 115 MB to 23 MB raw, 3.1 MB gzipped, with every per-species
# file under 1.5 MB gzipped. Disclose the tolerance in the methods note.
SIMPLIFY_DEG = 0.0003
COORD_PRECISION = 5

# COMNAME as NMFS spells it, mapped to the slug used in filenames and the UI.
SPECIES = {
    "Salmon, Chinook": "chinook",
    "Steelhead": "steelhead",
    "Salmon, coho": "coho",
    "Salmon, sockeye": "sockeye",
    "Sturgeon, green": "green_sturgeon",
    "Salmon, chum": "chum",
    "Eulachon": "eulachon",
}

FIELDS = "COMNAME, LISTENTITY, LISTSTATUS"


def export(layer: str, comname: str, slug: str, kind: str) -> dict | None:
    dest = OUT / f"{slug}_{kind}.geojson"
    sql = (f"SELECT {FIELDS}, Shape FROM {layer} "
           f"WHERE COMNAME = '{comname.replace(chr(39), chr(39)*2)}'")
    # Do NOT add -lco RFC7946=YES. It corrupts this data: measured 2026-09-08 on
    # the steelhead layer, RFC7946 mode turned 6,503 of 26,812 line features into
    # Points, MultiPoints and GeometryCollections, a 24% loss. Its geometry
    # normalisation collapses very short segments. The same export without it
    # yields zero degenerate features and is marginally smaller. The flag was
    # only ever there to force WGS84 output, which is redundant: the source is
    # already EPSG:4326 and GDAL writes a CRS84 crs member regardless.
    cmd = [
        "ogr2ogr", "-f", "GeoJSON", str(dest), str(GDB),
        "-dialect", "SQLite", "-sql", sql,
        "-simplify", str(SIMPLIFY_DEG),
        "-lco", f"COORDINATE_PRECISION={COORD_PRECISION}",
    ]
    if kind == "poly":
        # Simplifying a polygon can self-intersect it; repair before writing.
        cmd += ["-makevalid"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ! {slug}_{kind}: ogr2ogr failed\n{r.stderr.strip()[:300]}",
              file=sys.stderr)
        return None
    if not dest.exists():
        return None
    gj = json.loads(dest.read_text())
    n = len(gj.get("features", []))
    if n == 0:
        dest.unlink()
        return None
    return {"file": dest.name, "features": n, "bytes": dest.stat().st_size}


def main() -> int:
    if not GDB.exists():
        print(f"geodatabase not found: {GDB}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, dict] = {}
    print(f"{'species':16} {'geom':5} {'features':>9} {'size':>10}")
    print("-" * 46)
    for comname, slug in SPECIES.items():
        entry: dict = {"comname": comname, "parts": []}
        for layer, kind in ((LINE_LAYER, "line"), (POLY_LAYER, "poly")):
            got = export(layer, comname, slug, kind)
            if not got:
                continue
            entry["parts"].append(got)
            print(f"{slug:16} {kind:5} {got['features']:>9,} "
                  f"{got['bytes']/1048576:>9.2f}M")
        if entry["parts"]:
            manifest[slug] = entry

    total_f = sum(p["features"] for e in manifest.values() for p in e["parts"])
    total_b = sum(p["bytes"] for e in manifest.values() for p in e["parts"])
    print("-" * 46)
    print(f"{'TOTAL':16} {'':5} {total_f:>9,} {total_b/1048576:>9.2f}M")

    (OUT / "manifest.json").write_text(json.dumps({
        "source": "NMFS_WCR_ESA_Critical_Habitat_20230717.gdb",
        "source_vintage": "2023-07-17",
        "vintage_verified": "2026-09-08",
        "simplify_degrees": SIMPLIFY_DEG,
        "simplify_note": "display only; joins must use full-resolution source",
        "coordinate_precision": COORD_PRECISION,
        "missing": "SONCC coho ESU: never published by NMFS, built separately",
        "species": manifest,
    }, indent=2))
    print(f"\nwrote {(OUT / 'manifest.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
