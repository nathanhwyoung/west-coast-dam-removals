#!/usr/bin/env Rscript
# The same-stream sweep: what does each same-stream match actually rest on?
#
# Written 2026-09-13 for PHASE2_AUDIT.md section 2, "Same-stream, 42 rows to 59".
#
# WHY. The tolerance's second clause extends the base 75 m out to 500 m when the source's
# stream name matches the dam's river. It is the loosest part of the tolerance, and it was
# TIGHTENED on 2026-09-12 (standing rule 40) to require the normalised names to be EQUAL
# rather than to share a token, after four matches were found where a dam on a tributary
# inherited the main stem's species from a few hundred metres away. Seventeen new matches
# arrived under the tightened rule and none had been looked at.
#
# TWO HALVES, because a name check alone is not the audit.
#
#   1. WHAT THE NAME AGREEMENT RESTS ON. Rule 40 compares names after dropping generic
#      words, so two names can be "equal" while the raw strings differ. That is correct
#      for "Kelley Creek, tributary to Johnson Creek" against "Kelley Creek", and
#      NOT obviously correct if the generic word itself differs: the NOISE list holds
#      `creek`, `gulch`, `slough`, `pond`, `ditch` and `canal`, so "Bear Creek" and "Bear
#      Gulch" reduce to the same token and may be two different watercourses. This reports
#      the raw pair and the generic words dropped from each side.
#
#   2. WHETHER THE DAM'S OWN CHANNEL IS MAPPED AND CARRIES SOMETHING DIFFERENT. This is
#      the half a name check cannot do, and it is the phase 1 tell. A same-stream match
#      means the nearest PASSING feature of that species is further than 75 m, but the
#      join only keeps candidates that agree on the name, so a CLOSER feature on a
#      DIFFERENTLY named stream is discarded silently. If a dam's recorded river is "X",
#      its match is on X at 400 m, and there is a "Y" mapped 30 m away, then the dam is
#      probably on Y and the recorded river is wrong. That is exactly OR-066, whose
#      `River` read "South Fork Little Butte" while the dam sat 5 m from South Fork Big
#      Butte Creek.
#
# So for every dam holding a same-stream match this lists EVERY distinct stream name
# mapped within the extension distance, nearest first, marking which ones rule 40 accepts.
# A healthy row has the agreeing name nearest or close to it. A suspect row has a
# non-agreeing name much nearer.
#
# Reads the same built layers the join reads, so it cannot disagree with it. Writes
# nothing but its own report.
#
# USAGE
#   Rscript build/sweep_same_stream.R
#
# OUTPUT, WORKING/JOIN/audit/
#   same_stream_sweep.csv   one row per dam/stream-name within the extension distance
#   same_stream_sweep.txt   the readable version, grouped by dam

suppressMessages({library(sf); library(dplyr)})
sf_use_s2(FALSE)

args <- commandArgs(trailingOnly = FALSE)
HERE <- dirname(normalizePath(sub("^--file=", "", args[grep("^--file=", args)])))
ROOT <- normalizePath(file.path(HERE, "..", ".."))
P <- function(...) file.path(ROOT, ...)

# BASE_M, EXT_M and the name helpers (NOISE / trib_cut / toks / same_stream) all come
# from here, so this cannot disagree with the join about what "same stream" means
# (standing rule 44).
source(file.path(HERE, "rules_shared.R"))

CRS <- 5070

SHEET <- P("WORKING/American Rivers Dam Removal Database/_WORKING_WestCoast_CA_OR_WA.csv")
PRES  <- P("WORKING/LAYERS/presence/presence_fullres.gpkg")
SONCC <- P("WORKING/LAYERS/derived/soncc_coho_derived_fullres.gpkg")
JOIN  <- P("WORKING/JOIN")
OUT   <- file.path(JOIN, "audit")

say <- function(...) cat(sprintf(...), "\n", sep = "")

# ---- which dams ------------------------------------------------------------
matches <- read.csv(file.path(JOIN, "dam_species_matches.csv"), colClasses = "character")
ss <- matches |> filter(grepl("^same-stream", matched_rule))
say("same-stream matches: %d rows, %d dams, %d species",
    nrow(ss), n_distinct(ss$AR_ID), n_distinct(ss$label))

sheet <- read.csv(SHEET, colClasses = "character", fileEncoding = "UTF-8-BOM")
has <- function(v) !is.na(v) & nzchar(trimws(v))
if (!"River_DRP" %in% names(sheet)) sheet$River_DRP <- ""
dams <- sheet |>
  filter(!has(Duplicate_Of_DRP), !has(Coordinate_Void_DRP)) |>
  mutate(lat = as.numeric(ifelse(has(Latitude_DRP), Latitude_DRP, Latitude)),
         lon = as.numeric(ifelse(has(Longitude_DRP), Longitude_DRP, Longitude)),
         River = ifelse(has(River_DRP), River_DRP, River)) |>
  filter(!is.na(lat), !is.na(lon)) |>
  st_as_sf(coords = c("lon", "lat"), crs = 4326)
dams <- dams[dams$AR_ID %in% ss$AR_ID, ]
say("auditing %d dams", nrow(dams))

# ---- per dam, every stream name mapped nearby ------------------------------
# Read with a per-dam spatial filter rather than loading the whole 1.22 GB layer: the
# GeoPackage carries an RTree index, so 24 small windowed reads are far cheaper than one
# full read. The window is generous (about 1.1 km) and exact distances are computed after.
PAD <- 0.01
win <- function(pt) {
  xy <- st_coordinates(pt)[1, ]
  st_as_text(st_as_sfc(st_bbox(c(xmin = xy[[1]] - PAD, ymin = xy[[2]] - PAD,
                                 xmax = xy[[1]] + PAD, ymax = xy[[2]] + PAD), crs = 4326)))
}

rows <- list()
for (i in seq_len(nrow(dams))) {
  d  <- dams[i, ]
  id <- d$AR_ID
  w  <- win(d)
  # presence lines, plus the derived SONCC layer, which is the only ESA source carrying a
  # stream name and therefore the only one the extension can apply to.
  pl <- tryCatch(st_read(PRES, layer = "presence_lines", wkt_filter = w, quiet = TRUE),
                 error = function(e) NULL)
  sc <- tryCatch(st_read(SONCC, wkt_filter = w, quiet = TRUE), error = function(e) NULL)
  parts <- list()
  if (!is.null(pl) && nrow(pl))
    parts[[1]] <- transmute(pl, stream_name, label = species, kind = "presence")
  if (!is.null(sc) && nrow(sc))
    parts[[2]] <- transmute(sc, stream_name, label = "Coho salmon (SONCC, derived)", kind = "ESA")
  if (!length(parts)) { say("  %-9s nothing mapped nearby", id); next }
  x <- do.call(rbind, parts) |> st_transform(CRS)
  dp <- st_transform(d, CRS)

  dist <- as.numeric(st_distance(dp, x))
  keep <- !is.na(dist) & dist <= EXT_M
  if (!any(keep)) { say("  %-9s nothing within %d m", id, EXT_M); next }
  x <- x[keep, ]; dist <- dist[keep]

  nm <- ifelse(is.na(x$stream_name) | !nzchar(x$stream_name), "(unnamed)", x$stream_name)
  agree <- same_stream(toks(trib_cut(d$River))[[1]], nm)
  agree[nm == "(unnamed)"] <- FALSE

  # DOES THE DAM'S OWN NAME NAME ITS STREAM? This is the discriminator that caught OR-066,
  # whose `River` read "South Fork Little Butte" while the dam's own name said Big Butte.
  # Overlap, not equality, because a dam name carries extra words ("Maple Gulch DIVERSION
  # Dam"); `dam` and `gulch` are already in NOISE so they cannot create a false hit.
  dnm <- toks(trib_cut(d$Dam_Name))[[1]]
  rvt <- toks(trib_cut(d$River))[[1]]
  name_vs_river <- length(intersect(dnm, rvt)) > 0
  name_hits <- vapply(toks(trib_cut(nm)), function(v) length(intersect(dnm, v)) > 0, logical(1))

  # one row per distinct stream name: its nearest distance, and what it carries
  for (n in unique(nm)) {
    k <- which(nm == n)
    rows[[length(rows) + 1]] <- data.frame(
      AR_ID = id, dam = d$Dam_Name[1], state = d$State[1],
      lat = round(st_coordinates(d)[1, 2], 5), lon = round(st_coordinates(d)[1, 1], 5),
      river_recorded = d$River[1], stream_name = n,
      rule40_agrees = any(agree[k]), nearest_m = round(min(dist[k]), 1),
      dam_name_names_this_stream = any(name_hits[k]),
      dam_name_names_recorded_river = name_vs_river,
      species_here = paste(sort(unique(x$label[k])), collapse = "; "),
      stringsAsFactors = FALSE)
  }
  say("  %-9s %-30s %d distinct stream names within %d m", id, substr(d$Dam_Name[1], 1, 30),
      n_distinct(nm), EXT_M)
}

res <- bind_rows(rows) |> arrange(AR_ID, nearest_m)
dir.create(OUT, showWarnings = FALSE, recursive = TRUE)
write.csv(res, file.path(OUT, "same_stream_sweep.csv"), row.names = FALSE)

# ---- the verdict per dam ---------------------------------------------------
# SUSPECT when a stream rule 40 does NOT accept is mapped materially nearer than the one
# it does: the shape that says the dam is probably on the other channel.
ORDER <- c("STRONG SUSPECT: dam's own name names the nearer stream, not the recorded river",
           "SUSPECT: a non-agreeing stream is inside the base tolerance",
           "LOOK: a non-agreeing stream is much nearer",
           "no agreeing stream mapped (check)", "ok")
verdict <- res |> group_by(AR_ID, dam, state, lat, lon, river_recorded) |>
  summarise(agree_m = suppressWarnings(min(nearest_m[rule40_agrees])),
            other_m = suppressWarnings(min(nearest_m[!rule40_agrees])),
            other_nm = if (any(!rule40_agrees)) stream_name[!rule40_agrees][which.min(nearest_m[!rule40_agrees])] else NA_character_,
            # ANY near non-agreeing stream named by the dam, not just the single nearest.
            # Taking only the nearest missed OR-012, where three streams tie at 8.7 m and
            # `which.min` returned "(unnamed)" rather than "Maple Gulch", which is the
            # stream the dam is named after. A tie must not decide an audit verdict.
            other_named_by_dam = any(dam_name_names_this_stream & !rule40_agrees &
                                     nearest_m < BASE_M),
            named_by_dam_nm = if (any(dam_name_names_this_stream & !rule40_agrees &
                                      nearest_m < BASE_M))
              stream_name[dam_name_names_this_stream & !rule40_agrees &
                          nearest_m < BASE_M][1] else NA_character_,
            name_vs_river = first(dam_name_names_recorded_river),
            .groups = "drop") |>
  mutate(agree_m = ifelse(is.infinite(agree_m), NA, agree_m),
         other_m = ifelse(is.infinite(other_m), NA, other_m),
         # The escalation: a nearer non-agreeing stream is only weak evidence on its own,
         # because an unnamed side channel is often the same watercourse with a missing
         # name. It becomes strong when the DAM'S OWN NAME points at that other stream
         # while failing to point at the recorded river. That combination is what OR-066
         # looked like, and it is the one shape that rule 40 cannot catch: rule 40 stops
         # the SOURCE's name being a parent, and does nothing when the SHEET's name is.
         flag = case_when(
           is.na(agree_m) ~ ORDER[4],
           !is.na(other_m) & other_m < BASE_M & agree_m > BASE_M &
             other_named_by_dam & !name_vs_river ~ ORDER[1],
           !is.na(other_m) & other_m < BASE_M & agree_m > BASE_M ~ ORDER[2],
           !is.na(other_m) & other_m * 3 < agree_m ~ ORDER[3],
           TRUE ~ "ok")) |>
  arrange(match(flag, ORDER), AR_ID)

txt <- capture.output({
  cat(sprintf("Same-stream sweep, %s. Extension: %d m under name equality (rule 40).\n",
              format(Sys.Date()), EXT_M))
  cat(sprintf("Base tolerance %d m. %d matches over %d dams and %d species.\n\n",
              BASE_M, nrow(ss), n_distinct(ss$AR_ID), n_distinct(ss$label)))

  cat("VERDICT PER DAM. `agree` is the nearest stream rule 40 accepts; `other` is the\n")
  cat("nearest it does not. A non-agreeing stream much nearer means the dam may sit on\n")
  cat("that channel instead, which is what OR-066 looked like.\n\n")
  for (k in seq_len(nrow(verdict))) {
    v <- verdict[k, ]
    cat(sprintf("%-9s %-32s %s, %s\n", v$AR_ID, substr(v$dam, 1, 32), v$lat, v$lon))
    cat(sprintf("   river recorded : %s\n", v$river_recorded))
    cat(sprintf("   agreeing       : %s m\n", ifelse(is.na(v$agree_m), "none", v$agree_m)))
    cat(sprintf("   nearest other  : %s%s\n",
                ifelse(is.na(v$other_m), "none", paste0(v$other_m, " m")),
                ifelse(is.na(v$other_nm), "", paste0("  on ", v$other_nm))))
    cat(sprintf("   dam's own name : %s the recorded river; %s\n",
                ifelse(v$name_vs_river, "AGREES with", "does NOT agree with"),
                ifelse(v$other_named_by_dam,
                       paste0("NAMES a nearer non-agreeing stream: ", v$named_by_dam_nm),
                       "names no nearer stream")))
    cat(sprintf("   -> %s\n\n", v$flag))
  }
  cat("\nSUMMARY\n")
  for (f in unique(verdict$flag)) cat(sprintf("  %3d  %s\n", sum(verdict$flag == f), f))
})
writeLines(txt, file.path(OUT, "same_stream_sweep.txt"))
cat(paste(txt, collapse = "\n"), "\n")
say("wrote %s (%d rows)", file.path("WORKING/JOIN/audit", "same_stream_sweep.csv"), nrow(res))
