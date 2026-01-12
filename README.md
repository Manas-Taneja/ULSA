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

### Quick Start

Run the analysis for Delhi (default location):

```bash
python main.py
```

### Customize Location

Edit `main.py` to analyze a different location:

```python
# Change these coordinates
lat = 28.6139  # Your latitude
lon = 77.2090  # Your longitude
radius = 1000  # Search radius in meters
```

## Output

The script generates `dashboard.html` with:

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
