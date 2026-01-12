# Drone Launch Site Analysis

A geospatial analysis tool to identify and assess potential drone launch sites near critical infrastructure. Uses OpenStreetMap data to find alleys and vegetation areas, analyzes their accessibility, visibility, and threat level.

## Features

- **Morphological Analysis**: Identifies narrow alleys using geometric operations
- **Line-of-Sight Detection**: Determines if launch sites are hidden from roads by buildings
- **Threat Scoring**: Multi-factor risk assessment based on:
  - Accessibility (distance to road network)
  - Stealth (site type + visibility from roads)
  - Flight time to target
- **Interactive Dashboard**: Layered map with satellite imagery and toggleable threat categories

## Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

**Dependencies**: osmnx, geopandas, folium, shapely, matplotlib, numpy, pandas

## Usage

### Option 1: Standalone Dashboard (main.py)

Run the analysis for Delhi (default location) and generate an interactive HTML dashboard:

```bash
python main.py
```

Customize location by editing `main.py`:

```python
# Change these coordinates
lat = 28.6139  # Your latitude
lon = 77.2090  # Your longitude
radius = 1000  # Search radius in meters
```

### Option 2: FastAPI Backend (api.py)

Run as a REST API service:

```bash
uvicorn api:app --reload
```

**API Documentation**: Open http://localhost:8000/docs for interactive Swagger UI

**Example API Request**:

```bash
curl -X POST "http://localhost:8000/analyze" \
     -H "Content-Type: application/json" \
     -d '{"lat": 28.6139, "lon": 77.2090, "radius": 1000}'
```

**API Response**: Returns GeoJSON-compatible data with threat statistics

## Output

### Dashboard (main.py)

Generates `dashboard.html` with:

- **🔴 Hidden Threats**: Launch sites concealed from road view (highest risk)
- **🔵 Exposed Sites**: Visible locations (lower risk)
- **🎯 Primary Asset**: Center point marker (protected location)
- **Satellite Imagery**: Toggle between street map and aerial view

### Tooltip Information

Each site shows:
- **Type**: Alley or Vegetation
- **Threat Score**: 0-100 risk rating
- **Stealth**: Hidden (High Risk) or Exposed
- **Distance to Road**: Accessibility metric
- **Flight Time**: Estimated seconds to reach target (at 15 m/s)

### API Response (api.py)

Returns JSON with:

```json
{
  "status": "success",
  "stats": {
    "total_candidates": 42,
    "critical_count": 15,
    "hidden_count": 28,
    "mean_threat_score": 67.5,
    "mean_flight_time": 45.2
  },
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },
      "properties": {
        "type": "Alley",
        "threat_score": 95.2,
        "is_hidden": true,
        "dist_to_road": 127.5,
        "est_flight_time": 42.3
      }
    }
  ]
}
```

## Analysis Workflow

1. **Data Collection**: Downloads buildings, natural areas, and road network from OpenStreetMap
2. **Alley Detection**: Uses morphological operations to find narrow corridors
3. **Road Accessibility**: Calculates distance to nearest drivable road
4. **Line-of-Sight**: Ray-traces from each site to nearest road, checking for building obstruction
5. **Threat Scoring**: Combines accessibility (60%) and stealth (40%) with visibility modifiers
6. **Flight Metrics**: Calculates distance and time from launch sites to center point
7. **Dashboard**: Generates interactive map with layered visualization

## Threat Score Formula

```
Access Score: Linear decay 100 → 0 (50m → 500m from road)
Base Stealth: Alleys=80, Vegetation=60
Visibility Modifier: Hidden=+20, Exposed=-20
Final Score: (Access × 0.6) + (Stealth × 0.4), capped at 100
```

## Example Statistics

```
Total candidates: 42 (Alleys: 31, Vegetation: 11)
Critical threats (>80): 15 sites
Hidden from road: 28 sites (HIGH RISK)
Mean flight time: 45.2s
```

## License

For educational and security research purposes.
