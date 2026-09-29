# flood_model.py
# ArcGIS Script Tool — Flood Depth & Erosion Modeling
# Runs inside ArcGIS Pro with Spatial Analyst extension.
# Requires: arcpy, arcpy.sa (Spatial Analyst)
#
# Parameters (in order, as defined in FloodModel.pyt):
#   0  study_area          GPFeatureLayer  — polygon mask
#   1  dem                 GPRasterLayer   — elevation raster
#   2  dem_units           GPString        — elevation units, "Meters" or "Feet"
#   3  soil_layer          GPFeatureLayer  — polygon soil layer
#   4  hydro_group_field   Field           — A/B/C/D field in soil_layer
#   5  k_factor_field      Field           — optional K-factor field in soil_layer
#   6  rainfall_depth      GPDouble        — storm event rainfall total
#   7  rainfall_units      GPString        — "Inches" or "Millimeters"
#   8  output_workspace    DEWorkspace     — output folder or GDB
#   9  out_flood_raster    DERasterDataset — output flood depth raster name
#   10 out_erosion_raster  DERasterDataset — output soil loss raster name

import os
import math
import bisect
import numpy as np
import arcpy
from arcpy.sa import (
    Fill, FlowDirection, FlowAccumulation, Slope, Watershed, RegionGroup,
    ZonalStatistics, Con, IsNull, Raster, Float, Int, Sin
)
import arcpy.management as mgmt
import arcpy.conversion as conv
import lookups

# ---------------------------------------------------------------------------
# Helper: read script tool parameters
# ---------------------------------------------------------------------------
def get_params(parameters=None):
    """Pull all parameters from the .pyt parameter list, or from the
    Script Tool context when run as a standalone script tool."""
    def val(i):
        # .pyt passes Parameter objects; script tools use GetParameterAsText
        if parameters is not None:
            return parameters[i].valueAsText or ""
        return arcpy.GetParameterAsText(i)

    return {
        "study_area":        val(0),
        "dem":               val(1),
        "dem_units":         val(2),
        "soil_layer":        val(3),
        "hydro_group_field": val(4),
        "k_factor_field":    val(5),  # may be empty
        "rainfall_depth":    float(val(6)),
        "rainfall_units":    val(7),
        "output_workspace":  val(8),
        "out_flood_raster":  val(9),
        "out_erosion_raster": val(10),
    }

# ---------------------------------------------------------------------------
# Helper: log message to ArcGIS tool dialog
# ---------------------------------------------------------------------------
def log(msg):
    arcpy.AddMessage(msg)

# ---------------------------------------------------------------------------
# Step 0: Make sure the DEM is in a projected (length-based) coordinate system
# ---------------------------------------------------------------------------
def prepare_dem(dem, study_area):
    """
    Slope, cell area and flow length all need a DEM whose cells are measured in
    meters or feet. A geographic DEM (degrees, e.g. USGS 3DEP) is clipped to the
    study area and projected to the local UTM zone. Returns the DEM to use.
    """
    sr = arcpy.Describe(dem).spatialReference
    if sr.type != "Geographic":
        return dem

    # Study area bounds in the DEM's degrees, padded 10 cells so the projected
    # edge cells still have data to interpolate from
    ext = arcpy.Describe(study_area).extent.projectAs(sr)
    pad = arcpy.Describe(dem).meanCellWidth * 10
    clip_path = "in_memory\\dem_clip"
    mgmt.Clip(
        dem, f"{ext.XMin - pad} {ext.YMin - pad} {ext.XMax + pad} {ext.YMax + pad}",
        clip_path
    )

    # UTM zone from the study area's center; stay on NAD83 when the DEM is
    # NAD83 and the zone exists in NAD83 (zones 1–23 N), otherwise use WGS84
    lon = (ext.XMin + ext.XMax) / 2.0
    lat = (ext.YMin + ext.YMax) / 2.0
    zone = int((lon + 180.0) // 6) + 1
    if lat >= 0 and zone <= 23 and "North_American_1983" in sr.datumName:
        wkid = 26900 + zone
    else:
        wkid = (32600 if lat >= 0 else 32700) + zone
    utm = arcpy.SpatialReference(wkid)

    # Bilinear resampling is the right choice for continuous elevation data
    log(f"DEM is in degrees — projecting to {utm.name} (meters)...")
    out_path = "in_memory\\dem_utm"
    mgmt.ProjectRaster(clip_path, out_path, utm, "BILINEAR")
    return out_path

# ---------------------------------------------------------------------------
# Step 1: Rasterize soil hydrologic group → integer raster (A=1,B=2,C=3,D=4)
# ---------------------------------------------------------------------------
def build_hydro_group_raster(soil_fc, hydro_field, cell_size):
    """
    Converts SSURGO-style hydrologic group text field (A/B/C/D) to an integer
    raster. soil_fc must be a writable copy (the clipped in-memory soil layer).
    Cells with no soil polygon get lookups.UNKNOWN_HYDRO_GROUP.
    """
    log("  Building hydrologic group raster...")
    default_code = lookups.HYDRO_GROUP_MAP[lookups.UNKNOWN_HYDRO_GROUP]

    # Add a numeric field and fill it from the text group, tracking unknowns
    mgmt.AddField(soil_fc, "HYDGRP_INT", "SHORT")
    unknown = set()
    with arcpy.da.UpdateCursor(soil_fc, [hydro_field, "HYDGRP_INT"]) as cur:
        for row in cur:
            val = str(row[0]).strip().upper() if row[0] else ""
            code = lookups.HYDRO_GROUP_MAP.get(val)
            if code is None:
                unknown.add(val or "<blank>")
                code = default_code
            row[1] = code
            cur.updateRow(row)

    # Tell the user which values were guessed — they change runoff a lot
    if unknown:
        arcpy.AddWarning(
            f"  Unrecognised hydrologic group values {sorted(unknown)} were "
            f"treated as group {lookups.UNKNOWN_HYDRO_GROUP}."
        )

    # Rasterize, then fill gaps in soil coverage so runoff isn't NoData there
    out_path = "in_memory\\hydro_group_rast"
    conv.PolygonToRaster(soil_fc, "HYDGRP_INT", out_path, cellsize=cell_size)
    hydro = Raster(out_path)
    return Con(IsNull(hydro), default_code, hydro)

# ---------------------------------------------------------------------------
# Step 2: Build CN raster from hydrologic group (assumed uniform land cover)
# ---------------------------------------------------------------------------
def build_cn_raster(hydro_group_raster):
    """
    Builds a Curve Number raster from the soil hydrologic group raster.
    CN per group comes from lookups.CN_BY_HYDRO_GROUP (one assumed cover).
    Returns a raster where each cell = its CN value.
    """
    log("  Building Curve Number raster...")
    cn = lookups.CN_BY_HYDRO_GROUP

    # Map group integer (1-4) to its CN; 4 (D) is the final else
    return Con(
        hydro_group_raster == 1, cn["A"],
        Con(hydro_group_raster == 2, cn["B"],
            Con(hydro_group_raster == 3, cn["C"], cn["D"])
        )
    )

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
# Step 4: Flood depth — fill-depth ponding limited by runoff volume
# ---------------------------------------------------------------------------
def compute_flood_depth(dem_s, filled_dem, q_raster, cell_area_m2):
    """
    Ponds each storm's runoff in the terrain's depressions.

    1. Depressions = cells the Fill tool raised (filled_dem − dem_s > 0).
       Each connected depression with one spill level is a zone.
    2. Every cell's runoff (SCS Q × cell area) flows downhill on the unfilled
       DEM to the depression it drains into → runoff volume per depression.
    3. Each depression fills to the water level that holds exactly that volume,
       capped at its spill level; any extra spills out downstream.

    Returns (depth_m raster with NoData where dry, runoff raster in m³/cell).

    ponytail: spilled water leaves the model (no fill-and-spill cascade into
    lower depressions, no river overbank flooding). Upgrade path: HAND method
    or HEC-RAS 2D / ArcGIS Pro Flood Simulation.
    ponytail: merged depressions share one level (sub-basins under one spill
    level fill together) — fine for a storm-total snapshot.
    """
    log("  Finding depressions...")

    # Depth of each depression if filled to its spill point
    fill_depth = filled_dem - dem_s

    # No depressions at all (steep or smooth terrain) → nothing ponds
    max_fill = fill_depth.maximum
    if max_fill is not None and max_fill <= 0:
        log("  No depressions deep enough to hold water — flood map will be empty.")
        return Con(fill_depth < 0, fill_depth), q_raster * 0.0254 * cell_area_m2

    # Zones = connected depression cells with the same spill level (mm).
    # Grouping by level keeps two separate touching depressions apart.
    spill_mm = Con(fill_depth > 0, Int(filled_dem * 1000 + 0.5))
    zones = RegionGroup(spill_mm, "EIGHT", "WITHIN", "NO_LINK")

    log("  Routing runoff into depressions...")

    # Runoff volume produced by each cell (m³): Q (in → m) × cell area
    runoff_m3 = q_raster * 0.0254 * cell_area_m2

    # Catchment of each depression: follow the unfilled surface downhill
    catchments = Watershed(FlowDirection(dem_s), zones)

    # Total runoff arriving at each depression, written onto its cells
    inflow = Con(~IsNull(zones), ZonalStatistics(catchments, "VALUE", runoff_m3, "SUM", "DATA"))

    log("  Solving pond water levels...")
    depth_m = solve_pond_depths(zones, dem_s, filled_dem, inflow, cell_area_m2)
    return depth_m, runoff_m3

# ---------------------------------------------------------------------------
# Step 4b: Exact water level in every depression (numpy, one pass)
# ---------------------------------------------------------------------------
def solve_pond_depths(zones, dem_s, filled_dem, inflow, cell_area_m2):
    """
    For each depression, finds the flat water level whose stored volume equals
    its runoff inflow, capped at its spill level. Returns water depth (m) as a
    raster, NoData where dry or shallower than lookups.MIN_FLOOD_DEPTH_M.

    If the lowest k cells (elevations e1..ek) are under water at level h, the
    stored volume is area * (k*h - (e1+...+ek)). So with cells sorted by
    elevation, h = (inflow/area + running sum) / k, and the right k is the
    first one where that h does not reach the next cell up.
    """
    # Read every raster on the same grid (DEM's corner and size)
    lower_left = dem_s.extent.lowerLeft
    ncols, nrows = dem_s.width, dem_s.height
    def to_array(r, nodata):
        return arcpy.RasterToNumPyArray(r, lower_left, ncols, nrows, nodata).ravel()
    zone = to_array(zones, 0)
    ground = to_array(dem_s, np.nan).astype(float)
    spill = to_array(filled_dem, np.nan).astype(float)
    inflow_depth = np.nan_to_num(to_array(inflow, 0).astype(float)) / cell_area_m2

    # Depression cells only, sorted by depression then by elevation
    cells = np.flatnonzero(zone > 0)
    order = np.lexsort((ground[cells], zone[cells]))
    cells = cells[order]
    z, e = zone[cells], ground[cells]

    # Where each depression's run of cells starts and ends in the sorted list
    is_start = np.r_[True, z[1:] != z[:-1]]
    starts = np.flatnonzero(is_start)
    ends = np.r_[starts[1:] - 1, len(z) - 1]
    group = np.cumsum(is_start) - 1
    log(f"    {len(starts):,} depressions, {len(cells):,} cells")

    # k = number of cells at or below this one; running sum of their elevations
    k = np.arange(len(z)) - starts[group] + 1
    running = np.cumsum(e)
    running -= (running[starts] - e[starts])[group]

    # Candidate level if exactly the lowest k cells are wet
    level = (inflow_depth[cells] + running) / k

    # Valid when the level doesn't reach the next-higher cell in the depression
    next_e = np.r_[e[1:], np.inf]
    next_e[ends] = np.inf
    valid = level <= next_e

    # First valid candidate per depression (the last cell is always valid)
    valid_idx = np.flatnonzero(valid)
    _, first = np.unique(group[valid_idx], return_index=True)
    level_by_group = level[valid_idx[first]]

    # Never above the spill level: extra water overflows out of the depression
    level_by_group = np.minimum(level_by_group, np.maximum.reduceat(spill[cells], starts))

    # Water depth per cell; dry/very shallow cells become NoData.
    # float32: numpy defaults to 64-bit, which Pro can't symbolize properly
    depth = level_by_group[group] - e
    nodata = -9999.0
    out = np.full(zone.size, nodata, dtype=np.float32)
    out[cells] = np.where(depth >= lookups.MIN_FLOOD_DEPTH_M, depth, nodata)

    # Back to a raster on the DEM grid, saved to the scratch GDB with the DEM's CRS
    depth_raster = arcpy.NumPyArrayToRaster(
        out.reshape(nrows, ncols), lower_left, dem_s.meanCellWidth,
        dem_s.meanCellHeight, nodata
    )
    out_path = os.path.join(arcpy.env.scratchGDB, "pond_depth")
    depth_raster.save(out_path)
    mgmt.DefineProjection(out_path, dem_s.spatialReference)
    return Raster(out_path)

# ---------------------------------------------------------------------------
# Step 5a: Storm rainfall erosivity (RUSLE R for one event)
# ---------------------------------------------------------------------------
def event_erosivity(rainfall_mm):
    """
    EI30 for one storm (MJ·mm / ha·h), the RUSLE event R factor.
    The storm's depth is spread over 24 h with the SCS Type II pattern; the
    kinetic energy E comes from each 15-minute burst's intensity
    (Brown & Foster 1987), and I30 is the peak 30-minute intensity.
    """
    hours, fractions = zip(*lookups.SCS_TYPE_II)

    # Cumulative rainfall (mm) every 15 minutes, interpolated from the table
    def cumulative(t):
        i = min(bisect.bisect_right(hours, t), len(hours) - 1)
        t0, t1, f0, f1 = hours[i - 1], hours[i], fractions[i - 1], fractions[i]
        return rainfall_mm * (f0 + (f1 - f0) * (t - t0) / (t1 - t0))
    step_h = 0.25
    cum = [cumulative(k * step_h) for k in range(int(24 / step_h) + 1)]

    # Storm kinetic energy: sum of unit energy × depth for each burst
    energy = 0.0
    for a, b in zip(cum, cum[1:]):
        depth = b - a
        intensity = depth / step_h
        energy += 0.29 * (1 - 0.72 * math.exp(-0.05 * intensity)) * depth

    # Peak 30-minute intensity (two 15-minute steps), mm/h
    i30 = max(cum[k + 2] - cum[k] for k in range(len(cum) - 2)) / 0.5
    return energy * i30

# ---------------------------------------------------------------------------
# Step 5b: RUSLE soil loss (A, t/ha for this storm)
# ---------------------------------------------------------------------------
def compute_rusle(
    dem_s, filled_dem, soil_fc, k_factor_field, cell_size, cell_size_m,
    z_factor, rainfall_mm, flood_depth_m
):
    """
    Computes RUSLE A = R * K * LS * C * P in SI units.
    Returns soil loss raster in tonnes per hectare for this storm.
    Cells under standing water get 0 (sediment settles there, it isn't lost).
    """
    log("  Computing RUSLE soil loss...")

    # --- R factor: event erosivity EI30 (MJ·mm / ha·h) ---
    r_factor = event_erosivity(rainfall_mm)
    log(f"    R factor (EI30) = {r_factor:.1f} MJ·mm/ha·h")

    # --- K factor: soil erodibility, US units → SI ---
    if k_factor_field and k_factor_field.strip():
        log("    Building K-factor raster from soil layer field...")
        k_path = "in_memory\\k_factor_rast"
        conv.PolygonToRaster(soil_fc, k_factor_field, k_path, cellsize=cell_size)
        k_raster = Raster(k_path)
        # Replace NoData cells with the default K value
        k_raster = Con(IsNull(k_raster), lookups.K_DEFAULT, k_raster)
    else:
        log(f"    No K-factor field provided — using default K={lookups.K_DEFAULT}")
        k_raster = lookups.K_DEFAULT  # scalar; arcpy.sa handles constant * raster
    k_si = k_raster * lookups.K_US_TO_SI

    # --- LS factor (Moore & Burch 1986) ---
    # Flow routed over the filled surface so it passes through depressions
    flow_acc = FlowAccumulation(FlowDirection(filled_dem))
    # Upslope length per unit contour width (m), counting the cell itself;
    # capped because RUSLE covers hillslope sheet/rill erosion, not channels
    flow_length = (Float(flow_acc) + 1.0) * cell_size_m
    flow_length = Con(flow_length > lookups.MAX_SLOPE_LENGTH_M,
                      lookups.MAX_SLOPE_LENGTH_M, flow_length)
    l_factor = (flow_length / 22.13) ** 0.4
    # Slope on the real (unfilled) surface; z-factor fixes feet/meter mixes
    slope_deg = Slope(dem_s, "DEGREE", z_factor)
    slope_rad = slope_deg * float(math.pi / 180.0)
    s_factor = (Sin(slope_rad) / 0.0896) ** 1.3
    ls_raster = l_factor * s_factor

    # --- C factor: cover management (constant for the assumed land cover) ---
    c_factor = lookups.C_FACTOR
    log(f"    C factor = {c_factor} (assumed uniform land cover)")

    # --- P factor: support practice (default 1.0, no special practices assumed) ---
    p_factor = 1.0

    # --- A = R * K * LS * C * P, zero where water is ponded ---
    a_raster = Float(r_factor) * k_si * ls_raster * c_factor * Float(p_factor)
    return Con(IsNull(flood_depth_m), a_raster, 0.0)

# ---------------------------------------------------------------------------
# Helper: add an output raster to the map with a color ramp
# ---------------------------------------------------------------------------
def add_to_map(aprx, path, ramp_wildcard, stretch_type):
    """Adds the raster to the active map and applies a stretched color ramp.
    Any symbology failure leaves ArcGIS Pro's default look in place."""
    layer = aprx.activeMap.addDataFromPath(path)
    try:
        ramps = aprx.listColorRamps(ramp_wildcard)
        sym = layer.symbology
        sym.updateColorizer("RasterStretchColorizer")
        if ramps:
            sym.colorizer.colorRamp = ramps[0]
        sym.colorizer.stretchType = stretch_type
        layer.symbology = sym
    except Exception:
        log(f"Note: could not style {os.path.basename(path)} — set its symbology manually.")

# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------
def main(parameters=None):
    p = get_params(parameters)
    log("=== Flood & Erosion Model ===")

    # --- Normalize rainfall to inches and mm ---
    if p["rainfall_units"] == "Inches":
        rainfall_inches = p["rainfall_depth"]
        rainfall_mm = p["rainfall_depth"] * 25.4
    else:
        rainfall_mm = p["rainfall_depth"]
        rainfall_inches = p["rainfall_depth"] / 25.4
    log(f"Rainfall: {rainfall_inches:.2f} in / {rainfall_mm:.1f} mm")

    # EnvManager puts every environment back when the tool finishes, so the
    # extent/mask set here don't leak into the user's next geoprocessing run
    # qualifiedFieldNames=False: a joined soil layer's "muaggatt.hydgrpdcd"
    # comes out of Clip as plain "hydgrpdcd"
    with arcpy.EnvManager(overwriteOutput=True, qualifiedFieldNames=False):
        # --- DEM in a projected CRS (auto-projects geographic DEMs) ---
        dem_path = prepare_dem(p["dem"], p["study_area"])
        sr = arcpy.Describe(dem_path).spatialReference
        study_extent = arcpy.Describe(p["study_area"]).extent.projectAs(sr)

        # Extent = study area so Fill/flow tools only process that area (mask
        # alone only blanks cells); outputs land on the DEM's grid and CRS
        with arcpy.EnvManager(
            extent=study_extent, mask=p["study_area"], snapRaster=dem_path,
            cellSize=dem_path, outputCoordinateSystem=sr
        ):
            run_model(p, dem_path, sr, rainfall_inches, rainfall_mm)


def run_model(p, dem_path, sr, rainfall_inches, rainfall_mm):
    """Everything after environment setup; see main()."""
    dem_raster = Raster(dem_path)

    # --- Cell size in native units and in meters ---
    cell_size = arcpy.Describe(dem_path).meanCellWidth
    cell_size_m = cell_size * sr.metersPerUnit
    cell_area_m2 = cell_size_m ** 2
    log(f"Cell size: {cell_size_m:.2f} m ({sr.name})")

    # --- Elevations to meters for internal calculations ---
    if p["dem_units"] == "Feet":
        log("Converting DEM elevations from feet to meters...")
        dem_m = dem_raster * 0.3048
    else:
        dem_m = dem_raster

    # Slope z-factor: elevations are now meters, horizontal is in map units
    z_factor = 1.0 / sr.metersPerUnit

    # --- Terrain surfaces ---
    # dem_s: DEM with noise-sized sinks removed (the "real" ground surface)
    # filled_dem: every depression filled to its spill point
    log("Filling DEM sinks...")
    dem_s = Fill(dem_m, lookups.MIN_SINK_DEPTH_M)
    filled_dem = Fill(dem_s)

    # --- Soil layer clipped to the study area (writable, small copy) ---
    log("Clipping soil layer to study area...")
    soil_fc = "in_memory\\soil_clip"
    arcpy.analysis.Clip(p["soil_layer"], p["study_area"], soil_fc)
    # Field names in the clipped copy lose any join prefix ("table.field")
    hydro_field = p["hydro_group_field"].split(".")[-1]
    k_field = p["k_factor_field"].split(".")[-1]

    # --- Runoff: hydro group → CN → SCS-CN Q ---
    hydro_raster = build_hydro_group_raster(soil_fc, hydro_field, cell_size)
    cn_raster = build_cn_raster(hydro_raster)
    q_raster = compute_runoff(cn_raster, rainfall_inches)

    # --- Flood depth (m) ---
    log("Modeling ponded flood water...")
    flood_depth_m, runoff_m3 = compute_flood_depth(dem_s, filled_dem, q_raster, cell_area_m2)

    # --- RUSLE soil loss ---
    log("Modeling erosion...")
    erosion_raster = compute_rusle(
        dem_s, filled_dem, soil_fc, k_field, cell_size, cell_size_m,
        z_factor, rainfall_mm, flood_depth_m
    )

    # --- Flood depth back to the DEM's elevation units ---
    unit_label = "ft" if p["dem_units"] == "Feet" else "m"
    flood_depth_out = flood_depth_m * 3.28084 if unit_label == "ft" else flood_depth_m

    # --- Save outputs ---
    out_flood_path = os.path.join(p["output_workspace"], p["out_flood_raster"])
    out_erosion_path = os.path.join(p["output_workspace"], p["out_erosion_raster"])

    log(f"Saving flood depth raster → {out_flood_path}")
    flood_depth_out.save(out_flood_path)

    log(f"Saving soil loss raster → {out_erosion_path}")
    erosion_raster.save(out_erosion_path)

    # Statistics let Pro stretch the color ramp over the real value range
    mgmt.CalculateStatistics(out_flood_path)
    mgmt.CalculateStatistics(out_erosion_path)

    # --- Add outputs to the current ArcGIS Pro map, styled ---
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        if aprx.activeMap:
            add_to_map(aprx, out_flood_path, "Blue*", "MinimumMaximum")
            add_to_map(aprx, out_erosion_path, "Yellow*Red*", "PercentClip")
            log("Both output layers added to the active map.")
    except Exception:
        # Running outside of ArcGIS Pro (e.g., standalone script) — skip map add
        log("Note: outputs not added to map (no active ArcGIS Pro session).")

    # --- Summary statistics ---
    # Water budget: how much of the storm's runoff is standing in depressions
    depth_arr = arcpy.RasterToNumPyArray(flood_depth_m, nodata_to_value=0)
    runoff_arr = arcpy.RasterToNumPyArray(runoff_m3, nodata_to_value=0)
    stored_m3 = float(depth_arr.sum()) * cell_area_m2
    runoff_total_m3 = float(runoff_arr.sum())
    flooded_ha = float((depth_arr > 0).sum()) * cell_area_m2 / 10000.0
    stored_pct = 100.0 * stored_m3 / runoff_total_m3 if runoff_total_m3 else 0.0

    erosion_mean = arcpy.GetRasterProperties_management(out_erosion_path, "MEAN")
    erosion_max = arcpy.GetRasterProperties_management(out_erosion_path, "MAXIMUM")

    log("\n--- Summary ---")
    log(f"Flooded area: {flooded_ha:,.2f} ha")
    log(f"Max flood depth: {float(depth_arr.max()) * (3.28084 if unit_label == 'ft' else 1):.2f} {unit_label}")
    log(f"Runoff: {runoff_total_m3:,.0f} m³ total, {stored_m3:,.0f} m³ ({stored_pct:.0f}%) "
        "ponds in depressions; the rest drains out of the study area as streamflow")
    log(f"Soil loss: mean {float(erosion_mean.getOutput(0)):.3f}, "
        f"max {float(erosion_max.getOutput(0)):.2f} t/ha for this storm")
    log("=== Complete ===")


# When ArcGIS runs a Script Tool it calls the script directly;
# the main() call below is the entry point.
if __name__ == "__main__":
    main()
