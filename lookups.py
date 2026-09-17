# lookups.py
# Lookup tables for the Flood & Erosion Modeling tool.
# Sources:
#   CN values  — USDA TR-55 Table 2-2 (Antecedent Runoff Condition II)
#   C factors  — USDA Agriculture Handbook 703
#   K default  — USDA RUSLE2 documentation (0.28 = loam midpoint)

# ---------------------------------------------------------------------------
# SCS Curve Number table
# Key: (nlcd_code, hydro_group)  where hydro_group is "A", "B", "C", or "D"
# Value: CN integer
# NLCD 2019 class codes:
#   11=Open Water, 21=Developed-Open, 22=Dev-Low, 23=Dev-Med, 24=Dev-High
#   31=Barren, 41=Deciduous Forest, 42=Evergreen Forest, 43=Mixed Forest
#   52=Shrub/Scrub, 71=Grassland/Herbaceous
#   81=Pasture/Hay, 82=Cultivated Crops
#   90=Woody Wetlands, 95=Emergent Wetlands
# ---------------------------------------------------------------------------
CN_TABLE = {
    # Open Water — treated as impervious (all runoff)
    (11, "A"): 98, (11, "B"): 98, (11, "C"): 98, (11, "D"): 98,

    # Developed — Open Space (lawns, parks, golf courses, cemeteries > 75% grass)
    (21, "A"): 39, (21, "B"): 61, (21, "C"): 74, (21, "D"): 80,

    # Developed — Low Intensity (~20-49% impervious)
    (22, "A"): 57, (22, "B"): 72, (22, "C"): 81, (22, "D"): 86,

    # Developed — Medium Intensity (~50-79% impervious)
    (23, "A"): 72, (23, "B"): 82, (23, "C"): 88, (23, "D"): 91,

    # Developed — High Intensity (~80-100% impervious)
    (24, "A"): 89, (24, "B"): 92, (24, "C"): 94, (24, "D"): 95,

    # Barren Land
    (31, "A"): 77, (31, "B"): 86, (31, "C"): 91, (31, "D"): 94,

    # Deciduous Forest (good condition)
    (41, "A"): 30, (41, "B"): 55, (41, "C"): 70, (41, "D"): 77,

    # Evergreen Forest (good condition)
    (42, "A"): 30, (42, "B"): 55, (42, "C"): 70, (42, "D"): 77,

    # Mixed Forest (good condition)
    (43, "A"): 30, (43, "B"): 55, (43, "C"): 70, (43, "D"): 77,

    # Shrub/Scrub
    (52, "A"): 35, (52, "B"): 56, (52, "C"): 70, (52, "D"): 77,

    # Grassland / Herbaceous (good condition pasture)
    (71, "A"): 39, (71, "B"): 61, (71, "C"): 74, (71, "D"): 80,

    # Pasture / Hay (good condition)
    (81, "A"): 39, (81, "B"): 61, (81, "C"): 74, (81, "D"): 80,

    # Cultivated Crops (row crops, straight rows, good condition)
    (82, "A"): 67, (82, "B"): 78, (82, "C"): 85, (82, "D"): 89,

    # Woody Wetlands — high retention
    (90, "A"): 30, (90, "B"): 48, (90, "C"): 65, (90, "D"): 73,

    # Emergent Wetlands
    (95, "A"): 30, (95, "B"): 48, (95, "C"): 65, (95, "D"): 73,
}

# Fallback CN when a cell's NLCD/hydro combo is not in the table
CN_DEFAULT = 75

# ---------------------------------------------------------------------------
# RUSLE C-factor (cover-management factor) by NLCD code
# Dimensionless; range ~0.001 (dense forest) to ~0.50 (bare cultivated)
# ---------------------------------------------------------------------------
C_FACTOR_TABLE = {
    11: 0.001,  # Open Water — essentially no erosion
    21: 0.010,  # Developed-Open (grass/parks)
    22: 0.005,  # Developed-Low (mix of impervious and lawn)
    23: 0.002,  # Developed-Med (mostly impervious)
    24: 0.001,  # Developed-High (nearly all impervious)
    31: 0.450,  # Barren — exposed soil, highest erodibility
    41: 0.003,  # Deciduous Forest
    42: 0.003,  # Evergreen Forest
    43: 0.003,  # Mixed Forest
    52: 0.030,  # Shrub/Scrub
    71: 0.015,  # Grassland
    81: 0.013,  # Pasture/Hay
    82: 0.350,  # Cultivated Crops (row crops, conventional till)
    90: 0.005,  # Woody Wetlands
    95: 0.010,  # Emergent Wetlands
}

# Fallback C when NLCD code is not in the table
C_FACTOR_DEFAULT = 0.10

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

# Integer codes back to letter (used in CN lookup)
HYDRO_INT_TO_LETTER = {1: "A", 2: "B", 3: "C", 4: "D"}
