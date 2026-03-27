# Config Parameters

Configuration for `src/constellation_path_viewer.py` is a JSON object.

Required:
- `place_a`: first endpoint, either `"City, Country"` or `"lat,lon"`
- `place_b`: second endpoint, either `"City, Country"` or `"lat,lon"`
- `constellation_a`: path to the primary constellation JSON, resolved relative to the config file
- `constellation_b`: path to the secondary constellation JSON, resolved relative to the config file

Common optional fields:
- `constellation_ixp`: path to an optional relay/IXP constellation JSON
- `city_db`: override `data/major-cities.csv`
- `log_dir`: override `logs/`
- `earth_texture_path`: override the Earth texture PNG; set to `""` to disable texture lookup
- `conservative_switch_threshold`: keep the current route unless a new route is sufficiently better
- `min_elevation_deg`: minimum ground-to-satellite elevation
- `default_isl_range_km`: fallback ISL range when the constellation JSON does not define one
- `default_inter_processing_delay_us`: per-satellite forwarding and processing delay, default `500`
- `log_interval_seconds`: CSV logging cadence

Viewer and UI knobs:
- `initial_time_scale`
- `autoplay`
- `initial_yaw_deg`
- `initial_pitch_deg`
- `initial_zoom`
- `show_earth`
- `window_title`
- `window_geometry`
- `min_window_width`
- `min_window_height`
- `step_seconds_small`
- `step_seconds_large`
- `zoom_min`
- `zoom_max`
- `zoom_factor`
- `drag_sensitivity`
- `pitch_limit_deg`
- `satellite_radius_active`
- `satellite_radius_inactive`
- `route_line_width`
- `earth_grid_line_width`
- `earth_texture_step_deg`
- `earth_grid_hidden_line_threshold`
- `earth_texture_hidden_line_threshold`
- `earth_texture_visible_vertex_threshold`
- `continent_visible_vertex_threshold`
- `camera_distance_multiplier`
- `scale_fill_ratio`
- `scale_divisor`

Reference configs:
- `config/oslo_auckland_starlink.json`
- `config/telesat-trd-ta.json`

Minimal example:
```json
{
  "place_a": "Oslo, Norway",
  "place_b": "Auckland, NZ",
  "constellation_a": "../data/starlink-constellation-shells.json",
  "constellation_b": "../data/starlink-constellation-shells.json"
}
```

Full template:
```bash
python3 src/constellation_path_viewer.py --emtpy-config config/my_route.json
```
