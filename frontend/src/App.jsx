import { useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, Marker, Popup } from 'react-leaflet';
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

      console.log('📊 Analysis Response:', response.data);
      console.log('🗺️ First Feature Coordinates:', 
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

  const onEachFeature = (feature, layer) => {
    const props = feature.properties;
    const popupContent = `
      <div style="font-family: Arial, sans-serif;">
        <h4 style="margin: 0 0 8px 0; color: #333;">${props.type} Launch Site</h4>
        <p style="margin: 4px 0;"><strong>Threat Score:</strong> <span style="color: #FF0033; font-weight: bold;">${props.threat_score.toFixed(1)}/100</span></p>
        <p style="margin: 4px 0;"><strong>Stealth:</strong> ${props.is_hidden ? '🔴 HIDDEN (HIGH RISK)' : '🔵 EXPOSED'}</p>
        <p style="margin: 4px 0;"><strong>Flight Time:</strong> <span style="color: #FF6600; font-weight: bold;">${props.est_flight_time.toFixed(1)}s</span></p>
        <p style="margin: 4px 0;"><strong>Distance to Road:</strong> ${props.dist_to_road.toFixed(1)}m</p>
      </div>
    `;
    layer.bindPopup(popupContent);
  };

  return (
    <div className="dashboard">
      {/* Sidebar */}
      <div className="sidebar">
        <div className="sidebar-header">
          <h1>🎯 Drone Launch Site Analysis</h1>
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
              '🛰️ Scan Area'
            )}
          </button>

          {error && (
            <div className="error-message">
              <strong>Error:</strong> {error}
            </div>
          )}

          {data && (
            <div className="stats">
              <h3>📊 Analysis Results</h3>
              <div className="stat-grid">
                <div className="stat-item">
                  <span className="stat-label">Total Candidates</span>
                  <span className="stat-value">{data.stats.total_candidates}</span>
                </div>
                <div className="stat-item critical">
                  <span className="stat-label">Critical (&gt;80)</span>
                  <span className="stat-value">{data.stats.critical_count}</span>
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
                <h4>Legend</h4>
                <div className="legend-item">
                  <span className="legend-color" style={{backgroundColor: '#FF0033', opacity: 0.8}}></span>
                  <span>Hidden Threats (Critical)</span>
                </div>
                <div className="legend-item">
                  <span className="legend-color" style={{backgroundColor: '#00FFFF', opacity: 0.3}}></span>
                  <span>Exposed Sites (Lower Risk)</span>
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
              <strong>🎯 Primary Asset</strong>
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
              style={(feature) => ({
                fillColor: feature.properties.is_hidden ? '#FF0033' : '#00FFFF',
                color: feature.properties.is_hidden ? '#FF0033' : '#00FFFF',
                weight: 2,
                fillOpacity: feature.properties.is_hidden ? 0.8 : 0.3
              })}
              onEachFeature={onEachFeature}
            />
          )}
        </MapContainer>
      </div>
    </div>
  );
}

export default App;
