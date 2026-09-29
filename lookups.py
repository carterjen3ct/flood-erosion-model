# lookups.py
# Lookup tables and model constants for the Flood & Erosion Modeling tool.
# Sources:
#   CN values        — USDA TR-55 Table 2-2 (Antecedent Runoff Condition II)
#   C factors        — USDA Agriculture Handbook 703 (RUSLE)
#   K default        — USDA RUSLE2 documentation (0.28 = loam midpoint)
#   Storm pattern    — USDA TR-55 Appendix B, SCS Type II 24-hour distribution
#   Rain energy      — Brown & Foster (1987), as used in AH-703 (RUSLE)

# ---------------------------------------------------------------------------
# Assumed land cover
# The tool has no land use input, so one cover type is assumed for the whole
# study area: pasture / grassland in fair condition (a mid-range cover).
# ponytail: uniform cover ignores urban/forest differences; re-add a land use
# input if runoff must vary by cover type.
# ---------------------------------------------------------------------------

# SCS Curve Number by hydrologic soil group (TR-55 Table 2-2c, pasture, fair)
CN_BY_HYDRO_GROUP = {"A": 49, "B": 69, "C": 79, "D": 84}

# RUSLE C-factor for the assumed cover (pasture, Handbook 703)
C_FACTOR = 0.013

# ---------------------------------------------------------------------------
# RUSLE K-factor default, US customary units
# (ton·acre·hr / hundreds·acre·ft·tonf·in) — the units SSURGO kffact/kwfact use.
# Used when the user does not supply a K-factor field in their soil layer.
# 0.28 = representative loam (USDA midpoint for most agricultural soils)
# ---------------------------------------------------------------------------
K_DEFAULT = 0.28

# Converts K from US customary units to SI (t·ha·h / ha·MJ·mm)
K_US_TO_SI = 0.1317

# ---------------------------------------------------------------------------
# Hydrologic soil groups
# ---------------------------------------------------------------------------

# Mapping of SSURGO hydgrp text values to integer codes used in raster math.
# Dual groups (A/D etc.) use the undrained class (D): these soils have a high
# water table in their natural state, which is what a flood map should show.
HYDRO_GROUP_MAP = {
    "A": 1,
    "A/D": 4,
    "B": 2,
    "B/D": 4,
    "C": 3,
    "C/D": 4,
    "D": 4,
}

# Group used for blank/unrecognised values and for gaps in soil coverage.
# Blank hydgrp in SSURGO is mostly water, urban land and pits — all high runoff.
UNKNOWN_HYDRO_GROUP = "D"

# ---------------------------------------------------------------------------
# Flood model calibration knobs (all in meters)
# ---------------------------------------------------------------------------

# Sinks shallower than this are treated as DEM noise and filled before routing,
# so they don't trap runoff that should reach real depressions downstream.
# ~0.1 m suits 10–30 m DEMs; lower it (e.g. 0.03) for 1 m lidar DEMs.
MIN_SINK_DEPTH_M = 0.1

# Water shallower than this is left off the flood map (≈ 1 inch).
MIN_FLOOD_DEPTH_M = 0.03

# ---------------------------------------------------------------------------
# Erosion model constants
# ---------------------------------------------------------------------------

# RUSLE applies to sheet/rill erosion on hillslopes; slope lengths beyond
# ~300 m (≈1000 ft) are channels, so the flow length used in LS is capped here.
MAX_SLOPE_LENGTH_M = 300.0

# SCS Type II 24-hour rainfall distribution: (hour, cumulative fraction of P).
# Type II covers most of the US interior; swap in Type I/IA (Pacific) or
# Type III (Gulf/Atlantic coast) ordinates if the study area is there.
SCS_TYPE_II = [
    (0.0, 0.000), (2.0, 0.022), (4.0, 0.048), (6.0, 0.080), (7.0, 0.098),
    (8.0, 0.120), (8.5, 0.133), (9.0, 0.147), (9.5, 0.163), (9.75, 0.172),
    (10.0, 0.181), (10.5, 0.204), (11.0, 0.235), (11.5, 0.283), (11.75, 0.357),
    (12.0, 0.663), (12.5, 0.735), (13.0, 0.772), (13.5, 0.799), (14.0, 0.820),
    (16.0, 0.880), (20.0, 0.952), (24.0, 1.000),
]
