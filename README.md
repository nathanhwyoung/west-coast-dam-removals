# West Coast dam removals

Every recorded dam removal in California, Oregon and Washington, drawn against ESA critical habitat
and mapped species presence for 27 native fish.

Static page. No basemap, no tile service, no API key, no analytics, no CDN: every file the page loads
is served alongside it, including D3. An Albers equal-area conic projection, drawn with D3 to a canvas.

## Sources

Dam records from the American Rivers Dam Removal Database (March 2026). Recovered coordinates from the
National Aquatic Barrier Inventory v4.3.0, compiled by SARP and NFHP. Critical habitat from NMFS and
USFWS. Species presence from ODFW, WDFW (SWIFD), CDFW, USFWS and PISCES (Santos et al. 2014, UC Davis
Center for Watershed Sciences, used under its noncommercial attribution share-alike terms). Elevation
from AWS Terrain Tiles; lakes and coastline from Natural Earth; state outlines from the US Census.

Full method notes and caveats are in the map's Info panel, under the About, Methods and Sources tabs.

## What's in this repo

The site itself is the files at the top level (`index.html`, `dams.geojson`, `habitat/`, `presence/`,
`natural/`, `info/`). Everything below is how it was built and checked.

### Build scripts

Python and R scripts in [`build/`](build/), listed in the order the pipeline runs. They expect this repo
to sit in a folder named `D3/` beside a `WORKING/` folder that holds the raw source downloads (about
4 GB, not published here; every source is listed in the Sources tab). The comments in each script
refer to project notes that aren't in the repo.

**Placing the dams**

- [`link_ar_to_nacc.py`](build/link_ar_to_nacc.py) links every American Rivers row to its record in the
  National Aquatic Barrier Inventory (NACC), in three tiers from most to least trustworthy. Writes
  [`ar_nacc_links.csv`](build/ar_nacc_links.csv), one row per dam with the tier it was linked by.
- [`match_ghosts_to_nacc.py`](build/match_ghosts_to_nacc.py) matches the rows American Rivers left
  without coordinates to NACC dams by name, then checks each candidate's river and removal year. Writes
  [`ghost_match_candidates.csv`](build/ghost_match_candidates.csv) for review by hand.
- [`find_missing_coords.py`](build/find_missing_coords.py) searches NACC by river first for the rows
  still unplaced, and ranks candidates by dam name, also for review by hand.
- [`apply_drp.py`](build/apply_drp.py) writes accepted coordinates and corrections into the working
  sheet's `_DRP` columns, never over the source columns, with a record of where each value came from.

**Critical habitat**

- [`make_species_layers.py`](build/make_species_layers.py) splits NMFS critical habitat into one layer
  per species.
- [`make_usfws_layers.py`](build/make_usfws_layers.py) builds one layer per USFWS fish species from the
  national critical habitat bundle.
- [`fetch_boundary_basins.py`](build/fetch_boundary_basins.py) delineates the basin above each of the
  eleven dams the SONCC coho regulation names as a boundary, using USGS StreamStats.
- [`make_soncc_layer.R`](build/make_soncc_layer.R) reconstructs SONCC coho critical habitat from the text
  of 50 CFR 226.210, one step per clause of the regulation. ([`make_soncc_layer.py`](build/make_soncc_layer.py)
  is the retired first version and only prints a pointer to the R script.)

**Species presence**

- [`fetch_presence_sources.py`](build/fetch_presence_sources.py) downloads a dated snapshot of each
  presence source.
- [`make_presence_layers.R`](build/make_presence_layers.R) filters every source by the five principles
  in the Methods tab, for all 21 species.

**The spatial join**

- [`rules_shared.R`](build/rules_shared.R) holds the rule values and helpers that more than one script
  uses, such as the 75 m tolerance, so the join and the audits can't drift apart.
- [`join_dams_to_habitat.R`](build/join_dams_to_habitat.R) matches every mapped dam to critical habitat
  and species presence, using the tolerance rules in the Methods tab.

**Checking the join**

- [`audit_join_gaps.R`](build/audit_join_gaps.R) explains every blank. For each dam and species with no
  match, it goes back to the raw, unfiltered source and reports which of four reasons applies.
- [`crosscheck_nacc.py`](build/crosscheck_nacc.py) compares this project's species results with NACC's
  own per-species habitat columns.
- [`name_channels_nhd.py`](build/name_channels_nhd.py) looks up the name the USGS National Hydrography
  Dataset gives the channel each checked dam sits on.
- [`sweep_same_stream.R`](build/sweep_same_stream.R) lists every match made through the same-stream
  extension, and what each one rests on.
- [`sweep_range_edges.R`](build/sweep_range_edges.R) measures how close each dam sits to the edge of
  each watershed range, to find results a small position error could flip.

**Building the site's files**

- [`make_sketch_data.py`](build/make_sketch_data.py) builds `dams.geojson` and `dams.js`, the dams with
  their coordinate sources, corrections and match results.
- [`make_habitat_display.py`](build/make_habitat_display.py) builds the simplified critical habitat
  files in `habitat/`.
- [`make_presence_display.py`](build/make_presence_display.py) builds the simplified presence files in
  `presence/`.
- [`make_base_outlines.py`](build/make_base_outlines.py) builds `base.js`, the state outlines everything
  is drawn against and clipped to.
- [`make_natural_features.py`](build/make_natural_features.py) builds the far-view shaded relief, lakes
  and labels in `natural/`.
- [`make_relief_hi.py`](build/make_relief_hi.py) builds the 115 m shaded relief tiles in
  `natural/relief_hi/`.
- [`copy_outputs.py`](build/copy_outputs.py) copies the published outputs below from `WORKING/` into
  `data/`. Run it after any rebuild.

### Results and audits

Outputs of the scripts above, copied into [`data/`](data/). The CSVs open as tables on GitHub.

**The join** ([`data/join/`](data/join/))

- [`dam_species_matches.csv`](data/join/dam_species_matches.csv) has one row per dam/species match: the
  distance, the rule that made the match, the stream it matched, the source, and the grade.
- [`dam_habitat_join.csv`](data/join/dam_habitat_join.csv) has one row per dam: its critical habitat and
  species present, with sources and grades. This is what the map's popups show.
- [`join_summary.txt`](data/join/join_summary.txt) is the run's summary counts.

**The audits** ([`data/audit/`](data/audit/)). Each CSV has a `.txt` report beside it that summarizes
the run, except the NHD lookup.

- [`join_gap_audit.csv`](data/audit/join_gap_audit.csv) gives the reason behind every blank, one row per
  dam and species ([report](data/audit/join_gap_audit.txt)).
- [`nacc_crosscheck.csv`](data/audit/nacc_crosscheck.csv) compares this project with NACC for each dam
  and species, including NACC's upstream and downstream habitat miles
  ([report](data/audit/nacc_crosscheck.txt)).
- [`nhd_channel_names.csv`](data/audit/nhd_channel_names.csv) is the NHD channel name at each checked
  dam, with dams whose answer was already known marked as controls.
- [`same_stream_sweep.csv`](data/audit/same_stream_sweep.csv) is every same-stream extension match and
  what supports it ([report](data/audit/same_stream_sweep.txt)).
- [`range_edge_sweep.csv`](data/audit/range_edge_sweep.csv) is each dam's distance to the edge of each
  watershed range, with the fragile ones flagged ([report](data/audit/range_edge_sweep.txt)).

**The SONCC coho reconstruction** ([`data/soncc/`](data/soncc/))

- [`soncc_coho_derived_fullres.gpkg`](data/soncc/soncc_coho_derived_fullres.gpkg) is the reconstructed
  critical habitat layer at full resolution. It's a reconstruction by this project, not an official
  NMFS layer.
- [`soncc_manifest.json`](data/soncc/soncc_manifest.json) records the inputs and versions it was built
  from.
- [`soncc_stage_accounting.csv`](data/soncc/soncc_stage_accounting.csv) gives the kilometers of stream
  left after each step, by state and watershed.
- [`soncc_boundary_dam_effect.csv`](data/soncc/soncc_boundary_dam_effect.csv) gives, for each boundary
  dam, the basin area above it and the kilometers of stream its basin removed.
- [`soncc_dam_checks.csv`](data/soncc/soncc_dam_checks.csv) compares each affected dam's distance to the
  layer before and after the rebuild.
- [`boundary_basins.geojson`](data/soncc/boundary_basins.geojson) holds the basins above the boundary
  dams, from USGS StreamStats, and [`boundary_basins_check.json`](data/soncc/boundary_basins_check.json)
  holds the checks run on them.

**Sources**

- [`presence_sources_manifest.json`](data/presence_sources_manifest.json) records every presence source
  download: what it is, where it came from and when.

### Licensing of the data files

The files in `data/` are derived from the public sources listed in the Sources tab, and each source's
terms still apply. PISCES watershed ranges are used under their noncommercial attribution
share-alike terms, so results that rest on PISCES carry those same terms.
