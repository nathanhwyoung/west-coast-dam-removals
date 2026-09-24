"""Phase 1, item 2: build one critical-habitat layer per USFWS species.

Nine species, fish only. The scope rule, decided 2026-09-08: include a species
only where **barrier passage is the mechanism**. That admits fish and excludes
Oregon spotted frog and the California amphibians, on one stated principle rather
than case by case. See SPECIES_AND_SOURCES.md.

ONE SOURCE, as of 2026-09-11: the USFWS national critical habitat bundle,
edition 2026-08-31, from
https://ecos.fws.gov/docs/crithab/crithab_all/crithab_all_shapefiles.zip
The nine species' folders are extracted to WORKING/LAYERS/usfws_NEW/.

Until 2026-09-11 six of the nine came from the national feature service, which
is a DISSOLVED ROLL-UP (one multipolygon per species, unit fields reading
"Please check current species specific shapefile"). The bundle has the real
per-unit shapefiles for all nine, so the service is no longer used and the build
needs no network. The previous two-source version is kept at
build/_old/make_usfws_layers_pre_bundle_2026-09-11.py.

A species folder can hold MORE THAN ONE shapefile, and every one is read. Warner
sucker ships as _LINE (19 designated reaches, 93.5 km) plus _POLY (two buffer
polygons around the main channels). The polygons miss ~24 km of braids and
feeders that only the lines carry, so dropping either file loses habitat. Lines
are therefore valid geometry here, not degenerate.

Simplification is DISPLAY ONLY, per standing rule 35. Phase 3 joins must run
against the full-resolution shapefiles in usfws_NEW/, never these outputs: the
~33 m simplification is wider than the 21 m Chiloquin test distance.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLE_DIR = ROOT / "WORKING/LAYERS/usfws_NEW"
OUT = ROOT / "WORKING/LAYERS/usfws"
SCRATCH = OUT / "_parts"

BUNDLE_URL = "https://ecos.fws.gov/docs/crithab/crithab_all/crithab_all_shapefiles.zip"
BUNDLE_EDITION = "2026-08-31"

SIMPLIFY_DEG = 0.0003          # ~33 m, same as the NMFS layers
COORD_PRECISION = 5

VALID_TYPES = ("Polygon", "MultiPolygon", "LineString", "MultiLineString")

# slug -> (comname, sciname, listing status, bundle folder)
# The bundle spells names inconsistently (TIDEWATER GOBY, Bull Trout, ...) and
# carries no listing status at all: its STATUS field is the critical habitat
# rule's status ("FINAL"). So names and listing status are fixed here, from the
# national service query of 2026-09-08 recorded in SPECIES_AND_SOURCES.md.
SPECIES = {
    "bull_trout":        ("Bull trout", "Salvelinus confluentus", "Threatened",
                          "FCH_SALVELINUS_CONFLUENTUS_20101018"),
    "lost_river_sucker": ("Lost River sucker", "Deltistes luxatus", "Endangered",
                          "FCH_DELTISTES_LUXATUS_20121211"),
    "shortnose_sucker":  ("Shortnose sucker", "Chasmistes brevirostris", "Endangered",
                          "FCH_CHASMISTES_BREVIROSTRIS_20121211"),
    "warner_sucker":     ("Warner sucker", "Catostomus warnerensis", "Threatened",
                          "FCH_Catostomus_warnerensis_19850927"),
    "delta_smelt":       ("Delta smelt", "Hypomesus transpacificus", "Threatened",
                          "FCH_Hypomesus_transpacificus_19941219"),
    "tidewater_goby":    ("Tidewater goby", "Eucyclogobius newberryi", "Endangered",
                          "FCH_Eucyclogobius_newberryi_20130206"),
    "santa_ana_sucker":  ("Santa Ana sucker", "Catostomus santaanae", "Threatened",
                          "FCH_Catostomus_santaanae_20101214"),
    # USFWS's own folder name reads 1078 for a 1978 designation. Kept as
    # published; never parse a date out of it.
    "little_kern_golden_trout": ("Little Kern golden trout",
                                 "Oncorhynchus aguabonita whitei", "Threatened",
                                 "FCH_Oncorhynchus_aguabonita_whitei_10780413"),
    "owens_tui_chub":    ("Owens tui chub", "Gila bicolor ssp. snyderi", "Endangered",
                          "FCH_Gila_bicolor_ssp_snyderi_19850805"),
}


def field_names(shp: Path) -> set[str]:
    """Attribute names of a shapefile, read with ogrinfo's JSON output."""
    r = subprocess.run(["ogrinfo", "-json", "-so", str(shp), shp.stem],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return set()
    info = json.loads(r.stdout)
    return {f["name"] for lyr in info.get("layers", []) for f in lyr.get("fields", [])}


def simplify(src: Path, dest: Path, comname: str, sci: str, status: str) -> bool:
    """Simplify one shapefile and normalise its attributes to the shared fields."""
    fields = field_names(src)
    # Unit label: UNITNAME where the file has it. Warner's _POLY file has no unit
    # fields; its ZoneDesc ("Estimated Maximum CH Area w/80' wide stream") is the
    # only thing that tells its two polygons apart.
    if "UNITNAME" in fields:
        unit = "UNITNAME"
    elif "ZoneDesc" in fields:
        unit = "ZoneDesc"
    else:
        unit = "''"
    # The geometry column MUST be named in the select list. Omitting it writes
    # attribute rows with null shapes, which looks like a successful export and
    # is not: it produced 2,422 shapeless "bull trout polygons" on 2026-09-08.
    sql = (f"SELECT '{comname}' AS comname, '{sci}' AS sciname, "
           f"'{status}' AS listing_status, {unit} AS unitname, "
           f"'{src.name}' AS source_file, geometry "
           f"FROM \"{src.stem}\"")
    cmd = ["ogr2ogr", "-f", "GeoJSON", str(dest), str(src),
           "-dialect", "SQLite", "-sql", sql,
           "-simplify", str(SIMPLIFY_DEG),
           "-lco", f"COORDINATE_PRECISION={COORD_PRECISION}",
           "-makevalid", "-t_srs", "EPSG:4326"]
    # NOTE: never add -lco RFC7946=YES here. On the NMFS layers it silently
    # turned 24% of features into Points. See make_species_layers.py.
    dest.unlink(missing_ok=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not dest.exists():
        print(f"  ! {src.name}: ogr2ogr failed\n{r.stderr.strip()[:300]}",
              file=sys.stderr)
        return False
    return True


def build_species(slug: str, comname: str, sci: str, status: str,
                  folder: str) -> dict | None:
    """Every shapefile in the species' bundle folder, merged into one GeoJSON."""
    shps = sorted((BUNDLE_DIR / folder).glob("*.shp"))
    if not shps:
        print(f"  ! {slug}: no shapefile in {folder}", file=sys.stderr)
        return None

    feats = []
    for shp in shps:
        part = SCRATCH / f"{shp.stem}.geojson"
        if not simplify(shp, part, comname, sci, status):
            return None
        feats += json.loads(part.read_text()).get("features", [])

    dest = OUT / f"{slug}.geojson"
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                               separators=(",", ":")))
    types = sorted({f["geometry"]["type"] for f in feats if f.get("geometry")})
    bad = sum(1 for f in feats
              if not f.get("geometry") or f["geometry"]["type"] not in VALID_TYPES)
    return {"file": dest.name, "features": len(feats),
            "bytes": dest.stat().st_size, "geometry_types": types,
            "degenerate": bad, "source_files": [s.name for s in shps],
            "bundle_folder": folder}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}

    print(f"{'species':26} {'files':>5} {'feats':>7} {'size':>9} {'bad':>4}  types")
    print("-" * 78)
    for slug, (comname, sci, status, folder) in SPECIES.items():
        got = build_species(slug, comname, sci, status, folder)
        if not got:
            continue
        got.update(source="bundle", comname=comname, sciname=sci,
                   listing_status=status)
        manifest[slug] = got
        flag = "  <-- DEGENERATE" if got["degenerate"] else ""
        print(f"{slug:26} {len(got['source_files']):>5} {got['features']:>7,} "
              f"{got['bytes']/1048576:>8.2f}M {got['degenerate']:>4}  "
              f"{','.join(got['geometry_types'])}{flag}")

    tot_f = sum(m["features"] for m in manifest.values())
    tot_b = sum(m["bytes"] for m in manifest.values())
    print("-" * 78)
    print(f"{'TOTAL':26} {'':>5} {tot_f:>7,} {tot_b/1048576:>8.2f}M")

    (OUT / "manifest.json").write_text(json.dumps({
        "scope_rule": "fish only: include a species where barrier passage is "
                      "the mechanism (decided 2026-09-08)",
        "source": "USFWS national critical habitat bundle",
        "bundle_url": BUNDLE_URL,
        "bundle_edition": BUNDLE_EDITION,
        "built_from": str(BUNDLE_DIR.relative_to(ROOT)),
        "names_and_listing_status": "fixed in make_usfws_layers.py, from the "
                                    "national service query of 2026-09-08",
        "simplify_degrees": SIMPLIFY_DEG,
        "simplify_note": "display only; joins must use the full-resolution "
                         "shapefiles in usfws_NEW/ (standing rule 35)",
        "species": manifest,
    }, indent=2))
    print(f"\nwrote {(OUT / 'manifest.json').relative_to(ROOT)}")
    return 0 if len(manifest) == len(SPECIES) else 1


if __name__ == "__main__":
    sys.exit(main())
