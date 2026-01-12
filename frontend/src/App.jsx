import { useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, Popup, Polyline, LayerGroup } from 'react-leaflet';
import axios from 'axios';
import 'leaflet/dist/leaflet.css';
import './App.css';

function App() {
  const [lat, setLat] = useState(28.6139);
  const [lon, setLon] = useState(77.2090);
  const [radius, setRadius] = useState(1000);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
    const isHidden = feature.properties.is_hidden;
    return {
      fillColor: isHidden ? '#FF0033' : '#00FFFF',
      color: isHidden ? '#FF0033' : '#00FFFF',
      weight: 2,
      fillOpacity: isHidden ? 0.8 : 0.3
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
        <p style="margin: 8px 0; font-size: 12px; color: #666; border-top: 1px solid #ddd; padding-top: 8px;">
          <b>Type:</b> ${props.type}
        </p>
      </div>
    `;
    layer.bindPopup(popupContent);
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
                  <span className="stat-sublabel">Attack vectors shown</span>
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
                    <span style={{fontSize: '12px'}}>Attack Vector (Critical)</span>
                  </div>
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
                const score = feature.properties.threat_score;
                let color;
                
                // Risk-based color coding
                if (score > 80) {
                  color = '#ff0000';  // Red (Critical)
                } else if (score > 50) {
                  color = '#ff9900';  // Orange (High)
                } else {
                  color = '#ffff00';  // Yellow (Medium)
                }
                
                return {
                  fillColor: color,
                  color: color,
                  weight: 1,
                  fillOpacity: 0.6,
                  opacity: 0.8
                };
              }}
              onEachFeature={onEachFeature}
            />
          )}

          {/* Attack Vectors for Critical Sites */}
          {data && data.features && data.features.length > 0 && (
            <LayerGroup>
              {data.features
                .filter(feature => feature.properties.threat_score > 80)
                .map((feature, idx) => {
                  // Calculate centroid of the polygon
                  const centroid = getCentroid(feature.geometry.coordinates);
                  const targetPosition = [parseFloat(lat), parseFloat(lon)];
                  
                  return (
                    <Polyline
                      key={`attack-vector-${idx}`}
                      positions={[centroid, targetPosition]}
                      color="#ff0000"
                      weight={2}
                      opacity={0.7}
                      dashArray="5, 10"
                    >
                      <Popup>
                        <div style={{ fontFamily: 'Arial, sans-serif' }}>
                          <strong>Attack Vector</strong>
                          <p style={{ margin: '4px 0', fontSize: '12px' }}>
                            Threat Score: {feature.properties.threat_score.toFixed(1)}
                          </p>
                          <p style={{ margin: '4px 0', fontSize: '12px' }}>
                            Flight Time: {feature.properties.est_flight_time.toFixed(1)}s
                          </p>
                        </div>
                      </Popup>
                    </Polyline>
                  );
                })}
            </LayerGroup>
          )}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;
