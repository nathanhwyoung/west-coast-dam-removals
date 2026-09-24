#!/usr/bin/env python3
"""Cross-check our species presence against NACC's per-species habitat columns.

Written 2026-09-12, the last item of the phase 1 join audit (PHASE1_AUDIT.md).
NACC is an independent compilation, so it is the only outside opinion this project
has on which fish are at which dam. It is also the source that reports almost
nothing above Elwha and Condit, so it is being used as a check, not as an
authority (standing rule: NACC is presence/absence, never mileage).

WHAT NACC ACTUALLY MEASURES, and this is the whole subtlety. Its columns are
`<Species>HabitatUpstreamMiles` and `Free<Species>HabitatDownstreamMiles`: miles of
mapped habitat in the barrier's connected NETWORK, above and below it. Ours is
"mapped habitat within 75 m of the dam". Those are different questions, and NACC's
is far broader: a dam with coho 1,200 miles downstream scores as having coho.
So the comparison is split three ways rather than being called agreement or not:

    habitat upstream (up > 0)        comparable, a real disagreement if we say no
    habitat only downstream          NOT a disagreement, a different question
    up == -1                         NACC has no answer (identical to HasNetwork = no)

THREE STATES, NOT TWO. `-1` is exactly `HasNetwork = no` (verified: a clean
one-to-one across all 17,484 NACC records). Collapsing it into "absent" would
manufacture disagreements out of missing data.

CALIFORNIA CANNOT BE COMPARED. NACC's per-species habitat comes from StreamNet,
which does not cover California: 46 of 8,551 Californian dams carry any Chinook
habitat (0.5%), against 31% in Oregon and Washington. So the comparison runs on
OR and WA only, and California is reported separately as uninformative.

OUTPUT, WORKING/JOIN/audit/:
  nacc_crosscheck.csv    one row per dam and phase 1 species, both opinions
  nacc_crosscheck.txt    the readable summary
"""
import glob
import pathlib
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "WORKING/JOIN/audit"

# our phase 1 label -> NACC's column stem
SPECIES = {
    # phase 1
    "Chinook salmon": "ChinookSalmon",
    "Coho salmon": "CohoSalmon",
    "Steelhead": "Steelhead",
    "Pacific lamprey": "PacificLamprey",
    "Coastal cutthroat trout": "CoastalCutthroatTrout",
    # phase 2, added 2026-09-12: the ones NACC has a habitat column for. It has no
    # column for the suckers, sturgeon, eulachon, western river lamprey, mountain
    # whitefish or westslope cutthroat, so those cannot be cross-checked at all and
    # are simply absent here rather than reading as disagreements.
    "Chum salmon": "ChumSalmon",
    "Sockeye salmon": "SockeyeSalmon",
    "Pink salmon": "PinkSalmon",
    "Bull trout": "BullTrout",
    "Redband trout": "RedbandTrout",
}
STATE_NAME = {"CA": "California", "OR": "Oregon", "WA": "Washington"}


def load_nacc() -> pd.DataFrame:
    files = sorted(glob.glob(str(ROOT / "WORKING/NACC/dams_*/dams.csv")))
    if not files:
        sys.exit("no NACC dam files found under WORKING/NACC/")
    n = pd.concat([pd.read_csv(f, dtype=str, low_memory=False) for f in files],
                  ignore_index=True)
    return n.set_index("SARPID")


def classify(rec, stem):
    """NACC's opinion for one dam and one species, with `where` for the split."""
    up = pd.to_numeric(rec[f"{stem}HabitatUpstreamMiles"], errors="coerce")
    dn = pd.to_numeric(rec[f"Free{stem}HabitatDownstreamMiles"], errors="coerce")
    if up == -1:                      # identical to HasNetwork = no
        return "no network", None, up, dn
    if up > 0:
        return "present", "upstream", up, dn
    if dn > 0:
        return "present", "downstream only", up, dn
    return "absent", None, up, dn


def main() -> int:
    nacc = load_nacc()
    link = pd.read_csv(ROOT / "D3/build/ar_nacc_links.csv", dtype=str)
    dams = pd.read_csv(ROOT / "WORKING/JOIN/dam_habitat_join.csv", dtype=str)
    matches = pd.read_csv(ROOT / "WORKING/JOIN/dam_species_matches.csv", dtype=str)
    ours = {a: set(g) for a, g in
            matches[matches.kind == "presence"].groupby("AR_ID")["label"]}
    sarpid = dict(zip(link.AR_ID, link.nacc_SARPID))

    rows = []
    for _, d in dams.iterrows():
        sid = sarpid.get(d.AR_ID)
        rec = None
        if isinstance(sid, str) and sid in nacc.index:
            rec = nacc.loc[sid]
            if isinstance(rec, pd.DataFrame):      # duplicate SARPID, take the first
                rec = rec.iloc[0]
        for label, stem in SPECIES.items():
            if rec is None:
                verdict, where, up, dn = "unlinked", None, None, None
            else:
                verdict, where, up, dn = classify(rec, stem)
            rows.append(dict(
                AR_ID=d.AR_ID, dam=d.Dam_Name, state=d.State, species=label,
                nacc=verdict, nacc_where=where,
                ours="present" if label in ours.get(d.AR_ID, set()) else "absent",
                nacc_upstream_mi=up, nacc_downstream_mi=dn, nacc_sarpid=sid))
    c = pd.DataFrame(rows)

    # ---- the readable summary -------------------------------------------------
    L = []
    say = L.append
    say(f"NACC cross-check, {pd.Timestamp.today():%Y-%m-%d}")
    say(f"{len(c):,} dam/species pairs over {c.AR_ID.nunique()} mapped dams\n")

    say("Can NACC answer at all? (dam level)")
    avail = (c[c.species == "Steelhead"].groupby(["state", "nacc"]).size()
             .unstack(fill_value=0))
    say(avail.to_string() + "\n")

    say("NACC per-species coverage across ALL its dams, which is why CA is excluded:")
    allrec = pd.concat([pd.read_csv(f, dtype=str, low_memory=False)
                        for f in sorted(glob.glob(str(ROOT / "WORKING/NACC/dams_*/dams.csv")))],
                       ignore_index=True)
    cov = []
    for label, stem in SPECIES.items():
        r = {"species": label}
        for code, name in STATE_NAME.items():
            s = allrec[allrec.State == name]
            up = pd.to_numeric(s[f"{stem}HabitatUpstreamMiles"], errors="coerce")
            dn = pd.to_numeric(s[f"Free{stem}HabitatDownstreamMiles"], errors="coerce")
            r[code] = f"{int(((up > 0) | (dn > 0)).sum()):,}/{len(s):,}"
        cov.append(r)
    say(pd.DataFrame(cov).to_string(index=False) + "\n")

    comp = c[c.state.isin(["OR", "WA"]) & ~c.nacc.isin(["unlinked", "no network"])]
    say(f"COMPARABLE: {len(comp)} pairs over {comp.AR_ID.nunique()} Oregon and Washington dams")
    say(pd.crosstab(comp.nacc, comp.ours, margins=True).to_string())
    agree = int((comp.nacc == comp.ours).sum())
    say(f"raw agreement: {agree}/{len(comp)} = {agree / len(comp) * 100:.1f}%\n")

    nacc_only = comp[(comp.nacc == "present") & (comp.ours == "absent")]
    down = nacc_only[nacc_only.nacc_where == "downstream only"]
    upst = nacc_only[nacc_only.nacc_where == "upstream"]
    say("Where NACC says present and we say absent, split by WHERE its habitat is:")
    say(f"  only downstream : {len(down):3d}   a different question, not a disagreement "
        f"(median {down.nacc_downstream_mi.median():.1f} mi away, max {down.nacc_downstream_mi.max():.1f})")
    say(f"  upstream        : {len(upst):3d}   the real disagreements, over "
        f"{upst.AR_ID.nunique()} dams\n")
    if len(upst):
        say(upst.sort_values("nacc_upstream_mi", ascending=False)
            [["AR_ID", "dam", "species", "nacc_upstream_mi"]].to_string(index=False) + "\n")

    ours_only = comp[(comp.ours == "present") & (comp.nacc == "absent")]
    say(f"Where we say present and NACC maps no habitat at all: {len(ours_only)}")
    if len(ours_only):
        say(ours_only[["AR_ID", "dam", "state", "species"]].to_string(index=False))

    OUT.mkdir(parents=True, exist_ok=True)
    c.to_csv(OUT / "nacc_crosscheck.csv", index=False)
    (OUT / "nacc_crosscheck.txt").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\nwrote {OUT/'nacc_crosscheck.csv'} and .txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
