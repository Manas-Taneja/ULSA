# DTRAS: Drone Threat Risk Analysis System v2.0

## 1. System Overview

**DTRAS (Drone Threat Risk Analysis System)** is an automated geospatial intelligence tool that identifies and rates potential drone launch sites based on the **Analytical Hierarchical Process (AHP)** methodology. It replaces manual QGIS workflows with a "Zero-Human-In-The-Loop" web application, providing real-time threat assessment for critical infrastructure protection.

**Core Capabilities:**
- Automated identification of concealed launch sites (Alleys, Vegetation, Building Rooftops)
- Multi-factor threat scoring using research-based AHP weights
- 360° Ray-tracing for line-of-sight visibility analysis
- Security proximity detection (Guardian Layer)
- Elevation-aware terrain analysis
- Interactive web-based visualization
- Intelligence reporting (CSV export)

---

## 2. Methodology: The AHP Model

The system calculates a **Threat Score (0-100)** using 7 weighted factors derived from research-based threat assessment criteria. Each factor is normalized to a 0-100 scale and weighted according to the AHP matrix.

### AHP Factor Breakdown

| Factor | Weight | Logic | Score Range |
| :--- | :--- | :--- | :--- |
| **1. Distance to Core** | **36.29%** | Closer = Higher Risk. <500m = Score 5, >5km = Score 1. | 1-5 (normalized to 0-100) |
| **2. Building Structure** | **29.24%** | Residential (5) > Govt/Public (3) > Commercial (2). Only applies to Building-type sites. | 1-5 (normalized to 0-100) |
| **3. Road Infrastructure**| **13.68%** | Unpaved/Village Roads (5) > Residential (4) > Expressways (1). Based on OSM highway tags. | 1-5 (normalized to 0-100) |
| **4. Elevation Profile** | **10.57%** | High Ground Advantage. >10m above target = Score 5, >10m below = Score 2, level = Score 3. | 1-5 (normalized to 0-100) |
| **5. Land Use (LULC)** | **10.57%** | Alleys/Barren (5) > Fallow/Grass (3) > Agriculture (2). Based on natural/landuse OSM tags. | 1-5 (normalized to 0-100) |
| **6. Visual Line of Sight**| **4.60%** | Hidden Sites (5) > Exposed Sites (1). Ray-tracing from site to nearest road. | 1-5 (normalized to 0-100) |
| **7. Terrain Type** | **2.54%** | Hills/Peaks (5) > Water/Wetlands (4) > Plains (2). Based on natural OSM tags. | 1-5 (normalized to 0-100) |

### Threat Score Calculation

```
Threat Score = Σ(Component_i × Weight_i)

Where:
- Component_i = Normalized score (0-100) for factor i
- Weight_i = AHP weight for factor i
- Final score capped at 0-100
```

### Score Interpretation

- **80-100:** Critical threat (immediate attention required)
- **50-80:** High threat (priority monitoring)
- **0-50:** Medium threat (routine surveillance)

### Example Calculation

**Site:** Residential Building, 300m from core, hidden from road, 15m elevation advantage, unpaved road access

```
Distance:     5 × 20 × 0.3629 = 36.29
Building:     5 × 20 × 0.2924 = 29.24
Road:         5 × 20 × 0.1368 = 13.68
Elevation:    5 × 20 × 0.1057 = 10.57
LULC:         3 × 20 × 0.1057 = 6.34
VLOS:         5 × 20 × 0.0460 = 4.60
Terrain:      2 × 20 × 0.0254 = 1.02
─────────────────────────────────────
Total:                             101.74 → 100.00 (capped)
Result:        CRITICAL (>80)
```

---

## 3. Technical Architecture

### Technology Stack

**Backend:**
- **Python 3.12+** - Core language
- **FastAPI** - REST API framework
- **OSMnx** - OpenStreetMap data retrieval
- **GeoPandas** - Geospatial operations
- **Shapely** - Geometric computations
- **NetworkX** - Road network graph analysis
- **Scikit-Learn (cKDTree)** - Efficient spatial indexing for security proximity
- **Requests** - HTTP client for elevation API

**Frontend:**
- **React 19** - UI framework
- **Vite** - Build tool and dev server
- **React-Leaflet** - Interactive map visualization
- **Axios** - HTTP client

### System Flow

```
┌─────────────────┐
│   React Frontend │
│   (Vite Dev)     │
└────────┬─────────┘
         │ HTTP POST /analyze
         │ {lat, lon, radius}
         ↓
┌─────────────────┐
│   FastAPI       │
│   Backend       │
└────────┬────────┘
         │
         ├─→ OSMnx ──→ OpenStreetMap API
         │   (Buildings, Roads, Natural Areas, Security Assets)
         │
         ├─→ OpenTopoData API
         │   (SRTM 30m Elevation Data)
         │
         ├─→ Morphological Analysis
         │   (Alley Detection via Erosion/Dilation)
         │
         ├─→ Geometric Processing
         │   (Line-of-Sight Ray-Tracing, Distance Calculations)
         │
         ├─→ Spatial Indexing (KD-Tree)
         │   (Security Proximity Analysis)
         │
         └─→ AHP Threat Scoring
             (7-Factor Weighted Calculation)
         ↓
┌─────────────────┐
│   GeoJSON       │
│   Response      │
│   + Statistics  │
└─────────────────┘
```

### Data Sources

1. **OpenStreetMap (OSM)**
   - Building footprints and types
   - Road network (highway classification)
   - Natural areas (water, wood, sand, etc.)
   - Land use (forest, grass, construction, etc.)
   - Security assets (police, military, government buildings)

2. **OpenTopoData API**
   - SRTM 30m Global Elevation Data
   - Batch processing (50 coordinates per request)
   - Retry logic with 30-second timeout

---

## 4. Key Features

### 4.1 Morphological Detection

**Alley Detection Algorithm:**
- Uses morphological erosion/dilation to identify narrow corridors between buildings
- Erosion: `buffer(-2.0m)` removes gaps <4m wide
- Dilation: `buffer(2.1m)` reconstructs larger spaces
- Difference operation extracts alleys (4-10m wide passages)
- Filters: Area 25-2000 m², removes building edge artifacts

**Candidate Types:**
- **Alley:** Narrow urban corridors
- **Vegetation:** Parks, forests, open spaces
- **Building:** Rooftops (50-5000 m², filtered by size)

### 4.2 Stealth Analysis

**Line-of-Sight Ray-Tracing:**
- Creates straight line from launch site centroid to nearest road node
- Checks intersection with building union geometry
- Result: `is_hidden = True` if line intersects buildings
- Used in AHP VLOS scoring (4.60% weight)

### 4.3 Security Proximity (Guardian Layer)

**Security Asset Detection:**
- Automatically identifies:
  - Police stations, fire stations, courthouses
  - Government buildings, embassies, military facilities
  - Civic administration offices
- Uses KD-Tree spatial index for efficient nearest neighbor search
- Calculates `nearest_security_dist` for each candidate
- Visualized as green markers on map

**Security Zones:**
- **<150m:** Near security (highly monitored)
- **<300m:** Security-monitored zone
- **>300m:** Unmonitored area

### 4.4 Elevation-Aware Analysis

**Terrain Advantage:**
- Fetches elevation for target (core) and all candidates
- Compares site elevation vs. target elevation
- **>10m above:** Score 5 (tactical advantage)
- **Level (±10m):** Score 3 (neutral)
- **>10m below:** Score 2 (disadvantage)

### 4.5 Intelligence Reporting

**CSV Export:**
- Exports all candidates with full metadata
- Columns: ID, Site Type, Risk Score, Classification, Stealth Status, Altitude, Distance to Target, Road Type, Natural/Land Use Tags, Building Metadata, Security Distance
- Filename: `DTRAS_Threat_Report.csv`

---

## 5. Setup & Usage

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- Internet connection (for OSM and elevation API)

### Installation

**1. Backend Setup:**

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install fastapi uvicorn osmnx geopandas shapely numpy pandas scipy requests
```

**2. Frontend Setup:**

```bash
cd frontend
npm install
```

### Running the System

**1. Start Backend API:**

```bash
# From project root
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

API will be available at:
- **API:** http://localhost:8000
- **Interactive Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

**2. Start Frontend:**

```bash
# From frontend directory
npm run dev
```

Frontend will be available at:
- **Web App:** http://localhost:5173

### Usage Workflow

1. **Input Parameters:**
   - Enter latitude/longitude of primary asset (target)
   - Set search radius (100-5000 meters)
   - Click "Scan Area"

2. **Analysis Process:**
   - Backend downloads OSM data (~5-10s)
   - Performs morphological analysis (~2-3s)
   - Calculates accessibility and line-of-sight (~2-3s)
   - Fetches elevation data (~3-5s)
   - Applies AHP scoring (~1s)
   - **Total:** ~12-20 seconds

3. **Results:**
   - Interactive map with color-coded threat polygons
   - Statistics panel (total candidates, critical count, etc.)
   - Click polygons to view detailed threat intelligence
   - Click sites to display attack vectors
   - Export CSV report for offline analysis

### API Endpoint

**POST /analyze**

```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "Content-Type: application/json" \
     -d '{
       "lat": 28.6139,
       "lon": 77.2090,
       "radius": 1000
     }'
```

**Response:**
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
    "alley_count": 12,
    "vegetation_count": 18,
    "building_count": 12,
    "mean_threat_score": 67.5,
    "max_threat_score": 95.2,
    "mean_flight_time": 45.2,
    "min_flight_time": 12.5,
    "near_security_count": 5,
    "security_monitored_count": 12
  },
  "features": [...],
  "security_debug_layer": [...]
}
```

---

## 6. Output Format

### GeoJSON Feature Properties

Each launch site feature includes:

| Property | Type | Description |
|----------|------|-------------|
| `id` | integer | Unique feature identifier |
| `type` | string | 'Alley', 'Vegetation', or 'Building' |
| `threat_score` | float | AHP threat score (0-100) |
| `is_hidden` | boolean | Line-of-sight status (true = hidden) |
| `dist_to_road` | float | Distance to nearest road (meters) |
| `dist_to_center` | float | Distance to primary asset (meters) |
| `est_flight_time` | float | Estimated flight time at 15 m/s (seconds) |
| `area` | float | Site area (square meters) |
| `nearest_security_dist` | float | Distance to nearest security asset (meters, 9999 if none) |
| `nearest_road_type` | string | OSM highway tag (e.g., 'residential', 'motorway') |
| `natural_tag` | string | OSM natural tag (e.g., 'water', 'wood') |
| `landuse_tag` | string | OSM landuse tag (e.g., 'forest', 'grass') |
| `elevation_z` | float | Elevation in meters (from OpenTopoData) |
| `levels` | integer | Building floors (Building sites only) |
| `building_type` | string | Building classification (Building sites only) |
| `office_type` | string | Office classification (Building sites only) |

### Statistics Explained

| Metric | Description |
|--------|-------------|
| `total_candidates` | Total launch sites identified (all types) |
| `critical_count` | Sites with threat_score > 80 |
| `high_count` | Sites with threat_score 50-80 |
| `medium_count` | Sites with threat_score < 50 |
| `hidden_count` | Sites concealed from roads (is_hidden = true) |
| `exposed_count` | Sites visible from roads (is_hidden = false) |
| `alley_count` | Number of alley-type sites |
| `vegetation_count` | Number of vegetation-type sites |
| `building_count` | Number of building (rooftop) sites |
| `mean_threat_score` | Average threat score across all sites |
| `max_threat_score` | Highest threat score found |
| `mean_flight_time` | Average estimated flight time (seconds) |
| `min_flight_time` | Minimum estimated flight time (seconds) |
| `near_security_count` | Sites within 150m of security assets |
| `security_monitored_count` | Sites within 300m of security assets |

---

## 7. Mathematical Algorithms

### 7.1 Morphological Alley Detection

**Algorithm Steps:**

1. **Define Study Area:**
   ```python
   study_area = box(*gdf_buildings_proj.total_bounds)
   ```

2. **Calculate Open Space:**
   ```python
   buildings_union = unary_union(gdf_buildings_proj.geometry)
   open_space = study_area.difference(buildings_union)
   ```

3. **Morphological Erosion:**
   ```python
   wide_space = open_space.buffer(-2.0)  # Shrink by 2m
   ```
   - Removes gaps narrower than 4m (2m × 2)

4. **Morphological Dilation:**
   ```python
   reconstructed = wide_space.buffer(2.1)  # Expand by 2.1m
   ```
   - Slightly larger than erosion to prevent precision artifacts

5. **Extract Alleys:**
   ```python
   alleys = open_space.difference(reconstructed)
   ```
   - Difference = narrow corridors that vanished during erosion

6. **Filtering:**
   - Area: 25-2000 m²
   - Remove building edge artifacts (1m buffer check)

### 7.2 Line-of-Sight Ray-Tracing

**Algorithm:**
```python
def check_line_of_sight(centroid, nearest_node, G_proj, buildings_union):
    # Create sight line from site to road
    sight_line = LineString([
        (centroid.x, centroid.y),
        (node_x, node_y)
    ])
    
    # Check intersection with buildings
    is_hidden = sight_line.intersects(buildings_union)
    return is_hidden
```

**Complexity:** O(n log n) per site (Bentley-Ottmann algorithm)

### 7.3 Security Proximity (KD-Tree)

**Algorithm:**
```python
from scipy.spatial import cKDTree

# Build spatial index
security_tree = cKDTree(security_coords)

# Query nearest neighbor
distances, indices = security_tree.query(candidate_coords, k=1)
```

**Complexity:** O(log n) per query (vs. O(n) brute force)

### 7.4 Elevation Batch Processing

**Algorithm:**
- Process coordinates in batches of 50 (API limit)
- Retry logic: 3 attempts with 30-second timeout
- Fallback to 0m if API fails
- Parallel processing for efficiency

---

## 8. Performance Considerations

### Computational Complexity

| Operation | Complexity | Typical Time |
|-----------|-----------|--------------|
| OSM Data Download | O(n) | 5-10s |
| Morphological Operations | O(n×m) | 2-3s |
| Spatial Indexing (KD-Tree) | O(n log n) | <1s |
| Nearest Neighbor Search | O(log n) per query | <1s |
| Line-of-Sight Check | O(n log n) per site | 2-3s |
| Elevation API Calls | O(n/50) batches | 3-5s |
| AHP Threat Scoring | O(n) | <1s |

**Total Processing Time:** ~12-20 seconds for typical 1km radius analysis

### Scalability

- **Optimal radius:** 500-1500m
- **Maximum recommended:** 2500m
- **Performance degrades beyond 3000m** due to:
  - Increased OSM data volume
  - More buildings to process
  - Larger road network graph
  - More elevation API calls

### Optimization Strategies

1. **Caching:** Cache OSM data for repeated queries
2. **Parallel Processing:** Batch elevation requests
3. **Spatial Indexing:** KD-Tree for security proximity
4. **Early Filtering:** Remove invalid candidates before expensive operations

---

## 9. Use Cases

### 9.1 Critical Infrastructure Protection
- Identify vulnerable approach vectors
- Plan defensive countermeasures (sensor placement, barriers)
- Optimize security resource allocation

### 9.2 Event Security Planning
- Assess venues for drone threats before events
- Define security perimeters dynamically
- Allocate security resources based on threat density

### 9.3 Urban Planning
- Evaluate site vulnerability during design phase
- Identify high-risk areas requiring mitigation
- Inform building placement decisions

### 9.4 Threat Intelligence
- Generate reports on area vulnerability
- Compare threat profiles across multiple locations
- Track changes over time (historical analysis)

---

## 10. Limitations & Future Enhancements

### Current Limitations

1. **2D Analysis Only:** Does not consider building heights or 3D line-of-sight
2. **Static Data:** Uses snapshot of OSM data (not real-time updates)
3. **Weather Effects:** No wind, visibility, or seasonal vegetation changes
4. **Drone Capabilities:** Assumes standard commercial drone (15 m/s, direct path)

### Planned Enhancements

1. **3D Analysis:**
   - Building height consideration (OSM `building:levels`)
   - Vertical line-of-sight calculations
   - Elevation-aware flight paths

2. **Machine Learning Integration:**
   - Train model on historical drone incidents
   - Predict high-risk patterns
   - Automated feature weighting optimization

3. **Real-Time Monitoring:**
   - WebSocket integration for live updates
   - Change detection algorithms
   - Alert system for new threats

4. **Weather Integration:**
   - Wind speed/direction effects on flight time
   - Visibility conditions (fog, rain)
   - Seasonal vegetation changes

5. **Advanced Visualization:**
   - 3D terrain rendering
   - Heat maps for threat density
   - Time-series analysis

---

## 11. References

### Academic Foundations
- **Analytic Hierarchy Process (AHP):** Saaty, T.L. (1980). *The Analytic Hierarchy Process*
- **Morphological Image Processing:** Serra, J. (1982). *Image Analysis and Mathematical Morphology*
- **Computational Geometry:** de Berg, M., et al. (2008). *Computational Geometry: Algorithms and Applications*

### Technical Standards
- **GeoJSON Specification:** RFC 7946
- **WGS84 Coordinate System:** EPSG:4326
- **UTM Projection:** EPSG:326XX (varies by location)

### Data Sources
- **OpenStreetMap:** https://www.openstreetmap.org/
- **OpenTopoData API:** https://www.opentopodata.org/
- **OSMnx Documentation:** Boeing, G. (2017). *OSMnx: New Methods for Acquiring, Constructing, Analyzing, and Visualizing Complex Street Networks*

---

## 12. License & Disclaimer

**For Educational and Security Research Purposes**

This system is designed for legitimate security assessments and research. Users are responsible for complying with all applicable laws and regulations regarding:
- Drone operations
- Privacy considerations
- Data usage restrictions
- Security research ethics

**Not for Malicious Use**

The system is intended to help security professionals protect critical infrastructure, not to facilitate attacks. Any misuse of this tool is strictly prohibited.

---

## 13. Version History

- **v2.0 (Current):** AHP-based scoring, security proximity, elevation analysis, building rooftops
- **v1.0 (Legacy):** Simple 2-factor scoring, basic alley/vegetation detection (see `legacy_main_v1.py`)

---

**Documentation Version:** 2.0  
**Last Updated:** 2024  
**System Version:** DTRAS v2.0
