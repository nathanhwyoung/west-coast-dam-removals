"""Build the GeoJSON behind the dashboard sketch.

Every dam we can currently place on a map, with its coordinate provenance carried
as an attribute. Two sources, per the linking work of 2026-09-08:

  ar    the American Rivers March 2026 coordinate
  nacc  recovered from the NACC/SARP inventory via the T2 SourceID join,
        for rows American Rivers left blank

Rows with a known coordinate defect are flagged rather than dropped, so the map
shows what is actually in the data instead of a tidied version of it.

Writes D3/dams.geojson and a small dams_meta.json of counts, so the
page can state its own denominators rather than hardcoding them.

Added 2026-09-11: if WORKING/JOIN/dam_habitat_join.csv exists, each dam also
carries `species_present` and `esa_critical_habitat` from that join, so the
sketch's hover popup can show the two fields side by side. That is a preview of
display option A (popup only); the display decision itself is still open and
belongs to the dashboard build, stage 9. The join is a generated product: if the
file is absent the sketch simply builds without those two attributes.
"""

import csv
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_habitat_display import GROUPS as _HABITAT_GROUPS   # noqa: E402

# ---- ESA species names in the popups (Nathan, 2026-09-18) --------------------------------------
# DECIDED: the popups show the SPECIES NAME ONLY, spelled exactly as the map's layer switches spell
# it. The listing entity (the ESU or DPS) is NOT carried. Nathan: "i don't think we need to include
# the listing entity in the popups. species name can be normalized in the same way that they were
# for the map layers."
#
# WHAT THIS COSTS, so it is not rediscovered as a bug: the ESU/DPS is the actual unit the ESA lists,
# and it is being dropped. Eight Chinook designations and ten Steelhead designations collapse to one
# name each, so a popup can no longer say WHICH Chinook run's critical habitat a dam sits in. The
# join itself is untouched; this is a display decision about the popup only.
#
# THE TARGETS ARE NOT WRITTEN OUT HERE. They are read from make_habitat_display.GROUPS, which is the
# table that names the map's layer switches, so the popup and the switch cannot drift apart
# (standing rule 44). A third copy of this crosswalk exists as esa_species() in audit_join_gaps.R,
# in R, for the audit; it maps to the PRESENCE vocabulary rather than these labels and is a
# different job.
ESA_LABELS = {label for _key, label, _files in _HABITAT_GROUPS}

# Raw agency label (lowercased, matched on PREFIX) -> the canonical label above.
_ESA_RULES = [
    ("salmon, chinook",          "Chinook salmon"),
    ("chinook salmon",           "Chinook salmon"),
    ("salmon, coho",             "Coho salmon"),
    ("coho salmon",              "Coho salmon"),
    ("salmon, chum",             "Chum salmon"),
    ("chum salmon",              "Chum salmon"),
    ("salmon, sockeye",          "Sockeye salmon"),
    ("sockeye salmon",           "Sockeye salmon"),
    ("steelhead",                "Steelhead"),
    ("eulachon",                 "Eulachon"),
    ("sturgeon, green",          "Green sturgeon"),
    ("green sturgeon",           "Green sturgeon"),
    ("bull trout",               "Bull trout"),
    ("lost river sucker",        "Lost River sucker"),
    ("shortnose sucker",         "Shortnose sucker"),
    ("warner sucker",            "Warner sucker"),
    ("santa ana sucker",         "Santa Ana sucker"),
    ("tidewater goby",           "Tidewater goby"),
    ("delta smelt",              "Delta smelt"),
    ("little kern golden trout", "Little Kern golden trout"),
    ("owens tui chub",           "Owens tui chub"),
]
assert all(v in ESA_LABELS for _, v in _ESA_RULES), (
    "an ESA crosswalk target is not a map layer label: "
    + str(sorted({v for _, v in _ESA_RULES} - ESA_LABELS)))

_esa_unmapped = set()


def esa_display(raw):
    """Semicolon-joined raw ESA labels -> semicolon-joined canonical species names, de-duplicated.

    Returns None for an empty value, so a dam that matched nothing keeps a null rather than "".
    An unrecognised label is kept VERBATIM and recorded, so a new designation shows up in the build
    output instead of silently vanishing from a popup.
    """
    if not raw:
        return None
    out = []
    for part in (x.strip() for x in raw.split(";")):
        if not part:
            continue
        low = part.lower()
        # SONCC IS TESTED FIRST AND AS A SUBSTRING, NOT A PREFIX, and that distinction is the whole
        # point: the raw label is "Coho salmon (SONCC, derived)", which STARTS WITH "coho salmon".
        # A prefix rule ordered first still loses to it, so ordering alone cannot protect this.
        # Getting it wrong relabels this project's own reconstruction as the federal designation and
        # silently destroys the disclosure the layer's manifest requires.
        if "soncc" in low:
            name = "Coho, SONCC (derived)"
        else:
            name = next((v for k, v in _ESA_RULES if low.startswith(k)), None)
        if name is None:
            _esa_unmapped.add(part)
            name = part
        if name not in out:
            out.append(name)
    return "; ".join(out) or None

ROOT = Path(__file__).resolve().parent.parent.parent
AR_PATH = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
LINKS = ROOT / "D3/build/ar_nacc_links.csv"
JOIN = ROOT / "WORKING/JOIN/dam_habitat_join.csv"
OUT_DIR = ROOT / "D3"  # was WORKING/DASHBOARD_SKETCH until 2026-09-14

# Audit findings, so the sketch can be used to LOOK at the dams an audit flagged instead
# of reading their coordinates out of a table. Added 2026-09-13 at Nathan's request.
# All three are generated products and all three are optional: absent, the sketch builds
# exactly as before.
SWEEP_SS = ROOT / "WORKING/JOIN/audit/same_stream_sweep.csv"      # build/sweep_same_stream.R
SWEEP_RANGE = ROOT / "WORKING/JOIN/audit/range_edge_sweep.csv"    # build/sweep_range_edges.R
NHD = ROOT / "WORKING/JOIN/audit/nhd_channel_names.csv"           # build/name_channels_nhd.py

# Dams where standing rule 45 switched the same-stream extension off, decided by Nathan
# 2026-09-13. They no longer appear in the same-stream sweep, because they no longer hold
# a same-stream match, so they cannot be recovered from it and are named here.
# Each lost species that had rested entirely on a reach 212 to 490 m away.
RULE45_BLOCKED = {
    # Blocked on a NAMED channel, the rule as first decided.
    "OR-012": "on Maple Gulch, 8.7 m away; was taking Chinook, coho, lamprey and a SONCC "
              "coho designation from Evans Creek 226 m off",
    "OR-026": "on Sodom Ditch, 26.6 m away; was taking five species from the Calapooia "
              "212 m off",
    "OR-052": "on Odell Creek, 8.9 m away; was taking five species from the Hood River "
              "490 m off",
    # Blocked on an UNNAMED channel, after the rule was amended 2026-09-13 to count any
    # mapped channel. NHD independently leaves each of these nameless too while putting
    # the recorded river 250 to 372 m away, which is what settled it.
    "OR-086": "on an unnamed channel 12.3 m away; was taking steelhead from Baker Creek "
              "249 m off, which NHD independently puts at 250 m",
    "WA-009": "on an unnamed channel 8.9 m away, an NHD artificial flow path; was taking "
              "Pacific lamprey from Satus Creek 312 m off",
    "WA-006": "on an unnamed channel 13.7 m away, an NHD artificial flow path; was taking "
              "Chinook and steelhead from Icicle Creek 316 m off",
}

# Rows whose coordinate was WRONG and has since been corrected, kept visible
# because a corrected point is worth showing rather than quietly swapping in.
# Every entry here must also carry a Latitude_DRP/Longitude_DRP in the sheet.
#
# Rewritten 2026-09-09. The previous version of this dict flagged four rows as
# "known coordinate defects" and that was wrong on two counts. OR-086, OR-095 and
# OR-087 to OR-088 have a bad `NABI_ID`, not a bad coordinate: their American
# Rivers points were never in question, so flagging them on the map claimed a
# defect that does not exist. And WA-023's note said the current point was at
# Granite Falls; it is in the Sultan River basin. See 09-08_PROBLEMS.md.
CORRECTED = {
    "WA-023": "American Rivers moved this point 26.5 km between its 2023 and 2026 "
              "editions; corrected back to the 2023 position at Sultan, which the "
              "NOAA project record confirms",
    "CA-133": "American Rivers' point sits 1.24 km from San Francisquito Creek, the "
              "creek this row itself names, beside Lake Lagunita, which the dam fed "
              "through a flume dead since the 1930s; corrected to the creek near the "
              "east end of Happy Hollow Lane, where the 2018 removal took place",
}


def num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def read_rows(path):
    if not path.exists():
        print(f"  ! {path.name} not found; sketch builds without it")
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def build_audit():
    """Per dam, what the audits found, in a form a popup can read.

    Three separate questions, kept apart:
      same_stream  is the dam on the stream its species came from?
      nhd          what does the national river network call the channel at its feet?
      range_edge   how close is it to falling out of a watershed range?
    """
    audit = {}

    def slot(arid):
        return audit.setdefault(arid, {})

    # --- the same-stream sweep: the channel at the dam's feet versus the matched one
    per = {}
    for r in read_rows(SWEEP_SS):
        per.setdefault(r["AR_ID"], []).append(r)
    for arid, rows in per.items():
        agree = [r for r in rows if r["rule40_agrees"] == "TRUE"]
        other = [r for r in rows if r["rule40_agrees"] != "TRUE"]
        if not agree:
            continue
        a = min(agree, key=lambda r: float(r["nearest_m"]))
        o = min(other, key=lambda r: float(r["nearest_m"])) if other else None
        s = {"matched_stream": a["stream_name"], "matched_m": float(a["nearest_m"])}
        if o:
            s["feet_stream"] = o["stream_name"]
            s["feet_m"] = float(o["nearest_m"])
        # The shape that matters: something is at the dam's feet and the stream its
        # species came from is well beyond the base tolerance. Rule 45 blocks this when
        # the near channel is NAMED; where it is unnamed the match stands and the dam
        # needs eyes, which is what this flag is for.
        if o and float(o["nearest_m"]) <= 75 < float(a["nearest_m"]):
            s["flag"] = ("kept by rule 45's named-only limit: an UNNAMED channel sits at "
                         "the dam's feet while its species come from further off")
        slot(arid)["same_stream"] = s

    # --- NHD, an independent opinion on what the channel is called
    per = {}
    for r in read_rows(NHD):
        per.setdefault(r["AR_ID"], []).append(r)
    for arid, rows in per.items():
        rows.sort(key=lambda r: float(r["nhd_m"]))
        named = [r for r in rows if r["nhd_name"] != "(unnamed in NHD)"]
        n = {"nearest": rows[0]["nhd_name"], "nearest_m": float(rows[0]["nhd_m"]),
             "nearest_ftype": rows[0]["nhd_ftype"], "control": rows[0]["control"] == "True"}
        if named:
            n["nearest_named"] = named[0]["nhd_name"]
            n["nearest_named_m"] = float(named[0]["nhd_m"])
        # Does NHD put the river the sheet names at the dam's feet? Where the sheet is
        # right this lands at a few metres, which is what makes the misses legible.
        river = (rows[0]["river_recorded"] or "").lower()
        hit = [r for r in named if r["nhd_name"].lower() in river
               or river.startswith(r["nhd_name"].lower())]
        if hit:
            n["recorded_river_m"] = float(min(hit, key=lambda r: float(r["nhd_m"]))["nhd_m"])
        slot(arid)["nhd"] = n

    # --- range edges: a containment match balanced on the rim of a watershed range
    for r in read_rows(SWEEP_RANGE):
        if r.get("fragile"):
            slot(r["AR_ID"]).setdefault("range_edge", []).append(
                {"species": r["species"], "position": r["position"],
                 "edge_m": float(r["edge_m"]), "note": r["fragile"]})

    for arid, why in RULE45_BLOCKED.items():
        slot(arid)["rule45_blocked"] = why
    return audit


def main():
    ar = pd.read_csv(AR_PATH, dtype=str)
    audit = build_audit()
    links = pd.read_csv(LINKS, dtype=str).set_index("AR_ID")
    join = pd.read_csv(JOIN, dtype=str).set_index("AR_ID") if JOIN.exists() else None
    if join is None:
        print("  ! no join output yet; building without species or ESA attributes")

    feats, n_ar, n_nacc, n_drp, unmapped, dupes = [], 0, 0, 0, [], []
    clustered = {}          # AR_ID -> cluster id, for non-duplicate rows only

    def cell(r, col):
        v = r.get(col)
        return (v or "").strip() if pd.notna(v) else ""

    for _, r in ar.iterrows():
        arid = r["AR_ID"]

        # A duplicate is not a removal. It leaves the map AND the count of
        # distinct removals, which is what separates it from a voided coordinate.
        dup = cell(r, "Duplicate_Of_DRP")
        if dup:
            dupes.append({"AR_ID": arid, "name": r.get("Dam_Name"),
                          "duplicate_of": dup})
            continue

        cid = cell(r, "Cluster_ID_DRP")
        if cid:
            clustered[arid] = cid

        # A voided coordinate is one known to be wrong with no replacement. The
        # removal is real and still counts; it just cannot be placed. Checked
        # before reading any coordinate so it never falls through to the source.
        void = cell(r, "Coordinate_Void_DRP")
        if void:
            unmapped.append({"AR_ID": arid, "name": r.get("Dam_Name"),
                             "state": r.get("State"), "river": r.get("River"),
                             "year": r.get("Year_Removed"), "reason": void})
            continue

        # A _DRP coordinate outranks the source column. This was missing until
        # 2026-09-09, so values written to _DRP never reached the map.
        #
        # Two different things live in _DRP and the sheet distinguishes them by
        # what the source column holds: over a BLANK source it is a coordinate
        # RECOVERED for a row that had none, over an existing value it is a
        # CORRECTION of a coordinate that was wrong. Worth separating, because
        # the second is a claim against American Rivers and the first is not.
        lat_drp, lon_drp = num(r.get("Latitude_DRP")), num(r.get("Longitude_DRP"))
        lat_src, lon_src = num(r.get("Latitude")), num(r.get("Longitude"))
        lat = lon = None

        if lat_drp is not None and lon_drp is not None:
            lat, lon = lat_drp, lon_drp
            src = "nacc" if (lat_src is None or lon_src is None) else "drp"
        elif lat_src is not None and lon_src is not None:
            lat, lon, src = lat_src, lon_src, "ar"
        elif arid in links.index:
            # safety net: a NACC point for a row that never got written to _DRP
            row = links.loc[arid]
            nlat, nlon = num(row.get("nacc_lat")), num(row.get("nacc_lon"))
            if nlat is not None and nlon is not None:
                lat, lon, src = nlat, nlon, "nacc"

        if lat is None or lon is None:
            unmapped.append({"AR_ID": arid, "name": r.get("Dam_Name"),
                             "state": r.get("State"), "river": r.get("River"),
                             "year": r.get("Year_Removed"),
                             "reason": "no coordinate in any source"})
            continue

        n_ar += src == "ar"
        n_nacc += src == "nacc"
        n_drp += src == "drp"

        yr = r.get("Year_Removed")
        yr = int(float(yr)) if num(yr) is not None else None

        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": arid,
                "name": r.get("Dam_Name") or "Unnamed",
                "river": r.get("River"),
                "state": r.get("State"),
                "year": yr,
                "height_ft": r.get("Dam_Height_ft"),
                "coord_source": src,
                "corrected": CORRECTED.get(arid),
                "cluster": clustered.get(arid),
                # from build/join_dams_to_habitat.R; None where the dam matched nothing
                "species_present": (join.at[arid, "species_present"]
                                    if join is not None and arid in join.index
                                    and isinstance(join.at[arid, "species_present"], str) else None),
                # Normalised to the map's own layer names, listing entity dropped (2026-09-18,
                # Nathan). See esa_display() at the top of this file for what that costs.
                "esa_critical_habitat": esa_display(
                    join.at[arid, "esa_critical_habitat"]
                    if join is not None and arid in join.index
                    and isinstance(join.at[arid, "esa_critical_habitat"], str) else None),
                # Species paired with the grade of the best claim behind each, e.g.
                # "Steelhead=observed; Chinook salmon=range". Added 2026-09-12 so the map
                # can say how strong a presence value is rather than only that it exists;
                # phase 2 adds `inferred` (Washington redband) and `proxy` (Washington
                # eulachon), which are the values this exists for.
                "species_present_grades": (join.at[arid, "species_present_grades"]
                                           if join is not None and arid in join.index
                                           and "species_present_grades" in join.columns
                                           and isinstance(join.at[arid, "species_present_grades"], str) else None),
                # What the audits found here, so the map can be used to LOOK at a
                # flagged dam rather than read its coordinate out of a table.
                # None for the great majority of dams, which is the point.
                "audit": audit.get(arid) or None,
            },
        })

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gj = {"type": "FeatureCollection", "features": feats}
    (OUT_DIR / "dams.geojson").write_text(json.dumps(gj))

    meta = {
        # Two different claims, and neither replaces the other. "Rows in the
        # source database" is what American Rivers publishes; "distinct removals"
        # is what this project believes happened after removing duplicates.
        # Reporting only one of them would be the quiet swap this project keeps
        # catching elsewhere.
        "total_rows": len(ar),
        "distinct_removals": len(ar) - len(dupes),
        "duplicates": len(dupes),
        "duplicate_rows": dupes,
        # A site is a place. Rows sharing a Cluster_ID_DRP are one barrier as far
        # as NACC and as far as any distance join are concerned, so they collapse
        # to a single site. Structures and sites are both true counts of different
        # things; the map draws structures.
        "sites": (len(ar) - len(dupes)) - len(clustered) + len(set(clustered.values())),
        "clusters": len(set(clustered.values())),
        "clustered_rows": len(clustered),
        "mapped": len(feats),
        "from_ar": n_ar,
        "from_nacc": n_nacc,
        "from_drp": n_drp,
        "unmapped": len(unmapped),
        "voided": len([u for u in unmapped if u["reason"] != "no coordinate in any source"]),
        "corrected": len([f for f in feats if f["properties"]["corrected"]]),
        "with_year": len([f for f in feats if f["properties"]["year"]]),
        "by_state": {s: len([f for f in feats if f["properties"]["state"] == s])
                     for s in sorted({f["properties"]["state"] for f in feats})},
        "unmapped_rows": unmapped,
        "audit_flagged": len([f for f in feats if f["properties"]["audit"]]),
        "audit_rule45_blocked": len([f for f in feats if (f["properties"]["audit"] or {}).get("rule45_blocked")]),
        "audit_needs_eyes": len([f for f in feats if ((f["properties"]["audit"] or {}).get("same_stream") or {}).get("flag")]),
        "generated": __import__("datetime").date.today().isoformat(),
    }
    (OUT_DIR / "dams_meta.json").write_text(json.dumps(meta, indent=2))

    # Same payload as a plain script, so index.html opens from file:// with no
    # local server. The real build fetches the .geojson instead.
    (OUT_DIR / "dams.js").write_text(
        "// generated by build/make_sketch_data.py, do not edit\n"
        f"const DAMS = {json.dumps(gj)};\n"
        f"const META = {json.dumps(meta)};\n"
    )

    print(f"{len(ar)} AR rows, {meta['distinct_removals']} distinct removals "
          f"({len(dupes)} duplicate), {meta['sites']} sites "
          f"({meta['clustered_rows']} rows in {meta['clusters']} clusters)")
    print(f"  mapped    {len(feats):3}  ({n_ar} from American Rivers, "
          f"{n_nacc} recovered from NACC, {n_drp} corrected)")
    print(f"  unmapped  {len(unmapped):3}  ({meta['voided']} voided as wrong, "
          f"{len(unmapped) - meta['voided']} never had a coordinate)")
    print(f"  corrected {meta['corrected']:3}  (shown on the map as corrected)")
    # The CORRECTED dict is hand-written because it holds an explanation, which
    # cannot be derived; `n_drp` is counted from the sheet. So the two can drift
    # apart silently the moment a correction is written without a note here, and
    # the map then swaps a point in quietly, which is what this dict exists to
    # prevent. Say so loudly rather than leaving two numbers to be compared by eye.
    missing = sorted({f["properties"]["id"] for f in feats
                      if f["properties"]["coord_source"] == "drp"
                      and not f["properties"]["corrected"]})
    if missing:
        print(f"  WARNING: {len(missing)} corrected coordinate(s) carry no explanation "
              f"in CORRECTED and will not be flagged on the map: {', '.join(missing)}")
    print(f"  by state  {meta['by_state']}")
    # A designation this crosswalk has never seen is kept verbatim rather than dropped, but it must
    # be LOUD: silently passing an un-normalised label through is exactly the defect being fixed.
    if _esa_unmapped:
        print(f"  WARNING: {len(_esa_unmapped)} ESA label(s) not in the crosswalk, "
              f"passed through verbatim: {sorted(_esa_unmapped)}")
    print(f"\nwrote {(OUT_DIR / 'dams.geojson').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
