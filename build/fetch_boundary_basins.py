"""Stage 5, boundary dams: delineate the basin above each dam Table 6 names.

50 CFR 226.210: "Inaccessible reaches are those above specific dams identified
in Table 6." For SONCC coho, Table 6 names eleven. This script draws the land
upstream of each one, so make_soncc_layer.py can remove it from the designation.

WHY STREAMSTATS, NOT NLDI. NLDI's basin endpoint is built from whole NHDPlus
catchments, so a basin started at a dam also swallows the rest of the dam's own
catchment, which runs a short way BELOW the dam. That would erase real habitat
immediately downstream. StreamStats delineates from the exact point on a 10 m
DEM, so the basin starts at the dam. NLDI's point-split option only works for
its registered feature sources, and NID is not one of them (checked 2026-09-11).

THE CHECK (standing rule 10: snapping picks the nearest flowline, not the correct
one). StreamStats snaps the point to its stream grid, and a snap onto the wrong
channel gives a plausible-looking wrong basin. So every basin's area is compared
with an INDEPENDENT drainage area: NID's `drainageArea` for the standing dams,
and the USGS gauge just below Iron Gate, which NID no longer carries because the
dam was removed in 2024 (standing rule 34). Dwinnell has no NID drainage area,
so its check is weaker and is flagged as such.

Network only here; the build itself is offline. Responses are cached as raw
JSON, so re-running fetches nothing that is already on disk (rule 2, snapshot
the source).
"""

import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

import certifi
from pyproj import Geod

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "WORKING/SS_BASINS"
API = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{st}?lat={lat}&lon={lon}"

# python.org Python on macOS needs certifi passed explicitly; see make_usfws_layers
# history and JOB_ALERTS/sources/_http.py.
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
GEOD = Geod(ellps="WGS84")
SQMI = 2_589_988.110336

# id -> (Table 6 unit, name as Table 6 gives it, dam as identified, source id,
#        lat, lon, StreamStats region, reference drainage area sq mi, reference)
# Coordinates and drainage areas from NID national export of 2026-09-11
# (WORKING/NID_DSOD/nid_nation_2026-09-11.gpkg) unless stated.
DAMS = {
    "agate":      ("17100307", "Agate Lake", "Agate Dam", "NID OR00422",
                   42.4153, -122.7733, "OR", 14.55, "NID drainageArea"),
    "fish_lake":  ("17100307", "Fish Lake", "Fish Lake Dam", "NID OR00021",
                   42.3781, -122.3486, "OR", 15.93, "NID drainageArea"),
    # Willow Lake near Butte Falls is the City of Medford's reservoir; NID names
    # the dam "Willow Creek", owner City of Medford.
    "willow":     ("17100307", "Willow Lake", "Willow Creek (Willow Lake)", "NID OR00212",
                   42.47919082, -122.4493866, "OR", 21.0, "NID drainageArea"),
    # Table 6 "Lost Creek" is the USACE Rogue mainstem dam, renamed William L.
    # Jess in 1996; NID carries "Lost Creek" as its former name. NOT the small
    # "Lost Creek Dam" on Lost Creek in the American Rivers list.
    "lost_creek": ("17100307", "Lost Creek", "William L. Jess Dam (Lost Creek Lake)", "NID OR00612",
                   42.67048024, -122.67431654, "OR", 674.0, "NID drainageArea"),
    "emigrant":   ("17100308", "Emigrant Lake", "Emigrant Dam", "NID OR00581",
                   42.1618, -122.6052, "OR", 63.79, "NID drainageArea"),
    "applegate":  ("17100309", "Applegate", "Applegate Dam", "NID OR00624",
                   42.05601063, -123.11497743, "OR", 223.0, "NID drainageArea"),
    # NID names this "Mcmullen Creek", other name Selmac Lake.
    "selmac":     ("17100311", "Selmac Lake", "Selmac Lake Dam (NID 'Mcmullen Creek')", "NID OR00513",
                   42.26544189, -123.5792313, "OR", 13.69, "NID drainageArea"),
    # Removed 2024, so absent from NID by construction (rule 34). Coordinate from
    # the American Rivers sheet (CA-186); area from USGS gauge 11516530, "Klamath
    # R bl Iron Gate Dam CA", about 0.9 km downstream.
    "iron_gate":  ("18010206", "Iron Gate", "Iron Gate Dam (removed 2024)", "AR CA-186",
                   41.9349, -122.4367, "CA", 4630.0, "USGS 11516530 drain_area_va, just below dam"),
    # NID carries no "Dwinnell" name. Identified by attribute: the only large dam
    # on the Shasta River mainstem, 96 ft, at Lake Shastina. No NID drainage area.
    "dwinnell":   ("18010207", "Dwinnell", "Dwinnell Dam (NID 'Shasta River')", "NID CA00244",
                   41.5411, -122.3737, "CA", None, "none available; check is weaker"),
    "lewiston":   ("18010211", "Lewiston", "Lewiston Dam", "NID CA10165",
                   40.7264, -122.793, "CA", 718.57, "NID drainageArea"),
    "scott":      ("18010103", "Scott", "Scott Dam (Lake Pillsbury)", "NID CA00398",
                   39.407324, -122.959074, "CA", 289.0, "NID drainageArea"),
}


# What the area check found on 2026-09-11, and what was done about it. Each of
# these was a wrong-but-plausible basin (rule 4 of batch 4: neither threw).
FIXES = {
    # The NID point sits off the channel; StreamStats snapped to a 0.1 sq mi
    # cell. Started instead from NLDI's hydrolocation "indexed" point, 74 m away
    # on NHDPlus flowline 23924068: 14.6 sq mi against NID's 14.55.
    "agate": {"start": (42.41583, -122.77276),
              "note": "NID point off-channel (0.1 sq mi); re-started from NLDI indexed "
                      "point 74 m away on comid 23924068"},
    # StreamStats 28.9 and NLDI's catchment basin 28.3 agree with each other and
    # disagree with NID's 21. NID lists the dam on "Willow & Four Bit Creeks", so
    # 28.9 is plausible for the whole dam; NID's figure is the likelier outlier.
    "willow": {"note": "NID drainageArea 21 disagrees with two independent delineations "
                       "(StreamStats 28.9, NLDI 28.3); accepted, disagreement recorded"},
    # StreamStats' California grid does not route the Shasta River through this
    # dam: 0.0 sq mi from the NID point and from three points on the outlet
    # flowline. NHDPlus splits catchments at reservoir outlets, so the NLDI basin
    # of the flowline ENDING at the outlet (comid 3918012) stops at the dam, and
    # the whole-catchment overreach that rules NLDI out elsewhere does not arise.
    # 126.1 sq mi, against 233.2 for the flowline below (which carries 14 km of
    # river downstream of the dam). No independent reference area exists.
    "dwinnell": {"nldi_comid": 3918012,
                 "note": "StreamStats CA returns 0.0 here; NLDI basin of comid 3918012, "
                         "which ends at the Lake Shastina outlet; no reference area"},
    # +78% against the gauge because the basin includes the Lost River / Tule
    # Lake closed basin, which the gauge's drainage area leaves out. Checked: Tule
    # Lake and Upper Klamath Lake inside; Bogus Creek (coho, joins just below the
    # dam) 0 of 11.7 km inside; 10 m of Klamath mainstem at the dam point.
    "iron_gate": {"note": "area includes the Lost River/Tule Lake closed basin; checked "
                          "Bogus Creek (just below dam) is untouched"},
}


def nldi_basin(key: str, comid: int) -> dict | None:
    raw = OUT / f"{key}_nldi_basin_comid{comid}_raw.json"
    if not raw.exists():
        url = f"https://api.water.usgs.gov/nldi/linked-data/comid/{comid}/basin?f=json"
        raw.write_bytes(urllib.request.urlopen(url, context=SSL_CTX, timeout=300).read())
    return json.loads(raw.read_text())


def fetch(key: str, st: str, lat: float, lon: float) -> dict | None:
    raw = OUT / f"{key}_streamstats_{lat:.5f}_{lon:.5f}_raw.json"
    if raw.exists():
        return json.loads(raw.read_text())
    url = API.format(st=st, lat=lat, lon=lon)
    for attempt in range(3):
        try:
            body = urllib.request.urlopen(url, context=SSL_CTX, timeout=300).read()
            d = json.loads(body)
            raw.write_bytes(body)
            return d
        except Exception as e:
            print(f"  ! {key}: attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(5)
    return None


def parts(d: dict) -> tuple[dict | None, list | None]:
    """The snapped point and the watershed polygon from a StreamStats response."""
    fc = d["bcrequest"]["wsresp"]["featurecollection"]
    items = [x for sub in fc for x in (sub if isinstance(sub, list) else [sub])]
    point = poly = None
    for it in items:
        feats = it["feature"]["features"]
        if it["name"] == "globalwatershedpoint" and feats:
            point = feats[0]["geometry"]
        elif it["name"] == "globalwatershed" and feats:
            poly = feats[0]["geometry"]
    return point, poly


def area_sqmi(geom: dict) -> float:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    total = 0.0
    for poly in polys:
        for i, ring in enumerate(poly):        # outer ring minus any holes
            a = abs(GEOD.polygon_area_perimeter([p[0] for p in ring],
                                                [p[1] for p in ring])[0])
            total += a if i == 0 else -a
    return total / SQMI


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    feats, rows, failed = [], [], 0
    print(f"{'dam':11} {'unit':9} {'ref sqmi':>9} {'SS sqmi':>9} {'diff':>7} {'snap m':>7}")
    print("-" * 58)
    for key, (unit, t6, name, src, lat, lon, st, ref, ref_src) in DAMS.items():
        fix = FIXES.get(key, {})
        if "nldi_comid" in fix:
            b = nldi_basin(key, fix["nldi_comid"])
            point, poly = None, b["features"][0]["geometry"]
            method = f"NLDI basin of NHDPlus comid {fix['nldi_comid']}"
        else:
            slat, slon = fix.get("start", (lat, lon))
            d = fetch(key, st, slat, slon)
            point, poly = parts(d) if d else (None, None)
            method = "USGS StreamStats ss-delineate v1, sshydro/" + st
        if not poly:
            print(f"{key:11} FAILED", file=sys.stderr)
            failed += 1
            continue
        a = area_sqmi(poly)
        snap = GEOD.inv(lon, lat, *point["coordinates"][:2])[2] if point else None
        diff = (a - ref) / ref * 100 if ref else None
        print(f"{key:11} {unit:9} {ref if ref else '-':>9} {a:>9.1f} "
              f"{(f'{diff:+.1f}%' if diff is not None else '-'):>7} "
              f"{(f'{snap:.0f}' if snap is not None else '-'):>7}")
        props = {"key": key, "table6_unit": unit, "table6_name": t6, "dam": name,
                 "dam_source": src, "dam_lat": lat, "dam_lon": lon,
                 "snapped_lon": point["coordinates"][0] if point else None,
                 "snapped_lat": point["coordinates"][1] if point else None,
                 "snap_m": round(snap, 1) if snap is not None else None,
                 "basin_sqmi": round(a, 2), "reference_sqmi": ref,
                 "reference_source": ref_src,
                 "area_diff_pct": round(diff, 2) if diff is not None else None,
                 "method": method, "note": fix.get("note", "")}
        feats.append({"type": "Feature", "properties": props, "geometry": poly})
        rows.append(props)

    (OUT / "boundary_basins.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}))
    (OUT / "boundary_basins_check.json").write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {len(feats)} basins to {(OUT / 'boundary_basins.geojson').relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
