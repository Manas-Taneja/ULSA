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
    """Calculate distance to nearest road and line-of-sight for each candidate."""
    distances = []
    hidden_status = []
    
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        nearest_node = ox.distance.nearest_nodes(G_proj, centroid.x, centroid.y)
        
        node_x = G_proj.nodes[nearest_node]['x']
        node_y = G_proj.nodes[nearest_node]['y']
        dist = np.sqrt((centroid.x - node_x)**2 + (centroid.y - node_y)**2)
        distances.append(dist)
        
        is_hidden = check_line_of_sight(centroid, nearest_node, G_proj, buildings_union)
        hidden_status.append(is_hidden)
    
    gdf_candidates['dist_to_road'] = distances
    gdf_candidates['is_hidden'] = hidden_status
    
    return gdf_candidates


def calculate_security_proximity(gdf_candidates, gdf_security_proj):
    """
    Calculate distance to nearest security presence for each candidate.
    
    Parameters:
    -----------
    gdf_candidates : GeoDataFrame
        Launch candidates in projected UTM CRS
    gdf_security_proj : GeoDataFrame
        Security locations in projected UTM CRS
        
    Returns:
    --------
    GeoDataFrame
        Candidates with nearest_security_dist column added
    """
    if len(gdf_security_proj) == 0:
        # No security presence, set large distance
        gdf_candidates['nearest_security_dist'] = 999999
        print("No security presence detected in area")
        return gdf_candidates
    
    # Get all security point coordinates
    security_points = []
    for idx, row in gdf_security_proj.iterrows():
        if row.geometry.geom_type == 'Point':
            security_points.append(row.geometry)
        elif row.geometry.geom_type in ['Polygon', 'MultiPolygon']:
            # Use centroid for polygon features
            security_points.append(row.geometry.centroid)
    
    # Calculate distance to nearest security for each candidate
    distances = []
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        
        # Find minimum distance to any security point
        min_dist = min([centroid.distance(sec_pt) for sec_pt in security_points])
        distances.append(min_dist)
    
    gdf_candidates['nearest_security_dist'] = distances
    print(f"Calculated security proximity (mean: {np.mean(distances):.1f}m)")
    return gdf_candidates


def calculate_score(row):
    """Calculate threat score based on accessibility, stealth, line-of-sight, and security presence."""
    dist = row['dist_to_road']
    site_type = row['type']
    is_hidden = row['is_hidden']
    security_dist = row.get('nearest_security_dist', 999999)
    
    # Access Score: Linear decay from 100 (at <50m) to 0 (at >500m)
    if dist < 50:
        access_score = 100
    elif dist > 500:
        access_score = 0
    else:
        access_score = 100 - ((dist - 50) / (500 - 50)) * 100
    
    # Base Stealth Score
    if site_type == 'Alley':
        stealth_score = 80
    else:  # Vegetation
        stealth_score = 60
    
    # Line-of-sight adjustment
    if is_hidden:
        stealth_score += 20
    else:
        stealth_score -= 20
    
    # Total: Weighted combination (Access 60%, Stealth 40%)
    raw_score = (access_score * 0.6) + (stealth_score * 0.4)
    raw_score = min(raw_score, 100)
    
    # Apply security presence penalty
    security_penalty = 0.0
    if security_dist < 150:
        security_penalty = 0.5  # 50% reduction within 150m
    elif security_dist < 300:
        security_penalty = 0.2  # 20% reduction within 300m
    
    final_score = raw_score * (1 - security_penalty)
    
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
    
    # Download security/guardian locations
    print("Downloading security presence data...")
    tags_security = {
        'amenity': ['police', 'embassy'],
        'military': ['barracks', 'office', 'checkpoint'],
        'man_made': ['surveillance'],
        'building': ['government']
    }
    try:
        gdf_security = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_security)
        print(f"Fetched {len(gdf_security)} security/guardian locations")
    except Exception as e:
        print(f"No security data found or error: {e}")
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
    
    # LOWERED area thresholds: min from 50 to 25, max from 1000 to 2000
    # This captures smaller parking spots and larger open areas
    gdf_alleys = gdf_alleys[(gdf_alleys['area'] > 25) & (gdf_alleys['area'] < 2000)]
    gdf_alleys['type'] = 'Alley'
    
    print(f"Remaining {len(gdf_alleys)} alleys after area filtering (25-2000 m²)")
    
    # Prepare natural areas
    print(f"Processing {len(gdf_nature_proj)} natural/open space areas")
    gdf_nature_proj['area'] = gdf_nature_proj.geometry.area
    gdf_nature_proj['type'] = 'Vegetation'
    
    # Keep only relevant columns for merging
    gdf_alleys_clean = gdf_alleys[['geometry', 'area', 'type']].copy()
    gdf_nature_clean = gdf_nature_proj[['geometry', 'area', 'type']].copy()
    
    # Merge both datasets
    gdf_candidates = pd.concat([gdf_alleys_clean, gdf_nature_clean], ignore_index=True)
    
    print(f"✓ Total launch candidates: {len(gdf_candidates)} (Alleys: {len(gdf_alleys)}, Open Spaces: {len(gdf_nature_clean)})")
    print(f"✓ Area range: {gdf_candidates['area'].min():.1f} - {gdf_candidates['area'].max():.1f} m²")
    
    # Calculate accessibility and line-of-sight
    gdf_candidates = calculate_road_accessibility(gdf_candidates, G_proj, buildings_union)
    
    # Project security data to UTM and calculate security proximity
    if len(gdf_security) > 0:
        gdf_security_proj = gdf_security.to_crs(utm_crs)
        gdf_candidates = calculate_security_proximity(gdf_candidates, gdf_security_proj)
    else:
        gdf_candidates['nearest_security_dist'] = 999999
        print("No security presence data available")
    
    # Apply threat scoring
    print("Calculating threat scores with stealth and security analysis...")
    gdf_candidates['threat_score'] = gdf_candidates.apply(calculate_score, axis=1)
    
    print(f"✓ Threat scoring complete: Mean={gdf_candidates['threat_score'].mean():.1f}, Max={gdf_candidates['threat_score'].max():.1f}")
    
    # Calculate flight metrics
    DRONE_SPEED = 15  # m/s
    dist_to_center = []
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        dist = np.sqrt((centroid.x - center_x)**2 + (centroid.y - center_y)**2)
        dist_to_center.append(dist)
    
    gdf_candidates['dist_to_center'] = dist_to_center
    gdf_candidates['est_flight_time'] = gdf_candidates['dist_to_center'] / DRONE_SPEED
    
    # Project back to EPSG:4326 for GeoJSON output
    gdf_candidates = gdf_candidates.to_crs(epsg=4326)
    
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
        for idx, row in gdf_candidates.iterrows():
            feature = {
                "type": "Feature",
                "geometry": row.geometry.__geo_interface__,
                "properties": {
                    "id": int(idx),
                    "type": row['type'],
                    "threat_score": float(row['threat_score']),
                    "is_hidden": bool(row['is_hidden']),
                    "dist_to_road": float(row['dist_to_road']),
                    "dist_to_center": float(row['dist_to_center']),
                    "est_flight_time": float(row['est_flight_time']),
                    "area": float(row['area']),
                    "nearest_security_dist": float(row['nearest_security_dist'])
                }
            }
            features.append(feature)
        
        return {
            "status": "success",
            "stats": stats,
            "features": features
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
