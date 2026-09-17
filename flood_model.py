# flood_model.py
# ArcGIS Script Tool — Flood Depth & Erosion Risk Modeling
# Runs inside ArcGIS Pro with Spatial Analyst extension.
# Requires: arcpy, arcpy.sa (Spatial Analyst)
#
# Parameters (in order, as defined in setup_toolbox.py):
#   0  study_area          GPFeatureLayer  — polygon mask
#   1  dem                 GPRasterLayer   — elevation raster
#   2  dem_units           GPString        — "Meters" or "Feet"
#   3  soil_layer          GPFeatureLayer  — polygon soil layer
#   4  hydro_group_field   Field           — A/B/C/D field in soil_layer
#   5  k_factor_field      Field           — optional K-factor field in soil_layer
#   6  land_use_layer      GPFeatureLayer  — land use polygon layer
#   7  land_use_field      Field           — land use class field in land_use_layer
#   8  classification      GPString        — "NLCD" or "Custom"
#   9  rainfall_depth      GPDouble        — storm event rainfall total
#   10 rainfall_units      GPString        — "Inches" or "Millimeters"
#   11 output_workspace    DEWorkspace     — output folder or GDB
#   12 out_flood_raster    DERasterDataset — output flood depth raster name
#   13 out_erosion_raster  DERasterDataset — output erosion risk raster name

import os
import math
import arcpy
from arcpy.sa import (
    Fill, FlowDirection, FlowAccumulation, Slope,
    Con, IsNull, Raster, RasterCalculator, Float,
    PolylineToRaster, PolygonToRaster, Sin, Cos,
    Lookup, ZonalStatisticsAsTable
)
import arcpy.management as mgmt
import lookups

# ---------------------------------------------------------------------------
# Helper: read script tool parameters
# ---------------------------------------------------------------------------
def get_params():
    """Pull all parameters from the running Script Tool context."""
    return {
        "study_area":        arcpy.GetParameterAsText(0),
        "dem":               arcpy.GetParameterAsText(1),
        "dem_units":         arcpy.GetParameterAsText(2),
        "soil_layer":        arcpy.GetParameterAsText(3),
        "hydro_group_field": arcpy.GetParameterAsText(4),
        "k_factor_field":    arcpy.GetParameterAsText(5),  # may be empty
        "land_use_layer":    arcpy.GetParameterAsText(6),
        "land_use_field":    arcpy.GetParameterAsText(7),
        "classification":    arcpy.GetParameterAsText(8),
        "rainfall_depth":    float(arcpy.GetParameterAsText(9)),
        "rainfall_units":    arcpy.GetParameterAsText(10),
        "output_workspace":  arcpy.GetParameterAsText(11),
        "out_flood_raster":  arcpy.GetParameterAsText(12),
        "out_erosion_raster": arcpy.GetParameterAsText(13),
    }

# ---------------------------------------------------------------------------
# Helper: log message to ArcGIS tool dialog
# ---------------------------------------------------------------------------
def log(msg):
    arcpy.AddMessage(msg)

# ---------------------------------------------------------------------------
# Helper: convert remap table to arcpy RemapValue for reclassify operations
# ---------------------------------------------------------------------------
def remap_value_list(mapping):
    """
    Build a flat [[old, new], ...] list from a dict for use with
    arcpy.sa.Reclassify or manual Con chains.
    """
    return [[k, v] for k, v in mapping.items()]

# ---------------------------------------------------------------------------
# Step 1: Rasterize soil hydrologic group → integer raster (A=1,B=2,C=3,D=4)
# ---------------------------------------------------------------------------
def build_hydro_group_raster(soil_layer, hydro_field, snap_raster, cell_size, mask):
    """
    Converts SSURGO-style hydrologic group text field (A/B/C/D) to integer raster.
    Returns a temporary in-memory raster path.
    """
    log("  Building hydrologic group raster...")

    # Add a temporary numeric field to the soil layer copy
    tmp_soil = "in_memory\\soil_tmp"
    mgmt.CopyFeatures(soil_layer, tmp_soil)
    mgmt.AddField(tmp_soil, "HYDGRP_INT", "SHORT")

    # Populate the integer field using the hydro group mapping
    with arcpy.da.UpdateCursor(tmp_soil, [hydro_field, "HYDGRP_INT"]) as cur:
        for row in cur:
            val = str(row[0]).strip().upper() if row[0] else ""
            row[1] = lookups.HYDRO_GROUP_MAP.get(val, 2)  # default B if unknown
            cur.updateRow(row)

    # Rasterize to a temp raster
    out_path = "in_memory\\hydro_group_rast"
    mgmt.PolygonToRaster(
        tmp_soil, "HYDGRP_INT", out_path,
        cellsize=cell_size
    )
    arcpy.env.snapRaster = snap_raster
    return Raster(out_path)

# ---------------------------------------------------------------------------
# Step 2: Build CN raster from land use + hydrologic group
# ---------------------------------------------------------------------------
def build_cn_raster(land_use_layer, land_use_field, classification,
                    hydro_group_raster, cell_size, snap_raster):
    """
    Builds a Curve Number raster by combining land use and soil hydro group.
    For NLCD: looks up (nlcd_code, hydro_group) in CN_TABLE.
    For Custom: expects land_use_field to already contain CN values.
    Returns a raster where each cell = its CN value.
    """
    log("  Building Curve Number raster...")

    if classification == "Custom":
        # User's land use field contains CN values directly
        lu_rast_path = "in_memory\\lu_cn_rast"
        mgmt.PolygonToRaster(
            land_use_layer, land_use_field, lu_rast_path, cellsize=cell_size
        )
        return Raster(lu_rast_path)

    # NLCD path: rasterize land use codes, then combine with hydro group per CN_TABLE
    log("    Rasterizing NLCD land use codes...")
    lu_rast_path = "in_memory\\lu_code_rast"
    mgmt.PolygonToRaster(
        land_use_layer, land_use_field, lu_rast_path, cellsize=cell_size
    )
    lu_raster = Raster(lu_rast_path)

    # Build CN lookup via Con chains for each NLCD code × hydro group combination.
    # We compute CN as a two-step raster:
    #   1. For each hydro group value (1-4), build a CN raster for that group
    #   2. Combine using Con(hydro_group_raster == X, cn_for_group_X, ...)
    log("    Mapping CN values from lookup table...")

    nlcd_codes = sorted(set(k[0] for k in lookups.CN_TABLE.keys()))

    # For each hydro group, build a land-use-to-CN raster
    group_cn_rasters = {}
    for grp_int, grp_letter in lookups.HYDRO_INT_TO_LETTER.items():
        # Build a Con chain mapping each NLCD code to its CN for this group
        cn_raster = None
        for code in nlcd_codes:
            cn_val = lookups.CN_TABLE.get((code, grp_letter), lookups.CN_DEFAULT)
            cell_cn = Con(lu_raster == code, cn_val, 0)
            cn_raster = cell_cn if cn_raster is None else cn_raster + cell_cn

        # Where no NLCD code matched, use default
        cn_raster = Con(cn_raster == 0, lookups.CN_DEFAULT, cn_raster)
        group_cn_rasters[grp_int] = cn_raster

    # Combine all four group CN rasters using the hydro group raster as selector
    cn_final = Con(
        hydro_group_raster == 1, group_cn_rasters[1],
        Con(hydro_group_raster == 2, group_cn_rasters[2],
            Con(hydro_group_raster == 3, group_cn_rasters[3],
                group_cn_rasters[4]
            )
        )
    )
    return cn_final

# ---------------------------------------------------------------------------
# Step 3: SCS-CN runoff depth (Q) in inches
# ---------------------------------------------------------------------------
def compute_runoff(cn_raster, rainfall_inches):
    """
    SCS Curve Number runoff equation (TR-55).
    Returns Q raster in inches. Cells where P <= Ia get Q=0.
    """
    log("  Computing SCS-CN runoff depth...")

    # S = potential maximum retention (inches)
    s_raster = Float(1000) / Float(cn_raster) - Float(10)

    # Initial abstraction Ia = 0.2 * S
    ia_raster = Float(0.2) * s_raster

    p = float(rainfall_inches)

    # Q = (P - Ia)^2 / (P - Ia + S) where P > Ia, else 0
    p_minus_ia = Float(p) - ia_raster
    q_raster = Con(
        p_minus_ia > 0,
        (p_minus_ia * p_minus_ia) / (p_minus_ia + s_raster),
        0.0
    )
    return q_raster

# ---------------------------------------------------------------------------
# Step 4: Flow routing and flood depth
# ---------------------------------------------------------------------------
def compute_flood_depth(filled_dem, q_raster, cell_size_m, dem_units):
    """
    Routes runoff using flow accumulation and computes a steady-state flood depth.
    Returns depth raster in the same units as the input DEM.

    ponytail: steady-state accumulation proxy — no Manning's n, no channel geometry.
    Upgrade path: HEC-RAS 2D or ArcGIS Pro Flood Simulation for dynamic routing.
    """
    log("  Computing flow direction and accumulation...")
    flow_dir = FlowDirection(filled_dem)
    flow_acc = FlowAccumulation(flow_dir)

    log("  Computing flood depth raster...")

    # Convert Q from inches to meters
    q_m = q_raster * 0.0254

    # Flood depth (m) = accumulated runoff depth across upstream cells
    # = flow_acc (upstream cell count) * Q_per_cell (m)
    flood_depth_m = Float(flow_acc) * q_m

    # Apply minimum flow accumulation threshold to suppress noise on hilltops
    # ponytail: 100-cell threshold works for most 30m DEMs; expose as param if needed
    min_acc = 100
    flood_depth_m = Con(flow_acc >= min_acc, flood_depth_m, 0.0)

    # Convert back to user's DEM units
    if dem_units == "Feet":
        flood_depth_out = flood_depth_m * 3.28084
    else:
        flood_depth_out = flood_depth_m

    return flood_depth_out, flow_dir, flow_acc

# ---------------------------------------------------------------------------
# Step 5: RUSLE erosion risk (A, tons/acre/event proxy)
# ---------------------------------------------------------------------------
def compute_rusle(
    filled_dem, slope_deg_raster, flow_acc,
    soil_layer, k_factor_field, cell_size_m,
    land_use_layer, land_use_field, classification,
    rainfall_mm
):
    """
    Computes RUSLE A = R * K * LS * C * P.
    Returns erosion risk raster in tons/acre/event (relative risk index).
    """
    log("  Computing RUSLE erosion risk...")

    # --- R factor: rainfall erosivity (simplified from event depth) ---
    # Using simplified Wischmeier & Smith approximation for a single storm event
    r_factor = float(0.04 * rainfall_mm * 1.15)
    log(f"    R factor = {r_factor:.3f}")

    # --- K factor: soil erodibility ---
    if k_factor_field and k_factor_field.strip():
        log("    Building K-factor raster from soil layer field...")
        k_path = "in_memory\\k_factor_rast"
        mgmt.PolygonToRaster(
            soil_layer, k_factor_field, k_path, cellsize=cell_size_m
        )
        k_raster = Raster(k_path)
        # Replace NoData cells with the default K value
        k_raster = Con(IsNull(k_raster), lookups.K_DEFAULT, k_raster)
    else:
        log(f"    No K-factor field provided — using default K={lookups.K_DEFAULT}")
        k_raster = lookups.K_DEFAULT  # scalar; arcpy.sa handles constant * raster

    # --- LS factor: slope-length and steepness ---
    # Flow accumulation area (m²) as proxy for slope length
    flow_acc_area = Float(flow_acc) * float(cell_size_m ** 2)
    # L = (contributing area / 22.13)^0.4  (standard RUSLE length factor)
    l_factor = (flow_acc_area / 22.13) ** 0.4
    # S = (sin(slope) / 0.0896)^1.3  (McCool et al. 1987)
    slope_rad = slope_deg_raster * float(math.pi / 180.0)
    s_factor = (Sin(slope_rad) / 0.0896) ** 1.3
    ls_raster = l_factor * s_factor

    # --- C factor: cover management from land use ---
    log("    Building C-factor raster from land use...")
    if classification == "Custom":
        # If custom, assume land_use_field already holds C values
        c_path = "in_memory\\c_factor_rast"
        mgmt.PolygonToRaster(
            land_use_layer, land_use_field, c_path, cellsize=cell_size_m
        )
        c_raster = Raster(c_path)
    else:
        # NLCD: rasterize code, then apply C_FACTOR_TABLE via Con chain
        lu_c_path = "in_memory\\lu_c_code_rast"
        mgmt.PolygonToRaster(
            land_use_layer, land_use_field, lu_c_path, cellsize=cell_size_m
        )
        lu_raster = Raster(lu_c_path)

        nlcd_codes = sorted(lookups.C_FACTOR_TABLE.keys())
        c_raster = None
        for code in nlcd_codes:
            c_val = lookups.C_FACTOR_TABLE[code]
            cell_c = Con(lu_raster == code, c_val, 0.0)
            c_raster = cell_c if c_raster is None else c_raster + cell_c
        # Cells with no matching code get the default
        c_raster = Con(c_raster == 0.0, lookups.C_FACTOR_DEFAULT, c_raster)

    # --- P factor: support practice (default 1.0, no special practices assumed) ---
    p_factor = 1.0

    # --- A = R * K * LS * C * P ---
    a_raster = Float(r_factor) * k_raster * ls_raster * c_raster * Float(p_factor)
    return a_raster

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
def main():
    p = get_params()

    # --- Environment setup ---
    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = p["output_workspace"]
    arcpy.env.mask = p["study_area"]

    # Use DEM as snap raster so all derived rasters align perfectly
    dem_raster = Raster(p["dem"])
    arcpy.env.snapRaster = dem_raster
    cell_size = arcpy.Describe(dem_raster).meanCellWidth  # native DEM cell size

    log("=== Flood & Erosion Model ===")
    log(f"Cell size: {cell_size}")

    # --- Normalize rainfall to inches and mm ---
    if p["rainfall_units"] == "Inches":
        rainfall_inches = p["rainfall_depth"]
        rainfall_mm = p["rainfall_depth"] * 25.4
    else:
        rainfall_mm = p["rainfall_depth"]
        rainfall_inches = p["rainfall_depth"] / 25.4
    log(f"Rainfall: {rainfall_inches:.2f} in / {rainfall_mm:.1f} mm")

    # --- Convert cell size to meters for flow calculations ---
    sr = arcpy.Describe(dem_raster).spatialReference
    if sr.linearUnitName in ("Foot", "Foot_US", "Foot US"):
        cell_size_m = cell_size * 0.3048
    else:
        cell_size_m = cell_size  # assumed meters

    # --- Convert DEM to meters for internal routing if needed ---
    if p["dem_units"] == "Feet":
        log("Converting DEM from feet to meters for internal calculations...")
        dem_m = dem_raster * 0.3048
    else:
        dem_m = dem_raster

    # --- Fill DEM sinks (standard pre-processing for flow routing) ---
    log("Filling DEM sinks...")
    filled_dem = Fill(dem_m)

    # --- Slope (degrees) for RUSLE LS factor and general context ---
    log("Computing slope...")
    slope_deg = Slope(filled_dem, "DEGREE")

    # --- Hydrologic group raster ---
    hydro_raster = build_hydro_group_raster(
        p["soil_layer"], p["hydro_group_field"], dem_raster, cell_size, p["study_area"]
    )

    # --- Curve Number raster ---
    cn_raster = build_cn_raster(
        p["land_use_layer"], p["land_use_field"], p["classification"],
        hydro_raster, cell_size, dem_raster
    )

    # --- Runoff depth (SCS-CN) ---
    q_raster = compute_runoff(cn_raster, rainfall_inches)

    # --- Flood depth ---
    flood_depth, flow_dir, flow_acc = compute_flood_depth(
        filled_dem, q_raster, cell_size_m, p["dem_units"]
    )

    # --- RUSLE erosion risk ---
    erosion_raster = compute_rusle(
        filled_dem, slope_deg, flow_acc,
        p["soil_layer"], p["k_factor_field"], cell_size_m,
        p["land_use_layer"], p["land_use_field"], p["classification"],
        rainfall_mm
    )

    # --- Save outputs ---
    out_flood_path = os.path.join(p["output_workspace"], p["out_flood_raster"])
    out_erosion_path = os.path.join(p["output_workspace"], p["out_erosion_raster"])

    log(f"Saving flood depth raster → {out_flood_path}")
    flood_depth.save(out_flood_path)

    log(f"Saving erosion risk raster → {out_erosion_path}")
    erosion_raster.save(out_erosion_path)

    # --- Add outputs to the current ArcGIS Pro map ---
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        active_map = aprx.activeMap
        if active_map:
            active_map.addDataFromPath(out_flood_path)
            active_map.addDataFromPath(out_erosion_path)
            log("Both output layers added to the active map.")
    except Exception:
        # Running outside of ArcGIS Pro (e.g., standalone script) — skip map add
        log("Note: outputs not added to map (no active ArcGIS Pro session).")

    # --- Summary statistics ---
    log("\n--- Summary ---")
    flood_result = arcpy.GetRasterProperties_management(out_flood_path, "MAXIMUM")
    erosion_result = arcpy.GetRasterProperties_management(out_erosion_path, "MEAN")
    log(f"Max flood depth: {float(flood_result.getOutput(0)):.3f} {p['dem_units'].lower()}")
    log(f"Mean erosion risk (A): {float(erosion_result.getOutput(0)):.4f} tons/acre/event")
    log("=== Complete ===")


# When ArcGIS runs a Script Tool it calls the script directly;
# the main() call below is the entry point.
if __name__ == "__main__":
    main()
