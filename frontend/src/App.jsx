import { useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, Polyline } from 'react-leaflet';
import L from 'leaflet';
import axios from 'axios';
import 'leaflet/dist/leaflet.css';
import './App.css';

// Fix default marker icon issue with Webpack
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

function App() {
  const [lat, setLat] = useState(28.6139);
  const [lon, setLon] = useState(77.2090);
  const [radius, setRadius] = useState(1000);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeAttackLine, setActiveAttackLine] = useState(null);

  const handleScanArea = async () => {
    setLoading(true);
    setError(null);
    setData(null);

    try {
      const response = await axios.post('http://127.0.0.1:8000/analyze', {
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        radius: parseInt(radius)
      });

      console.log('Analysis Response:', response.data);
      console.log('First Feature Coordinates:', 
        response.data.features[0]?.geometry?.coordinates);
      
      setData(response.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch analysis. Is the API running?');
      console.error('Error:', err);
    } finally {
      setLoading(false);
    }
  };

  const getFeatureStyle = (feature) => {
    const props = feature.properties;
    const score = props.threat_score;
    const siteType = props.type;
    
    // Determine fill color based on risk score
    let fillColor = '#ffff00'; // Default: Yellow (Low risk)
    if (score > 80) fillColor = '#ff0000'; // Red (Critical)
    else if (score > 50) fillColor = '#ff9900'; // Orange (High)
    
    // Distinguish by type
    if (siteType === 'Alley') {
      // Alleys: Black dashed border (urban corridors)
      return {
        fillColor: fillColor,
        color: '#000000',          // Black border
        weight: 3,                 // Thick border
        dashArray: '10, 5',        // Dashed pattern
        fillOpacity: 0.6
      };
    }
    
    if (siteType === 'Building') {
      // Buildings: Blue solid border (rooftops)
      return {
        fillColor: fillColor,
        color: '#0066ff',          // Blue border
        weight: 2,                 // Medium border
        dashArray: null,           // Solid line
        fillOpacity: 0.5
      };
    }
    
    // Vegetation: Green solid border (natural cover)
    return {
      fillColor: fillColor,
      color: '#00aa00',            // Green border
      weight: 1,                   // Thin border
      dashArray: null,             // Solid line
      fillOpacity: 0.4
    };
  };

  // Helper function to calculate centroid of a polygon
  const getCentroid = (coordinates) => {
    // For Polygon, coordinates[0] is the outer ring
    const ring = coordinates[0];
    let sumLat = 0;
    let sumLon = 0;
    
    for (let i = 0; i < ring.length; i++) {
      sumLon += ring[i][0];
      sumLat += ring[i][1];
    }
    
    return [sumLat / ring.length, sumLon / ring.length];
  };

  const onEachFeature = (feature, layer) => {
    const props = feature.properties;
    
    // DEBUG: Log feature properties to verify type field
    console.log("Feature Properties:", props);
    
    // Check if this is a security node (Point) vs launch site (Polygon)
    const isSecurityNode = feature.geometry.type === 'Point';
    
    if (isSecurityNode) {
      // Simple popup for security assets
      const securityName = props.amenity || props.name || props.building || 'Guardian';
      const popupContent = `
        <div style="font-family: 'Arial', sans-serif;">
          <h3 style="margin: 0 0 8px 0; color: #00aa00; font-size: 14px;">
            Security Asset
          </h3>
          <p style="margin: 4px 0; font-size: 12px;">
            <b>Type:</b> ${securityName}
          </p>
        </div>
      `;
      layer.bindPopup(popupContent);
      // Do NOT add attack vector click handler for security nodes
      return;
    }
    
    // Launch site logic (Polygon/MultiPolygon)
    const stealthStatus = props.is_hidden ? 'Hidden' : 'Exposed';
    const riskLevel = props.threat_score > 80 ? 'CRITICAL' : props.threat_score > 50 ? 'HIGH' : 'MEDIUM';
    
    const popupContent = `
      <div style="font-family: 'Arial', sans-serif; min-width: 250px;">
        <h3 style="margin: 0 0 12px 0; color: #333; border-bottom: 2px solid #666; padding-bottom: 8px; font-size: 16px;">
          Launch Site Detected
        </h3>
        <p style="margin: 8px 0; font-size: 14px;">
          <b>Risk Score:</b> 
          <span style="color: ${props.threat_score > 80 ? '#ff0000' : props.threat_score > 50 ? '#ff9900' : '#ffff00'}; font-weight: bold; font-size: 18px;">
            ${props.threat_score.toFixed(1)}/100
          </span>
          <span style="color: #666; font-size: 12px;"> (${riskLevel})</span>
        </p>
        <p style="margin: 8px 0; font-size: 14px;">
          <b>Stealth:</b> 
          <span style="color: ${props.is_hidden ? '#ff0000' : '#00aaff'}; font-weight: bold;">
            ${stealthStatus}
          </span>
        </p>
        <p style="margin: 8px 0; font-size: 14px;">
          <b>Distance to Road:</b> ${props.dist_to_road.toFixed(1)} m
        </p>
        <p style="margin: 8px 0; font-size: 14px;">
          <b>Flight Time:</b> ${props.est_flight_time.toFixed(1)}s
        </p>
        <p style="margin: 8px 0; font-size: 14px;">
          <b>Security Distance:</b> 
          <span style="color: ${props.nearest_security_dist < 150 ? '#00aa00' : props.nearest_security_dist < 300 ? '#ff9900' : '#ff0000'}; font-weight: bold;">
            ${props.nearest_security_dist < 999 ? props.nearest_security_dist.toFixed(0) + 'm' : 'None nearby'}
          </span>
        </p>
        <p style="margin: 8px 0; font-size: 12px; color: #666; border-top: 1px solid #ddd; padding-top: 8px;">
          <b>Type:</b> <span style="text-transform: capitalize; color: ${feature.properties.type === 'Alley' ? '#ff6600' : feature.properties.type === 'Building' ? '#0066ff' : '#00aa00'}; font-weight: bold;">${feature.properties.type}</span>
        </p>
        <p style="margin: 8px 0; font-size: 11px; color: #999; font-style: italic;">
          Click polygon to show attack vector
        </p>
      </div>
    `;
    layer.bindPopup(popupContent);
    
    // Add click event to show attack vector (only for launch sites)
    layer.on('click', () => {
      // Calculate centroid of the polygon
      const centroid = getCentroid(feature.geometry.coordinates);
      const targetPosition = [parseFloat(lat), parseFloat(lon)];
      
      // Set active attack line
      setActiveAttackLine([centroid, targetPosition]);
    });
  };

  return (
    <div className="dashboard">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <h1>Drone Launch Site Analysis</h1>
          <p className="subtitle">Geospatial Threat Assessment</p>
        </div>

        <div className="controls">
          <div className="input-group">
            <label htmlFor="lat">Latitude</label>
            <input
              id="lat"
              type="number"
              step="0.0001"
              value={lat}
              onChange={(e) => setLat(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="input-group">
            <label htmlFor="lon">Longitude</label>
            <input
              id="lon"
              type="number"
              step="0.0001"
              value={lon}
              onChange={(e) => setLon(e.target.value)}
              disabled={loading}
            />
          </div>

          <div className="input-group">
            <label htmlFor="radius">Radius (meters)</label>
            <input
              id="radius"
              type="number"
              step="100"
              value={radius}
              onChange={(e) => setRadius(e.target.value)}
              disabled={loading}
            />
          </div>

          <button
            className="scan-button"
            onClick={handleScanArea}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner"></span>
                Scanning...
              </>
            ) : (
              'Scan Area'
            )}
          </button>

          {error && (
            <div className="error-message">
              <strong>Error:</strong> {error}
            </div>
          )}

          {data && (
            <div className="stats">
              <h3>Analysis Results</h3>
              <div className="stat-grid">
                <div className="stat-item">
                  <span className="stat-label">Total Candidates</span>
                  <span className="stat-value">{data.stats.total_candidates}</span>
                </div>
                <div className="stat-item critical">
                  <span className="stat-label">Critical (&gt;80)</span>
                  <span className="stat-value">{data.stats.critical_count}</span>
                  <span className="stat-sublabel">Click sites to view vectors</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Hidden Sites</span>
                  <span className="stat-value">{data.stats.hidden_count}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Exposed Sites</span>
                  <span className="stat-value">{data.stats.exposed_count}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Mean Threat</span>
                  <span className="stat-value">{data.stats.mean_threat_score}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Min Flight Time</span>
                  <span className="stat-value">{data.stats.min_flight_time}s</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Near Security (&lt;150m)</span>
                  <span className="stat-value">{data.stats.near_security_count || 0}</span>
                </div>
                <div className="stat-item">
                  <span className="stat-label">Monitored (&lt;300m)</span>
                  <span className="stat-value">{data.stats.security_monitored_count || 0}</span>
                </div>
              </div>

              <div className="legend">
                <h4>Risk Level</h4>
                <div className="legend-item">
                  <span className="legend-color" style={{backgroundColor: '#ff0000', opacity: 0.6}}></span>
                  <span>Critical (&gt;80)</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color" style={{backgroundColor: '#ff9900', opacity: 0.6}}></span>
                  <span>High (50-80)</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color" style={{backgroundColor: '#ffff00', opacity: 0.6}}></span>
                  <span>Medium (&lt;50)</span>
                </div>
                <div style={{marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #334155'}}>
                  <div className="legend-item">
                    <span style={{display: 'inline-block', width: '24px', height: '2px', backgroundColor: '#ff0000', borderStyle: 'dashed'}}></span>
                    <span style={{fontSize: '12px'}}>Attack Vector (On Click)</span>
                  </div>
                  <p style={{fontSize: '11px', color: '#64748b', margin: '8px 0 0 0', fontStyle: 'italic'}}>
                    Click any polygon to show attack path
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Map */}
      <div className="map-container">
        <MapContainer
          center={[lat, lon]}
          zoom={15}
          style={{ height: '100%', width: '100%' }}
          onClick={() => setActiveAttackLine(null)}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {/* Primary Asset Marker */}
          <Marker position={[lat, lon]}>
            <Popup>
              <strong>Primary Asset</strong>
              <br />
              Center of Analysis
            </Popup>
          </Marker>

          {/* Render GeoJSON features */}
          {data && data.features && data.features.length > 0 && (
            <GeoJSON
              key={JSON.stringify(data.features)}
              data={{
                type: "FeatureCollection",
                features: data.features
              }}
              style={(feature) => {
                // Only apply style to polygons (launch sites)
                if (feature.geometry.type === 'Point') {
                  return {};
                }
                
                // Use our getFeatureStyle function that distinguishes Alleys from Vegetation
                return getFeatureStyle(feature);
              }}
              pointToLayer={(feature, latlng) => {
                // Create green markers for security nodes
                return L.marker(latlng, {
                  icon: L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                  })
                });
              }}
              onEachFeature={onEachFeature}
            />
          )}

          {/* Single Active Attack Vector (On-Demand) */}
          {activeAttackLine && (
            <Polyline
              positions={activeAttackLine}
              color="#ff0000"
              weight={2}
              opacity={0.8}
              dashArray="5, 10"
            >
              <Popup>
                <div style={{ fontFamily: 'Arial, sans-serif' }}>
                  <strong>Attack Vector</strong>
                  <p style={{ margin: '4px 0', fontSize: '12px' }}>
                    Click another site or map to clear
                  </p>
                </div>
              </Popup>
            </Polyline>
          )}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;
