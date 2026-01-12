# Drone Launch Site Analysis - Technical Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Data Ingestion](#data-ingestion)
4. [Mathematical Algorithms](#mathematical-algorithms)
5. [Threat Scoring Model](#threat-scoring-model)
6. [API Flow](#api-flow)
7. [Frontend Visualization](#frontend-visualization)
8. [Output Format](#output-format)

---

## System Overview

This system performs geospatial analysis to identify and assess potential drone launch sites near critical infrastructure. It combines OpenStreetMap data, geometric analysis, and threat modeling to provide actionable intelligence for security assessments.

**Core Capabilities:**
- Automated identification of concealed launch sites
- Line-of-sight visibility analysis
- Road network accessibility assessment
- Flight time estimation
- Interactive threat visualization

---

## Architecture

### Technology Stack

**Backend:**
- Python 3.12
- FastAPI (REST API)
- OSMnx (OpenStreetMap data)
- GeoPandas (Geospatial operations)
- Shapely (Geometric computations)
- NetworkX (Graph analysis)

**Frontend:**
- React 18
- Vite (Build tool)
- React-Leaflet (Map visualization)
- Axios (HTTP client)

**Data Sources:**
- OpenStreetMap (Buildings, natural areas, road network)

### System Diagram

```
┌─────────────────┐
│   Frontend      │
│   (React)       │
└────────┬────────┘
         │ HTTP POST /analyze
         │ {lat, lon, radius}
         ↓
┌─────────────────┐
│   FastAPI       │
│   Backend       │
└────────┬────────┘
         │
         ├─→ OSMnx ──→ OpenStreetMap API
         │   (Download spatial data)
         │
         ├─→ Geometric Analysis
         │   (Find alleys, calculate metrics)
         │
         └─→ Threat Assessment
             (Score and rank sites)
         ↓
┌─────────────────┐
│   GeoJSON       │
│   Response      │
└─────────────────┘
```

---

## Data Ingestion

### 1. Bounding Box Calculation

Given a center point (lat, lon) and radius (meters), the system calculates a geographic bounding box:

```python
bbox = ox.utils_geo.bbox_from_point((lat, lon), dist=radius_meters)
# Returns: (north, south, east, west)
```

**Mathematical Approach:**
- Uses Haversine formula to calculate corner coordinates
- Accounts for Earth's curvature
- Returns decimal degree coordinates

### 2. OpenStreetMap Data Retrieval

Three datasets are downloaded from OSM within the bounding box:

#### A. Buildings Layer
```python
tags = {'building': True}
gdf_buildings = ox.features_from_bbox(bbox, tags=tags)
```

**Retrieved Data:**
- Building footprints (polygons)
- Building types (residential, commercial, etc.)
- Address information (if available)

#### B. Natural/Vegetation Areas
```python
tags = {
    'natural': ['water', 'wood'],
    'landuse': ['forest', 'grass', 'basin']
}
gdf_nature = ox.features_from_bbox(bbox, tags=tags)
```

**Retrieved Data:**
- Parks and green spaces
- Forests and wooded areas
- Water bodies
- Open fields

#### C. Road Network
```python
G = ox.graph_from_bbox(bbox, network_type='drive')
```

**Retrieved Data:**
- Drivable road segments (edges)
- Road intersections (nodes)
- Road types and speeds
- Network topology

### 3. Coordinate System Transformation

All data is initially in WGS84 (EPSG:4326) but transformed to local UTM for metric calculations:

```python
utm_crs = gdf_buildings.estimate_utm_crs()
gdf_buildings_proj = gdf_buildings.to_crs(utm_crs)
```

**Why UTM?**
- Preserves distances and areas in meters
- Required for accurate buffer operations
- Enables precise geometric calculations

**Final Step:**
- All results converted back to WGS84 for web mapping

---

## Mathematical Algorithms

### 1. Alley Detection (Morphological Analysis)

**Objective:** Identify narrow corridors between buildings that could serve as concealed launch sites.

#### Algorithm Steps:

**Step 1: Define Study Area**
```python
study_area = box(*gdf_buildings_proj.total_bounds)
```
Creates a rectangular polygon encompassing all buildings.

**Step 2: Calculate Open Space**
```python
buildings_union = unary_union(gdf_buildings_proj.geometry)
open_space = study_area.difference(buildings_union)
```
Subtracts building footprints from study area to find unoccupied space.

**Step 3: Morphological Erosion**
```python
wide_space = open_space.buffer(-2.5)
```
Shrinks open space by 2.5 meters. Any gap narrower than 5 meters (2.5m × 2) vanishes.

**Mathematical Principle:**
- Buffer distance = -2.5m (negative = inward)
- Total filter = 2 × 2.5m = 5m minimum width
- Removes noise and very narrow passages

**Step 4: Morphological Dilation**
```python
reconstructed = wide_space.buffer(2.6)
```
Expands the eroded space by 2.6 meters (slightly more than erosion).

**Why 2.6m instead of 2.5m?**
- Prevents artifacts from floating-point precision
- Ensures proper reconstruction of legitimate open spaces

**Step 5: Extract Alleys**
```python
alleys = open_space.difference(reconstructed)
```
The difference represents narrow corridors that disappeared during erosion:
- These are the alleys (5-10m wide passages)
- Separated from larger open areas

**Step 6: Filtering**
```python
gdf_alleys = gdf_alleys[(gdf_alleys['area'] > 50) & (gdf_alleys['area'] < 1000)]
```
- **Minimum 50m²:** Removes noise and artifacts
- **Maximum 1000m²:** Excludes large plazas and squares

### 2. Line-of-Sight Analysis

**Objective:** Determine if a launch site is visible from the nearest road.

#### Ray-Tracing Algorithm:

```python
def check_line_of_sight(centroid, nearest_node, G_proj, buildings_union):
    # Get road node coordinates
    node_x = G_proj.nodes[nearest_node]['x']
    node_y = G_proj.nodes[nearest_node]['y']
    
    # Create sight line
    sight_line = LineString([
        (centroid.x, centroid.y),
        (node_x, node_y)
    ])
    
    # Check intersection with buildings
    is_hidden = sight_line.intersects(buildings_union)
    return is_hidden
```

**Mathematical Steps:**

1. **Find Centroid:** Calculate geometric center of launch site polygon
   ```
   centroid_x = Σ(x_i) / n
   centroid_y = Σ(y_i) / n
   ```

2. **Locate Nearest Road Node:** Use graph topology to find closest point in road network

3. **Create Ray:** Construct straight line from centroid to road node

4. **Intersection Test:** Use Shapely's `intersects()` which implements:
   - Bentley-Ottmann algorithm for line-polygon intersection
   - Complexity: O(n log n) where n = polygon vertices

5. **Result:**
   - `True` = Line intersects building → Site is **hidden**
   - `False` = No intersection → Site is **exposed**

### 3. Road Network Accessibility

**Objective:** Calculate distance from each launch site to the nearest drivable road.

#### Algorithm:

```python
def calculate_road_accessibility(gdf_candidates, G_proj, buildings_union):
    for row in gdf_candidates.iterrows():
        centroid = row.geometry.centroid
        
        # Find nearest node in road graph
        nearest_node = ox.distance.nearest_nodes(G_proj, centroid.x, centroid.y)
        
        # Calculate Euclidean distance
        node_x = G_proj.nodes[nearest_node]['x']
        node_y = G_proj.nodes[nearest_node]['y']
        dist = sqrt((centroid.x - node_x)² + (centroid.y - node_y)²)
```

**Mathematical Approach:**
- Uses K-D tree spatial index for efficient nearest neighbor search
- Complexity: O(log n) per query
- Euclidean distance formula:
  ```
  d = √[(x₂ - x₁)² + (y₂ - y₁)²]
  ```

### 4. Flight Time Estimation

**Objective:** Calculate time for drone to reach target from launch site.

```python
DRONE_SPEED = 15  # m/s (typical commercial drone, ~50 km/h)

# Distance to center (primary asset)
dist_to_center = sqrt((centroid.x - center_x)² + (centroid.y - center_y)²)

# Flight time
est_flight_time = dist_to_center / DRONE_SPEED
```

**Assumptions:**
- Constant speed (no acceleration/deceleration)
- Direct path (no obstacles)
- No wind effects
- Standard commercial drone capabilities

---

## Threat Scoring Model

### Analytical Hierarchy Process (AHP)

The system uses a weighted scoring model to quantify threat level:

```
Threat Score = (Access Score × 0.6) + (Stealth Score × 0.4)
```

### Component 1: Access Score

**Formula:**
```python
if distance_to_road < 50m:
    access_score = 100
elif distance_to_road > 500m:
    access_score = 0
else:
    access_score = 100 - ((dist - 50) / (500 - 50)) × 100
```

**Mathematical Representation:**
```
         ⎧ 100                              if d < 50
A(d) =   ⎨ 100 - [(d-50)/450 × 100]        if 50 ≤ d ≤ 500
         ⎩ 0                                if d > 500
```

**Rationale:**
- Sites < 50m from road: Excellent accessibility (100)
- Sites > 500m from road: Inaccessible for quick deployment (0)
- Linear decay between thresholds

### Component 2: Stealth Score

**Base Score by Type:**
```python
base_stealth = {
    'Alley': 80,       # High concealment (walls, buildings)
    'Vegetation': 60   # Moderate concealment (trees, bushes)
}
```

**Line-of-Sight Modifier:**
```python
if is_hidden:
    stealth_score = base_stealth + 20    # Bonus for invisibility
else:
    stealth_score = base_stealth - 20    # Penalty for visibility
```

**Mathematical Representation:**
```
         ⎧ base + 20    if hidden from road
S(t,v) = ⎨
         ⎩ base - 20    if visible from road

where:
  t = site type
  v = visibility status
  base = {80 for alleys, 60 for vegetation}
```

### Final Threat Score

```python
threat_score = min((A(d) × 0.6) + (S(t,v) × 0.4), 100)
```

**Score Interpretation:**
- **80-100:** Critical threat (immediate attention)
- **50-80:** High threat (priority monitoring)
- **0-50:** Medium threat (routine surveillance)

**Example Calculation:**

Site: Alley, 75m from road, hidden from view
```
Access Score:  100 - [(75-50)/450 × 100] = 94.4
Stealth Score: 80 + 20 = 100 (hidden alley)
Threat Score:  (94.4 × 0.6) + (100 × 0.4) = 96.64
Result:        CRITICAL (>80)
```

---

## API Flow

### Endpoint: POST /analyze

**Request:**
```json
{
  "lat": 28.6139,
  "lon": 77.2090,
  "radius": 1000
}
```

**Processing Pipeline:**

1. **Input Validation**
   - Pydantic model validates data types
   - Ensures radius between 100-5000m

2. **Data Retrieval** (~5-10 seconds)
   - Download buildings from OSM
   - Download natural areas from OSM
   - Download road network from OSM

3. **Geometric Processing** (~3-5 seconds)
   - Project to UTM
   - Apply morphological operations
   - Calculate centroids
   - Merge alley and vegetation datasets

4. **Accessibility Analysis** (~2-3 seconds)
   - Build spatial index
   - Find nearest road nodes
   - Calculate distances
   - Perform line-of-sight checks

5. **Threat Scoring** (~1 second)
   - Apply AHP formula to each site
   - Calculate flight metrics
   - Generate statistics

6. **Response Generation** (~1 second)
   - Convert to WGS84
   - Serialize to GeoJSON
   - Return formatted response

**Total Processing Time:** 12-20 seconds (varies by area complexity)

---

## Frontend Visualization

### React Component Architecture

```
App.jsx
├── Sidebar (Controls + Stats)
│   ├── Input Controls (lat, lon, radius)
│   ├── Scan Button
│   ├── Statistics Panel
│   └── Legend
└── Map Container (Leaflet)
    ├── Base Tile Layer (OpenStreetMap)
    ├── Primary Asset Marker
    ├── GeoJSON Layer (Polygons)
    └── Active Attack Vector (Polyline)
```

### Color Coding System

**Polygons:**
```javascript
if (threat_score > 80)  → Red (#ff0000)    // Critical
if (threat_score > 50)  → Orange (#ff9900) // High
if (threat_score ≤ 50)  → Yellow (#ffff00) // Medium
```

**Styling:**
- Fill Opacity: 0.6
- Stroke Weight: 1px
- Stroke Opacity: 0.8

### Interactive Features

**1. Polygon Click:**
- Displays detailed popup with metrics
- Shows attack vector line (dashed red)
- Calculates and renders path to primary asset

**2. Attack Vector:**
- Only one visible at a time (on-demand)
- Red dashed line (dashArray: "5, 10")
- Connects launch site centroid to primary asset
- Click elsewhere to clear

**3. Popups:**
- Threat score with color coding
- Stealth status (Hidden/Exposed)
- Distance to road
- Estimated flight time
- Site type

---

## Output Format

### GeoJSON Response Structure

```json
{
  "status": "success",
  "stats": {
    "total_candidates": 42,
    "critical_count": 15,
    "high_count": 18,
    "medium_count": 9,
    "hidden_count": 28,
    "exposed_count": 14,
    "alley_count": 31,
    "vegetation_count": 11,
    "mean_threat_score": 67.5,
    "max_threat_score": 95.2,
    "mean_flight_time": 45.2,
    "min_flight_time": 12.5
  },
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[77.2090, 28.6139], ...]]
      },
      "properties": {
        "id": 0,
        "type": "Alley",
        "threat_score": 95.2,
        "is_hidden": true,
        "dist_to_road": 127.5,
        "dist_to_center": 523.4,
        "est_flight_time": 34.9,
        "area": 245.6
      }
    }
  ]
}
```

### Statistics Explained

| Metric | Description | Units |
|--------|-------------|-------|
| `total_candidates` | Total launch sites identified | count |
| `critical_count` | Sites with score > 80 | count |
| `hidden_count` | Sites concealed from roads | count |
| `mean_threat_score` | Average threat across all sites | 0-100 |
| `mean_flight_time` | Average time to reach target | seconds |

### Feature Properties

| Property | Type | Description |
|----------|------|-------------|
| `threat_score` | float | Overall threat rating (0-100) |
| `is_hidden` | boolean | Line-of-sight status |
| `dist_to_road` | float | Distance to nearest road (meters) |
| `dist_to_center` | float | Distance to primary asset (meters) |
| `est_flight_time` | float | Estimated flight time (seconds) |
| `type` | string | 'Alley' or 'Vegetation' |
| `area` | float | Site area (square meters) |

---

## Use Cases

### 1. Critical Infrastructure Protection
- Identify vulnerable approach vectors
- Plan defensive countermeasures
- Optimize sensor placement

### 2. Event Security Planning
- Assess venues for drone threats
- Define security perimeters
- Allocate security resources

### 3. Urban Planning
- Evaluate site vulnerability during design phase
- Identify high-risk areas requiring mitigation
- Inform building placement decisions

### 4. Threat Intelligence
- Generate reports on area vulnerability
- Compare threat profiles across locations
- Track changes over time

---

## Performance Considerations

### Computational Complexity

| Operation | Complexity | Typical Time |
|-----------|-----------|--------------|
| OSM Data Download | O(n) | 5-10s |
| Morphological Operations | O(n×m) | 2-3s |
| Spatial Indexing | O(n log n) | 1s |
| Nearest Neighbor Search | O(log n) per query | <1s |
| Line-of-Sight Check | O(n) per site | 2-3s |
| Threat Scoring | O(n) | <1s |

**Total:** ~12-20 seconds for typical 1km radius analysis

### Scalability

- **Optimal radius:** 500-1500m
- **Maximum recommended:** 2500m
- **Performance degrades beyond 3000m** due to:
  - Increased OSM data volume
  - More buildings to process
  - Larger road network graph

---

## Future Enhancements

1. **Machine Learning Integration**
   - Train model on historical drone incidents
   - Predict high-risk patterns
   - Automated feature weighting

2. **Real-Time Monitoring**
   - WebSocket integration for live updates
   - Change detection algorithms
   - Alert system for new threats

3. **3D Analysis**
   - Building height consideration
   - Vertical line-of-sight
   - Elevation-aware flight paths

4. **Weather Integration**
   - Wind speed/direction effects
   - Visibility conditions
   - Seasonal vegetation changes

---

## References

### Academic Foundations
- Morphological Image Processing (Serra, 1982)
- Computational Geometry (de Berg et al., 2008)
- Analytic Hierarchy Process (Saaty, 1980)

### Technical Standards
- GeoJSON Specification (RFC 7946)
- Web Mercator Projection (EPSG:3857)
- WGS84 Coordinate System (EPSG:4326)

### Data Sources
- OpenStreetMap Contributors
- OSMnx Documentation (Boeing, 2017)

---

## License & Disclaimer

**For Educational and Security Research Purposes**

This system is designed for legitimate security assessments and research. Users are responsible for complying with all applicable laws and regulations regarding:
- Drone operations
- Privacy considerations
- Data usage restrictions
- Security research ethics

**Not for Malicious Use**
