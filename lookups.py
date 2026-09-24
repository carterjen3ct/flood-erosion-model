# lookups.py
# Lookup tables for the Flood & Erosion Modeling tool.
# Sources:
#   CN values  — USDA TR-55 Table 2-2 (Antecedent Runoff Condition II)
#   C factors  — USDA Agriculture Handbook 703
#   K default  — USDA RUSLE2 documentation (0.28 = loam midpoint)

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
# RUSLE K-factor default (soil erodibility, tons·acre·hr / hundreds·acre·ft·tonf·in)
# Used when user does not supply a K-factor field in their soil layer.
# 0.28 = representative loam (USDA midpoint for most agricultural soils)
# ---------------------------------------------------------------------------
K_DEFAULT = 0.28

# Mapping of SSURGO hydgrp text values to integer codes used in raster math
HYDRO_GROUP_MAP = {
    "A": 1,
    "A/D": 1,   # dual hydrologic group — use the drained (better) class
    "B": 2,
    "B/D": 2,
    "C": 3,
    "C/D": 3,
    "D": 4,
}
