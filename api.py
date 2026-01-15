"""
FastAPI Backend for Drone Launch Site Analysis
Provides REST API endpoint for geospatial threat assessment
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import osmnx as ox
import geopandas as gpd
from shapely.geometry import box, LineString
from shapely.ops import unary_union
import numpy as np
import pandas as pd
import json
from scipy.spatial import cKDTree

# AHP (Analytical Hierarchical Process) Weights for Risk Scoring Engine
# Based on research matrix for threat assessment criteria
AHP_WEIGHTS = {
    "distance": 0.3629,       # Distance from Core
    "building": 0.2924,       # Building Structures
    "road_infra": 0.1368,     # Road Infrastructure
    "elevation": 0.1057,      # Elevation Profile (Terrain Level)
    "lulc": 0.1057,           # Land Use / Land Cover
    "vlos": 0.0460,           # Visual Line of Sight
    "terrain": 0.0254         # Terrain Type (Physical)
}

# Initialize FastAPI app
app = FastAPI(
    title="Drone Launch Site Analysis API",
    description="Geospatial analysis API for identifying and assessing potential drone launch sites",
    version="1.0.0"
)

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Models
class AnalysisRequest(BaseModel):
    lat: float = Field(..., description="Latitude of the center point (Primary Asset)")
    lon: float = Field(..., description="Longitude of the center point (Primary Asset)")
    radius: int = Field(1000, description="Search radius in meters", ge=100, le=5000)


class AnalysisResponse(BaseModel):
    status: str
    stats: dict
    features: list
    security_debug_layer: list


# Core Logic Functions
def check_line_of_sight(centroid, nearest_node, G_proj, buildings_union):
    """Check if there's a clear line of sight from candidate to road."""
    node_x = G_proj.nodes[nearest_node]['x']
    node_y = G_proj.nodes[nearest_node]['y']
    
    sight_line = LineString([
        (centroid.x, centroid.y),
        (node_x, node_y)
    ])
    
    is_hidden = sight_line.intersects(buildings_union)
    return is_hidden


def calculate_road_accessibility(gdf_candidates, G_proj, buildings_union):
    """Calculate distance to nearest road, line-of-sight, and road type for each candidate."""
    distances = []
    hidden_status = []
    road_types = []
    
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        nearest_node = ox.distance.nearest_nodes(G_proj, centroid.x, centroid.y)
        
        node_x = G_proj.nodes[nearest_node]['x']
        node_y = G_proj.nodes[nearest_node]['y']
        dist = np.sqrt((centroid.x - node_x)**2 + (centroid.y - node_y)**2)
        distances.append(dist)
        
        is_hidden = check_line_of_sight(centroid, nearest_node, G_proj, buildings_union)
        hidden_status.append(is_hidden)
        
        # Extract highway tag from nearest road edge
        # Get edges connected to the nearest node
        road_type = 'residential'  # Default fallback
        if nearest_node in G_proj:
            # Try to get highway tag from incoming or outgoing edges
            edges = list(G_proj.edges(nearest_node, data=True))
            if edges:
                # Get the first edge's highway tag
                edge_data = edges[0][2]  # Edge data dict
                road_type = edge_data.get('highway', 'residential')
            else:
                # If no edges found, try reverse direction
                reverse_edges = list(G_proj.in_edges(nearest_node, data=True))
                if reverse_edges:
                    edge_data = reverse_edges[0][2]
                    road_type = edge_data.get('highway', 'residential')
        
        road_types.append(road_type)
    
    gdf_candidates['dist_to_road'] = distances
    gdf_candidates['is_hidden'] = hidden_status
    gdf_candidates['nearest_road_type'] = road_types
    
    return gdf_candidates


def calculate_security_proximity(gdf_candidates, gdf_security_proj):
    """
    Calculate distance to nearest security presence using KD-Tree for accuracy.
    
    Parameters:
    -----------
    gdf_candidates : GeoDataFrame
        Launch candidates in projected UTM CRS
    gdf_security_proj : GeoDataFrame
        Security locations in projected UTM CRS (MUST be same CRS as candidates)
        
    Returns:
    --------
    GeoDataFrame
        Candidates with nearest_security_dist column added
    """
    if len(gdf_security_proj) == 0:
        # No security presence, set large distance (no penalty applied)
        gdf_candidates['nearest_security_dist'] = 9999
        print("⚠️  No security presence detected in area")
        return gdf_candidates
    
    # Extract security node coordinates
    # Handle both Point and Polygon geometries
    security_coords = []
    for idx, row in gdf_security_proj.iterrows():
        if row.geometry.geom_type == 'Point':
            security_coords.append((row.geometry.x, row.geometry.y))
        elif row.geometry.geom_type in ['Polygon', 'MultiPolygon']:
            # Use centroid for polygon features (e.g., government buildings)
            centroid = row.geometry.centroid
            security_coords.append((centroid.x, centroid.y))
    
    if len(security_coords) == 0:
        gdf_candidates['nearest_security_dist'] = 9999
        print("⚠️  No valid security geometries found")
        return gdf_candidates
    
    # Build KD-Tree for efficient nearest neighbor search
    security_tree = cKDTree(security_coords)
    print(f"✓ Built Security Index with {len(security_coords)} nodes")
    
    # Extract candidate centroids
    candidate_coords = []
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        candidate_coords.append((centroid.x, centroid.y))
    
    # Query KD-Tree for nearest security node to each candidate
    # k=1 means find the single nearest neighbor
    distances, indices = security_tree.query(candidate_coords, k=1)
    
    # Assign distances to candidates
    gdf_candidates['nearest_security_dist'] = distances
    
    # Debug logging
    print(f"✓ Security proximity calculated:")
    print(f"  - Mean distance: {distances.mean():.1f}m")
    print(f"  - Min distance: {distances.min():.1f}m")
    print(f"  - Max distance: {distances.max():.1f}m")
    if len(gdf_candidates) > 0:
        print(f"  - Sample (first site): {gdf_candidates.iloc[0]['nearest_security_dist']:.1f}m")
    
    return gdf_candidates


def calculate_risk_score(row):
    """
    Calculate threat score using AHP (Analytical Hierarchical Process) framework.
    
    This function implements step-wise AHP scoring:
    - Step 1: Distance from Core (36.29% weight)
    - Step 2: Building Structures (29.24% weight)
    - Step 3: Road Infrastructure (13.68% weight)
    
    Combined, these three factors account for ~79% of the total threat weight.
    """
    # Get distance from site to Map Center (Target) in meters
    dist_to_center = row.get('dist_to_center', 9999)
    
    # ============================================================================
    # AHP DISTANCE SCORING (Step 1)
    # ============================================================================
    # Assign distance_score (1-5) based on lookup table
    if dist_to_center < 500:
        distance_score = 5
    elif dist_to_center < 1000:  # 500m - 1km
        distance_score = 4
    elif dist_to_center < 2000:  # 1km - 2km
        distance_score = 3
    elif dist_to_center < 5000:  # 2km - 5km
        distance_score = 2
    else:  # > 5km
        distance_score = 1
    
    # Normalize distance_score (1-5) to 0-100 scale
    distance_normalized = distance_score * 20  # Score * 20 = 0-100 scale
    
    # Apply AHP weight for distance
    distance_component = distance_normalized * AHP_WEIGHTS['distance']
    
    # ============================================================================
    # AHP BUILDING STRUCTURES SCORING (Step 2)
    # ============================================================================
    site_type = row['type']
    is_hidden = row['is_hidden']
    dist_to_road = row['dist_to_road']
    security_dist = row.get('nearest_security_dist', 9999)
    
    # Determine Building Score (1-5) based on research table
    building_score = 1  # Default lowest
    
    # Only apply building scoring to actual building sites
    if site_type == 'Building':
        # Get building and amenity tags (handle None/missing values)
        building_tag = row.get('building_tag')
        amenity_tag = row.get('amenity_tag')
        
        # Convert to string and lowercase for comparison (handle None/NaN)
        building_str = str(building_tag).lower() if pd.notna(building_tag) and building_tag is not None else ''
        amenity_str = str(amenity_tag).lower() if pd.notna(amenity_tag) and amenity_tag is not None else ''
        
        # Map OSM tags to Research Categories
        # Residential (Score 5) - Highest risk: anonymity and harder to patrol
        if (building_str in ['apartments', 'residential', 'house', 'detached', 'terrace'] or 
            amenity_str == 'residential'):
            building_score = 5
        # Public/Government/Industrial (Score 3) - Moderate risk
        elif (building_str in ['government', 'public', 'civic', 'industrial', 'warehouse', 'factory'] or 
              amenity_str in ['police', 'townhall', 'courthouse']):
            building_score = 3
        # Commercial (Score 2) - Lower risk: more visible and patrolled
        elif building_str in ['commercial', 'retail', 'office', 'shop', 'supermarket']:
            building_score = 2
        else:
            # Fallback for unclassified buildings (assume moderate risk)
            building_score = 2
    else:
        # For non-buildings (Alleys, Open Land), set score to 0 (not applicable)
        # These will rely on LULC factor later
        building_score = 0
    
    # Normalize building_score (1-5) to 0-100 scale
    building_normalized = building_score * 20  # Score * 20 = 0-100 scale
    
    # Apply AHP weight for building structures
    building_component = building_normalized * AHP_WEIGHTS['building']
    
    # ============================================================================
    # AHP ROAD INFRASTRUCTURE SCORING (Step 3)
    # ============================================================================
    # Road Infrastructure Score (1-5) based on research table
    # Better roads (expressways) are safer; unpaved/village roads are higher risk
    road_score = 3  # Default Moderate (District Road equivalent)
    
    # Get road type from nearest road (captured in calculate_road_accessibility)
    road_type = row.get('nearest_road_type', 'residential')  # Fallback to residential
    
    # Convert to string and lowercase for comparison
    road_type_str = str(road_type).lower() if pd.notna(road_type) and road_type is not None else 'residential'
    
    # Map OSM highway tags to AHP risk scores
    # Unpaved/Village roads - Highest risk (no cameras, no patrols)
    if road_type_str in ['unclassified', 'track', 'path', 'service']:
        road_score = 5
    # Residential/Tertiary - High risk
    elif road_type_str in ['residential', 'tertiary']:
        road_score = 4
    # Secondary/Primary - Moderate risk (District Road equivalent)
    elif road_type_str in ['secondary', 'primary']:
        road_score = 3
    # Trunk/Motorway Link - Lower risk (Highways with some monitoring)
    elif road_type_str in ['trunk', 'motorway_link']:
        road_score = 2
    # Motorway - Lowest risk (Expressway with cameras and patrols)
    elif road_type_str == 'motorway':
        road_score = 1
    else:
        # Fallback for unknown road types (assume moderate risk)
        road_score = 3
    
    # Normalize road_score (1-5) to 0-100 scale
    road_normalized = road_score * 20  # Score * 20 = 0-100 scale
    
    # Apply AHP weight for road infrastructure
    road_infra_component = road_normalized * AHP_WEIGHTS['road_infra']
    
    # Placeholder: Elevation Profile (10.57% weight)
    # TODO: Implement elevation-based scoring
    elevation_component = 0.0  # Placeholder
    
    # Placeholder: Land Use / Land Cover (10.57% weight)
    # TODO: Implement LULC-based scoring
    lulc_component = 0.0  # Placeholder
    
    # Placeholder: Visual Line of Sight (4.60% weight)
    # Map existing is_hidden logic as temporary placeholder
    vlos_score = 100 if is_hidden else 50
    vlos_component = vlos_score * AHP_WEIGHTS['vlos']
    
    # Placeholder: Terrain Type (2.54% weight)
    # TODO: Implement terrain type scoring
    terrain_component = 0.0  # Placeholder
    
    # ============================================================================
    # COMBINE AHP COMPONENTS
    # ============================================================================
    # Sum all weighted components
    total_score = (
        distance_component +
        building_component +
        road_infra_component +
        elevation_component +
        lulc_component +
        vlos_component +
        terrain_component
    )
    
    # Apply security presence penalty (temporary until integrated into AHP)
    security_penalty = 0.0
    if security_dist < 150:
        security_penalty = 0.5  # 50% reduction within 150m
    elif security_dist < 300:
        security_penalty = 0.2  # 20% reduction within 300m
    
    final_score = total_score * (1 - security_penalty)
    
    # Ensure score is within 0-100 range
    final_score = max(0, min(100, final_score))
    
    return round(final_score, 2)


def fetch_area_data(lat, lon, radius_meters):
    """Fetch building, natural area, and road network data."""
    bbox = ox.utils_geo.bbox_from_point((lat, lon), dist=radius_meters)
    north, south, east, west = bbox
    
    # Download buildings data
    tags_buildings = {'building': True}
    gdf_buildings = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_buildings)
    
    # Download natural/water areas and open spaces data (EXPANDED)
    tags_nature = {
        'natural': ['water', 'wood', 'sand', 'earth', 'scrub'],
        'landuse': ['forest', 'grass', 'basin', 'construction', 'brownfield', 'commercial', 'industrial'],
        'amenity': ['parking', 'school_yard'],
        'leisure': ['pitch', 'playground', 'common']
    }
    gdf_nature = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_nature)
    print(f"Fetched {len(gdf_nature)} raw natural/open space candidates")
    
    # Download road network
    G = ox.graph_from_bbox(bbox=(north, south, east, west), network_type='drive')
    
    # Download security/guardian locations (EXPANDED)
    print("Downloading security presence data...")
    tags_security = {
        'amenity': ['police', 'fire_station', 'courthouse', 'embassy', 'prison', 'townhall'],
        'building': ['government', 'military', 'public', 'civic'],
        'office': ['government', 'administrative', 'diplomatic', 'political'],
        'military': ['barracks', 'office', 'checkpoint', 'base', 'danger_area'],
        'landuse': ['military', 'civic_admin'],
        'man_made': ['surveillance']
    }
    try:
        gdf_security = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_security)
        print(f"✅ Fetched {len(gdf_security)} security/guardian locations")
        
        # Debug: Show breakdown by type
        if len(gdf_security) > 0:
            print(f"   Security breakdown by amenity: {dict(gdf_security['amenity'].value_counts()) if 'amenity' in gdf_security.columns else 'None'}")
            print(f"   Security breakdown by building: {dict(gdf_security['building'].value_counts()) if 'building' in gdf_security.columns else 'None'}")
            print(f"   Security breakdown by office: {dict(gdf_security['office'].value_counts()) if 'office' in gdf_security.columns else 'None'}")
            print(f"   Geometry types: {dict(gdf_security.geometry.geom_type.value_counts())}")
    except Exception as e:
        print(f"⚠️  No security data found or error: {e}")
        # Create empty GeoDataFrame if no security features found
        gdf_security = gpd.GeoDataFrame(geometry=[], crs='EPSG:4326')
    
    return gdf_buildings, gdf_nature, G, gdf_security


def find_launch_candidates(gdf_buildings, gdf_nature, G, gdf_security, center_lat, center_lon):
    """Find potential drone launch sites and score them."""
    # Estimate and project to local UTM CRS
    utm_crs = gdf_buildings.estimate_utm_crs()
    gdf_buildings_proj = gdf_buildings.to_crs(utm_crs)
    gdf_nature_proj = gdf_nature.to_crs(utm_crs)
    
    # Project center point to UTM for distance calculations
    center_point = gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([center_lon], [center_lat]),
        crs='EPSG:4326'
    ).to_crs(utm_crs)
    center_x = center_point.geometry.x.values[0]
    center_y = center_point.geometry.y.values[0]
    
    # Project road network to UTM
    G_proj = ox.project_graph(G, to_crs=utm_crs)
    
    # Define study area from bounding box
    study_area = box(*gdf_buildings_proj.total_bounds)
    
    # Calculate open space (area not occupied by buildings)
    buildings_union = unary_union(gdf_buildings_proj.geometry)
    open_space = study_area.difference(buildings_union)
    
    # Morphological operations to find alleys (RELAXED for better detection)
    # Reduced erosion from -2.5 to -2.0 to preserve narrower passages
    wide_space = open_space.buffer(-2.0)
    reconstructed = wide_space.buffer(2.1)
    alleys = open_space.difference(reconstructed)
    
    print(f"Morphological operations complete")
    
    # Convert to GeoDataFrame
    if alleys.geom_type == 'MultiPolygon':
        alley_polygons = list(alleys.geoms)
    elif alleys.geom_type == 'Polygon':
        alley_polygons = [alleys]
    else:
        alley_polygons = []
    
    gdf_alleys = gpd.GeoDataFrame(geometry=alley_polygons, crs=utm_crs)
    gdf_alleys['area'] = gdf_alleys.geometry.area
    
    print(f"Found {len(gdf_alleys)} raw alley polygons before filtering")
    
    # FILTER 1: Area thresholds (min 25 m², max 2000 m²)
    # This captures smaller parking spots and larger open areas
    gdf_alleys = gdf_alleys[(gdf_alleys['area'] > 25) & (gdf_alleys['area'] < 2000)]
    print(f"After area filter: {len(gdf_alleys)} alleys")
    
    # FILTER 2: Remove building edge artifacts
    # If an alley intersects with a building, it's likely a detection artifact
    # Keep only alleys that are truly separated from buildings (at least 1m clearance)
    if len(gdf_alleys) > 0:
        buildings_buffered = buildings_union.buffer(1.0)  # 1m buffer around buildings
        
        # Keep only alleys that DON'T intersect with buffered buildings
        valid_alleys = []
        for idx, row in gdf_alleys.iterrows():
            alley_geom = row.geometry
            # Check if alley is completely outside the buffered buildings
            if not alley_geom.intersects(buildings_buffered):
                valid_alleys.append(alley_geom)
        
        if len(valid_alleys) > 0:
            gdf_alleys = gpd.GeoDataFrame(geometry=valid_alleys, crs=utm_crs)
            gdf_alleys['area'] = gdf_alleys.geometry.area
            gdf_alleys['type'] = 'Alley'
            print(f"After building-edge filter: {len(gdf_alleys)} valid alleys (removed {len(alley_polygons) - len(gdf_alleys)} building artifacts)")
        else:
            # Create empty GeoDataFrame with required columns
            gdf_alleys = gpd.GeoDataFrame(geometry=[], crs=utm_crs)
            gdf_alleys['area'] = []
            gdf_alleys['type'] = []
            print(f"⚠️  All alleys were building edge artifacts - no valid alleys found")
    else:
        # If no alleys passed area filter, create empty GeoDataFrame with required columns
        gdf_alleys = gpd.GeoDataFrame(geometry=[], crs=utm_crs)
        gdf_alleys['area'] = []
        gdf_alleys['type'] = []
    
    print(f"✓ Final alley count: {len(gdf_alleys)} true outdoor corridors")
    
    # Prepare natural areas
    print(f"Processing {len(gdf_nature_proj)} natural/open space areas")
    original_count = len(gdf_nature_proj)
    
    # FILTER 1: Remove actual buildings that might have leaked through
    # (e.g., leisure=stadium might have building=yes)
    if 'building' in gdf_nature_proj.columns:
        gdf_nature_proj = gdf_nature_proj[
            gdf_nature_proj['building'].isnull() | (gdf_nature_proj['building'] == 'no')
        ]
        buildings_filtered = original_count - len(gdf_nature_proj)
        if buildings_filtered > 0:
            print(f"  ⚠️  Filtered out {buildings_filtered} buildings from vegetation candidates")
    
    # FILTER 2: Keep only Polygon and MultiPolygon geometries
    # (Remove any points or lines that might have been fetched)
    gdf_nature_proj = gdf_nature_proj[
        gdf_nature_proj.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])
    ]
    geometry_filtered = original_count - len(gdf_nature_proj)
    if geometry_filtered > 0:
        print(f"  ⚠️  Filtered out {geometry_filtered} non-polygon geometries from vegetation")
    
    print(f"  ✓ Remaining: {len(gdf_nature_proj)} valid vegetation/open space areas")
    
    gdf_nature_proj['area'] = gdf_nature_proj.geometry.area
    gdf_nature_proj['type'] = 'Vegetation'
    
    # Prepare buildings as potential rooftop launch sites
    print(f"Processing {len(gdf_buildings_proj)} buildings for rooftop analysis")
    gdf_buildings_proj['area'] = gdf_buildings_proj.geometry.area
    
    # Filter buildings for viable rooftops (reasonable size range)
    # Too small (<50 m²): sheds, garages - not viable
    # Too large (>5000 m²): massive complexes - too risky/secured
    gdf_buildings_filtered = gdf_buildings_proj[
        (gdf_buildings_proj['area'] > 50) & (gdf_buildings_proj['area'] < 5000)
    ]
    gdf_buildings_filtered = gdf_buildings_filtered.copy()
    gdf_buildings_filtered['type'] = 'Building'
    
    # Extract building-specific metadata for vertical accessibility analysis
    # Parse building:levels (handle missing, string values like "2;3", etc.)
    if 'building:levels' in gdf_buildings_filtered.columns:
        gdf_buildings_filtered['levels'] = gdf_buildings_filtered['building:levels'].apply(
            lambda x: int(str(x).split(';')[0]) if pd.notna(x) and str(x).replace('.','').isdigit() else 2
        )
    else:
        gdf_buildings_filtered['levels'] = 2  # Conservative default
    
    # Extract building type and office type for AHP building scoring
    gdf_buildings_filtered['building_type'] = gdf_buildings_filtered['building'] if 'building' in gdf_buildings_filtered.columns else None
    gdf_buildings_filtered['office_type'] = gdf_buildings_filtered['office'] if 'office' in gdf_buildings_filtered.columns else None
    # Preserve 'building' and 'amenity' columns for AHP building structure scoring
    gdf_buildings_filtered['building_tag'] = gdf_buildings_filtered['building'] if 'building' in gdf_buildings_filtered.columns else None
    gdf_buildings_filtered['amenity_tag'] = gdf_buildings_filtered['amenity'] if 'amenity' in gdf_buildings_filtered.columns else None
    
    print(f"  ✓ {len(gdf_buildings_filtered)} buildings qualify as potential rooftop sites (50-5000 m²)")
    print(f"  ✓ Building levels range: {gdf_buildings_filtered['levels'].min()}-{gdf_buildings_filtered['levels'].max()} floors")
    
    # Keep relevant columns for merging (add metadata columns)
    gdf_alleys_clean = gdf_alleys[['geometry', 'area', 'type']].copy()
    gdf_alleys_clean['levels'] = None
    gdf_alleys_clean['building_type'] = None
    gdf_alleys_clean['office_type'] = None
    gdf_alleys_clean['building_tag'] = None
    gdf_alleys_clean['amenity_tag'] = None
    
    gdf_nature_clean = gdf_nature_proj[['geometry', 'area', 'type']].copy()
    gdf_nature_clean['levels'] = None
    gdf_nature_clean['building_type'] = None
    gdf_nature_clean['office_type'] = None
    gdf_nature_clean['building_tag'] = None
    gdf_nature_clean['amenity_tag'] = None
    
    gdf_buildings_clean = gdf_buildings_filtered[['geometry', 'area', 'type', 'levels', 'building_type', 'office_type', 'building_tag', 'amenity_tag']].copy()
    
    # Merge all three datasets
    gdf_candidates = pd.concat([gdf_alleys_clean, gdf_nature_clean, gdf_buildings_clean], ignore_index=True)
    
    print(f"✓ Total launch candidates: {len(gdf_candidates)} (Alleys: {len(gdf_alleys)}, Vegetation: {len(gdf_nature_clean)}, Buildings: {len(gdf_buildings_clean)})")
    print(f"✓ Area range: {gdf_candidates['area'].min():.1f} - {gdf_candidates['area'].max():.1f} m²")
    
    # DEBUG: Verify type distribution after merge
    print(f"✓ Type distribution after merge: {dict(gdf_candidates['type'].value_counts())}")
    
    # Calculate accessibility and line-of-sight
    gdf_candidates = calculate_road_accessibility(gdf_candidates, G_proj, buildings_union)
    
    # Project security data to UTM and calculate security proximity
    # CRITICAL: Security data MUST be in same UTM CRS as candidates for accurate distance
    if len(gdf_security) > 0:
        gdf_security_proj = gdf_security.to_crs(utm_crs)
        print(f"✓ Security data projected to {utm_crs}")
        gdf_candidates = calculate_security_proximity(gdf_candidates, gdf_security_proj)
    else:
        gdf_candidates['nearest_security_dist'] = 9999
        print("⚠️  No security presence data available")
    
    # Calculate distance to center (Map Center / Target) for AHP distance scoring
    # This must be done before scoring so it's available in calculate_risk_score
    print("Calculating distances to map center for AHP distance scoring...")
    dist_to_center = []
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        dist = np.sqrt((centroid.x - center_x)**2 + (centroid.y - center_y)**2)
        dist_to_center.append(dist)
    
    gdf_candidates['dist_to_center'] = dist_to_center
    
    # Apply AHP-based threat scoring
    print("Calculating threat scores using AHP framework...")
    print(f"Applying AHP Distance Weight: {AHP_WEIGHTS['distance']}")
    gdf_candidates['threat_score'] = gdf_candidates.apply(calculate_risk_score, axis=1)
    
    print(f"✓ Threat scoring complete: Mean={gdf_candidates['threat_score'].mean():.1f}, Max={gdf_candidates['threat_score'].max():.1f}")
    
    # Calculate flight metrics
    DRONE_SPEED = 15  # m/s
    gdf_candidates['est_flight_time'] = gdf_candidates['dist_to_center'] / DRONE_SPEED
    
    # Project back to EPSG:4326 for GeoJSON output
    gdf_candidates = gdf_candidates.to_crs(epsg=4326)
    
    # DEBUG: Verify type distribution before returning
    print(f"✓ Final type distribution (before JSON): {dict(gdf_candidates['type'].value_counts())}")
    
    return gdf_candidates


# API Endpoints
@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": "Drone Launch Site Analysis API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Perform threat analysis for a location"
        }
    }


@app.post("/analyze", response_model=AnalysisResponse)
def analyze_location(request: AnalysisRequest):
    """
    Analyze a location for potential drone launch sites.
    
    Returns GeoJSON-compatible data with threat scores and statistics.
    """
    try:
        # Fetch area data
        gdf_buildings, gdf_nature, G, gdf_security = fetch_area_data(
            request.lat, 
            request.lon, 
            request.radius
        )
        
        # Find and score launch candidates
        gdf_candidates = find_launch_candidates(
            gdf_buildings, 
            gdf_nature, 
            G, 
            gdf_security,
            request.lat, 
            request.lon
        )
        
        # CRITICAL: Force conversion to WGS84 (EPSG:4326) for web mapping
        # This ensures coordinates are in Lat/Lon, not UTM meters
        gdf_candidates = gdf_candidates.to_crs(epsg=4326)
        
        # Debug: Verify CRS and sample coordinates
        print(f"✅ CRS after conversion: {gdf_candidates.crs}")
        if len(gdf_candidates) > 0:
            first_geom = gdf_candidates.iloc[0].geometry
            print(f"✅ Sample coordinates: {list(first_geom.exterior.coords)[:2]}")
        
        # Calculate statistics
        stats = {
            "total_candidates": len(gdf_candidates),
            "critical_count": len(gdf_candidates[gdf_candidates['threat_score'] > 80]),
            "high_count": len(gdf_candidates[(gdf_candidates['threat_score'] > 50) & (gdf_candidates['threat_score'] <= 80)]),
            "medium_count": len(gdf_candidates[gdf_candidates['threat_score'] <= 50]),
            "hidden_count": len(gdf_candidates[gdf_candidates['is_hidden']]),
            "exposed_count": len(gdf_candidates[~gdf_candidates['is_hidden']]),
            "alley_count": len(gdf_candidates[gdf_candidates['type'] == 'Alley']),
            "vegetation_count": len(gdf_candidates[gdf_candidates['type'] == 'Vegetation']),
            "mean_threat_score": round(gdf_candidates['threat_score'].mean(), 2),
            "max_threat_score": round(gdf_candidates['threat_score'].max(), 2),
            "mean_flight_time": round(gdf_candidates['est_flight_time'].mean(), 1),
            "min_flight_time": round(gdf_candidates['est_flight_time'].min(), 1),
            "near_security_count": len(gdf_candidates[gdf_candidates['nearest_security_dist'] < 150]),
            "security_monitored_count": len(gdf_candidates[gdf_candidates['nearest_security_dist'] < 300])
        }
        
        # Convert to GeoJSON features
        features = []
        for feature_id, (idx, row) in enumerate(gdf_candidates.iterrows()):
            feature = {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {
                    "id": feature_id,  # Use enumerate counter instead of index
                    "type": row['type'],
                    "threat_score": float(row['threat_score']),
                    "is_hidden": bool(row['is_hidden']),
                    "dist_to_road": float(row['dist_to_road']),
                    "dist_to_center": float(row['dist_to_center']),
                    "est_flight_time": float(row['est_flight_time']),
                    "area": float(row['area']),
                    "nearest_security_dist": float(row['nearest_security_dist']),
                    # Building-specific metadata
                    "levels": int(row['levels']) if pd.notna(row.get('levels')) else None,
                    "building_type": str(row['building_type']) if pd.notna(row.get('building_type')) else None,
                    "office_type": str(row['office_type']) if pd.notna(row.get('office_type')) else None
                }
            }
            features.append(feature)
        
        # DEBUG: Verify type distribution in serialized features
        type_counts = {}
        for f in features:
            t = f['properties']['type']
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"✅ Serialized features type breakdown: {type_counts}")
        
        # Serialize security nodes for debugging
        security_features = []
        if len(gdf_security) > 0:
            # Convert security data to WGS84 for web mapping
            gdf_security_wgs84 = gdf_security.to_crs(epsg=4326)
            print(f"✅ Serializing {len(gdf_security_wgs84)} security nodes for debug layer")
            
            for sec_id, (idx, row) in enumerate(gdf_security_wgs84.iterrows()):
                # Handle both Point and Polygon geometries
                if row.geometry.geom_type in ['Point', 'Polygon', 'MultiPolygon']:
                    security_feature = {
                        "type": "Feature",
                        "geometry": row.geometry.__geo_interface__,
                        "properties": {
                            "id": sec_id,  # Use enumerate counter
                            "amenity": str(row.get('amenity', '')),
                            "name": str(row.get('name', '')),
                            "building": str(row.get('building', '')),
                            "military": str(row.get('military', ''))
                        }
                    }
                    security_features.append(security_feature)
        
        return {
            "status": "success",
            "stats": stats,
            "features": features,
            "security_debug_layer": security_features
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Run with: uvicorn api:app --reload
# Access docs at: http://localhost:8000/docs
# Example request:
# curl -X POST "http://localhost:8000/analyze" \
#      -H "Content-Type: application/json" \
#      -d '{"lat": 28.6139, "lon": 77.2090, "radius": 1000}'
