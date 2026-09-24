#!/usr/bin/env Rscript
# Species-present tier: filtered presence layers, ALL 21 SPECIES (phase 1 + phase 2).
#
# Applies the per-source filtering rules in PROCESS.md stage 6, "Species-present
# tier: filtering rules", to the sources snapshotted on 2026-09-11. Phase 1 was five
# species (Chinook, coho, steelhead, Pacific lamprey, coastal cutthroat); phase 2 added
# the other sixteen on 2026-09-12.
# Rules and principles were decided by Nathan species by species; this script
# only implements them. Change a rule there first, then here.
#
# THE FIVE PRINCIPLES (full text in PROCESS.md):
#   1. presence needs evidence, not a model
#   2. reintroduced populations of a native species count
#   3. fish trucked past a barrier count
#   4. finest grain available for each run
#   5. life history: exclude only what the source marks resident-only
# Plus: historical records are out, and each source is used only inside its own
# state (clipped to the TIGER state line, the same seam rule as the SONCC layer).
#
# OUTPUTS, WORKING/LAYERS/presence/:
#   presence_fullres.gpkg
#     presence_lines   every stream-level source (reaches kept individually)
#     presence_ranges  PISCES HUC12 expert ranges (a different claim; kept apart)
#   presence_counts.csv   features and km (or HUC12s) by species/state/source
# Every feature carries stream_name where the source has one (ODFW fhdStNm, SWIFD
# LLID_STRM_NAME, CDFW Stream_Name/GNIS_Name, USFWS Stream_Name, PISCES HU_12_NAME):
# needed for popups and for the same-stream check when validating the join tolerance.
#
# FULL RESOLUTION. Joins read this file (standing rule 35). No display copy yet:
# how presence is shown is deferred to the dashboard build (stage 9).
# No tolerance is used here; the dam join is a separate step (Track B).

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)

# Rules that more than one script needs, defined once: the SWIFD grade/qualifier
# construction (rule 38), the federal scope marker (39), the name normaliser (40), the
# tolerance constants (41) and the claim-grade vocabulary. Three of those had already
# drifted between this script and `audit_join_gaps.R`; see the header of
# `rules_shared.R` for what went wrong and why it now lives in one place.
source(file.path(HERE, "rules_shared.R"))

FHD    <- P("_OLD/DOCS/DAM_DATA/ODFW/ODFW_1167_5_FHD_Publication.gdb/FHD_Publication_Streams.gdb")
SWIFD  <- P("WORKING/WDFW/SWIFD_WDFWFishDistribution_2026-09-11/WDFWFishDistribution.gdb")
LAMNW  <- P("WORKING/USFWS_LAMPREY/usfws_lamprey_NW_distribution_2022_2026-09-11.geojson")
CDFW   <- function(ds) P(sprintf("WORKING/CDFW/%s_2026-09-11/%s.gdb", ds, ds))
PISCES <- function(f) P("WORKING/pisces_2.0.4_all_ranges_shp_and_png", f)
STATES <- c(P("WORKING/CENSUS/states_CA_OR_2026-09-11.geojson"),
            P("WORKING/CENSUS/states_WA_2026-09-11.geojson"))
OUT    <- P("WORKING/LAYERS/presence")

CRS <- 5070   # CONUS Albers, metres, for clipping and lengths; output is 4326

# The SWIFD evidence rule (`GRADES`, `QUALIFIERS`, `EVIDENCE_SQL`) is rule 38 and now
# lives in `rules_shared.R`, with its full reasoning.
say <- function(...) cat(sprintf(...), "\n", sep = "")

states <- do.call(rbind, lapply(STATES, function(f)
  st_read(f, quiet = TRUE) |> transmute(state = STUSAB))) |>
  st_transform(CRS) |> st_make_valid()

# Clip to one state. Features wholly inside are kept as they are; only the ones
# crossing the line are cut, which keeps this fast on 40,000-reach layers.
#
# `st = "US"` means a FEDERAL source, clipped to the whole three-state project extent
# instead of to one state. The seam rule was written for STATE AGENCY sources, where "its
# own state" is meaningful; a federal layer has no own state, and clipping the USFWS
# lamprey layer to Washington was discarding its 1,897 Oregon features (PHASE1_AUDIT.md
# section 5). DECIDED by Nathan 2026-09-12.
clip_state <- function(x, st, type) {
  poly <- if (identical(st, "US")) st_union(st_geometry(states))
          else st_geometry(states[states$state == st, ])
  inside <- lengths(st_within(x, poly)) > 0
  touch  <- lengths(st_intersects(x, poly)) > 0
  cut <- x[touch & !inside, ]
  if (nrow(cut)) cut <- suppressWarnings(st_collection_extract(st_intersection(cut, poly), type))
  rbind(x[inside, ], cut)
}

# CLAIM GRADE, added 2026-09-12. `claim_type` is prose that packs the source and the
# method into one string ("documented distribution (ODFW FHD)"), which is the same
# mistake as SWIFD's DISTTYPE_DESC: two facts in one field, standing rule 38. So the
# grade is its own column, a short controlled vocabulary, and `claim_type` stays as the
# readable long form.
#
# `CLAIM_GRADES` itself moved to `rules_shared.R` on 2026-09-13. It had been defined here
# AND as `GRADE_ORDER` in join_dams_to_habitat.R, each with a comment saying it must match
# the other: the same one-rule-two-files shape as 38, 39 and 41, caught before it bit.
#
# Every source ends up with the same columns. `grade` may be one value for the whole
# source, or one per feature where the source states it cleanly (SWIFD and NOAA ds981).
std <- function(x, species, state, source_data, claim, grain, run, detail, stream = NA_character_,
                grade = "observed") {
  x <- st_zm(x) |> st_transform(CRS)
  st_geometry(x) <- "geometry"
  stopifnot(all(grade %in% CLAIM_GRADES))
  x$species <- species; x$state <- state; x$source_data <- source_data
  x$claim_type <- claim; x$claim_grade <- grade; x$grain <- grain; x$run <- run
  x$source_detail <- detail
  x$stream_name <- stream
  x[, c("species", "state", "source_data", "claim_type", "claim_grade", "grain", "run",
        "stream_name", "source_detail")]
}
kv <- function(df, cols) do.call(paste, c(lapply(cols, function(k) paste0(k, "=", df[[k]])), sep = "; "))

read_q <- function(dsn, sql) st_read(dsn, query = sql, quiet = TRUE)

# ---- ODFW (Oregon) ---------------------------------------------------------
odfw <- function(layer, species, where, run_col = NULL, extra = character()) {
  x <- read_q(FHD, sprintf("SELECT * FROM %s WHERE %s", layer, where))
  cols <- intersect(c(run_col, "fhdUseTy", "fhdOrig", "fhdAccess", "fhdBasis", "fhdLifeHst", extra), names(x))
  run <- if (!is.null(run_col)) tools::toTitleCase(tolower(x[[run_col]])) else NA_character_
  # NOT graded per feature, though it could be: ODFW's `fhdBasis` ranges from
  # DocObsFish through DownstreamDocObsFish to ConcurProfOpinion and IndivProfOpinion,
  # which would split observed from presumed the way SWIFD's does. Deliberately left
  # coarse: that split is a rule decision and belongs to Nathan, not to this script.
  # It is recorded in `source_detail` on every feature, so it can be done later.
  std(x, species, "OR", sprintf("ODFW Fish Habitat Distribution 1167_5, %s", layer),
      "documented distribution (ODFW FHD)", "reach", run, kv(st_drop_geometry(x), cols), x$fhdStNm)
}
# ---- WDFW SWIFD (Washington) -----------------------------------------------
# `east_only` keeps features east of the Cascade crest, taken as 121 W. Used only for
# the redband inference (PROCESS principle 5, the Washington redband exception): SWIFD
# has no redband label, so east-side "Rainbow Trout" with a migratory life history is
# read as Columbia River redband. `grade` then records that it is our inference, not
# WDFW's statement.
east_of_cascades <- function(x) {
  if (!nrow(x)) return(x)
  # st_zm() first: SWIFD geometry is a MEASURED line string (XYM) and GEOS rejects
  # those, so the centroid has to be taken after the M dimension is dropped. std()
  # does this too, but runs later.
  g <- st_transform(st_zm(st_geometry(x)), 4326)
  lon <- suppressWarnings(st_coordinates(st_centroid(g)))[, 1]
  x[!is.na(lon) & lon > -121, ]
}

swifd <- function(sp_value, species, extra_where = "", grade_override = NULL,
                  east_only = FALSE) {
  x <- read_q(SWIFD, sprintf("SELECT * FROM SWIFD WHERE SPECIES = '%s' AND DISTTYPE_DESC IN %s %s",
                              sp_value, EVIDENCE_SQL, extra_where))
  if (east_only) x <- east_of_cascades(x)
  # SWIFD spells its "no run" value several ways, including "Unknow or not applicable".
  run <- ifelse(grepl("^Unknow", x$RUNTIME_DESC, ignore.case = TRUE), NA_character_, x$RUNTIME_DESC)
  # Rule 38 already splits SWIFD's grade from its qualifier, so the per-feature grade is
  # free here: "Artificial - Documented" and "Transported - Documented" are Documented.
  std(x, species, "WA", "WDFW SWIFD, file geodatabase of 2026-04-17",
      "documented or presumed distribution (WDFW SWIFD)", "reach", run,
      kv(st_drop_geometry(x), c("DISTTYPE_DESC", "USETYPE_DESC", "LIFEHIST_DESC")), x$LLID_STRM_NAME,
      grade = if (!is.null(grade_override)) grade_override
              else ifelse(grepl("Documented$", x$DISTTYPE_DESC), "observed", "presumed"))
}
# ---- PISCES (California ranges) --------------------------------------------
pisces <- function(file, species, run) {
  x <- st_read(PISCES(file), quiet = TRUE) |> distinct(HUC_12, .keep_all = TRUE)  # each HUC12 appears twice
  std(x, species, "CA", sprintf("PISCES 2.0.4 extant range, %s", sub("_extant_1.shp", "", file)),
      "expert range, HUC12 (PISCES, generated 2014)", "HUC12 range", run,
      paste0("HUC_12=", x$HUC_12), x$HU_12_NAME, grade = "range")
}

say("1. reading and filtering sources")
pieces <- list(
  # Chinook
  odfw("fhd_ChinookFall",   "Chinook salmon", "fhdUseTy <> 'Historical'", "fhdRun"),
  odfw("fhd_ChinookSpring", "Chinook salmon", "fhdUseTy <> 'Historical'", "fhdRun"),
  swifd("Chinook Salmon",   "Chinook salmon"),
  { x <- read_q(CDFW("ds981"), "SELECT * FROM ds981 WHERE PRESENCE IN ('Yes','Likely')")
    # PROCESS stage 6 already calls ds981's "Likely" an expert presumption, so grade it so.
    std(x, "Chinook salmon", "CA", "NOAA ds981 California Coastal Chinook distribution, 2005",
        "distribution (NOAA 2005)", "reach", "California Coastal",
        kv(st_drop_geometry(x), c("PRESENCE", "ESU")), NA_character_,
        grade = ifelse(x$PRESENCE == "Likely", "presumed", "observed")) },
  { x <- read_q(CDFW("ds982"), "SELECT * FROM ds982")
    std(x, "Chinook salmon", "CA", "NOAA ds982 Central Valley spring-run Chinook distribution, 2005",
        "distribution (NOAA 2005)", "reach", "Central Valley spring",
        paste0("HAB_UTIL=", x$HAB_UTIL), NA_character_) },
  pisces("Oncorhynchus_tshawytscha_SOT01_extant_1.shp", "Chinook salmon", "Upper Klamath-Trinity fall"),
  pisces("Oncorhynchus_tshawytscha_SOT02_extant_1.shp", "Chinook salmon", "Upper Klamath-Trinity spring"),
  pisces("Oncorhynchus_tshawytscha_SOT03_extant_1.shp", "Chinook salmon", "SONCC fall"),
  pisces("Oncorhynchus_tshawytscha_SOT05_extant_1.shp", "Chinook salmon", "Central Valley winter"),
  pisces("Oncorhynchus_tshawytscha_SOT07_extant_1.shp", "Chinook salmon", "Central Valley late fall"),
  pisces("Oncorhynchus_tshawytscha_SOT08_extant_1.shp", "Chinook salmon", "Central Valley fall"),
  # Coho
  odfw("fhd_Coho", "Coho salmon", "fhdUseTy <> 'Historical'"),
  swifd("Coho Salmon", "Coho salmon"),
  { x <- st_read(CDFW("ds326"), layer = "ds326", quiet = TRUE)
    std(x, "Coho salmon", "CA", "CDFW BIOS ds326 Coho Distribution, August 2025",
        "observed distribution (sightings since 1990 traced to the sea)", "reach", NA_character_,
        paste0("DFGWATERID=", x$DFGWATERID), x$Stream_Name) },
  # Steelhead
  odfw("fhd_SteelheadWinter", "Steelhead", "fhdUseTy <> 'Historical'", "fhdRun"),
  odfw("fhd_SteelheadSummer", "Steelhead", "fhdUseTy <> 'Historical'", "fhdRun"),
  swifd("Steelhead Trout", "Steelhead"),
  { x <- read_q(CDFW("ds340"), "SELECT * FROM ds340")
    std(x, "Steelhead", "CA", "CDFW BIOS ds340 Winter Steelhead Distribution, June 2012",
        "observed distribution (CDFW)", "reach", "Winter",
        paste0("Early_Yr=", x$Early_Yr, "; Late_Yr=", x$Late_Yr), x$GNIS_Name) },
  { x <- read_q(CDFW("ds341"), "SELECT * FROM ds341 WHERE Late_Yr >= 1990")
    std(x, "Steelhead", "CA", "CDFW BIOS ds341 Summer Steelhead Distribution, October 2009",
        "observed distribution (CDFW)", "reach", "Summer",
        paste0("Early_Yr=", x$Early_Yr, "; Late_Yr=", x$Late_Yr), x$GNIS_Name) },
  # Pacific lamprey
  odfw("fhd_Lamprey_Pacific", "Pacific lamprey", "fhdUseTy <> 'Historical'"),
  # Federal source, so scope "US": used across the whole project extent, not just WA.
  { x <- st_read(LAMNW, quiet = TRUE)
    x <- x[!(x$Use_Type %in% c("Historical", "Historic")) & !(x$Historical_Data %in% "Y") &
           !is.na(x$Basis) & x$Basis != "None", ]
    std(x, "Pacific lamprey", "US", "USFWS Pacific Lamprey Known Observations And Distribution 2022, layer 45",
        "known distribution with a recorded basis (USFWS 2022)", "reach", NA_character_,
        kv(st_drop_geometry(x), c("Basis", "Use_Type", "Origin", "Originator_Entity")), x$Stream_Name) },
  { x <- read_q(CDFW("ds2673"), "SELECT * FROM ds2673 WHERE DistType = 'Current'")
    std(x, "Pacific lamprey", "US", "USFWS ds2673 Pacific lamprey current distribution, 2021",
        "current distribution, 4th-order streams and up (USFWS 2021)", "reach", NA_character_,
        paste0("DistType=", x$DistType, "; HUC8Name=", x$HUC8Name), x$Name) },
  # Coastal cutthroat
  odfw("fhd_Cutthroat_Coastal", "Coastal cutthroat trout", "fhdUseTy <> 'Historical' AND fhdLifeHst <> 'Resident'"),
  swifd("Cutthroat Trout", "Coastal cutthroat trout", "AND LIFEHIST_DESC <> 'Resident'"),
  pisces("Oncorhynchus_clarki_clarki_SOC01_extant_1.shp", "Coastal cutthroat trout", NA_character_),

  # ================== PHASE 2: the other sixteen species ==================
  # Added 2026-09-12. The five principles are unchanged; see PHASE2.md for the plan
  # and PROCESS stage 6 for the per-species rules. Where a state has no source the
  # species simply has no entry for it, and the gap is NAMED rather than filled.
  #
  # FOUR NAMED WASHINGTON GAPS: western river lamprey (data-poor everywhere),
  # largescale and bridgelip suckers (WDFW's layers are modelled occupancy, regional
  # and undocumented, so they fail principle 1), and eulachon (DECIDED 2026-09-12: a
  # named gap rather than a proxy built from the species' own ESA critical habitat,
  # which would make presence a restatement of the designation and collapse the two
  # separate claims rule 17 exists to keep apart; eulachon is listed, so the ESA tier
  # already carries it at Washington dams).
  #
  # "Strays only" (Nathan, 2026-09-11) is why chum, sockeye and pink take no
  # California source and pink takes none in Oregon.

  odfw("fhd_Chum", "Chum salmon", "fhdUseTy <> 'Historical'"),
  swifd("Chum Salmon", "Chum salmon"),

  odfw("fhd_Sockeye", "Sockeye salmon", "fhdUseTy <> 'Historical'"),
  swifd("Sockeye Salmon", "Sockeye salmon"),

  swifd("Pink Salmon", "Pink salmon"),

  # PISCES spells river lamprey `ayersi`; the accepted name is Lampetra ayresii.
  odfw("fhd_Lamprey_WesternRiver", "Western river lamprey", "fhdUseTy <> 'Historical'"),
  pisces("Lampetra_ayersi_PLA01_extant_1.shp", "Western river lamprey", NA_character_),

  # Both green sturgeon DPS ranges, rolled up to the species with the DPS kept in `run`,
  # the same treatment the Chinook runs get.
  odfw("fhd_SturgeonGreen", "Green sturgeon", "fhdUseTy <> 'Historical'"),
  swifd("Green Sturgeon", "Green sturgeon"),
  pisces("Acipenser_medirostris_AAM01_extant_1.shp", "Green sturgeon", "Northern DPS"),
  pisces("Acipenser_medirostris_AAM02_extant_1.shp", "Green sturgeon", "Southern DPS"),

  odfw("fhd_SturgeonWhite", "White sturgeon", "fhdUseTy <> 'Historical'"),
  swifd("White Sturgeon", "White sturgeon"),
  pisces("Acipenser_transmontanus_AAT01_extant_1.shp", "White sturgeon", NA_character_),

  odfw("fhd_Eulachon", "Eulachon", "fhdUseTy <> 'Historical'"),
  pisces("Thaleichthys_pacificus_OTP01_extant_1.shp", "Eulachon", NA_character_),

  # Bull trout is extirpated in California (McCloud River, not seen since the mid-1970s).
  # Principle 5 is a no-op in Oregon here: the layer records no resident-only reaches.
  odfw("fhd_Bulltrout", "Bull trout", "fhdUseTy <> 'Historical' AND fhdLifeHst <> 'Resident'"),
  swifd("Bull Trout", "Bull trout", "AND LIFEHIST_DESC <> 'Resident'"),

  # The three Klamath suckers: Oregon and California only, not native to Washington.
  # PISCES files Lost River sucker under Catostomus luxatus, NOT the accepted Deltistes
  # luxatus, so searching the accepted name returns a false "no source" (same family as
  # the tridentata/tridentatus pair already recorded).
  odfw("fhd_Sucker_LostRiver", "Lost River sucker", "fhdUseTy <> 'Historical'"),
  pisces("Catostomus_luxatus_CCL01_extant_1.shp", "Lost River sucker", NA_character_),
  odfw("fhd_Sucker_Shortnose", "Shortnose sucker", "fhdUseTy <> 'Historical'"),
  pisces("Chasmistes_brevirostris_CCB01_extant_1.shp", "Shortnose sucker", NA_character_),
  odfw("fhd_Sucker_KlamathLargescale", "Klamath largescale sucker", "fhdUseTy <> 'Historical'"),
  pisces("Catostomus_snyderi_CCS01_extant_1.shp", "Klamath largescale sucker", NA_character_),

  # REDBAND. Washington is an INFERENCE and is graded as one: SWIFD carries no redband
  # label, so east-side Rainbow Trout with a named migratory life history is read as
  # Columbia River redband. Fluvial/adfluvial only, deliberately NOT principle 5's
  # "drop resident-only" (DECIDED by Nathan 2026-09-12; the exception is argued at
  # principle 5 in PROCESS, and rests on east-side rainbow being 91% life-history-recorded
  # against cutthroat's 15%). California's two named redbands are McCloud River and
  # Goose Lake; SOM09 is coastal rainbow and is NOT redband.
  odfw("fhd_Redband", "Redband trout", "fhdUseTy <> 'Historical' AND fhdLifeHst <> 'Resident'"),
  swifd("Rainbow Trout", "Redband trout", "AND LIFEHIST_DESC IN ('Fluvial', 'Adfluvial')",
        grade_override = "inferred", east_only = TRUE),
  pisces("Oncorhynchus_mykiss_stonei_SOM10_extant_1.shp", "Redband trout", "McCloud River"),
  pisces("Oncorhynchus_mykiss_subspecies_SOM11_extant_1.shp", "Redband trout", "Goose Lake"),

  # Westslope cutthroat is not native to California. Principle 5 is severe here, dropping
  # 71 of Oregon's 81 features, because the fish is mostly resident at its Oregon range
  # edge. That is the principle working as designed, not a defect.
  odfw("fhd_Cutthroat_Westslope", "Westslope cutthroat trout",
       "fhdUseTy <> 'Historical' AND fhdLifeHst <> 'Resident'"),
  swifd("Westslope Cutthroat Trout", "Westslope cutthroat trout", "AND LIFEHIST_DESC <> 'Resident'"),

  odfw("fhd_Sucker_Largescale", "Largescale sucker", "fhdUseTy <> 'Historical'"),
  odfw("fhd_Sucker_Bridgelip", "Bridgelip sucker", "fhdUseTy <> 'Historical'"),

  odfw("fhd_MountainWhitefish", "Mountain whitefish", "fhdUseTy <> 'Historical'"),
  swifd("Mountain Whitefish", "Mountain whitefish"),
  pisces("Prosopium_williamsoni_SPW01_extant_1.shp", "Mountain whitefish", NA_character_)
)

say("2. clipping each source to its own state")
pre <- sapply(pieces, nrow)
pieces <- lapply(pieces, function(x) {
  type <- if (x$grain[1] == "HUC12 range") "POLYGON" else "LINESTRING"
  clip_state(x, x$state[1], type)
})

lines  <- do.call(rbind, pieces[sapply(pieces, function(x) x$grain[1] == "reach")])
ranges <- do.call(rbind, pieces[sapply(pieces, function(x) x$grain[1] == "HUC12 range")])

counts <- do.call(rbind, lapply(seq_along(pieces), function(i) {
  x <- pieces[[i]]
  data.frame(species = x$species[1], state = x$state[1], source = x$source_data[1],
             grain = x$grain[1], run = paste(unique(na.omit(x$run)), collapse = "/"),
             features_before_clip = pre[i], features = nrow(x),
             km = if (x$grain[1] == "reach") round(sum(as.numeric(st_length(x))) / 1000, 1) else NA,
             huc12s = if (x$grain[1] == "HUC12 range") nrow(x) else NA)
}))
print(counts[, c("species", "state", "grain", "run", "features_before_clip", "features", "km")], row.names = FALSE)

say("3. writing")
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
gpkg <- file.path(OUT, "presence_fullres.gpkg")
if (file.exists(gpkg)) file.remove(gpkg)
st_write(st_transform(lines, 4326), gpkg, layer = "presence_lines", quiet = TRUE)
st_write(st_transform(ranges, 4326), gpkg, layer = "presence_ranges", quiet = TRUE, append = TRUE)
write.csv(counts, file.path(OUT, "presence_counts.csv"), row.names = FALSE)

by_sp <- counts |> group_by(species, state) |> summarise(features = sum(features), km = sum(km, na.rm = TRUE),
                                                          huc12s = sum(huc12s, na.rm = TRUE), .groups = "drop")
print(as.data.frame(by_sp), row.names = FALSE)
say("\nwrote %s: %s line features, %s range polygons", basename(gpkg),
    format(nrow(lines), big.mark = ","), nrow(ranges))
