"""Write accepted values into the working sheet's _DRP columns, with provenance.

THE RULE THIS IMPLEMENTS. Standing rule 2: never edit a source column, write to
its `_DRP` twin, and **record where every value came from and by what method**.
The working sheet has the twins but nowhere to hold the provenance, so this
keeps a separate ledger: one row per written value, appended, never rewritten.

    PROVENANCE.csv
      applied_utc   when
      ar_id         which row
      field         which _DRP column
      value         what was written
      source        where it came from, specific enough to re-find
      method        how it was established
      script        what wrote it
      note          anything a reader needs

Two kinds of entry:
  * a VALUE entry writes to the sheet and logs the write
  * a DETERMINATION entry writes nothing and logs a finding, so that resolved
    negatives ("searched, not findable, and the blank is correct") are recorded
    rather than silently re-researched later

Safety: the sheet is backed up before any write, and a dry run is the default.
Nothing is written without --apply.
"""

import argparse
import csv
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
SHEET = ROOT / "WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv"
LEDGER = ROOT / "WORKING/American Rivers Dam Removal Database/PROVENANCE.csv"
LINKS = ROOT / "D3/build/ar_nacc_links.csv"

LEDGER_COLS = ["applied_utc", "ar_id", "field", "value", "source", "method",
               "script", "note"]

# A short human-readable note lives in the sheet itself as well as the ledger,
# so the context is visible when reading a row rather than only when auditing.
# Notes accumulate; they are never overwritten.
NOTES_COL = "Notes_DRP"

# Says "the source coordinate is wrong and must not be used", which a blank _DRP
# cannot express, since blank means "no override". Any build step that reads
# coordinates must skip a row whose value here is non-empty.
VOID_COL = "Coordinate_Void_DRP"

# Says "this row is not a distinct removal, it repeats another row", holding the
# AR_ID it duplicates. Deliberately NOT the same column as VOID_COL: a voided
# coordinate is a real removal that cannot be placed and still counts, whereas a
# duplicate must not be counted at all. Both are unmappable; only one is a dam.
DUP_COL = "Duplicate_Of_DRP"

# Groups AR rows that NACC records as one barrier, holding that barrier's
# SARPID. Blank means the row is its own site. Purely a COUNTING aid: it never
# removes a row from the map or from any total.
CLUSTER_COL = "Cluster_ID_DRP"

# Corrects American Rivers' own `River` value where it names the wrong stream.
# Blank means the source value stands. This is a NAME correction only: it never
# moves a dam, and nothing about the geometry depends on it. It matters because
# the join's same-stream rule reads the river name, so a wrong name there either
# loses a real match or, worse, buys a wrong one.
#
# NOT a new column: this is the ordinary `_DRP` override that the sheet has
# carried for every American Rivers field since the convention was set up. It is
# named here only because it now has a consumer. First used 2026-09-12 for OR-066.
RIVER_COL = "River_DRP"


def ghost_coordinates() -> list[dict]:
    """The nine coordinates recovered from NACC on 2026-09-08.

    Established by `build/link_ar_to_nacc.py` tier T2: American Rivers rows that
    NACC ingested and stored with `SourceID` equal to the AR_ID, so the link is
    a deterministic key match rather than a name guess. Every one was checked to
    agree with American Rivers on river name and removal year, and every one is
    flagged `Snapped = true` in NACC, meaning SARP placed it on a flowline.
    """
    links = pd.read_csv(LINKS, dtype=str)
    rows: list[dict] = []
    for _, r in links.iterrows():
        if r.get("tier") != "T2_SOURCEID":
            continue
        if pd.notna(r.get("ar_lat")):          # already had a coordinate
            continue
        if pd.isna(r.get("nacc_lat")) or pd.isna(r.get("nacc_lon")):
            continue
        src = (f"NACC National Aquatic Barrier Inventory v4.3.0 (published "
               f"2026-07-30, downloaded 2026-09-08), SARPID {r['nacc_SARPID']}")
        method = ("deterministic key join: NACC Source = 'American Rivers Dam "
                  "Removal Database' and NACC SourceID = this AR_ID; verified "
                  "the river name and removal year agree with American Rivers")
        note = (f"NACC river {r.get('nacc_River')!r}, "
                f"Snapped={r.get('nacc_Snapped')}")
        sheet_note = (f"coordinate from NACC v4.3.0 SARPID {r['nacc_SARPID']} "
                      f"via deterministic SourceID join; river and year verified")
        for field, value in (("Latitude_DRP", r["nacc_lat"]),
                             ("Longitude_DRP", r["nacc_lon"])):
            rows.append(dict(ar_id=r["AR_ID"], field=field, value=value,
                             source=src, method=method, note=note,
                             sheet_note=sheet_note))
    return rows


def determinations() -> list[dict]:
    """Findings that write no value but must not be re-researched."""
    src = ("_OLD/DOCS/DAM_PROJECT_HANDOFF/MEMORY_project_gis205_dam_removal.md, "
           "research done June 2026")
    method = "web research, June 2026; recorded here 2026-09-08"
    note = ("Above Bowman Dam (Prineville Reservoir) on a Crooked River "
            "tributary, isolated from anadromous fish by downstream "
            "infrastructure. Native species are resident redband trout, not "
            "listed. Coordinates searched for and NOT findable. The blank "
            "species value is the CORRECT answer, not a data gap. Do not "
            "re-research.")
    sheet_note = ("no coordinates findable (researched June 2026); above Bowman "
                  "Dam, cut off from anadromous fish, so the blank species value "
                  "is CORRECT not missing. Do not re-research.")
    return [dict(ar_id=a, field="(determination)", value="", source=src,
                 method=method, note=note, sheet_note=sheet_note)
            for a in ("OR-032", "OR-033")]


def ca032_still_unplaced() -> list[dict]:
    """CA-032 Happy Isles Dam: checked again 2026-09-10, STILL NOT PLACED.

    Logged so the 09-10 round is not repeated. Three things were established and
    none of them is a coordinate.

    1. **The National Park Service independently corroborates the removal.**
       Yosemite's own restoration page says "The dam above Happy Isles and the dam
       near Cascade Creek (removed in 2004) were abandoned and outdated
       structures", and that no dams now remain on the Merced inside the park.
       That matters because American Rivers records no river, no county and no
       coordinate for this row, so its only witness was AR. It is now AR plus the
       agency that did the work. **The row's status improves without its
       coordinate improving**, which is worth distinguishing.
    2. **A plausible hypothesis was tested and is NOT confirmed.** The Happy Isles
       Fish Hatchery ran 1927 to about 1956, and an 8 ft dam above Happy Isles
       would be a natural water supply for it; NPS calls the structure abandoned,
       and 1987 is 31 years after the hatchery closed. The story is coherent.
       **No source connects the dam to the hatchery.** The Yosemite Conservancy
       history, CDFW's hatchery history and the NPS page all describe the hatchery
       without mentioning a dam, intake or diversion. Recorded as a hypothesis so
       nobody mistakes coherence for evidence, and so the next person does not
       re-derive it.
    3. **The remaining instrument is historical topographic maps**, lead 6 in
       `COORDINATE_HUNT.md` and still untried for this row. Happy Isles sits on the
       **Half Dome 7.5-minute quad**; a pre-1987 edition would carry a dam symbol,
       and a dam symbol is a location. NGMDB's topoView API returned an HTML shell
       to every endpoint tried, so it needs a browser at ngmdb.usgs.gov/topoview or
       the direct GeoPDF path on the prd-tnm S3 bucket. Second instrument if that
       fails: the 2014 Merced River Plan FEIS, which inventoried park structures.

    Standing rule 33 applies and argues against spending more on this row: **it
    carries no reported river miles at all.** The pull of "an 8 ft NPS dam in
    Yosemite ought to be findable" is tidiness, not consequence, which is the exact
    instinct rule 33 exists to check. WA-009 earned its reopening with 90 miles.
    This row earns nothing by that test, and the honest status stays "not placed".

    The USGS gauge at Happy Isles Bridge (11264500, 37.73130/-119.55902) is still
    deliberately NOT used, per the 09-09 determination: the sources put the dam
    *above* Happy Isles and the gauge is the bridge.
    """
    src = ("Yosemite National Park restoration page, "
           "https://www.nps.gov/yose/learn/news/restoration1012.htm ; hatchery "
           "history checked against Yosemite Conservancy "
           "https://yosemite.org/happy-isles-happenings/ and CDFW "
           "https://wildlife.ca.gov/Fishing/Hatcheries/Merced-River/History")
    method = ("second search round 2026-09-10: NPS corroboration found, "
              "fish-hatchery water-supply hypothesis tested against three sources "
              "and NOT confirmed, historical topographic maps identified as the "
              "remaining instrument and not yet tried")
    note = ("STILL NOT PLACED after a second round. NPS independently corroborates "
            "the removal ('the dam above Happy Isles ... abandoned and outdated'), "
            "so the row is no longer AR-only even though it has no coordinate. "
            "HYPOTHESIS NOT CONFIRMED: the Happy Isles Fish Hatchery (1927-c.1956) "
            "is a plausible reason for an 8 ft dam here, and 1987 is 31 years after "
            "it closed, but no source connects the dam to the hatchery; coherence "
            "is not evidence. NEXT AND UNTRIED: historical USGS topo maps, Half "
            "Dome 7.5' quad, pre-1987 edition, which would show a dam symbol; "
            "topoView needs a browser. Then the 2014 Merced River Plan FEIS. "
            "Rule 33 argues against further effort: this row has NO reported river "
            "miles, so the motive is tidiness rather than consequence. The Happy "
            "Isles Bridge gauge remains deliberately unused.")
    sheet_note = ("checked again 2026-09-10, STILL NOT PLACED. NPS corroborates the "
                  "removal (nps.gov/yose restoration1012), so the row is no longer "
                  "AR-only. Fish-hatchery water-supply hypothesis tested against "
                  "three sources and NOT confirmed. Next and untried: historical "
                  "USGS topo, Half Dome 7.5' quad pre-1987, which would show a dam "
                  "symbol. Rule 33 note: this row has no reported river miles, so "
                  "further effort is tidiness not consequence.")
    return [dict(ar_id="CA-032", field="(determination)", value="", source=src,
                 method=method, note=note, sheet_note=sheet_note)]


def ca037_not_mapped() -> list[dict]:
    """CA-037 C-Lind Dam #1: searched 2026-09-10, NOT PLACED, and NOT TO BE MAPPED.

    **Nathan's call 2026-09-10: this one will not be mapped.** It stays an
    unplaceable removal and still counts as a removal, exactly like CA-032.

    NOT a `Coordinate_Void_DRP` case. That column means "the coordinate on the row is
    wrong and there is no replacement". CA-037 has no coordinate from any source, so
    it is an ordinary unplaceable row and the void column must not be used for it.
    See DATA_DICTIONARY.md, which warns about this distinction specifically.

    ## Why it had a claim on attention, and why that claim is now weaker

    At a stated **56 ft** it is the **10th tallest of the 247 rows carrying a height**,
    and nearly twice the next tallest unplaceable row (Red Hill Mining, 30 ft). Under
    standing rule 33 that is a real reason to look, which is why it was looked at.

    **But the height is unverified and suspect.** CA-037 sits in a batch of 42 rows all
    last updated 11/10/2017, and within that batch heights run 3 to 30 ft with a median
    of 10.5. Its immediate neighbours CA-032 to CA-043 run 6 to 12 ft. **56 is a 5x
    outlier inside its own source batch.** Suspect, not disproved, and nothing was
    changed on the strength of it.

    **A wrong argument, recorded so it is not reused: a blank `NID_ID` is NOT evidence
    against a large height.** Of the 30 rows at 25 ft or more, only 10 carry a
    `NID_ID`, and the twenty without include San Clemente Dam at 106 ft, Sweasey at
    55 ft, Marmot at 47 ft and Savage Rapids at 39 ft, all real and all famous. Claude
    advanced that argument and withdrew it the same session.

    ## Lead 3 is CLOSED, and for a structural reason worth more than this row

    `COORDINATE_HUNT.md` lead 3 was "the National Inventory of Dams, at 56 ft it should
    be in NID". It is not, and **NID cannot answer this class of question at all**:

    * **0 of 8 known-removed dams appear in NID today.** Tested against Elwha, Glines
      Canyon, Condit, Iron Gate (removed 2024), San Clemente, Sweasey, Marmot and
      Savage Rapids. **NID purges dams once they are gone.**
    * **DSOD is the same shape.** All 1,230 rows in California's jurisdictional dams
      dataset are `Certified`, `Not Certified` or `Certified/Inop`. There is no removed
      status; it is a current inventory, not a historical register.

    That is standing rule 29 again, and it generalises into **standing rule 34: a
    dam-safety inventory and a removal registry are different kinds of object.** This
    retires NID and DSOD for every pre-2000 row at once, not just this one.

    ## What was actually searched, so it is not repeated

    * All three NID name fields, **including `formerNames`**, across 1,534 California
      records. Nothing resembling "C-Lind", "Cline", "C-Line" or "Lynd". The five
      `Lind`-family hits are 8 to 39 ft and all still standing.
    * **Attribute-first rather than name-first**, since the name is the corrupted
      field: every California NID dam with any height in the 50 to 62 ft band. **157
      records, every one still standing**, none plausibly this dam.
    * DSOD's 1,230 jurisdictional dams, same name patterns, nothing.

    ## What is left, if anyone ever resumes

    All three are historical sources rather than current inventories, which is the only
    category that can answer it:

    1. **USGS historical topographic maps.** Now the single instrument for CA-032,
       CA-037 and the 19 mining-era rows, so do them in one sitting. Blocked for
       CA-037 specifically by having **no river and no county**, so there is no quad to
       start from. It needs the name solved first, or an owner.
    2. **DSOD's agency records of dams removed from jurisdiction.** A 56 ft dam was
       certainly DSOD-jurisdictional (threshold 25 ft or 50 acre-feet), so a file
       should exist even though the published dataset omits it. That is a records
       request, not a download.
    3. **1993 California newspaper archives**, once there is a county to narrow to.

    Data pulled for this is kept at `WORKING/NID_DSOD/` with a README recording the
    provenance and two retrieval gotchas (NID's GeoPackage is plain SQLite and far
    easier than its latin-1 CSV; DSOD is current-only).
    """
    src = ("National Inventory of Dams, USACE, data last updated 2026-08-28, pulled "
           "from https://nid.sec.usace.army.mil/api/nation/gpkg (92,604 rows; 1,534 "
           "California); California DWR Division of Safety of Dams jurisdictional "
           "dams, data.ca.gov dataset 'i17 California Jurisdictional Dams' (1,230 "
           "rows). Both saved under WORKING/NID_DSOD/ with a README.")
    method = ("searched both regulatory inventories by name across NID's name, "
              "otherNames and formerNames fields, then attribute-first on the 50-62 ft "
              "height band since the name is the corrupted field; then tested whether "
              "NID retains removed dams at all, using 8 known removals as controls")
    note = ("NOT PLACED and NOT TO BE MAPPED (Nathan's call 2026-09-10). Ordinary "
            "unplaceable row, NOT a Coordinate_Void_DRP case, since it has no "
            "coordinate from any source. LEAD 3 (NID) IS CLOSED FOR A STRUCTURAL "
            "REASON: 0 of 8 known-removed dams appear in NID today (Elwha, Glines "
            "Canyon, Condit, Iron Gate, San Clemente, Sweasey, Marmot, Savage Rapids "
            "all absent), so NID purges removed dams; DSOD is the same, all 1,230 rows "
            "Certified/Not Certified/Certified-Inop with no removed status. Now "
            "standing rule 34. SEARCHED AND NEGATIVE: all three NID name fields "
            "including formerNames across 1,534 CA records; and attribute-first, 157 "
            "CA dams in the 50-62 ft band, every one still standing. HEIGHT IS "
            "SUSPECT BUT NOT DISPROVED: 56 ft is a 5x outlier in its own 11/10/2017 "
            "batch of 42 rows, where heights run 3-30 ft, median 10.5. A WRONG "
            "ARGUMENT NOT TO REUSE: a blank NID_ID is not evidence against a large "
            "height, since only 10 of 30 rows >=25 ft carry one and San Clemente at "
            "106 ft has none. REMAINING: historical USGS topo (blocked here by having "
            "no river and no county, so the name must be solved first), a DSOD records "
            "request for dams removed from jurisdiction, and 1993 newspaper archives.")
    sheet_note = ("2026-09-10: NOT PLACED and will NOT be mapped (Nathan's call); still "
                  "counts as a removal. Not a void-coordinate case, it simply has no "
                  "coordinate. NID lead CLOSED structurally: 0 of 8 known-removed dams "
                  "appear in NID, so it purges removals; DSOD likewise is current-only. "
                  "Searched NID name/otherNames/formerNames and, attribute-first, all "
                  "157 CA dams at 50-62 ft: all still standing, no match. The 56 ft "
                  "height is a 5x outlier in its own source batch (median 10.5), so it "
                  "is suspect but not disproved. Left: historical topo maps (needs the "
                  "name or a county first), a DSOD records request, 1993 newspapers.")
    return [dict(ar_id="CA-037", field="(determination)", value="", source=src,
                 method=method, note=note, sheet_note=sheet_note)]


def ca054_source_notes() -> list[dict]:
    """CA-054 Cascade Diversion Dam: a primary source found, and two disagreements.

    **Recorded, deliberately NOT pursued as a project thread. Nathan's call,
    2026-09-10**, after it was raised as a possible portfolio angle: he did not
    feel the need to make it part of the project. So this is a source note and a
    pair of logged disagreements, nothing more. Do not revive it as a workstream
    without asking.

    The source: **USGS Open-File Report 88-733**, J.C. Blodgett, *Assessment of
    Hydraulic Changes Associated with Removal of Cascade Dam, Merced River,
    Yosemite Valley, California*, Sacramento, 1989, prepared in cooperation with
    the National Park Service. https://pubs.usgs.gov/of/1988/0733/report.pdf

    It is a **pre-removal** study, not a post-removal one. Its abstract opens "The
    National Park Service is considering plans to remove Cascade Diversion Dam",
    so NPS studied the removal around 1988 and carried it out roughly fifteen years
    later. It contains surveyed cross sections and water-surface profiles from April
    1988, records the pool extending about 550 ft upstream, and predicts bed scour
    to about 20 ft below the dam crest with bed and bank shear stresses six times
    present. That is a surveyed "before" for a dam this project maps, which is
    unusual in this dataset. Noted for whoever wants it; not taken up here.

    Two disagreements, neither resolvable from here and neither acted on:

    * **Build year: the report says 1917, `Year_Built` says 1918.**
    * **Removal year: `Year_Removed` says 2003, the NPS restoration page says
      2004** ("the dam near Cascade Creek (removed in 2004)").

    Per standing rule 2 no source column is edited, and per the OR-076 and CA-175
    precedent a contested year is left alone rather than picked. The value of the
    note is not the years; it is that this row has now been checked against an
    outside source and found to differ, which is a different condition from never
    having been checked, and the two look identical in the sheet without this entry.
    """
    src = ("USGS Open-File Report 88-733, J.C. Blodgett, 'Assessment of Hydraulic "
           "Changes Associated with Removal of Cascade Dam, Merced River, Yosemite "
           "Valley, California', 1989, prepared with the National Park Service, "
           "https://pubs.usgs.gov/of/1988/0733/report.pdf ; removal year cross-"
           "checked against https://www.nps.gov/yose/learn/news/restoration1012.htm")
    method = ("primary-source check 2026-09-10 while researching CA-032; no value "
              "written, per rule 2 and the OR-076/CA-175 precedent on contested years")
    note = ("SOURCE NOTE, recorded and NOT pursued as a project thread (Nathan's "
            "call 2026-09-10). USGS OFR 88-733 (Blodgett, 1989, with NPS) is a "
            "PRE-removal hydraulic study of this dam: surveyed cross sections and "
            "water-surface profiles from April 1988, pool extending ~550 ft "
            "upstream, and predictions of ~20 ft of bed scour below the dam crest "
            "with bed/bank shear six times present. NPS was 'considering plans to "
            "remove' it in 1988 and did so ~15 years later, so a surveyed 'before' "
            "exists for this row, which is rare in this dataset. TWO DISAGREEMENTS, "
            "neither resolved and neither acted on: build year 1917 in the report "
            "against 1918 in Year_Built; removal year 2003 in Year_Removed against "
            "2004 on the NPS page. The point of logging them is that this row has "
            "now been checked against an outside source and found to differ, which "
            "is not the same condition as never having been checked.")
    sheet_note = ("2026-09-10 source note, not a project thread: USGS OFR 88-733 "
                  "(Blodgett 1989, with NPS) is a PRE-removal hydraulic study of "
                  "this dam, with April 1988 surveys and predicted ~20 ft of scour. "
                  "pubs.usgs.gov/of/1988/0733/report.pdf . Two unresolved "
                  "disagreements recorded, neither acted on: built 1917 (report) vs "
                  "1918 (Year_Built), and removed 2003 (Year_Removed) vs 2004 (NPS "
                  "restoration page).")
    return [dict(ar_id="CA-054", field="(determination)", value="", source=src,
                 method=method, note=note, sheet_note=sheet_note)]


def voided_coordinates() -> list[dict]:
    """Coordinates known to be wrong, with no replacement available.

    WHY A NEW COLUMN. A blank `_DRP` means "no override", so the schema had no way
    to say "the source value is wrong and must not be used". `Coordinate_Void_DRP`
    says exactly that. Any build step that reads coordinates must skip a row whose
    value here is non-empty, exactly as it skips a row with no coordinate at all.

    WHAT THIS IS NOT. These rows are **not removed from the study**. They are real
    removals that cannot be placed, which is the category the 43 coordinate-less
    American Rivers rows already occupy. They still count as dam removals; they
    are not mapped and not joined. Counts move from 281 usable coordinates to 279,
    and from 43 unplaceable rows to 45. The 333 total does not change.

    THE DEFECT. CA-157 (SCFD4) and CA-158 (SCFD5) are Silverado Creek Fish Dams
    carrying coordinates byte-identical to CA-143 (SJFD4) and CA-144 (SJFD5) on
    San Juan Creek, 24.6 km away in an unrelated basin: Silverado drains to
    Santiago Creek and the Santa Ana River, San Juan runs straight to the Pacific.
    Four of the six SCFD rows sit together in Silverado Canyon near 33.752 N,
    -117.570 W; these two are the only members of the series that do not.
    CA-157 still declares HUC8 "Santa Ana", contradicting its own coordinate.

    REPAIR LEAD, recorded so it is not lost. The four sound SCFD rows span about
    280 m of Silverado Canyon from -117.5711 (SCFD7) to -117.5681 (SCFD12), so
    the series numbers upstream and SCFD4 and SCFD5 would lie west of -117.5711.
    Weak evidence though: those four are dated 2017 and these two 2019, a
    different removal phase, so they need not be contiguous with them.
    """
    common = dict(
        source=("internal consistency check on _WORKING_WestCoast_CA_OR_WA.csv "
                "plus NACC v4.3.0 records CA104129/CA104130 sourced from the "
                "California Passage Assessment Database (CA PAD, 2023-06-20)"),
        method=("whole-sheet exact-coordinate collision scan; the SCFD row's "
                "coordinate is byte-identical to the SJFD row's, and the SJFD "
                "row is corroborated by an independent CA PAD record within 6 m "
                "while the SCFD row's four series siblings sit 24.6 km north in "
                "Silverado Canyon"),
    )
    rows = []
    for ar_id, name, twin, twin_name, huc in (
        ("CA-157", "SCFD4", "CA-143", "SJFD4", "declares HUC8 'Santa Ana', which "
         "contradicts its own coordinate"),
        ("CA-158", "SCFD5", "CA-144", "SJFD5", "declares HUC8 'Aliso-San Onofre', "
         "unlike every other SCFD row"),
    ):
        reason = (f"{name} carries {twin_name}'s San Juan Creek coordinate "
                  f"(byte-identical to {twin}); 24.6 km from Silverado Creek, "
                  f"wrong basin. Not mapped, not joined. Still counts as a "
                  f"removal. See 09-08_PROBLEMS.md Problem 1.")
        rows.append(dict(
            ar_id=ar_id, field="Coordinate_Void_DRP", value=reason,
            note=(f"{name} is a Silverado Creek Fish Dam but its coordinate is "
                  f"byte-identical to {twin} {twin_name} on San Juan Creek, "
                  f"24.6 km away in an unrelated basin (Silverado drains to the "
                  f"Santa Ana River, San Juan to the Pacific). The row {huc}. "
                  f"Four of six SCFD rows sit near 33.752 N, -117.570 W in "
                  f"Silverado Canyon; these two do not. No replacement coordinate "
                  f"available, so the coordinate is voided rather than corrected. "
                  f"REPAIR LEAD: SCFD numbering runs upstream, so SCFD4/5 likely "
                  f"lie west of -117.5711; weak, since the sound rows are 2017 "
                  f"removals and these are 2019."),
            sheet_note=(f"coordinate VOIDED: {name} carries {twin_name}'s San "
                        f"Juan Creek coordinate, 24.6 km from Silverado Creek. "
                        f"Not mapped, not joined, still counted as a removal."),
            **common))
    return rows


def duplicate_rows() -> list[dict]:
    """Rows that repeat another row rather than recording a separate removal.

    CA-091 and CA-148 are both named TCFD11, on Trabuco Creek, both 6.5 ft, both
    carrying `NABI_ID` CA104126, 12 m apart. One dam recorded twice: CA-091 from
    a coarse 2014 source at 3 decimal places, CA-148 from a precise 2018 record
    at 8. Nathan's call 2026-09-09 is to keep the later, precise row.

    COUNTING. A duplicate is not a removal, so `Duplicate_Of_DRP` removes the row
    from the count of distinct removals as well as from the map. The database
    still holds 333 rows; the distinct-removal count becomes 332. **Both numbers
    are reported and neither replaces the other**, the same rule the cluster work
    uses, because "rows in the source database" and "dam removals" are different
    claims and the project should never quietly swap one for the other.

    ONE THING LEFT OPEN, and it is about the year rather than the coordinate.
    TCFD9, TCFD10 and TCFD11 were removed together in 2014 per the other Trabuco
    rows. Keeping CA-148 means the surviving record says 2018 while its two batch
    siblings say 2014. Either the Orange County programme re-treated this dam in
    2018, or CA-148's year is the error and its coordinate is still the better
    one. Voiding CA-091 does not settle that, and this note is here so the
    question is not lost.
    """
    return [dict(
        ar_id="CA-091", field=DUP_COL, value="CA-148",
        source=("internal duplicate scan of _WORKING_WestCoast_CA_OR_WA.csv; "
                "both rows also link to NACC SARPID CA104126"),
        method=("matched on dam name, river, height and NABI_ID, with the two "
                "coordinates 12 m apart; the surviving row was chosen for "
                "coordinate precision (8 dp against 3 dp)"),
        note=("CA-091 and CA-148 are both 'TCFD11' on Trabuco Creek, both 6.5 ft, "
              "both NABI_ID CA104126, 12 m apart, dated 2014 and 2018. Treated as "
              "one dam recorded twice. CA-091 is the coarse 2014 record and is "
              "retired; CA-148 is kept. NOT a removal in its own right, so it is "
              "excluded from the distinct-removal count as well as from the map. "
              "OPEN: TCFD9 and TCFD10 are both dated 2014, so the surviving row's "
              "2018 date disagrees with its batch. That is a question about the "
              "year, not the coordinate, and is unresolved."),
        sheet_note=("DUPLICATE of CA-148: same name TCFD11, same creek, same "
                    "height, same NABI_ID, 12 m apart. This is the coarse 2014 "
                    "record; CA-148 is kept. Not mapped and not counted as a "
                    "distinct removal."),
    )]


def cluster_ids(df) -> list[dict]:
    """Group AR rows that a distance join cannot tell apart.

    WHAT A CLUSTER IS. A set of American Rivers rows that the NACC/SARP inventory
    records as **one barrier**. The id is that barrier's SARPID, so the grouping
    is traceable to an external agency's judgement about what counts as a single
    structure rather than to a threshold picked here.

    WHY SARPID AND NOT A SHARED COORDINATE. Both were tested. All six exact
    coordinate collisions turn out to be subsets of NACC collision groups, so
    SARPID is the broader basis and loses nothing.

    WHY NOT A DISTANCE THRESHOLD. That would need the join tolerance, which is the
    decision this work is meant to inform. Deriving the clusters from the tolerance
    and then using the clusters to sanity-check the tolerance would be circular.

    WHO IS EXCLUDED, and it matters. Duplicates and voided-coordinate rows are left
    out before grouping. That is not tidying: CA104129 and CA104130 stop being
    clusters entirely once CA-157 and CA-158 are removed, because those two only
    appeared to sit beside CA-143 and CA-144 as a result of the copied coordinates
    documented in 09-08_PROBLEMS.md Problem 1. Clustering them would have preserved
    the very error that was just removed.

    WHAT IT IS FOR. Counting. "34 dams in SONCC habitat" and "34 sites in SONCC
    habitat" are different claims when two of them are Lithia Park Dam 1 and 2
    twenty metres apart. This column lets both be reported. It also marks the rows
    a tolerance join **cannot** separate, whose identical species results are an
    artefact of the geometry rather than a finding.

    Blank means the row is its own site. Only multi-row groups are populated.
    """
    links = pd.read_csv(LINKS, dtype=str)
    state = {r["AR_ID"]: r for _, r in df.iterrows()}

    def eligible(ar_id):
        r = state.get(ar_id)
        if r is None:
            return False
        for col in (DUP_COL, VOID_COL):
            v = r.get(col)
            if pd.notna(v) and str(v).strip():
                return False
        return True

    groups: dict[str, list[str]] = {}
    for _, r in links.iterrows():
        sarpid = r.get("nacc_SARPID")
        if pd.isna(sarpid) or not str(sarpid).strip():
            continue
        groups.setdefault(str(sarpid).strip(), []).append(r["AR_ID"])

    rows = []
    for sarpid, members in sorted(groups.items()):
        keep = [m for m in members if eligible(m)]
        if len(keep) < 2:
            continue
        names = ", ".join(sorted(keep))
        for ar_id in keep:
            others = sorted(m for m in keep if m != ar_id)
            rows.append(dict(
                ar_id=ar_id, field="Cluster_ID_DRP", value=sarpid,
                source=(f"NACC National Aquatic Barrier Inventory v4.3.0, SARPID "
                        f"{sarpid} (downloaded 2026-09-08)"),
                method=("AR rows sharing one NACC barrier record, after excluding "
                        "duplicate and voided-coordinate rows"),
                note=(f"{len(keep)} American Rivers rows ({names}) that NACC "
                      f"records as the single barrier {sarpid}. A distance join "
                      f"cannot separate them, so identical species results across "
                      f"this cluster are an artefact of the geometry, not a "
                      f"finding. Count as {len(keep)} structures or 1 site "
                      f"depending on the claim being made."),
                sheet_note=(f"cluster {sarpid}: NACC records this and "
                            f"{', '.join(others)} as one barrier. Not separable "
                            f"by a distance join."),
            ))
    return rows


def plainview_coordinate() -> list[dict]:
    """OR-076 Plainview Dam, recovered 2026-09-09 from the NACC inventory.

    One of the five Oregon rows American Rivers left without a coordinate, and one
    of the three whose June 2026 research left no record. Found by searching the
    NACC Oregon barrier file already on disk rather than by web search.

    THE MATCH, and it holds on five independent checks:
      * name        NACC "Plainview Ditch Dam" against AR "Plainview Dam"
      * river       Whychus Creek, exact
      * place       NACC Deschutes County against AR City_County "Sisters"
      * status      NACC Removed = yes
      * unclaimed   no other AR row links to SARPID OR1058, and the only other
                    Whychus row, OR-046 Pine Meadow Ranch Dam, is separately
                    accounted for by SARPID OR2713 (Sokol Dam)

    THE CONFIRMATION THAT MATTERS, because it comes from a different lineage.
    Press coverage of the removal places it "about 4 miles south of Sisters". This
    coordinate is **3.94 miles** from Sisters. NACC's record derives from the ODFW
    fish passage database; the press figure derives from the Upper Deschutes
    Watershed Council. Two sources that do not share a source agree.

    THE DISCREPANCY, recorded rather than smoothed over. **AR says removed 2021,
    NACC says 2022.** The project was scheduled for September 2020, postponed by
    wildfire and smoke on the Deschutes National Forest, and resumed in summer
    2021, so completion sits on the 2021/2022 boundary and the two databases
    landed on different sides of it. This does not affect the coordinate, and no
    year is written here. **If the removal year ever matters, it is unresolved.**
    """
    src = ("NACC National Aquatic Barrier Inventory v4.3.0 (downloaded 2026-09-08), "
           "SARPID OR1058 'Plainview Ditch Dam', whose own source is the ODFW fish "
           "passage database (Jun 10 2022), SourceID 5699, Snapped=true; location "
           "corroborated by press coverage of the Upper Deschutes Watershed Council "
           "project placing the dam about 4 miles south of Sisters")
    method = ("searched the NACC Oregon barrier file for River containing "
              "'Whychus'; five records, one named Plainview, flagged Removed=yes, "
              "in the right county, claimed by no other AR row; distance from "
              "Sisters computed as 3.94 mi against the published 'about 4 miles "
              "south'")
    note = ("Recovers one of the five coordinate-less Oregon rows. Match confirmed "
            "on name, river, county, removed status, and an independent distance "
            "check against press coverage. NOTE the year disagreement: AR says "
            "2021, NACC/ODFW says 2022. The removal was postponed from September "
            "2020 by wildfire and resumed in summer 2021, so completion straddles "
            "the boundary. Coordinate is unaffected; the year is NOT resolved and "
            "no year has been written.")
    sheet_note = ("coordinate from NACC SARPID OR1058 'Plainview Ditch Dam' (ODFW "
                  "fish passage db); confirmed 3.94 mi from Sisters against press "
                  "'about 4 miles south'. AR year 2021 vs NACC 2022 unresolved.")
    return [dict(ar_id="OR-076", field=f, value=v, source=src, method=method,
                 note=note, sheet_note=sheet_note)
            for f, v in (("Latitude_DRP", "44.234966"),
                         ("Longitude_DRP", "-121.56447"))]


def little_shasta_coordinate() -> list[dict]:
    """CA-175 Little Shasta River Flashboard Dam, recovered 2026-09-09.

    Found by `build/find_missing_coords.py`, which searches NACC by RIVER rather
    than by dam name, then confirmed against the restoration literature.

    THE MATCH:
      * river      Little Shasta River, exact, and CA-175 is the ONLY American
                   Rivers row on that river
      * removed    NACC CA98151 "Blair Hart Diversion Dam (Removed)" is the only
                   NACC record on the Little Shasta flagged removed in 2019
      * year       2019 exact
      * county     Siskiyou, agreeing with AR's City_County
      * unclaimed  no other AR row links to CA98151

    CORROBORATION FROM A SECOND RECORD. NACC also holds CA625799, a FIS Projects
    2023 restoration record dated 2019, **99 m away**. Different source, same
    place, same year: something was removed there in 2019 and two agencies logged
    it.

    CORROBORATION FROM THE LITERATURE. California Trout describes working with the
    Hart Ranch on the Little Shasta from 2017 and removing a diversion dam that
    was a complete barrier to fish passage, the work including "removing the
    existing concrete and flash board diversion structure". AR's row is named
    "Little Shasta River Flashboard Dam" and NACC's is "Blair Hart". The
    flashboard and the Hart both land.

    TWO WRINKLES, recorded rather than smoothed:
      * **CalTrout dates the dam removal to 2020**, while AR and NACC both say
        2019. The ranch work ran in stages from 2017, so the phases are dated
        differently by different tellers. No year is written here.
      * **CA103987 "Musgrave Flashboard Dam" sits 403 m away** and is also a
        flashboard dam on the Little Shasta. It is flagged Removed=no, which is
        why it was not chosen, but standing rule 23 says that flag alone proves
        little. It is the alternative if this ever needs revisiting.
    """
    src = ("NACC National Aquatic Barrier Inventory v4.3.0 (downloaded "
           "2026-09-08), SARPID CA98151 'Blair Hart Diversion Dam (Removed)', "
           "sourced from the California Passage Assessment Database (CA PAD, "
           "2023-06-20); corroborated by NACC CA625799 (FIS Projects 2023, same "
           "year, 99 m away) and by California Trout's account of the Hart Ranch "
           "flashboard diversion removal on the Little Shasta River")
    method = ("river-first search of the NACC California file via "
              "build/find_missing_coords.py; CA-175 is the only AR row on the "
              "Little Shasta and CA98151 is the only NACC record on that river "
              "flagged removed in 2019; county and year both agree and the record "
              "is unclaimed")
    note = ("Only AR row on the Little Shasta River, matched to the only NACC "
            "record there flagged removed in 2019. Second NACC record 99 m away "
            "from a different source, same year. Name evidence: AR says "
            "'Flashboard', NACC says 'Blair Hart', and CalTrout describes removing "
            "a concrete and flashboard diversion at the Hart Ranch. WRINKLES: "
            "CalTrout dates the removal 2020 against AR and NACC's 2019, so no "
            "year is written; and CA103987 'Musgrave Flashboard Dam' 403 m away is "
            "the alternative, rejected only because it is flagged Removed=no, "
            "which standing rule 23 says is weak evidence on its own.")
    sheet_note = ("coordinate from NACC SARPID CA98151 'Blair Hart Diversion Dam' "
                  "(CA PAD); only NACC record on the Little Shasta removed in "
                  "2019, corroborated by a second record 99 m away and by "
                  "CalTrout's Hart Ranch flashboard removal. Alternative if ever "
                  "revisited: CA103987 Musgrave Flashboard Dam, 403 m away.")
    return [dict(ar_id="CA-175", field=f, value=v, source=src, method=method,
                 note=note, sheet_note=sheet_note)
            for f, v in (("Latitude_DRP", "41.722256"),
                         ("Longitude_DRP", "-122.37027"))]


def searched_not_found() -> list[dict]:
    """Coordinate hunts that came back empty, recorded so they are not repeated.

    Two of the five coordinate-less Oregon rows. Both were searched on 2026-09-09
    against the NACC Oregon barrier inventory and the open web, and neither can be
    placed. **This is a record of an attempt, not a resolved negative**, which is
    what separates these from OR-032 and OR-033: those two have a positive finding
    behind the blank, and these two are simply undocumented.
    """
    common_method = ("searched the NACC Oregon barrier file by river name and ran "
                     "targeted web searches; recorded 2026-09-09")
    butte_src = ("NACC California file; CEQAnet 1996105590 'Butte Creek Siphon and "
                 "Dam Removal Project'; Western Canal Water District project page; "
                 "CDFW ERP-96-M01 grant description")
    butte_method = ("river-first NACC search via build/find_missing_coords.py, then "
                    "document research; recorded 2026-09-09")
    butte_lead = (
        "STRONG LEAD, NO COORDINATE. The 1997-98 Butte Creek Siphon and Dam Removal "
        "Project removed FOUR dams for spring-run Chinook: McGowan and McPherrin, "
        "which American Rivers already has with coordinates (CA-103, CA-039), plus "
        "the two Western Canal dams. The canal now passes UNDER Butte Creek through "
        "the Gary N. Brown Butte Creek Siphon, three 10-ft pipes, built May to "
        "November 1997, $9.5M. **So the Western Canal dams stood where the Western "
        "Canal crossed Butte Creek**, at Nelson, Butte County, about 6.5 miles "
        "south-southeast of Durham. NACC holds NO record named 'Western Canal' or "
        "'Point Four' anywhere in California, so the inventory is a dead end. "
        "Neither CEQAnet nor the district's own page nor CDFW's grant description "
        "gives a coordinate. **Next thing to try: locate the canal/creek crossing "
        "from hydrography or the Library of Congress engineering record for "
        "'Western Canal, Butte Creek, Nelson, Ca.' (loc.gov/item/2004674840), which "
        "returned HTTP 403 to an automated fetch and may need a browser.** For "
        "scale, NACC's Butte Creek removals sit between 39.447 and 39.702 N.")

    return [
        dict(
            ar_id="CA-040", field="(determination)", value="",
            label="not found, strong lead: Western Canal siphon at Nelson",
            source=butte_src, method=butte_method,
            note="Western Canal East Dam. " + butte_lead,
            sheet_note=("coordinate searched 2026-09-09, NOT found. Stood where "
                        "the Western Canal crossed Butte Creek at Nelson, Butte "
                        "County, replaced by the Gary N. Brown siphon in 1997. "
                        "NACC holds no Western Canal record."),
        ),
        dict(
            ar_id="CA-041", field="(determination)", value="",
            label="not found, strong lead: Western Canal siphon at Nelson",
            source=butte_src, method=butte_method,
            note="Western Canal Main Dam. " + butte_lead,
            sheet_note=("coordinate searched 2026-09-09, NOT found. Stood where "
                        "the Western Canal crossed Butte Creek at Nelson, Butte "
                        "County, replaced by the Gary N. Brown siphon in 1997. "
                        "NACC holds no Western Canal record."),
        ),
        dict(
            ar_id="CA-032", field="(determination)", value="",
            label="not found, located to Happy Isles but not to the structure",
            source=("USGS site 11264500 'MERCED R A HAPPY ISLES BRIDGE NR YOSEMITE "
                    "CA'; NPS Yosemite restoration material"),
            method="web research and USGS site service; recorded 2026-09-09",
            note=("Happy Isles Dam, 1987. American Rivers records NO river for this "
                  "row, but it is the Merced River in Yosemite Valley. **Happy "
                  "Isles itself is fixed: the USGS gauge at Happy Isles Bridge is "
                  "at 37.73130, -119.55902 (NAD83).** That is NOT written as the "
                  "dam's position, because the sources describe the removed "
                  "structure as the dam *above* Happy Isles, and the gauge is the "
                  "bridge. Using it would manufacture precision the evidence does "
                  "not support. NPS's Merced River Phase 2 restoration report does "
                  "not cover this structure. For context, the other Yosemite "
                  "removal, CA-054 Cascade Diversion Dam (2003), is already placed "
                  "at 37.71827. **Next thing to try: an NPS Yosemite cultural "
                  "resource or gauging-station history, which would fix the "
                  "structure rather than the reach.**"),
            sheet_note=("coordinate searched 2026-09-09, NOT found. Merced River in "
                        "Yosemite; the dam was ABOVE Happy Isles. The USGS gauge at "
                        "Happy Isles Bridge is 37.73130, -119.55902, deliberately "
                        "NOT used as the dam position."),
        ),
        dict(
            ar_id="OR-014", field="(determination)", value="",
            label="searched, not found",
            source=("NACC National Aquatic Barrier Inventory v4.3.0 Oregon file; "
                    "open web search"),
            method=common_method,
            note=("Dinner Creek Dam, removed 2003, 10 ft high and 35 ft long. NACC "
                  "holds exactly ONE Dinner Creek record, OR7073 in LANE County, "
                  "and it is not a match: sourced from the USFS Activity Database "
                  "2023, Removed=no, Passability 'No barrier', and its name "
                  "'Dinner Creek-0.0292262' is an auto-generated crossing "
                  "identifier rather than a dam name. Web search returned nothing "
                  "on a 2003 Dinner Creek removal. **Oregon has more than one "
                  "Dinner Creek**, so even the county is unestablished. NOT "
                  "PLACED. If revisited, start by establishing which Dinner Creek, "
                  "possibly via the ODFW fish passage database directly rather "
                  "than through NACC."),
            sheet_note=("coordinate searched 2026-09-09 and NOT found. The only "
                        "NACC Dinner Creek record is a Lane County USFS road "
                        "crossing, not this dam. Which Dinner Creek is unknown."),
        ),
        dict(
            ar_id="OR-016", field="(determination)", value="",
            label="searched, not found, 3 weak candidates",
            source=("NACC National Aquatic Barrier Inventory v4.3.0 Oregon file; "
                    "open web search"),
            method=common_method,
            note=("Unnamed Dam on Wagner Creek, Jackson County, removed 2003, 4 ft "
                  "high. NACC holds six Wagner Creek barriers. The only one flagged "
                  "removed is OR2668 Lower Wagner Diversion (2017), which is "
                  "already claimed by OR-055 Beeson-Robinson Diversion Dam and is a "
                  "different structure. Three UNNAMED candidates remain, all "
                  "flagged Removed=no: OR3391 (42.181545, -122.77864, 2 ft), "
                  "OR3392 (42.177696, -122.781136, 2 ft), OR3654 (42.188316, "
                  "-122.77883, no height). **Not written, for two reasons:** the "
                  "heights disagree (2 ft against AR's 4 ft) and there is no way "
                  "to choose among three. Worth knowing that NACC's Removed flag "
                  "was shown unreliable on 2026-09-09, so a stale 'no' on one of "
                  "these is possible. NOT PLACED."),
            sheet_note=("coordinate searched 2026-09-09 and NOT found. Three "
                        "unnamed NACC Wagner Creek candidates exist (OR3391, "
                        "OR3392, OR3654) but all read Removed=no and 2 ft against "
                        "this row's 4 ft, and there is no way to choose among "
                        "them."),
        ),
    ]


def nacc_era_limitation(df) -> list[dict]:
    """The pre-1990 unplaceable rows: a CLASS finding, not 19 separate failures.

    THE STRUCTURAL FACT. **NACC is a barrier inventory, not a removal registry.**
    Its `Removed` flags arrive from modern restoration tracking (CA PAD, ODFW and
    WDFW fish passage databases, USFS activity records), so removals before about
    1990 are absent almost by construction. Measured on the files in hand:

        state   removals with a year   median year   before 1990
        CA              373                2014           5
        OR              152                2017           1
        WA              116                2013           0

    **So a dam removed in 1949 is not merely hard to find in NACC, it is outside
    what that source can answer.** Recording this per row stops each one being
    re-searched in isolation as though it were an individual gap.

    WHAT THIS CLASS IS. Overwhelmingly the Klamath and Trinity mining-era dams,
    1925 to 1951, on the Trinity forks, the Salmon forks, the Scott, Canyon Creek,
    Hayfork Creek and Indian Creek. Small, private, seventy-five to a hundred years
    old, and undocumented online.

    HOW THIS SHOULD BE REPORTED. Not as 19 anonymous gaps but as a stated
    limitation with a reason: this project maps modern dam removal, and the
    mining-era removals in its source are inherited history that the modern
    inventories never recorded. **That is a finding about the data, not a failure
    of the search.**

    WHERE TO GO IF SOMEONE EVER WANTS THEM. Not NACC and not the open web, both
    tried. California Department of Fish and Game historical files, county
    records, or the USGS historical topographic map series, which would show a
    dam standing at the time of survey.
    """
    src = ("measured directly on WORKING/NACC/dams_{CA,OR,WA}/dams.csv, "
           "v4.3.0 downloaded 2026-09-08")
    method = ("compared the year distribution of NACC's removal records against "
              "the removal years of the unplaceable rows; recorded 2026-09-09")
    note = ("CLASS FINDING, applies to every unplaceable row removed before 1990. "
            "NACC is a barrier inventory whose removal flags come from modern "
            "restoration tracking, so its removals are overwhelmingly recent: "
            "median year 2014 (CA), 2017 (OR), 2013 (WA), with 5, 1 and 0 records "
            "respectively before 1990. A pre-1990 removal is therefore OUTSIDE "
            "what NACC can answer, not merely hard to find in it. Do not re-search "
            "these rows against NACC. Remaining routes, none tried: CDFG "
            "historical files, county records, or USGS historical topographic "
            "maps showing the dam standing at survey date.")
    sheet_note = ("pre-1990 removal: outside NACC's coverage by construction "
                  "(its removals are median-year 2013-2017, almost none before "
                  "1990). Not a search failure, a source limitation. Do not "
                  "re-search against NACC.")

    # pandas with dtype=str yields NaN for an empty cell, and `str(NaN)` is the
    # non-empty string "nan", which is truthy. Reading these columns naively made
    # every row look populated and this function silently returned nothing, with
    # no error. Hence an explicit null check rather than `or ""`.
    def val(r, col):
        v = r.get(col)
        return "" if v is None or pd.isna(v) else str(v).strip()

    rows = []
    for _, r in df.iterrows():
        if val(r, DUP_COL) or val(r, VOID_COL):
            continue
        if val(r, "Latitude") or val(r, "Latitude_DRP"):
            continue
        try:
            yr = int(float(val(r, "Year_Removed")))
        except ValueError:
            continue
        if yr >= 1990:
            continue
        rows.append(dict(ar_id=r["AR_ID"], field="(determination)", value="",
                         label=f"pre-1990 ({yr}), outside NACC coverage",
                         source=src, method=method, note=note,
                         sheet_note=sheet_note))
    return rows


# Rows worked on 2026-09-09 that NACC and the open web could not place. Each
# carries what was actually checked, so the next attempt starts further along.
_BATCH2 = [
    ("CA-034", "Wildcat Creek 1992",
     "NACC holds 11 Wildcat Creek records but only ONE flagged removed, "
     "CA98699 'Wildcat Creek Fish Ladder', removed 2023, 31 years off and a "
     "ladder rather than a dam. Note California has several Wildcat Creeks; the "
     "NACC one is in the Richmond/San Pablo area. Not placed."),
    ("CA-035", "Wildcat Creek 1992",
     "Same as CA-034: the only removed Wildcat Creek record in NACC is a 2023 "
     "fish ladder. These two rows are a pair (Unnamed Dam #1 and #2) and would "
     "need the same source. Not placed."),
    ("CA-037", "C-Lind Dam #1 1993, 56 ft",
     "AR records NO river for this row, so a river-first NACC search is "
     "impossible. **At 56 ft this is by far the largest unplaceable dam on the "
     "list** and should have left a trace, but a name search returns nothing. "
     "The name may be garbled in the source. Not placed. Next: try the name "
     "against the National Inventory of Dams, where a 56 ft dam would appear."),
    ("CA-048", "Ferrari Creek 2002",
     "NACC holds no record whose river contains 'Ferrari' anywhere in "
     "California. Not placed."),
    ("CA-050", "North Debris Dam 2002, LA River tributary",
     "A 20 ft debris dam on an unnamed tributary to the Los Angeles River. NACC "
     "has no matching removed record. Not placed. Next: Los Angeles County "
     "Public Works debris basin inventory, which is the agency that would own "
     "it, rather than a fish passage database."),
    ("OR-006", "Poorman Creek 1999",
     "NACC holds four candidates, NONE flagged removed: OR3422 and OR3820 on "
     "Poorman Creek near 42.66-42.68 N, -123.52, and OR874 and OR932 on "
     "'Poormans Creek' near 42.26-42.27 N, -123.02. **Two different creeks with "
     "near-identical names**, so even the drainage is unresolved. Not placed."),
    ("WA-002", "Headquarters Creek 2000",
     "NACC holds no record whose river contains 'Headquarters' in Washington. "
     "Not placed."),
    # WA-009 Satus Dam was here until 2026-09-10, when it was PLACED from the
    # Yakama Nation Fisheries project map; see wa009_coordinate(). The 09-09
    # determination stays in PROVENANCE.csv as history, which is what an
    # append-only ledger is for, but it is removed from this list because this
    # list is the set of rows still not placed.
    ("WA-012", "Skokomish River 2009",
     "NACC's only Skokomish records are the Cushman dams on the North Fork, all "
     "still standing. The Skokomish is heavily studied, so a 2009 removal should "
     "be documented somewhere, but AR gives no name, height or place to search "
     "on. Not placed."),
]


def searched_not_found_batch2() -> list[dict]:
    """Second sweep, 2026-09-09: rows checked against NACC and the open web.

    Recorded so the next attempt starts from what was eliminated rather than
    repeating it. **A negative with its reasoning attached is worth keeping**;
    a blank row is not.

    ONE SOURCE CHECKED AND DISQUALIFIED FOR EVERYTHING HERE. Wikipedia's "List of
    dam removals in California" reproduces the American Rivers database: same
    names, same heights, same years, same blanks. **It cannot corroborate a row
    that came from American Rivers in the first place.** Checking it feels like
    verification and is circular.
    """
    return [dict(ar_id=ar, field="(determination)", value="",
                 label=f"searched 2026-09-09, not found ({short})",
                 source=("NACC v4.3.0 state files; targeted web search; "
                         "Wikipedia's California list checked and rejected as "
                         "circular, being derived from American Rivers"),
                 method=("river-first NACC search via "
                         "build/find_missing_coords.py plus manual research; "
                         "recorded 2026-09-09"),
                 note=note,
                 sheet_note=f"searched 2026-09-09, NOT found. {note[:180]}")
            for ar, short, note in _BATCH2]


_NO_YEAR = [
    ("CA-001", "Big Creek Manufacturing Dam, Big Creek, 14 ft, no year",
     "**No removal year recorded**, which is the main obstacle: without one, a "
     "NACC candidate cannot be dated in or out, and the era test that resolved "
     "the mining-dam class cannot be applied. 'Big Creek' is also among the most "
     "common stream names in California, so the river alone does not locate it "
     "(a naive river search matched Big Tujunga Creek, 500 km away). Not placed."),
    ("CA-003", "Lone Jack Dam, Trinity River East Fork of North Fork, 24 ft, no year",
     "**No removal year recorded.** By river and name this belongs with the "
     "Klamath and Trinity mining-era block, all of which fall outside NACC's "
     "coverage, but without a year it cannot be formally placed in that class. "
     "NACC's only East Fork candidate is a 2016 USFS project, far too late. "
     "Treat as mining-era unless evidence says otherwise. Not placed."),
    ("CA-004", "Arco Pond Dam, 10 ft, no river, no year",
     "**Neither a river nor a year is recorded**, so there is nothing to search "
     "on but the name, and the name returns nothing. This is the least tractable "
     "row in the dataset. Not placed."),
    ("CA-036", "Point Four Dam, Butte Creek, 6 ft, 1993",
     "Part of the Butte Creek complex, see CA-040 and CA-041. NACC's Butte Creek "
     "removals are Durham Mutual (1998), McGowan (1998), McPherrin (1997) and a "
     "Colusa floodgate (2000): all differently named and four to five years off "
     "1993, and the two that match American Rivers rows are already claimed by "
     "CA-103 and CA-039. **NACC holds no record named 'Point Four' anywhere in "
     "California.** Not placed. Next: the same sources as the Western Canal dams."),
    ("WA-017", "Coffee Creek Dam, Coffee Creek, 10 ft, no year",
     "**No removal year recorded**, and NACC holds no Washington record whose "
     "river contains 'Coffee'. Not placed."),
    ("WA-020", "Stromer Lake Dam, tributary to the Columbia River, 5 ft, no year",
     "**No removal year recorded.** 'Tributary to Columbia River' is not a "
     "searchable river name; NACC has 60 records matching the word and none is a "
     "plausible match. A name search for 'Stromer Lake' returns nothing at all, "
     "which is unusual for a named lake and suggests the name may be garbled in "
     "the source. Not placed."),
    ("WA-021", "PEO Dam #48, tributary to Hanford Creek, 3 ft, no year",
     "**No removal year recorded**, and NACC holds no Washington record whose "
     "river contains 'Hanford'. The name 'PEO Dam #48' reads like an internal "
     "numbering scheme from some owner's inventory rather than a public name, "
     "which is a lead in itself: identifying who used that scheme would locate "
     "the whole series. Not placed."),
]


def no_year_rows() -> list[dict]:
    """The last unplaceable rows, six of which record no removal year.

    **The missing year is itself the obstacle**, and worth stating rather than
    leaving these as anonymous blanks. Without a year, a NACC candidate cannot be
    dated in or out, so even a plausible same-river record cannot be accepted or
    rejected; and the era test that resolved the mining-dam class cannot be
    applied to decide whether the row is even in scope for that source.

    These six sit alongside about 22 rows removed 1925-1951 that also carry
    little detail. **The pattern suggests an older American Rivers data lineage**
    with sparser fields, distinct from the modern restoration records that make up
    most of the database. That is a hypothesis, not an established fact.
    """
    return [dict(ar_id=ar, field="(determination)", value="",
                 label=f"not placed ({short.split(',')[0]})",
                 source="NACC v4.3.0 state files; targeted web search",
                 method=("river-first NACC search and name search; "
                         "recorded 2026-09-09"),
                 note=f"{short}. {note}",
                 sheet_note=f"searched 2026-09-09, NOT found. {note[:200]}")
            for ar, short, note in _NO_YEAR]


def wa023_coordinate() -> list[dict]:
    """WA-023 Sultan Mill Pond: American Rivers regressed its own coordinate.

    Names match, rivers match, NACC says `Removed = yes`, and the two points are
    **26.5 km apart**, by far the largest disagreement in the dataset. NACC's
    source for this record is American Rivers' own 02/24/2023 edition, so this is
    American Rivers disagreeing with its older self, not two agencies disagreeing.

    NACC's point is the correct one. NOAA's project record names the site "US
    2/Wagley's Creek Tributary (Sultan Mill Pond)", and US 2 runs east-west
    through Sultan at about 47.86 N. NACC's coordinate sits on that corridor
    about 1.2 km east of the town centre. The current American Rivers coordinate
    is 23 km north-northwest, up in the Sultan River basin, nowhere near US 2 or
    a mill pond.

    Research hazard recorded so it is not repeated: there are two "Mill Pond Dam"
    removals in Washington, and the Sullivan Creek one in Pend Oreille County
    dominates search results. It is a different dam.
    """
    src = ("NACC National Aquatic Barrier Inventory v4.3.0, SARPID WA10068, whose "
           "own source is American Rivers Dam Removal Database 02/24/2023; "
           "corroborated by NOAA NWFSC project record 'US 2/Wagley's Creek "
           "Tributary (Sultan Mill Pond)', "
           "https://www.webapps.nwfsc.noaa.gov/apex/f?p=409:19:::::P19_PROJECTID:39216831")
    method = ("the 2026 American Rivers coordinate disagrees with the 2023 "
              "American Rivers coordinate NACC ingested by 26.5 km; resolved in "
              "favour of the 2023 value because the NOAA project record places "
              "the site on the US 2 corridor at Sultan, which the 2023 value "
              "matches and the 2026 value misses by 23 km")
    note = ("AR 2026 gives 48.07256, -121.973 (Sultan River basin). NACC/AR 2023 "
            "gives 47.86408, -121.80055 (US 2 at Sultan). Largest AR-NACC "
            "disagreement in the dataset. NB two different WA dams are called "
            "Mill Pond Dam; the Sullivan Creek one is not this.")
    sheet_note = ("coordinate corrected to NACC/AR-2023 47.86408, -121.80055; the "
                  "2026 AR coordinate is 26.5 km off, in the Sultan River basin "
                  "rather than on US 2 at Sultan (NOAA project record)")
    return [dict(ar_id="WA-023", field=f, value=v, source=src, method=method,
                 note=note, sheet_note=sheet_note)
            for f, v in (("Latitude_DRP", "47.86408"),
                         ("Longitude_DRP", "-121.80055"))]


def wa009_coordinate() -> list[dict]:
    """WA-009 Satus Dam: placed 2026-09-10, superseding the 09-09 determination.

    Nathan found it by opening the "show project map" link on the Yakama Nation
    Fisheries project page and lining its dam symbol up against Google Maps. So
    this is a hand georeference of a published project map, not a published
    coordinate, and the precision is the precision of that eyeball. Recorded as
    such rather than dressed up.

    Four checks, in the order they were run.

    1. **It is on Satus Creek.** The point sits 22 to 133 m from Satus Creek
       water. See check 3 for why the naive distance looks like 314 m.
    2. **It is the right part of Satus Creek.** The rejected NACC record WA13891
       traces out 2.9 km UPSTREAM of this point on the same creek, so the two
       records are consistent rather than rival.
    3. **The channel it sits on is unnamed, and that is an artefact, not a
       problem.** The nearest channel (133 m) and the channel NHD labels "Satus
       Creek" (314 m) are both stream order 6 carrying the same accumulated
       drainage, 1193.5 vs 1195.2 sq km. One creek, two mapped channels through a
       split reach, with the GNIS name hung on one of them. NHDPlus flags the
       unnamed one `divergence = 2` and routes 212.9 cfs down the named line and
       0.007 down this one, which is a routing convention at a split, not a width
       measurement. An initial NLDI snap returned this channel as a headwater with
       nothing above it; that is the medium-resolution network representing the
       divergent channel as a disconnected stub, and it is wrong.
    4. **The upstream network supports the 90-mile claim.** Tracing
       upstream-with-tributaries from the point gives 570 miles of network above
       it. That is an upper bound on the network rather than a habitat figure, but
       it clears the claim, and critically it is the test the rejected NACC record
       FAILS: WA13891 has 14.9 upstream miles, which cannot produce 90 under any
       definition. This is the strongest single piece of evidence for the placement.

    Two source disagreements found while doing this, recorded but not acted on:
    YNF says the dam was 65 ft wide against AR's 125 ft length, and "about a
    two-foot drop" against AR's 3.5 ft height.

    NOT written: a coordinate snapped onto a channel centreline. The offset to the
    creek is 22 to 133 m depending on which channel line is measured to, and
    choosing one would be this project's choice rather than the evidence's. Same
    reasoning as CA-032 Happy Isles, where a known nearby fix was deliberately not
    written as the dam's position.
    """
    src = ("Yakama Nation Fisheries project page 'Satus Creek Irrigation Dam "
           "Removal', https://yakamafish-nsn.gov/restore/projects/"
           "satus-creek-irrigation-dam-removal , via its 'show project map' link; "
           "dam symbol georeferenced by eye against Google Maps imagery. "
           "Hydrography checks against NHDPlus HR "
           "(hydro.nationalmap.gov NHDPlus_HR MapServer layer 3) and USGS NLDI.")
    method = ("hand georeference of the sponsor's own published project map, then "
              "validated four ways: 22-133 m from Satus Creek water; the rejected "
              "NACC record WA13891 traces 2.9 km upstream of it on the same creek; "
              "the unnamed channel it sits on is stream order 6 with the same "
              "1193.5 sq km drainage as the channel NHD labels Satus Creek, so it "
              "is one creek mapped as two through a split reach; and 570 mi of "
              "upstream network supports AR's 90 reported river miles where "
              "WA13891's 14.9 mi cannot")
    note = ("Placed 2026-09-10, superseding the 2026-09-09 determination that this "
            "row was documented but unplaceable. PRECISION CAVEAT: this is a hand "
            "georeference of a project map, not a published coordinate; treat it as "
            "good to roughly 100 m, not better. The point lands ~30 m from an "
            "irrigation canal/ditch and 22-133 m from Satus Creek channel lines, "
            "which is the correct signature for a diversion dam (structure on the "
            "creek, canal taking off it). Deliberately NOT snapped to a channel "
            "centreline. Source disagreements noted: YNF says 65 ft wide and a "
            "~2 ft drop, AR says 125 ft long and 3.5 ft high.")
    sheet_note = ("PLACED at 46.277033, -120.249119 from the Yakama Nation Fisheries "
                  "project map, the 'show project map' link at "
                  "https://yakamafish-nsn.gov/restore/projects/"
                  "satus-creek-irrigation-dam-removal , georeferenced by eye, so good "
                  "to ~100 m and no better. Supersedes the 09-09 'not found' "
                  "determination. Validated: 22-133 m from Satus Creek water; the "
                  "rejected NACC record WA13891 is 2.9 km upstream on the same "
                  "creek; the unnamed channel here is order 6 with the same drainage "
                  "as the line NHD labels Satus Creek (one creek, split reach); and "
                  "570 mi of upstream network supports AR's 90 reported miles, which "
                  "WA13891's 14.9 mi could not.")
    return [dict(ar_id="WA-009", field=f, value=v, source=src, method=method,
                 note=note, sheet_note=sheet_note)
            for f, v in (("Latitude_DRP", "46.277033"),
                         ("Longitude_DRP", "-120.249119"))]


def ca133_coordinate() -> list[dict]:
    """CA-133 Lagunita Diversion Dam: the published coordinate is 1.47 km wrong.

    A CORRECTION, not a recovery: American Rivers publishes a coordinate here and
    this replaces it. Only the second such row, after WA-023.

    Found 2026-09-12 by following up the one dam left on the audit's "look before
    publishing" list. The row read as having no ESA critical habitat and no species
    present, which is a conspicuous result for a removal carried out expressly for
    steelhead passage.

    **The row contradicts itself.** `River` says San Francisquito Creek, and the
    published point sits **1.24 km from San Francisquito Creek**. Everything else
    in the row is right: 8 ft height, built 1900, removed 2018. Stanford's own
    account and the local press both describe an eight-foot concrete structure,
    119 years old, removed over five months from June 2018, with 480 feet of
    San Francisquito Creek restored, explicitly to benefit Central California
    Coast steelhead. Only the coordinate disagrees with the rest of the record.

    **What the published point probably is.** It lies beside Lake Lagunita, which
    is what the dam fed, through a flume the press reports as not operational
    since the 1930s. A coordinate on the thing the structure served rather than
    the structure.

    **NACC is NOT independent corroboration here, and that is worth remembering.**
    NACC record CA33454 sits 1.04 m from the published point, which looks like
    agreement until you read it: its `Source` is NID, its `Snapped` is false, and
    it calls the river "Unnamed Tributary To San Francisco Bay" with HUC8 Coyote.
    The odd river name and the basin are *consequences* of the same bad point, not
    separate evidence for it. **Two sources agreeing is one source counted twice
    when they share an upstream source.**

    **The placement.** The Almanac locates the dam "north of the east end of Happy
    Hollow Lane near Alpine Road and near the Stanford Weekend Acres neighborhood",
    unincorporated Menlo Park. Nathan placed the point on San Francisquito Creek
    there from imagery. It falls 146 m north and east of the geocoded 50 Happy
    Hollow Lane, which matches the description's bearing.

    **Validated against three independent agency layers**, none of which was used
    to choose the point: CDFW ds340 winter steelhead 21.0 m, NMFS Central
    California Coast steelhead critical habitat 18.6 m, USFWS Pacific lamprey
    17.4 m, all on San Francisquito Creek and all inside the 75 m join tolerance.

    PRECISION CAVEAT: this is a hand placement from imagery against a published
    prose description, not a surveyed or published coordinate. **Recorded at six
    decimal places but good to roughly 50 m, not better.** Nathan supplied it at
    14 decimal places, which is an artefact of a map click; the extra digits are
    dropped deliberately rather than carried as false precision.
    """
    src = ("Location description from The Almanac, 'Stanford removes dam, giving "
           "endangered fish room to roam', 2019-03-07, https://www.almanacnews.com/"
           "news/2019/03/07/stanford-removes-dam-giving-endangered-fish-room-to-roam/ "
           "('north of the east end of Happy Hollow Lane near Alpine Road and near "
           "the Stanford Weekend Acres neighborhood'); corroborated by Stanford "
           "Report, 'Stanford removes Lagunita Diversion Dam', 2019-02, "
           "https://news.stanford.edu/stories/2019/02/stanford-removes-lagunita-diversion-dam . "
           "Point placed on San Francisquito Creek from satellite imagery by Nathan.")
    method = ("the row's own River value and every non-coordinate field agree with the "
              "published accounts (8 ft, built 1900, removed 2018, San Francisquito "
              "Creek) while the published coordinate lies 1.24 km from that creek; "
              "replacement point placed from imagery at the described location, then "
              "validated against three layers not used to choose it: CDFW ds340 "
              "steelhead 21.0 m, NMFS CCC steelhead critical habitat 18.6 m, USFWS "
              "Pacific lamprey 17.4 m, all on San Francisquito Creek")
    note = ("CORRECTION of a published American Rivers coordinate, the second after "
            "WA-023. Old value 37.4234, -122.1742 sits 1,467 m from the new point and "
            "1.24 km from San Francisquito Creek, beside Lake Lagunita, which the dam "
            "fed via a flume not operational since the 1930s. NACC CA33454 agrees with "
            "the OLD point to 1.04 m but is not independent evidence: Source = NID, "
            "Snapped = false, and its river reads 'Unnamed Tributary To San Francisco "
            "Bay' with HUC8 Coyote, both consequences of the same bad point. PRECISION: "
            "hand placement from imagery against a prose location description, good to "
            "roughly 50 m; supplied at 14 decimal places and deliberately reduced to 6. "
            "Consequence for the join: CA-133 gains Central California Coast steelhead "
            "critical habitat plus steelhead and Pacific lamprey presence, having read "
            "as no ESA and no species, on a dam removed expressly for steelhead passage.")
    sheet_note = ("COORDINATE CORRECTED to 37.415217, -122.187261 on San Francisquito "
                  "Creek, near the east end of Happy Hollow Lane, Menlo Park. AR's "
                  "published 37.4234, -122.1742 is 1.24 km from the creek this row "
                  "names, beside Lake Lagunita, which the dam fed through a flume dead "
                  "since the 1930s. Every other field in the row matches the published "
                  "accounts of the 2018 removal (8 ft, built 1900, 480 ft of creek "
                  "restored for Central California Coast steelhead). New point "
                  "validated at 21.0 m from CDFW steelhead, 18.6 m from NMFS critical "
                  "habitat and 17.4 m from USFWS lamprey, all San Francisquito Creek. "
                  "NACC CA33454 matches the OLD point but inherits it from NID and is "
                  "not independent. Hand placement from imagery: good to ~50 m.")
    return [dict(ar_id="CA-133", field=f, value=v, source=src, method=method,
                 note=note, sheet_note=sheet_note)
            for f, v in (("Latitude_DRP", "37.415217"),
                         ("Longitude_DRP", "-122.187261"))]


def or066_river() -> list[dict]:
    """OR-066: American Rivers names the wrong creek, and the dam's own name says so.

    The row reads `River = "South Fork Little Butte"`, but South Fork Little Butte
    Creek and South Fork Big Butte Creek are different streams in the Rogue basin,
    about 15 km apart. Three independent things agree that this dam is on Big Butte
    and not on Little Butte:

    1. **The geometry.** The row's coordinate (42.53623, -122.54519) sits **5 m**
       from a stream line named "South Fork Big Butte Creek" in ODFW's own Fish
       Habitat Distribution data. Nothing named Little Butte is anywhere near it.
    2. **The dam's own name.** American Rivers calls it "South Fork Big Butte Dam"
       in the same row that calls the river Little Butte, so the file contradicts
       itself and only one half can be right.
    3. **The place.** The coordinate is beside Butte Falls, which is on Big Butte
       Creek. South Fork Little Butte Creek runs well to the south, past Lake Creek.

    Found during the 2026-09-12 audit of the join's same-stream rule, and it is a
    good illustration of why that rule needed tightening: OR-066 matched its coho
    habitat correctly, but only because the old rule stripped "little" and "big" as
    generic words and then matched on the single shared token "butte". A correct
    answer reached by a rule that cannot tell Big Butte from Little Butte is luck.
    Under the tightened rule (names must be equal) this row needs the corrected name
    or it loses a match that is right.

    NOT written: anything about the coordinate, which is fine and unchanged, or the
    dam's name, which is already right. Only the river name is wrong.
    """
    src = ("ODFW Fish Habitat Distribution 1167_5 stream names measured against the "
           "row's own coordinate (nearest line 'South Fork Big Butte Creek', 5 m); "
           "American Rivers' own Dam_Name field for this row ('South Fork Big Butte "
           "Dam'); and the coordinate's position beside Butte Falls, Oregon.")
    method = ("three-way agreement between the row's coordinate, the row's own dam "
              "name and the local toponymy, against a River value that matches none "
              "of them")
    note = ("American Rivers' River value 'South Fork Little Butte' is wrong; the dam "
            "is on South Fork Big Butte Creek. Name correction only: the coordinate "
            "is unchanged and is not in question. Consumed by the join's same-stream "
            "rule (build/join_dams_to_habitat.R), which after the 2026-09-12 "
            "tightening requires the two names to be equal rather than to share one "
            "token. Under the old rule this row matched anyway, because 'little' and "
            "'big' were both stripped as generic words.")
    sheet_note = ("River corrected to 'South Fork Big Butte Creek'. AR's own River "
                  "value reads 'South Fork Little Butte', but the row's coordinate is "
                  "5 m from ODFW's 'South Fork Big Butte Creek' line, the row's own "
                  "Dam_Name is 'South Fork Big Butte Dam', and the coordinate sits by "
                  "Butte Falls. South Fork Little Butte Creek is ~15 km south. Name "
                  "only; the coordinate is unchanged.")
    return [dict(ar_id="OR-066", field=RIVER_COL, value="South Fork Big Butte Creek",
                 source=src, method=method, note=note, sheet_note=sheet_note)]


# The three American Rivers rows whose NABI_ID resolves to a different structure.
# All three: NACC says the barrier was never removed, it sits on a DIFFERENT
# river, and it is hundreds of metres to over a kilometre away. A removal record
# cannot point at a barrier that is still standing on another creek.
_BAD_NABI = [
    ("OR-086", "OR2281", "Baker Creek Dam", "Baker Creek",
     "Wellspring Dam", "Unnamed Trib Heaton Creek", 1356.3),
    ("OR-095", "OR1269", "Whiskey Creek Hydro Dam", "Whiskey Creek",
     "Log Crib Mill Dam", "Parsons Creek", 1116.1),
    ("OR-087 to OR-088", "OR2409", "Krumwiede Diversion 1 & 2 Pushup Dams",
     "Salt Creek", "Long Branch Reservoir", "Long Branch Creek", 398.7),
]


def bad_nabi_ids() -> list[dict]:
    """Three AR rows whose documented NABI_ID cross-reference is simply wrong.

    Recorded as determinations, not as edits. Standing rule 2 says never edit a
    source column, so `NABI_ID` keeps its published value and this ledger entry
    is what tells a later reader not to trust it. American Rivers' own
    coordinates for these three rows are retained and are not in question.
    """
    out = []
    for ar_id, sarpid, ar_name, ar_river, nacc_name, nacc_river, dist in _BAD_NABI:
        out.append(dict(
            ar_id=ar_id, field="(determination)", value="",
            label=f"bad NABI_ID {sarpid}",
            source=("NACC National Aquatic Barrier Inventory v4.3.0 (downloaded "
                    f"2026-09-08), SARPID {sarpid}"),
            method=("NABI_ID key join checked against distance, river name and "
                    "the NACC removed flag; failed all three"),
            note=(f"AR NABI_ID {sarpid} resolves to {nacc_name!r} on "
                  f"{nacc_river!r}, {dist:.0f} m away and flagged Removed=no, "
                  f"whereas AR describes {ar_name!r} on {ar_river!r}. The "
                  "cross-reference is wrong. DO NOT use this NABI_ID to pull "
                  "NACC attributes for this row. AR's own coordinate stands."),
            sheet_note=(f"published NABI_ID {sarpid} is WRONG: it resolves to "
                        f"{nacc_name!r} on {nacc_river!r}, {dist:.0f} m away and "
                        "not removed. Do not use it to pull NACC attributes."),
        ))
    return out


# Six links where NACC says `Removed = no` but the link is plainly correct:
# same river, 1 to 27 m apart. Here the flag is the defect, not the link. The
# clearest case is CA-139, whose NACC name literally ends "(Removed)".
_REMOVED_FLAG_DEFECTS = [
    ("CA-138", "CA104146", "Rock And Mortar Dam With Spillway (Removed)", 1.1),
    ("CA-139", "CA104147", "Rock And Mortar Dam (Removed)", 1.3),
    ("CA-141", "CA104148", "Rock And Mortar Fill With Spillway (Removed)", 26.7),
    ("OR-027", "OR6562", "Fivemile Creek Irrigation Diversion Dam", 4.7),
    ("OR-094", "OR3821", "Squaw Creek Dam", 25.7),
    ("WA-010", "WA1614", "Water diversion", 24.6),
]


def nacc_removed_flag_defects() -> list[dict]:
    """Six links that are correct despite NACC saying the barrier was not removed.

    Recorded so that a later pass does not "discover" these as broken links and
    drop them. The discriminator that separates these from the three genuine bad
    cross-references above is **distance plus river agreement**, not the flag on
    its own: a wrong flag at 1 m is a wrong flag, a wrong flag at 1.4 km on a
    different creek is a wrong link.
    """
    out = []
    for ar_id, sarpid, nacc_name, dist in _REMOVED_FLAG_DEFECTS:
        extra = ""
        if "(Removed)" in nacc_name:
            extra = (" NACC's own name for this barrier ends '(Removed)', "
                     "contradicting its own flag.")
        if ar_id == "OR-094":
            extra = (" The name difference is a toponym change: Oregon renamed "
                     "its 'Squaw' place names, so Squaw Creek is now Takelma "
                     "Creek. Same structure, same creek, renamed.")
        out.append(dict(
            ar_id=ar_id, field="(determination)", value="",
            label=f"NACC Removed flag wrong, link OK ({dist:.0f} m)",
            source=("NACC National Aquatic Barrier Inventory v4.3.0 (downloaded "
                    f"2026-09-08), SARPID {sarpid}"),
            method=("NACC Removed=no was checked against distance and river "
                    "agreement; at this range on the same river the link is "
                    "sound and the flag is the error"),
            note=(f"NACC {sarpid} {nacc_name!r} is {dist:.1f} m from the AR point "
                  "on the same river but carries Removed=no. The link is CORRECT "
                  f"and must not be dropped.{extra}"),
            sheet_note=(f"NACC {sarpid} says Removed=no, but at {dist:.0f} m on "
                        "the same river the link is sound; the NACC flag is the "
                        f"error, not the link.{extra}"),
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually write. Without this it is a dry run.")
    args = ap.parse_args()

    df = pd.read_csv(SHEET, dtype=str)
    for col in (NOTES_COL, VOID_COL, DUP_COL, CLUSTER_COL, RIVER_COL):
        if col not in df.columns:
            df[col] = pd.NA
            print(f"added column {col}")
    by_id = {v: i for i, v in enumerate(df["AR_ID"])}

    values = (ghost_coordinates() + wa023_coordinate() + plainview_coordinate()
              + little_shasta_coordinate() + wa009_coordinate()
              + ca133_coordinate() + or066_river()
              + voided_coordinates() + duplicate_rows()
              + cluster_ids(df))
    dets = (determinations() + bad_nabi_ids() + nacc_removed_flag_defects()
            + searched_not_found()
            + searched_not_found_batch2() + nacc_era_limitation(df)
            + no_year_rows()
            + ca032_still_unplaced() + ca054_source_notes()
            + ca037_not_mapped())

    # A value write is guarded by the sheet itself: an occupied _DRP cell is never
    # overwritten. A determination writes no cell, so it has no such guard and a
    # re-run would append it to the ledger twice. Drop the ones already logged, so
    # that "safe to re-run" is true for both kinds of entry.
    if LEDGER.exists():
        with LEDGER.open(newline="") as fh:
            logged = {(r["ar_id"], r["note"]) for r in csv.DictReader(fh)}
        already = [d for d in dets if (d["ar_id"], d["note"]) in logged]
        dets = [d for d in dets if (d["ar_id"], d["note"]) not in logged]
        for d in already:
            print(f"   already logged, skipping: {d['ar_id']} "
                  f"{d.get('label', 'resolved negative')}")

    print(f"{'AR_ID':10} {'field':16} {'current':10} -> {'new':12} ")
    print("-" * 62)
    writes, skips = [], []
    for row in values:
        i = by_id.get(row["ar_id"])
        if i is None:
            skips.append((row, "AR_ID not in sheet"))
            continue
        cur = df.at[i, row["field"]]
        if pd.notna(cur) and str(cur).strip():
            # Never silently overwrite an existing _DRP value.
            skips.append((row, f"already holds {cur!r}"))
            continue
        writes.append((i, row))
        shown = row["value"] if len(row["value"]) <= 46 else row["value"][:43] + "..."
        print(f"{row['ar_id']:10} {row['field']:21} {'(blank)':8} -> {shown}")

    print("-" * 62)
    print(f"{len(writes)} values to write, {len(skips)} skipped")
    for row, why in skips:
        print(f"   skip {row['ar_id']} {row['field']}: {why}")
    print(f"{len(dets)} determinations to log (no value written)")
    for d in dets:
        print(f"   {d['ar_id']:18} {d.get('label', 'resolved negative')}")

    if not args.apply:
        print("\nDRY RUN. Nothing written. Re-run with --apply to commit.")
        return 0

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = SHEET.with_name(f"{SHEET.stem}.backup-{stamp}.csv")
    shutil.copy2(SHEET, backup)
    print(f"\nbacked up sheet to {backup.name}")

    def add_note(idx: int, text: str) -> None:
        stamped = f"{dt.date.today().isoformat()}: {text}"
        cur = df.at[idx, NOTES_COL]
        if pd.isna(cur) or not str(cur).strip():
            df.at[idx, NOTES_COL] = stamped
        elif text not in str(cur):        # do not duplicate on a re-run
            df.at[idx, NOTES_COL] = f"{cur} | {stamped}"

    for i, row in writes:
        df.at[i, row["field"]] = row["value"]
    for i, row in {w[0]: w[1] for w in writes}.items():
        add_note(i, row["sheet_note"])
    for d in dets:
        j = by_id.get(d["ar_id"])
        if j is not None:
            add_note(j, d["sheet_note"])
    df.to_csv(SHEET, index=False)
    print(f"wrote {len(writes)} values into {SHEET.name}")

    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    new_ledger = not LEDGER.exists()
    with LEDGER.open("a", newline="") as fh:
        # sheet_note lives in the sheet, not the ledger, so ignore the extra key
        w = csv.DictWriter(fh, fieldnames=LEDGER_COLS,
                           extrasaction="ignore")
        if new_ledger:
            w.writeheader()
        for _, row in writes:
            w.writerow({**row, "applied_utc": now,
                        "script": "build/apply_drp.py"})
        for d in dets:
            w.writerow({**d, "applied_utc": now,
                        "script": "build/apply_drp.py"})
    print(f"logged {len(writes) + len(dets)} rows to {LEDGER.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
