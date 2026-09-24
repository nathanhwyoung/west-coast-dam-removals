"""What does the national river network call the channel each dam actually sits on?

Written 2026-09-13 for the same-stream sweep (`PHASE2_AUDIT.md` section 2, writeup
`09-13_WORKING.md` section 9).

WHY AN OUTSIDE SOURCE IS NEEDED. The same-stream extension credits a dam with fish from
a stream up to 500 m away when the source's stream name matches the river the sheet
records. Standing rule 45 now blocks that where a NAMED channel sits within the base
tolerance and disagrees. But at three dams the channel at the dam's feet is UNNAMED in
the state fish layer, so rule 45 is blind to it, and our own layers cannot say whether
that channel is the dam's own creek or a separate tributary: the whole problem is that
the field is blank. NHD names flowlines independently, so it can.

CONTROLS ARE THE POINT OF THIS SCRIPT. The three dams rule 45 already blocked are queried
too. If NHD does not name Odell Creek at Odell Dam, the method is not trustworthy and the
output must not be used. Two earlier attempts at this lookup returned "no name" for all
six dams and BOTH were my own bugs, caught only because the controls were there:
  1. NLDI's `comid/position` endpoint returns identifiers only, no `gnis_name`, so the
     field I read was absent rather than empty.
  2. This service's fields are lower case (`gnis_name`), and ArcGIS silently ignores
     `outFields=GNIS_NAME`, returning no attributes at all.
Both times the missing field rendered as my own default text and read like evidence.
**A default string standing in for an absent field is indistinguishable from data.**

CAVEAT, standing rule 10: this reports the nearest flowline, which is not necessarily the
correct one. Distances are printed so the reader can judge, and the dam's recorded river
is shown alongside for comparison. Evidence, not proof.

OUTPUT, WORKING/JOIN/audit/nhd_channel_names.csv
  one row per dam per nearby named channel, nearest first, plus the recorded river
"""

import csv
import json
import math
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:                                    # noqa: BLE001
    # The python.org macOS build ships no root store; same fix as the RRR harvester.
    CTX = ssl.create_default_context()

ROOT = Path(__file__).resolve().parent.parent.parent
SHEET = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
SWEEP = ROOT / "WORKING/JOIN/audit/same_stream_sweep.csv"
OUT = ROOT / "WORKING/JOIN/audit/nhd_channel_names.csv"

# NHD Flowline, large scale. Field names are LOWER CASE on this service.
URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query"
SEARCH_M = 500          # same as the same-stream extension, so the two are comparable

# Dams rule 45 blocked. Queried as controls; NHD should name the channel it sits on.
CONTROLS = {"OR-012", "OR-026", "OR-052"}

FTYPE = {460: "StreamRiver", 558: "ArtificialPath", 336: "CanalDitch",
         334: "Connector", 420: "Underground conduit", 428: "Pipeline"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dam-removal-tracker/audit"})
    with urllib.request.urlopen(req, context=CTX, timeout=90) as fh:
        return json.load(fh)


def metres(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def channels(lon, lat):
    """Nearest distance to each distinct nearby flowline name."""
    params = {
        "geometry": json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": str(SEARCH_M), "units": "esriSRUnit_Meter",
        "outFields": "gnis_name,ftype,fcode", "returnGeometry": "true",
        "outSR": "4326", "f": "json",
    }
    j = get(URL + "?" + urllib.parse.urlencode(params))
    if "error" in j:
        raise RuntimeError(j["error"].get("message", "service error"))
    rows = []
    for f in j.get("features", []):
        at = f.get("attributes", {})
        nm = (at.get("gnis_name") or "").strip()
        d = min((metres(lon, lat, x, y)
                 for path in f.get("geometry", {}).get("paths", []) for x, y in path),
                default=None)
        if d is not None:
            rows.append((d, nm, FTYPE.get(at.get("ftype"), at.get("ftype"))))
    rows.sort()
    best, seen = [], set()
    for d, nm, ft in rows:
        key = nm or "(unnamed in NHD)"
        if key in seen:
            continue
        seen.add(key)
        best.append((d, key, ft))
    return best


def main():
    # AR_IDs may be passed as arguments; otherwise the same-stream sweep's dams are used.
    # The controls are ALWAYS queried, whatever else is asked for, because a run whose
    # controls fail should be discarded rather than read.
    # NOTE one AR_ID contains a space, `OR-087 to OR-088`, so quote it in a shell.
    import sys
    asked = [a for a in sys.argv[1:] if a.strip()]

    sheet = {r["AR_ID"]: r for r in csv.DictReader(SHEET.open(encoding="utf-8-sig"))}
    want = set(CONTROLS)
    if asked:
        want |= set(asked)
        print(f"  querying {len(asked)} named dams, plus the {len(CONTROLS)} controls")
    elif SWEEP.exists():
        want |= {r["AR_ID"] for r in csv.DictReader(SWEEP.open())}
    else:
        print("  ! no same_stream_sweep.csv; querying the controls only")

    out = []
    for arid in sorted(want):
        r = sheet.get(arid)
        if not r:
            print(f"  ! {arid} not in the sheet, skipped")
            continue
        lat = (r.get("Latitude_DRP") or r.get("Latitude") or "").strip()
        lon = (r.get("Longitude_DRP") or r.get("Longitude") or "").strip()
        if not lat or not lon:
            continue
        tag = "CONTROL" if arid in CONTROLS else ""
        try:
            found = channels(float(lon), float(lat))
        except Exception as e:                        # noqa: BLE001
            print(f"  {arid:9s} FAILED {type(e).__name__}: {e}")
            continue
        river = (r.get("River") or "").strip()
        print(f"  {arid:9s} {tag:8s} sheet says {river[:26]:26s}")
        for d, nm, ft in found[:6]:
            print(f"      {d:7.1f} m  {nm[:34]:34s} {ft}")
            out.append({"AR_ID": arid, "dam": r.get("Dam_Name"), "control": bool(tag),
                        "river_recorded": river, "nhd_name": nm,
                        "nhd_m": round(d, 1), "nhd_ftype": ft})

    # MERGE, do not overwrite. This file is a lookup that accumulates, and the dashboard
    # sketch reads it: a run over a handful of named dams must not wipe the rows for every
    # other dam already looked up. Rows for a dam queried this run replace that dam's old
    # rows; every other dam is carried through untouched.
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = ["AR_ID", "dam", "control", "river_recorded", "nhd_name", "nhd_m", "nhd_ftype"]
    kept = []
    if OUT.exists():
        fresh = {o["AR_ID"] for o in out}
        kept = [r for r in csv.DictReader(OUT.open()) if r["AR_ID"] not in fresh]
        if kept:
            print(f"  carrying forward {len({r['AR_ID'] for r in kept})} dams already looked up")
    with OUT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(sorted(kept + out, key=lambda r: (r["AR_ID"], float(r["nhd_m"]))))
    total = kept + out
    print(f"\nwrote {OUT.relative_to(ROOT)}: {len(out)} new rows over "
          f"{len({o['AR_ID'] for o in out})} dams queried, "
          f"{len(total)} rows over {len({r['AR_ID'] for r in total})} dams in the file")

    # The controls decide whether any of this is usable.
    print("\nCONTROL CHECK, the reason this script has controls:")
    for arid in sorted(CONTROLS):
        rows = [o for o in out if o["AR_ID"] == arid]
        near = [o for o in rows if o["nhd_name"] != "(unnamed in NHD)"]
        near.sort(key=lambda o: o["nhd_m"])
        if near and near[0]["nhd_m"] <= 75:
            print(f"  {arid}: NHD names {near[0]['nhd_name']!r} at {near[0]['nhd_m']} m "
                  f"(sheet said {rows[0]['river_recorded']!r}) -> rule 45 corroborated")
        else:
            print(f"  {arid}: NHD names nothing within 75 m; "
                  f"nearest named is {near[0]['nhd_name']!r} at {near[0]['nhd_m']} m"
                  if near else f"  {arid}: NHD names nothing nearby")


if __name__ == "__main__":
    main()
