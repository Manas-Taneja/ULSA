import osmnx as ox
import geopandas as gpd
import folium
from shapely.geometry import box, Polygon, LineString
from shapely.ops import unary_union
import numpy as np
import pandas as pd


def check_line_of_sight(centroid, nearest_node, G_proj, buildings_union):
    """
    Check if there's a clear line of sight from candidate to road.
    
    Parameters:
    -----------
    centroid : Point
        Centroid of the candidate site
    nearest_node : node ID
        Nearest road network node
    G_proj : networkx.MultiDiGraph
        Road network in projected UTM CRS
    buildings_union : Shapely geometry
        Union of all buildings
        
    Returns:
    --------
    bool
        True if hidden (line of sight blocked by buildings), False if exposed
    """
    # Get coordinates of the nearest road node
    node_x = G_proj.nodes[nearest_node]['x']
    node_y = G_proj.nodes[nearest_node]['y']
    
    # Create a line from candidate to road
    sight_line = LineString([
        (centroid.x, centroid.y),
        (node_x, node_y)
    ])
    
    # Check if this line intersects with any building
    # If it intersects, the site is hidden from the road
    is_hidden = sight_line.intersects(buildings_union)
    
    return is_hidden


def calculate_road_accessibility(gdf_candidates, G_proj, buildings_union):
    """
    Calculate distance to nearest road and line-of-sight for each candidate.
    
    Parameters:
    -----------
    gdf_candidates : GeoDataFrame
        Launch candidates in projected UTM CRS
    G_proj : networkx.MultiDiGraph
        Road network in projected UTM CRS
    buildings_union : Shapely geometry
        Union of all buildings for line-of-sight checks
        
    Returns:
    --------
    GeoDataFrame
        Candidates with dist_to_road and is_hidden columns added
    """
    # Calculate distance to nearest road and line of sight for each candidate
    distances = []
    hidden_status = []
    
    for idx, row in gdf_candidates.iterrows():
        # Get centroid of the candidate
        centroid = row.geometry.centroid
        
        # Find nearest node
        nearest_node = ox.distance.nearest_nodes(G_proj, centroid.x, centroid.y)
        
        # Calculate distance to nearest node
        node_x = G_proj.nodes[nearest_node]['x']
        node_y = G_proj.nodes[nearest_node]['y']
        dist = np.sqrt((centroid.x - node_x)**2 + (centroid.y - node_y)**2)
        distances.append(dist)
        
        # Check line of sight
        is_hidden = check_line_of_sight(centroid, nearest_node, G_proj, buildings_union)
        hidden_status.append(is_hidden)
    
    gdf_candidates['dist_to_road'] = distances
    gdf_candidates['is_hidden'] = hidden_status
    
    return gdf_candidates


def calculate_score(row):
    """
    Calculate threat score based on accessibility, stealth, and line-of-sight.
    
    Parameters:
    -----------
    row : Series
        Row from GeoDataFrame with dist_to_road, type, and is_hidden columns
        
    Returns:
    --------
    float
        Threat score (0-100)
    """
    dist = row['dist_to_road']
    site_type = row['type']
    is_hidden = row['is_hidden']
    
    # Access Score: Linear decay from 100 (at <50m) to 0 (at >500m)
    if dist < 50:
        access_score = 100
    elif dist > 500:
        access_score = 0
    else:
        # Linear interpolation between 50m and 500m
        access_score = 100 - ((dist - 50) / (500 - 50)) * 100
    
    # Base Stealth Score: Based on site type
    if site_type == 'Alley':
        stealth_score = 80  # Alleys are more hidden
    else:  # Vegetation (parks, forests, etc.)
        stealth_score = 60  # Parks are less hidden than walled alleys
    
    # Line-of-sight adjustment
    if is_hidden:
        # Hidden from road = MORE dangerous (stealth bonus)
        stealth_score += 20
    else:
        # Visible from road = LESS dangerous (exposure penalty)
        stealth_score -= 20
    
    # Total: Weighted combination (Access 60%, Stealth 40%)
    total_score = (access_score * 0.6) + (stealth_score * 0.4)
    
    # Cap at 100
    total_score = min(total_score, 100)
    
    return round(total_score, 2)


def fetch_area_data(lat, lon, radius_meters):
    """
    Fetch building and natural area data for a given location.
    
    Parameters:
    -----------
    lat : float
        Latitude of the center point
    lon : float
        Longitude of the center point
    radius_meters : int
        Radius in meters to search around the center point
        
    Returns:
    --------
    tuple
        (gdf_buildings, gdf_nature, G) - Two GeoDataFrames and road network graph
    """
    # Calculate bounding box from center point
    bbox = ox.utils_geo.bbox_from_point((lat, lon), dist=radius_meters)
    north, south, east, west = bbox
    
    print(f"Bounding box: North={north:.4f}, South={south:.4f}, East={east:.4f}, West={west:.4f}")
    
    # Download buildings data
    print("Downloading buildings data...")
    tags_buildings = {'building': True}
    gdf_buildings = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_buildings)
    
    # Download natural/water areas data
    print("Downloading natural/water areas data...")
    tags_nature = {
        'natural': ['water', 'wood'],
        'landuse': ['forest', 'grass', 'basin']
    }
    gdf_nature = ox.features_from_bbox(bbox=(north, south, east, west), tags=tags_nature)
    
    # Download road network
    print("Downloading road network...")
    G = ox.graph_from_bbox(bbox=(north, south, east, west), network_type='drive')
    
    return gdf_buildings, gdf_nature, G


def find_launch_candidates(gdf_buildings, gdf_nature, G, center_lat, center_lon):
    """
    Find potential drone launch sites (alleys + natural areas) and score them.
    
    Parameters:
    -----------
    gdf_buildings : GeoDataFrame
        Buildings data
    gdf_nature : GeoDataFrame
        Natural/water areas data
    G : networkx.MultiDiGraph
        Road network graph
    center_lat : float
        Latitude of the primary asset/center point
    center_lon : float
        Longitude of the primary asset/center point
        
    Returns:
    --------
    GeoDataFrame
        All launch candidates with threat scores in WGS84
    """
    print("Projecting data to UTM CRS...")
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
    print("Projecting road network to UTM...")
    G_proj = ox.project_graph(G, to_crs=utm_crs)
    
    print("Calculating alleys using morphological operations...")
    # Define study area from bounding box
    study_area = box(*gdf_buildings_proj.total_bounds)
    
    # Calculate open space (area not occupied by buildings)
    buildings_union = unary_union(gdf_buildings_proj.geometry)
    open_space = study_area.difference(buildings_union)
    
    # Morphological operations to find alleys
    # Shrink by 2.5m (gaps narrower than 5m will vanish)
    wide_space = open_space.buffer(-2.5)
    
    # Reconstruct with slightly larger buffer
    reconstructed = wide_space.buffer(2.6)
    
    # Alleys are the difference between open space and reconstructed
    alleys = open_space.difference(reconstructed)
    
    # Convert to GeoDataFrame
    if alleys.geom_type == 'MultiPolygon':
        alley_polygons = list(alleys.geoms)
    elif alleys.geom_type == 'Polygon':
        alley_polygons = [alleys]
    else:
        alley_polygons = []
    
    gdf_alleys = gpd.GeoDataFrame(geometry=alley_polygons, crs=utm_crs)
    
    # Calculate area for each alley
    gdf_alleys['area'] = gdf_alleys.geometry.area
    
    # Filter: keep only alleys with area between 50 and 1000 sq meters
    gdf_alleys = gdf_alleys[(gdf_alleys['area'] > 50) & (gdf_alleys['area'] < 1000)]
    gdf_alleys['type'] = 'Alley'
    
    print(f"Found {len(gdf_alleys)} potential alleys")
    
    # Prepare natural areas
    print("Processing natural/vegetation areas...")
    gdf_nature_proj['area'] = gdf_nature_proj.geometry.area
    gdf_nature_proj['type'] = 'Vegetation'
    
    # Keep only relevant columns for merging
    gdf_alleys_clean = gdf_alleys[['geometry', 'area', 'type']].copy()
    gdf_nature_clean = gdf_nature_proj[['geometry', 'area', 'type']].copy()
    
    # Merge both datasets
    print("Merging alleys and vegetation into unified candidates...")
    gdf_candidates = pd.concat([gdf_alleys_clean, gdf_nature_clean], ignore_index=True)
    
    print(f"Total launch candidates: {len(gdf_candidates)} (Alleys: {len(gdf_alleys)}, Vegetation: {len(gdf_nature_clean)})")
    
    # Calculate accessibility and line-of-sight for ALL candidates
    print("Calculating distance to nearest road and line-of-sight for all candidates...")
    gdf_candidates = calculate_road_accessibility(gdf_candidates, G_proj, buildings_union)
    
    # Apply threat scoring to ALL candidates
    print("Calculating threat scores with stealth analysis...")
    gdf_candidates['threat_score'] = gdf_candidates.apply(calculate_score, axis=1)
    
    # Calculate flight metrics
    print("Calculating flight time estimates...")
    DRONE_SPEED = 15  # m/s (approx 50 km/h for commercial drones)
    
    # Calculate distance to center for each candidate
    dist_to_center = []
    for idx, row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        dist = np.sqrt((centroid.x - center_x)**2 + (centroid.y - center_y)**2)
        dist_to_center.append(dist)
    
    gdf_candidates['dist_to_center'] = dist_to_center
    gdf_candidates['est_flight_time'] = gdf_candidates['dist_to_center'] / DRONE_SPEED
    
    # Project back to EPSG:4326 for mapping
    gdf_candidates = gdf_candidates.to_crs(epsg=4326)
    
    return gdf_candidates


def get_color_by_score(score):
    """
    Get color based on threat score.
    
    Parameters:
    -----------
    score : float
        Threat score (0-100)
        
    Returns:
    --------
    str
        Color name
    """
    if score > 80:
        return 'darkred'  # Critical
    elif score > 50:
        return 'orange'   # High
    else:
        return 'yellow'   # Medium


def create_map(lat, lon, gdf_candidates, output_file='dashboard.html'):
    """
    Create and save an operational dashboard with layered visualization.
    
    Parameters:
    -----------
    lat : float
        Center latitude (Primary Asset location)
    lon : float
        Center longitude (Primary Asset location)
    gdf_candidates : GeoDataFrame
        All launch candidates with threat scores (in EPSG:4326)
    output_file : str
        Output HTML file name
    """
    print("Creating operational dashboard...")
    
    # Initialize map centered on the location with satellite base layer
    m = folium.Map(
        location=[lat, lon],
        zoom_start=15,
        tiles='OpenStreetMap'
    )
    
    # Add satellite imagery layer
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite Imagery',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Add OpenStreetMap layer
    folium.TileLayer(
        tiles='OpenStreetMap',
        name='Street Map',
        overlay=False,
        control=True
    ).add_to(m)
    
    # Create feature groups for different threat levels
    hidden_threats = folium.FeatureGroup(name='🔴 Hidden Threats (High Risk)', show=True)
    exposed_sites = folium.FeatureGroup(name='🔵 Exposed Sites (Lower Risk)', show=True)
    
    # Add candidates to appropriate layers
    if len(gdf_candidates) > 0:
        for idx, row in gdf_candidates.iterrows():
            score = row['threat_score']
            dist = row['dist_to_road']
            site_type = row['type']
            is_hidden = row['is_hidden']
            flight_time = row['est_flight_time']
            
            # Determine stealth status text
            if is_hidden:
                stealth_status = "Hidden (High Risk)"
                layer = hidden_threats
                color = 'red'
            else:
                stealth_status = "Exposed"
                layer = exposed_sites
                # Use orange for higher scores, blue for lower
                color = 'orange' if score > 50 else 'blue'
            
            # Create comprehensive tooltip with all metrics
            tooltip_text = (
                f"<b>Type:</b> {site_type}<br>"
                f"<b>Threat Score:</b> {score:.1f}/100<br>"
                f"<b>Stealth:</b> {stealth_status}<br>"
                f"<b>Dist to Road:</b> {dist:.1f}m<br>"
                f"<b>Flight Time:</b> {flight_time:.1f}s"
            )
            
            folium.GeoJson(
                row.geometry.__geo_interface__,
                style_function=lambda x, color=color: {
                    'fillColor': color,
                    'color': 'black',
                    'weight': 2,
                    'fillOpacity': 0.7
                },
                tooltip=folium.Tooltip(tooltip_text, sticky=True)
            ).add_to(layer)
    
    # Add feature groups to map
    hidden_threats.add_to(m)
    exposed_sites.add_to(m)
    
    # Add primary asset marker at center
    folium.Marker(
        location=[lat, lon],
        popup='<b>Primary Asset</b><br>Center of Analysis',
        tooltip='Primary Asset',
        icon=folium.Icon(color='black', icon='star', prefix='fa')
    ).add_to(m)
    
    # Add layer control to toggle layers
    folium.LayerControl(position='topright', collapsed=False).add_to(m)
    
    # Save map
    m.save(output_file)
    print(f"Dashboard saved to {output_file}")


if __name__ == "__main__":
    # Delhi coordinates
    lat = 28.6139
    lon = 77.2090
    radius = 1000  # meters
    
    print(f"Fetching data for location: ({lat}, {lon}) with radius {radius}m")
    print("-" * 60)
    
    # Fetch area data including road network
    gdf_buildings, gdf_nature, G = fetch_area_data(lat, lon, radius)
    
    # Print results
    print("-" * 60)
    print(f"Buildings retrieved: {gdf_buildings.shape}")
    print(f"Natural areas retrieved: {gdf_nature.shape}")
    print(f"Road network nodes: {len(G.nodes())}")
    print(f"Road network edges: {len(G.edges())}")
    print("-" * 60)
    
    # Find ALL potential drone launch sites (alleys + vegetation) and calculate threat scores
    gdf_candidates = find_launch_candidates(gdf_buildings, gdf_nature, G, lat, lon)
    
    print("-" * 60)
    print(f"Threat score statistics (all candidates):")
    print(f"  Mean: {gdf_candidates['threat_score'].mean():.2f}")
    print(f"  Max: {gdf_candidates['threat_score'].max():.2f}")
    print(f"  Min: {gdf_candidates['threat_score'].min():.2f}")
    print(f"  Critical (>80): {len(gdf_candidates[gdf_candidates['threat_score'] > 80])}")
    print(f"  High (50-80): {len(gdf_candidates[(gdf_candidates['threat_score'] > 50) & (gdf_candidates['threat_score'] <= 80)])}")
    print(f"  Medium (<50): {len(gdf_candidates[gdf_candidates['threat_score'] <= 50])}")
    print()
    print(f"Breakdown by type:")
    print(f"  Alleys: {len(gdf_candidates[gdf_candidates['type'] == 'Alley'])}")
    print(f"  Vegetation: {len(gdf_candidates[gdf_candidates['type'] == 'Vegetation'])}")
    print()
    print(f"Line-of-sight analysis:")
    print(f"  Hidden from road: {len(gdf_candidates[gdf_candidates['is_hidden']])} (HIGH RISK)")
    print(f"  Exposed to road: {len(gdf_candidates[~gdf_candidates['is_hidden']])}")
    print()
    print(f"Flight time statistics (at 15 m/s):")
    print(f"  Mean: {gdf_candidates['est_flight_time'].mean():.1f}s")
    print(f"  Min: {gdf_candidates['est_flight_time'].min():.1f}s")
    print(f"  Max: {gdf_candidates['est_flight_time'].max():.1f}s")
    print("-" * 60)
    
    # Create and save operational dashboard
    create_map(lat, lon, gdf_candidates, 'dashboard.html')
