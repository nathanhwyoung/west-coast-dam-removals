#!/usr/bin/env Rscript
# Join removed dams to habitat: ESA critical habitat, and species presence.
#
# THE TOLERANCE, decided by Nathan 2026-09-11 (PROCESS.md stage 6, "DECIDED
# 2026-09-11: the join tolerance is 75 m"):
#   1. base 75 m;
#   2. same-stream extension to 500 m, only where the source carries a stream
#      name and that name matches the dam's river. "Tributary to X" does not
#      match X. NMFS and the USFWS layers carry no stream name, so they get the
#      base only;
#   3. PISCES HUC12 ranges match by containment, OR within the same 75 m base.
#      AMENDED 2026-09-12, DECIDED by Nathan, after the NACC cross-check found
#      Iron Gate Dam sitting 0.238 m outside the Upper Klamath-Trinity Chinook
#      range (PHASE1_AUDIT.md section 6). The original clause said "inside the
#      polygon or not", on the reasoning that the 75 m budget is built for
#      point-to-line error. Two of its three components are indeed line-specific
#      (stream mapping error, centre line against abutment), but the third,
#      COORDINATE ERROR (40 m at the 75th percentile, 116 m at the 90th), applies
#      to the dam point whatever it is tested against. That is what the carve-out
#      missed. It is also structural rather than bad luck: HUC12 boundaries are
#      drainage divides, a subwatershed's outlet is a point on the mainstem, and
#      that is exactly where dams get built, so a bare containment test is a coin
#      flip there and fails silently as an absent fish. Measured across all 157
#      mapped Californian dams and all seven ranges in use: one dam is affected,
#      and the next one outside a range is 27 km away, so any tolerance between
#      about 1 m and 400 m gives the same answer.
#
# The two fields are separate claims and never share a column (rule 17):
#   esa_critical_habitat   a designation overlaps this site
#   species_present        which migratory fish this removal concerns
# Every presence value carries its source, so ODFW, SWIFD, CDFW, USFWS and
# PISCES stay distinguishable (the reason species_present_source exists).
#
# INPUTS, all full resolution (rule 35). Nothing here reads a simplified
# display copy, and nothing writes to the working sheet: these outputs are
# generated wholesale on every run (rule 3).
#
# OUTPUTS, WORKING/JOIN/:
#   dam_habitat_join.csv     one row per mapped dam: the two fields, counts, and
#                            species_present_detail / species_present_grades, which pair
#                            each species with the BEST claim behind it (see below)
#   dam_species_matches.csv  one row per dam/species/layer match: distance, which
#                            rule matched it, the source, the matched stream
#   join_summary.txt         the console summary, kept for the record

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)

# Rules that more than one script needs, defined once: the tolerance constants BASE_M
# and EXT_M (rule 41 and the 2026-09-11 decision), the name normaliser (rule 40), the
# claim-grade vocabulary, the federal scope marker (39) and the SWIFD evidence rule (38).
# Three of those had already drifted between `make_presence_layers.R` and
# `audit_join_gaps.R`; see the header of `rules_shared.R`.
source(file.path(HERE, "rules_shared.R"))

CRS    <- 5070

NMFS <- P("_OLD/DOCS/DAM_DATA/NOAA/NMFS_WCR_ESA_Critical_Habitat_20230717.gdb/NMFS_WCR_ESA_Critical_Habitat_20230717.gdb")
SONCC <- P("WORKING/LAYERS/derived/soncc_coho_derived_fullres.gpkg")
PRES <- P("WORKING/LAYERS/presence/presence_fullres.gpkg")
SHEET <- P("WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv")
OUT <- P("WORKING/JOIN")

say <- function(...) cat(sprintf(...), "\n", sep = "")
fixgeom <- function(x) { st_geometry(x) <- "geometry"; x }

# The name comparison (`NOISE`, `trib_cut`, `toks`, `same_stream`) is rule 40 and now
# lives in `rules_shared.R`, with its full reasoning. `audit_join_gaps.R` needs the same
# helpers to say whether the same-stream extension would have rescued a match, which is
# why they are shared rather than defined here.

# ---- dams ------------------------------------------------------------------
sheet <- read.csv(SHEET, colClasses = "character", fileEncoding = "UTF-8-BOM")
has <- function(v) !is.na(v) & nzchar(trimws(v))
# River_DRP is a correction to American Rivers' own river name, used for the same-stream
# rule only (it never moves a dam). Added 2026-09-12 for OR-066, whose River reads "South
# Fork Little Butte" while the dam sits 5 m from South Fork Big Butte Creek. Tolerated as
# absent so the join still runs against an older copy of the sheet.
if (!"River_DRP" %in% names(sheet)) sheet$River_DRP <- ""
dams <- sheet |>
  filter(!has(Duplicate_Of_DRP), !has(Coordinate_Void_DRP)) |>
  mutate(lat = as.numeric(ifelse(has(Latitude_DRP), Latitude_DRP, Latitude)),
         lon = as.numeric(ifelse(has(Longitude_DRP), Longitude_DRP, Longitude)),
         River = ifelse(has(River_DRP), River_DRP, River)) |>
  filter(!is.na(lat), !is.na(lon)) |>
  st_as_sf(coords = c("lon", "lat"), crs = 4326) |> st_transform(CRS)
dam_tok <- toks(trib_cut(dams$River))
say("dams to join: %d mapped (of 332 distinct removals)", nrow(dams))

# ---- layers ----------------------------------------------------------------
say("reading layers")
nmfs <- st_read(NMFS, layer = "All_WCR_critical_habitat_line_20230717", quiet = TRUE) |>
  st_zm() |> st_transform(CRS) |> fixgeom() |>
  transmute(label = as.character(LISTENTITY), source_data = "NMFS West Coast critical habitat 20230717",
            stream_name = NA_character_, claim_grade = NA_character_, kind = "ESA")
usfws <- do.call(rbind, lapply(Sys.glob(P("WORKING/LAYERS/usfws_NEW/*/*.shp")), function(f) {
  x <- st_read(f, quiet = TRUE) |> st_zm() |> st_transform(CRS) |> fixgeom()
  nm <- if ("COMNAME" %in% names(x)) as.character(x$COMNAME) else basename(dirname(f))
  transmute(x, label = tools::toTitleCase(tolower(nm)),
            source_data = paste("USFWS critical habitat bundle 2026-08-31,", basename(f)),
            stream_name = NA_character_, claim_grade = NA_character_, kind = "ESA") }))
soncc <- st_read(SONCC, quiet = TRUE) |> st_transform(CRS) |> fixgeom() |>
  transmute(label = "Coho salmon (SONCC, derived)", source_data = paste0("derived SONCC layer; ", source_data),
            stream_name = stream_name, claim_grade = NA_character_, kind = "ESA")
pres_l <- st_read(PRES, layer = "presence_lines", quiet = TRUE) |> st_transform(CRS) |> fixgeom() |>
  transmute(label = species, source_data = source_data, stream_name = stream_name,
            claim_grade = claim_grade, kind = "presence")
pres_r <- st_read(PRES, layer = "presence_ranges", quiet = TRUE) |> st_transform(CRS) |> fixgeom() |>
  transmute(label = species, source_data = source_data, stream_name = stream_name,
            claim_grade = claim_grade, kind = "presence_range")
say("  ESA: %s NMFS + %s USFWS + %s SONCC | presence: %s lines + %s ranges",
    format(nrow(nmfs), big.mark = ","), format(nrow(usfws), big.mark = ","), format(nrow(soncc), big.mark = ","),
    format(nrow(pres_l), big.mark = ","), nrow(pres_r))

# ---- rule 45: the extension may not reach past the channel the dam sits on -
# DECIDED by Nathan 2026-09-13, from the same-stream sweep (`build/sweep_same_stream.R`,
# writeup `09-13_WORKING.md` section 9).
#
# Rule 40 tightened the name comparison so a SOURCE feature on "Anderson Creek" can no
# longer claim a dam recorded on "East Fork Anderson Creek". It does nothing about the
# mirror image: when the SHEET records the PARENT stream and the dam actually sits on a
# tributary, both names genuinely are "Hood River" and equality holds, so the extension
# reaches 490 m across a confluence and hands the dam the main stem's whole species list.
# Three dams had exactly that shape, each sitting within 27 m of a named channel it is
# NAMED AFTER: OR-052 Odell (Odell Creek 8.9 m, matched Hood River at 490 m), OR-026 Sodom
# (Sodom Ditch 26.6 m, Calapooia 211.7 m), OR-012 Maple Gulch (Maple Gulch 8.7 m, Evans
# Creek 226.4 m). At all three the extension was the SOLE source of every species listed.
#
# THE RULE: if a NAMED mapped channel lies within BASE_M of the dam and its name does not
# agree with the dam's river, the dam is on that channel, and the extension may not reach
# past it. The base tolerance still applies, so nothing at the dam's feet is lost.
#
# It is computed ONCE PER DAM from every layer carrying a stream name, not per layer,
# because "which channel is this dam on" is a fact about the dam's location, not about one
# species layer. Per layer it would miss OR-012's ESA row, since the SONCC layer holds only
# coho reaches and does not carry Maple Gulch at all.
#
# AMENDED 2026-09-13, DECIDED by Nathan: ANY mapped channel counts, NAMED OR NOT.
#
# The rule first shipped requiring the near channel to be named, on the reasoning that an
# unnamed feature is usually the same watercourse with a missing name attribute rather
# than a different stream. **The evidence did not support that.** At the three dams the
# limit spared, the near channel carries a SMALLER species set than the far one every
# time, which is not what a missing attribute on the same creek looks like; and NHD, asked
# independently, also leaves that channel nameless while putting the recorded river 250 to
# 372 m away (`build/name_channels_nhd.py`; `09-13_WORKING.md` section 10).
#
# Two reasons for dropping it. Keying on whether an agency wrote down a name makes the
# result depend on the completeness of a text column, which is the defect already recorded
# at OR-036 Shear, whose blank `River` cost it five species that its neighbour 20 m away
# kept. And it errs toward understating what a removal helped, the direction this project
# has chosen every other time (the mileage figure, the SONCC gap).
#
# Cost, measured before deciding: 4 species at 3 dams. Reversible per dam through
# `River_DRP` if imagery later shows the channel IS the recorded river.
#
# An unnamed channel needs no special case: it has no tokens, so `same_stream` returns
# FALSE for it, which now counts as disagreeing. `is_named()` in rules_shared.R is
# therefore no longer used here; it remains because the same-stream sweep reports with it.
named_ch <- rbind(transmute(soncc, stream_name), transmute(pres_l, stream_name))
near_ch <- st_is_within_distance(dams, named_ch, BASE_M)
blocked <- vapply(seq_along(near_ch), function(i) {
  k <- near_ch[[i]]
  if (!length(k)) return(FALSE)
  any(!same_stream(dam_tok[[i]], named_ch$stream_name[k]))
}, logical(1))
say("rule 45: %d of %d dams sit within %d m of a mapped channel that disagrees with their river",
    sum(blocked), length(blocked), BASE_M)

# ---- the join --------------------------------------------------------------
match_lines <- function(layer, tag) {
  cand <- st_is_within_distance(dams, layer, EXT_M)
  out <- list()
  for (i in seq_along(cand)) {
    k <- cand[[i]]
    if (!length(k)) next
    dist <- as.numeric(st_distance(dams[i, ], layer[k, ]))
    named <- !is.na(layer$stream_name[k]) & nzchar(layer$stream_name[k])
    agree <- rep(FALSE, length(k))
    if (any(named)) agree[named] <- same_stream(dam_tok[[i]], layer$stream_name[k][named])
    # `!blocked[i]` is rule 45: where the dam sits on a differently-named channel, only
    # the base tolerance applies and the extension is switched off for this dam entirely.
    keep <- dist <= BASE_M | (!blocked[i] & agree & dist <= EXT_M)
    if (!any(keep)) next
    df <- data.frame(AR_ID = dams$AR_ID[i], dam = dams$Dam_Name[i], state = dams$State[i],
                     river = dams$River[i], kind = tag, label = layer$label[k][keep],
                     distance_m = round(dist[keep]),
                     matched_rule = ifelse(dist[keep] <= BASE_M, "base 75 m", "same-stream <=500 m"),
                     matched_stream = layer$stream_name[k][keep], source_data = layer$source_data[k][keep],
                     claim_grade = layer$claim_grade[k][keep])
    # Keep the nearest row per label AND GRADE, not per label alone (changed 2026-09-12).
    # Two sources can both put a species at one dam on different evidence, and collapsing
    # to the nearest would silently discard the better-graded claim whenever it happens to
    # sit further away. This bounds the output at one row per species per grade.
    out[[length(out) + 1]] <- df |> group_by(label, claim_grade) |>
      slice_min(distance_m, n = 1, with_ties = FALSE) |> ungroup()
  }
  if (!length(out)) return(NULL)
  bind_rows(out)
}
match_ranges <- function(layer, tag) {
  # Containment, or within the base tolerance of the polygon edge (see rule 3 in
  # the header). A dam inside reads 0 m, so the two cases stay distinguishable in
  # `matched_rule` and a reader can see which dams leaned on the tolerance.
  cand <- st_is_within_distance(dams, layer, BASE_M)
  out <- list()
  for (i in seq_along(cand)) {
    k <- cand[[i]]
    if (!length(k)) next
    dist <- as.numeric(st_distance(dams[i, ], layer[k, ]))
    out[[length(out) + 1]] <- data.frame(
      AR_ID = dams$AR_ID[i], dam = dams$Dam_Name[i], state = dams$State[i], river = dams$River[i],
      kind = tag, label = layer$label[k], distance_m = round(dist),
      matched_rule = ifelse(dist == 0, "inside HUC12 range",
                            sprintf("HUC12 range within %d m", BASE_M)),
      matched_stream = layer$stream_name[k], source_data = layer$source_data[k],
      claim_grade = layer$claim_grade[k]) |>
      group_by(label, claim_grade) |> slice_min(distance_m, n = 1, with_ties = FALSE) |> ungroup()
  }
  if (!length(out)) return(NULL)
  bind_rows(out)
}

say("joining")
matches <- bind_rows(
  match_lines(rbind(nmfs, usfws), "ESA"),
  match_lines(soncc, "ESA"),
  match_lines(pres_l, "presence"),
  match_ranges(pres_r, "presence"))

# ---- per-dam table ---------------------------------------------------------
roll <- function(df) paste(sort(unique(df)), collapse = "; ")

# CLAIM GRADE, added 2026-09-12. `species_present_source` is a union of the sources at a
# dam across ALL its species, so it cannot say which source backs which fish, and an
# "inferred" or "proxy" value would have nowhere to attach. `species_present_detail`
# pairs each species with the BEST claim behind it and that claim's source.
#
# Best, not nearest. A containment match is always 0 m, so ranking by distance would let
# a whole-watershed range outrank a documented reach every time the two coexist. Three
# Californian Chinook dams already have that shape (CA-039, CA-044, CA-103).
#
# The vocabulary and its order are `CLAIM_GRADES` in `rules_shared.R` as of 2026-09-13.
# It used to be defined here as well, with a comment in each file saying it must match
# the other; kept as a local alias so the uses below read unchanged.
GRADE_ORDER <- CLAIM_GRADES
best_grade <- function(g) {
  g <- g[!is.na(g)]
  if (!length(g)) return(NA_character_)
  GRADE_ORDER[min(match(g, GRADE_ORDER), na.rm = TRUE)]
}

# One row per dam and species, carrying the best-graded claim and the source that made it.
per_species <- matches |> filter(kind == "presence") |> group_by(AR_ID, label) |>
  arrange(match(claim_grade, GRADE_ORDER), distance_m, .by_group = TRUE) |>
  summarise(grade = best_grade(claim_grade), src = first(source_data),
            n_sources = n_distinct(source_data), .groups = "drop") |>
  mutate(detail = sprintf("%s [%s] %s", label, ifelse(is.na(grade), "ungraded", grade), src))

per_dam <- matches |> group_by(AR_ID, kind) |>
  summarise(labels = roll(label), sources = roll(source_data), n = n_distinct(label), .groups = "drop")
detail <- per_species |> group_by(AR_ID) |>
  summarise(species_present_detail = paste(detail, collapse = " | "),
            species_present_grades = paste(sprintf("%s=%s", label,
                                           ifelse(is.na(grade), "ungraded", grade)), collapse = "; "),
            .groups = "drop")
out <- st_drop_geometry(dams)[, c("AR_ID", "Dam_Name", "State", "River", "Year_Removed")] |>
  left_join(per_dam |> filter(kind == "ESA") |> transmute(AR_ID, esa_critical_habitat = labels,
                                                          esa_source = sources, esa_n = n), by = "AR_ID") |>
  left_join(per_dam |> filter(kind == "presence") |> transmute(AR_ID, species_present = labels,
                                                               species_present_source = sources, species_n = n), by = "AR_ID") |>
  left_join(detail, by = "AR_ID")
out$esa_n[is.na(out$esa_n)] <- 0; out$species_n[is.na(out$species_n)] <- 0

dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
write.csv(out, file.path(OUT, "dam_habitat_join.csv"), row.names = FALSE)
write.csv(matches[order(matches$AR_ID, matches$kind, matches$label), ],
          file.path(OUT, "dam_species_matches.csv"), row.names = FALSE)

# ---- summary ---------------------------------------------------------------
txt <- capture.output({
  cat(sprintf("Join run %s | tolerance: base %d m, same-stream extension %d m, ranges by containment\n\n",
              format(Sys.Date()), BASE_M, EXT_M))
  cat(sprintf("dams mapped: %d\n  with ESA critical habitat: %d\n  with any species present: %d\n  with both: %d\n  with neither: %d\n\n",
      nrow(out), sum(out$esa_n > 0), sum(out$species_n > 0),
      sum(out$esa_n > 0 & out$species_n > 0), sum(out$esa_n == 0 & out$species_n == 0)))
  # COUNT DISTINCT DAMS, not match rows. Since 2026-09-12 a species can hold more than
  # one row at a dam, one per claim grade, so count(label) would count evidence rather
  # than dams and read high.
  cat("dams per species (presence):\n")
  print(as.data.frame(matches |> filter(kind == "presence") |> group_by(label) |>
    summarise(dams = n_distinct(AR_ID), .groups = "drop") |> arrange(desc(dams))), row.names = FALSE)
  cat("\ndams per listed entity (ESA), top 12:\n")
  print(as.data.frame(matches |> filter(kind == "ESA") |> group_by(label) |>
    summarise(dams = n_distinct(AR_ID), .groups = "drop") |> arrange(desc(dams)) |> head(12)), row.names = FALSE)
  cat("\nmatch ROWS by rule (a species may hold one row per claim grade):\n"); print(as.data.frame(matches |> count(kind, matched_rule, name = "matches")), row.names = FALSE)
  cat("\npresence claims by grade (best claim per dam and species):\n")
  print(as.data.frame(per_species |> count(grade, name = "dam_species_pairs") |>
                        arrange(match(grade, GRADE_ORDER))), row.names = FALSE)
  cat("\ntest cases:\n")
  for (id in c("OR-022", "OR-023", "OR-096", "CA-186", "CA-175", "WA-009", "WA-013", "WA-035")) {
    r <- out[out$AR_ID == id, ]
    if (!nrow(r)) next
    cat(sprintf("  %-7s %-30s ESA: %-48s | present: %s\n", r$AR_ID, substr(r$Dam_Name, 1, 30),
                substr(ifelse(is.na(r$esa_critical_habitat), "none", r$esa_critical_habitat), 1, 48),
                ifelse(is.na(r$species_present), "none", r$species_present)))
  }
})
writeLines(txt, file.path(OUT, "join_summary.txt"))
cat(paste(txt, collapse = "\n"), "\n")
say("\nwrote %s and %s (%s match rows)", "dam_habitat_join.csv", "dam_species_matches.csv",
    format(nrow(matches), big.mark = ","))
