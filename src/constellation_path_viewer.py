#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Visualize a dynamic satellite path between two ground locations.

Usage:
    python3 tools/src/constellation_path_viewer.py tools/config/oslo_auckland_starlink.json

This viewer is stdlib-only. Place resolution uses a small built-in gazetteer
plus direct "lat,lon" parsing for arbitrary coordinates.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import os
import pathlib
import re
import time
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk


SCRIPT_PATH = pathlib.Path(__file__).resolve()
EARTH_RADIUS_KM = 6371.0
EARTH_MU_M3_S2 = 3.986004418e14
SECONDS_PER_HOUR = 3600.0
LIGHT_SPEED_KM_S = 299792.458
MIN_ELEVATION_DEG = 10.0
DEFAULT_ISL_RANGE_KM = 2600.0
DEFAULT_INTER_PROCESSING_DELAY_US = 500.0
EARTH_TEXTURE_STEP_DEG = 6
GROUND_LINK_ELEVATION_PREFERENCE = 0.65
LOG_INTERVAL_SECONDS = 15.0


COUNTRY_ALIASES = {
    "nz": "newzealand",
    "uk": "unitedkingdom",
    "us": "unitedstates",
    "usa": "unitedstates",
    "uae": "unitedarabemirates",
}


CONTINENT_POLYGONS = [
    [
        (72, -165), (60, -150), (50, -130), (42, -124), (32, -117), (24, -110), (18, -103),
        (15, -95), (20, -85), (28, -81), (35, -76), (43, -66), (50, -60), (57, -72), (64, -95),
        (70, -120), (72, -165),
    ],
    [
        (60, -52), (72, -44), (79, -20), (74, -12), (66, -24), (60, -40), (60, -52),
    ],
    [
        (12, -81), (8, -75), (3, -70), (-5, -66), (-15, -63), (-25, -60), (-35, -58), (-47, -67),
        (-55, -73), (-52, -58), (-40, -49), (-25, -45), (-10, -38), (0, -42), (6, -50), (10, -60),
        (12, -81),
    ],
    [
        (72, -10), (70, 20), (66, 45), (62, 65), (58, 95), (56, 125), (50, 145), (42, 150),
        (32, 138), (20, 122), (10, 105), (8, 86), (20, 74), (24, 58), (31, 42), (35, 30),
        (32, 20), (30, 10), (36, -5), (46, -10), (56, -5), (64, -8), (72, -10),
    ],
    [
        (37, -17), (31, 0), (25, 12), (18, 20), (9, 22), (2, 28), (-8, 33), (-18, 32), (-27, 28),
        (-34, 20), (-35, 10), (-30, 2), (-22, -5), (-8, -10), (5, -5), (15, -2), (24, -10),
        (32, -14), (37, -17),
    ],
    [
        (6, 95), (15, 100), (22, 108), (18, 118), (10, 122), (2, 120), (-4, 114), (-6, 105), (0, 98), (6, 95),
    ],
    [
        (-10, 113), (-20, 115), (-28, 121), (-34, 131), (-36, 142), (-31, 153), (-23, 151), (-16, 144),
        (-13, 134), (-12, 124), (-10, 113),
    ],
    [
        (-35, 172), (-41, 174), (-45, 169), (-43, 176), (-36, 178), (-35, 172),
    ],
]


@dataclass(frozen=True)
class ShellDefinition:
    dataset_label: str
    section_label: str
    shell_id: str
    shell_label: str
    altitude_km: float
    inclination_deg: float
    num_planes: int
    sats_per_plane: int
    planned_satellites: int
    notes: str
    exact_layout: bool

    @property
    def satellite_count(self) -> int:
        return self.num_planes * self.sats_per_plane


@dataclass(frozen=True)
class Satellite:
    index: int
    node_id: str
    constellation_role: str
    constellation_label: str
    shell_index: int
    shell: ShellDefinition
    plane_index: int
    slot_index: int
    label: str


@dataclass(frozen=True)
class GroundPoint:
    name: str
    latitude_deg: float
    longitude_deg: float

    @property
    def position(self) -> tuple[float, float, float]:
        return geodetic_to_ecef(self.latitude_deg, self.longitude_deg)


@dataclass(frozen=True)
class PathViewerSettings:
    city_db_path: pathlib.Path = field(default_factory=lambda: CITY_DB_PATH)
    log_dir: pathlib.Path = field(default_factory=lambda: LOG_DIR)
    earth_texture_path: pathlib.Path | None = field(default_factory=lambda: EARTH_TEXTURE_PATH)
    conservative_switch_threshold: float = 0.0
    min_elevation_deg: float = MIN_ELEVATION_DEG
    default_isl_range_km: float = DEFAULT_ISL_RANGE_KM
    default_inter_processing_delay_us: float = DEFAULT_INTER_PROCESSING_DELAY_US
    earth_texture_step_deg: int = EARTH_TEXTURE_STEP_DEG
    ground_link_elevation_preference: float = GROUND_LINK_ELEVATION_PREFERENCE
    log_interval_seconds: float = LOG_INTERVAL_SECONDS
    initial_time_scale: float = 1.0 / 60.0
    autoplay: bool = True
    initial_yaw_deg: float = -25.0
    initial_pitch_deg: float = 18.0
    initial_zoom: float = 1.0
    show_earth: bool = True
    window_title: str = "STARS Constellation Path Viewer"
    window_geometry: str = "1460x900"
    min_window_width: int = 1180
    min_window_height: int = 760
    step_seconds_small: float = 300.0
    step_seconds_large: float = 1800.0
    zoom_min: float = 0.5
    zoom_max: float = 3.5
    zoom_factor: float = 1.1
    drag_sensitivity: float = 0.008
    pitch_limit_deg: float = 89.0
    satellite_radius_active: float = 4.2
    satellite_radius_inactive: float = 1.5
    route_line_width: int = 3
    earth_grid_line_width: int = 1
    earth_grid_hidden_line_threshold: float = 0.05
    earth_texture_hidden_line_threshold: float = 0.08
    earth_texture_visible_vertex_threshold: float = 0.12
    continent_visible_vertex_threshold: float = 0.15
    camera_distance_multiplier: float = 3.2
    scale_fill_ratio: float = 0.9
    scale_divisor: float = 4.5

    @classmethod
    def from_payload(cls, payload: dict, config_path: pathlib.Path) -> PathViewerSettings:
        return cls(
            city_db_path=resolve_optional_path(payload.get("city_db"), config_path.parent, CITY_DB_PATH),
            log_dir=resolve_optional_path(payload.get("log_dir"), config_path.parent, LOG_DIR, must_exist=False),
            earth_texture_path=resolve_optional_path(
                payload.get("earth_texture_path"),
                config_path.parent,
                EARTH_TEXTURE_PATH,
                allow_none=True,
            ),
            conservative_switch_threshold=require_non_negative_float(
                payload, "conservative_switch_threshold", 0.0
            ),
            min_elevation_deg=require_non_negative_float(payload, "min_elevation_deg", MIN_ELEVATION_DEG),
            default_isl_range_km=require_positive_float(payload, "default_isl_range_km", DEFAULT_ISL_RANGE_KM),
            default_inter_processing_delay_us=require_non_negative_float(
                payload, "default_inter_processing_delay_us", DEFAULT_INTER_PROCESSING_DELAY_US
            ),
            earth_texture_step_deg=require_positive_int(payload, "earth_texture_step_deg", EARTH_TEXTURE_STEP_DEG),
            ground_link_elevation_preference=require_non_negative_float(
                payload, "ground_link_elevation_preference", GROUND_LINK_ELEVATION_PREFERENCE
            ),
            log_interval_seconds=require_positive_float(payload, "log_interval_seconds", LOG_INTERVAL_SECONDS),
            initial_time_scale=require_non_negative_float(payload, "initial_time_scale", 1.0 / 60.0),
            autoplay=require_bool(payload, "autoplay", True),
            initial_yaw_deg=require_float(payload, "initial_yaw_deg", -25.0),
            initial_pitch_deg=require_float(payload, "initial_pitch_deg", 18.0),
            initial_zoom=require_positive_float(payload, "initial_zoom", 1.0),
            show_earth=require_bool(payload, "show_earth", True),
            window_title=require_string(payload, "window_title", "STARS Constellation Path Viewer"),
            window_geometry=require_string(payload, "window_geometry", "1460x900"),
            min_window_width=require_positive_int(payload, "min_window_width", 1180),
            min_window_height=require_positive_int(payload, "min_window_height", 760),
            step_seconds_small=require_non_negative_float(payload, "step_seconds_small", 300.0),
            step_seconds_large=require_non_negative_float(payload, "step_seconds_large", 1800.0),
            zoom_min=require_positive_float(payload, "zoom_min", 0.5),
            zoom_max=require_positive_float(payload, "zoom_max", 3.5),
            zoom_factor=require_positive_float(payload, "zoom_factor", 1.1),
            drag_sensitivity=require_positive_float(payload, "drag_sensitivity", 0.008),
            pitch_limit_deg=require_positive_float(payload, "pitch_limit_deg", 89.0),
            satellite_radius_active=require_positive_float(payload, "satellite_radius_active", 4.2),
            satellite_radius_inactive=require_positive_float(payload, "satellite_radius_inactive", 1.5),
            route_line_width=require_positive_int(payload, "route_line_width", 3),
            earth_grid_line_width=require_positive_int(payload, "earth_grid_line_width", 1),
            earth_grid_hidden_line_threshold=require_non_negative_float(
                payload, "earth_grid_hidden_line_threshold", 0.05
            ),
            earth_texture_hidden_line_threshold=require_non_negative_float(
                payload, "earth_texture_hidden_line_threshold", 0.08
            ),
            earth_texture_visible_vertex_threshold=require_non_negative_float(
                payload, "earth_texture_visible_vertex_threshold", 0.12
            ),
            continent_visible_vertex_threshold=require_non_negative_float(
                payload, "continent_visible_vertex_threshold", 0.15
            ),
            camera_distance_multiplier=require_positive_float(payload, "camera_distance_multiplier", 3.2),
            scale_fill_ratio=require_positive_float(payload, "scale_fill_ratio", 0.9),
            scale_divisor=require_positive_float(payload, "scale_divisor", 4.5),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "city_db_path": str(self.city_db_path),
            "log_dir": str(self.log_dir),
            "earth_texture_path": str(self.earth_texture_path) if self.earth_texture_path else None,
            "conservative_switch_threshold": self.conservative_switch_threshold,
            "min_elevation_deg": self.min_elevation_deg,
            "default_isl_range_km": self.default_isl_range_km,
            "default_inter_processing_delay_us": self.default_inter_processing_delay_us,
            "earth_texture_step_deg": self.earth_texture_step_deg,
            "ground_link_elevation_preference": self.ground_link_elevation_preference,
            "log_interval_seconds": self.log_interval_seconds,
            "initial_time_scale": self.initial_time_scale,
            "autoplay": self.autoplay,
            "initial_yaw_deg": self.initial_yaw_deg,
            "initial_pitch_deg": self.initial_pitch_deg,
            "initial_zoom": self.initial_zoom,
            "show_earth": self.show_earth,
            "window_title": self.window_title,
            "window_geometry": self.window_geometry,
            "min_window_width": self.min_window_width,
            "min_window_height": self.min_window_height,
            "step_seconds_small": self.step_seconds_small,
            "step_seconds_large": self.step_seconds_large,
            "zoom_min": self.zoom_min,
            "zoom_max": self.zoom_max,
            "zoom_factor": self.zoom_factor,
            "drag_sensitivity": self.drag_sensitivity,
            "pitch_limit_deg": self.pitch_limit_deg,
            "satellite_radius_active": self.satellite_radius_active,
            "satellite_radius_inactive": self.satellite_radius_inactive,
            "route_line_width": self.route_line_width,
            "earth_grid_line_width": self.earth_grid_line_width,
            "earth_grid_hidden_line_threshold": self.earth_grid_hidden_line_threshold,
            "earth_texture_hidden_line_threshold": self.earth_texture_hidden_line_threshold,
            "earth_texture_visible_vertex_threshold": self.earth_texture_visible_vertex_threshold,
            "continent_visible_vertex_threshold": self.continent_visible_vertex_threshold,
            "camera_distance_multiplier": self.camera_distance_multiplier,
            "scale_fill_ratio": self.scale_fill_ratio,
            "scale_divisor": self.scale_divisor,
        }


@dataclass(frozen=True)
class ViewerConfig:
    place_a: str
    place_b: str
    constellation_a: pathlib.Path
    constellation_b: pathlib.Path
    settings: PathViewerSettings
    constellation_ixp: pathlib.Path | None = None


@dataclass(frozen=True)
class LoadedConstellation:
    role: str
    path: pathlib.Path
    shells: list[ShellDefinition]
    isl_range_km: float


@dataclass(frozen=True)
class CityEntry:
    name: str
    country: str
    latitude_deg: float
    longitude_deg: float


def find_project_root(start: pathlib.Path | None = None) -> pathlib.Path:
    search_start = (start or SCRIPT_PATH).resolve()
    for candidate in (search_start, *search_start.parents):
        if (candidate / "data" / "major-cities.csv").exists():
            return candidate
    raise SystemExit(
        f"Could not locate project root from {search_start}. Expected to find data/major-cities.csv in a parent directory."
    )


PROJECT_ROOT = find_project_root()
CITY_DB_PATH = PROJECT_ROOT / "data" / "major-cities.csv"
LOG_DIR = PROJECT_ROOT / "logs"


def resolve_earth_texture_path() -> pathlib.Path | None:
    candidates = [
        PROJECT_ROOT / "data" / "world_map-960.png",
        PROJECT_ROOT / "assets" / "world_map-960.png",
        PROJECT_ROOT / "assets" / "earth" / "world_map-960.png",
        pathlib.Path("/usr/share/ubiquity/pixmaps/world_map-960.png"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


EARTH_TEXTURE_PATH = resolve_earth_texture_path()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def require_string(payload: dict, key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"Config field '{key}' must be a non-empty string.")
    return value.strip()


def require_bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise SystemExit(f"Config field '{key}' must be a boolean.")
    return value


def require_float(payload: dict, key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise SystemExit(f"Config field '{key}' must be a number.")


def require_non_negative_float(payload: dict, key: str, default: float) -> float:
    value = require_float(payload, key, default)
    if value < 0.0:
        raise SystemExit(f"Config field '{key}' must be non-negative.")
    return value


def require_positive_float(payload: dict, key: str, default: float) -> float:
    value = require_float(payload, key, default)
    if value <= 0.0:
        raise SystemExit(f"Config field '{key}' must be positive.")
    return value


def require_positive_int(payload: dict, key: str, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise SystemExit(f"Config field '{key}' must be a positive integer.")
    return value


def resolve_optional_path(
    raw_value: object,
    base_dir: pathlib.Path,
    default: pathlib.Path | None,
    *,
    must_exist: bool = True,
    allow_none: bool = False,
) -> pathlib.Path | None:
    if raw_value is None:
        resolved = default
    elif isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            resolved = None if allow_none else default
        else:
            resolved = (base_dir / stripped).resolve()
    else:
        raise SystemExit("Config path fields must be strings when provided.")

    if resolved is None:
        return None
    if must_exist and not resolved.exists():
        raise SystemExit(f"Configured path does not exist: {resolved}")
    return resolved


def format_config_path(target: pathlib.Path, config_dir: pathlib.Path) -> str:
    if os.path.commonpath([str(target), str(PROJECT_ROOT)]) != str(PROJECT_ROOT):
        return str(target)
    if os.path.commonpath([str(config_dir), str(PROJECT_ROOT)]) != str(PROJECT_ROOT):
        return str(target)
    return os.path.relpath(target, start=config_dir)


def build_default_config_payload(output_path: pathlib.Path) -> dict[str, object]:
    config_dir = output_path.parent.resolve()
    settings = PathViewerSettings()
    return {
        "_documentation": {
            "required_fields": {
                "place_a": "First endpoint. Use 'City, Country' or 'lat,lon'.",
                "place_b": "Second endpoint. Use 'City, Country' or 'lat,lon'.",
                "constellation_a": "Primary constellation JSON, resolved relative to this config file.",
                "constellation_b": "Secondary constellation JSON, resolved relative to this config file.",
            },
            "optional_fields": {
                "constellation_ixp": "Optional relay/IXP constellation JSON.",
                "city_db": "Override city database CSV path.",
                "log_dir": "Override output directory for generated CSV logs.",
                "earth_texture_path": "Override Earth texture PNG path. Use empty string to disable.",
            },
            "settings_note": "All settings below are optional at runtime, but this template writes them explicitly with current defaults.",
        },
        "place_a": "Trondheim, Norway",
        "place_b": "Te Aroha, New Zealand",
        "constellation_a": format_config_path(PROJECT_ROOT / "data" / "telesat-lightspeed-constellation-shells.json", config_dir),
        "constellation_b": format_config_path(PROJECT_ROOT / "data" / "telesat-lightspeed-constellation-shells.json", config_dir),
        "constellation_ixp": None,
        "city_db": format_config_path(settings.city_db_path, config_dir),
        "log_dir": format_config_path(settings.log_dir, config_dir),
        "earth_texture_path": (
            format_config_path(settings.earth_texture_path, config_dir)
            if settings.earth_texture_path is not None
            else ""
        ),
        "conservative_switch_threshold": settings.conservative_switch_threshold,
        "min_elevation_deg": settings.min_elevation_deg,
        "default_isl_range_km": settings.default_isl_range_km,
        "default_inter_processing_delay_us": settings.default_inter_processing_delay_us,
        "earth_texture_step_deg": settings.earth_texture_step_deg,
        "ground_link_elevation_preference": settings.ground_link_elevation_preference,
        "log_interval_seconds": settings.log_interval_seconds,
        "initial_time_scale": settings.initial_time_scale,
        "autoplay": settings.autoplay,
        "initial_yaw_deg": settings.initial_yaw_deg,
        "initial_pitch_deg": settings.initial_pitch_deg,
        "initial_zoom": settings.initial_zoom,
        "show_earth": settings.show_earth,
        "window_title": settings.window_title,
        "window_geometry": settings.window_geometry,
        "min_window_width": settings.min_window_width,
        "min_window_height": settings.min_window_height,
        "step_seconds_small": settings.step_seconds_small,
        "step_seconds_large": settings.step_seconds_large,
        "zoom_min": settings.zoom_min,
        "zoom_max": settings.zoom_max,
        "zoom_factor": settings.zoom_factor,
        "drag_sensitivity": settings.drag_sensitivity,
        "pitch_limit_deg": settings.pitch_limit_deg,
        "satellite_radius_active": settings.satellite_radius_active,
        "satellite_radius_inactive": settings.satellite_radius_inactive,
        "route_line_width": settings.route_line_width,
        "earth_grid_line_width": settings.earth_grid_line_width,
        "earth_grid_hidden_line_threshold": settings.earth_grid_hidden_line_threshold,
        "earth_texture_hidden_line_threshold": settings.earth_texture_hidden_line_threshold,
        "earth_texture_visible_vertex_threshold": settings.earth_texture_visible_vertex_threshold,
        "continent_visible_vertex_threshold": settings.continent_visible_vertex_threshold,
        "camera_distance_multiplier": settings.camera_distance_multiplier,
        "scale_fill_ratio": settings.scale_fill_ratio,
        "scale_divisor": settings.scale_divisor,
    }


def write_default_config(output_path: pathlib.Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_config_payload(output_path.resolve())
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def choose_altitude_km(shell: dict) -> float | None:
    if isinstance(shell.get("actual_altitude_km"), (int, float)):
        return float(shell["actual_altitude_km"])
    if isinstance(shell.get("altitude_km"), (int, float)):
        return float(shell["altitude_km"])
    if isinstance(shell.get("actual_altitude_km_range"), list) and shell["actual_altitude_km_range"]:
        values = [float(v) for v in shell["actual_altitude_km_range"] if isinstance(v, (int, float))]
        if values:
            return sum(values) / len(values)
    if isinstance(shell.get("altitude_km_range"), list) and shell["altitude_km_range"]:
        values = [float(v) for v in shell["altitude_km_range"] if isinstance(v, (int, float))]
        if values:
            return sum(values) / len(values)
    return None


def infer_layout(shell: dict) -> tuple[int, int, bool]:
    num_planes = shell.get("num_planes")
    sats_per_plane = shell.get("sats_per_plane")
    if isinstance(num_planes, int) and num_planes > 0 and isinstance(sats_per_plane, int) and sats_per_plane > 0:
        return num_planes, sats_per_plane, True

    planned = shell.get("planned_satellites")
    if not isinstance(planned, int) or planned <= 0:
        return 1, 1, False

    estimated_planes = max(1, round(math.sqrt(planned)))
    estimated_sats_per_plane = math.ceil(planned / estimated_planes)
    return estimated_planes, estimated_sats_per_plane, False


def shell_label(shell: dict) -> str:
    for key in ("shell_id", "group", "description"):
        value = shell.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    groups = shell.get("groups")
    if isinstance(groups, list) and groups:
        return ", ".join(str(group) for group in groups)
    return "unnamed-shell"


def load_shells(json_path: pathlib.Path, default_isl_range_km: float) -> tuple[list[ShellDefinition], float]:
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    dataset_label = json_path.stem.replace("-", " ").title()
    metadata = payload.get("_metadata", {})
    if isinstance(metadata, dict):
        dataset_label = str(metadata.get("constellation_name") or metadata.get("description") or dataset_label)

    shells: list[ShellDefinition] = []
    isl_range_km = default_isl_range_km

    hardware = payload.get("satellite_hardware")
    if isinstance(hardware, dict) and isinstance(hardware.get("isl_max_range_km"), (int, float)):
        isl_range_km = float(hardware["isl_max_range_km"])

    for section_key, section_value in payload.items():
        if not isinstance(section_value, dict):
            continue
        section_shells = section_value.get("shells")
        if not isinstance(section_shells, list):
            continue

        section_label = str(section_value.get("description") or section_key.replace("_", " ").title())
        for raw_shell in section_shells:
            if not isinstance(raw_shell, dict):
                continue
            altitude_km = choose_altitude_km(raw_shell)
            inclination_deg = raw_shell.get("inclination_deg")
            if altitude_km is None or not isinstance(inclination_deg, (int, float)):
                continue
            num_planes, sats_per_plane, exact_layout = infer_layout(raw_shell)
            planned_satellites = raw_shell.get("planned_satellites")
            if not isinstance(planned_satellites, int) or planned_satellites <= 0:
                planned_satellites = num_planes * sats_per_plane
            shells.append(
                ShellDefinition(
                    dataset_label=dataset_label,
                    section_label=section_label,
                    shell_id=str(raw_shell.get("shell_id") or shell_label(raw_shell)),
                    shell_label=shell_label(raw_shell),
                    altitude_km=float(altitude_km),
                    inclination_deg=float(inclination_deg),
                    num_planes=num_planes,
                    sats_per_plane=sats_per_plane,
                    planned_satellites=planned_satellites,
                    notes=str(raw_shell.get("notes") or "").strip(),
                    exact_layout=exact_layout,
                )
            )

    return shells, isl_range_km


def orbital_radius_km(shell: ShellDefinition) -> float:
    return EARTH_RADIUS_KM + shell.altitude_km


def orbital_period_seconds(shell: ShellDefinition) -> float:
    radius_m = orbital_radius_km(shell) * 1000.0
    mean_motion = math.sqrt(EARTH_MU_M3_S2 / (radius_m ** 3))
    return (2.0 * math.pi) / mean_motion


def satellite_position(shell: ShellDefinition, plane_index: int, slot_index: int, t_seconds: float) -> tuple[float, float, float]:
    radius = orbital_radius_km(shell)
    mean_motion = (2.0 * math.pi) / orbital_period_seconds(shell)
    inclination = math.radians(shell.inclination_deg)
    raan = (2.0 * math.pi * plane_index) / shell.num_planes
    base_anomaly = (2.0 * math.pi * slot_index) / shell.sats_per_plane
    phase_offset = (math.pi * plane_index) / max(shell.num_planes, shell.sats_per_plane)
    theta = base_anomaly + phase_offset + mean_motion * t_seconds

    cos_raan = math.cos(raan)
    sin_raan = math.sin(raan)
    cos_inc = math.cos(inclination)
    sin_inc = math.sin(inclination)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)

    x = radius * (cos_raan * cos_theta - sin_raan * sin_theta * cos_inc)
    y = radius * (sin_raan * cos_theta + cos_raan * sin_theta * cos_inc)
    z = radius * (sin_theta * sin_inc)
    return x, y, z


def rotate_point(x: float, y: float, z: float, yaw: float, pitch: float) -> tuple[float, float, float]:
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    x1 = x * cos_yaw - y * sin_yaw
    y1 = x * sin_yaw + y * cos_yaw

    cos_pitch = math.cos(pitch)
    sin_pitch = math.sin(pitch)
    y2 = y1 * cos_pitch - z * sin_pitch
    z2 = y1 * sin_pitch + z * cos_pitch
    return x1, y2, z2


def project_point(
    x: float,
    y: float,
    z: float,
    width: int,
    height: int,
    camera_distance_km: float,
    scale: float,
) -> tuple[float, float, float] | None:
    depth = z + camera_distance_km
    if depth <= 1.0:
        return None
    perspective = scale / depth
    screen_x = (width / 2.0) + (x * perspective)
    screen_y = (height / 2.0) - (y * perspective)
    return screen_x, screen_y, depth


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float) -> tuple[float, float, float]:
    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    x = EARTH_RADIUS_KM * math.cos(lat) * math.cos(lon)
    y = EARTH_RADIUS_KM * math.cos(lat) * math.sin(lon)
    z = EARTH_RADIUS_KM * math.sin(lat)
    return x, y, z


def normalize_place_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "run"


def load_city_db(csv_path: pathlib.Path) -> dict[str, list[CityEntry]]:
    city_db: dict[str, list[CityEntry]] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                entry = CityEntry(
                    name=row["name"].strip(),
                    country=row["country"].strip(),
                    latitude_deg=float(row["latitude"]),
                    longitude_deg=float(row["longitude"]),
                )
            except (KeyError, ValueError):
                continue

            keys = {
                normalize_place_name(entry.name),
                normalize_place_name(f"{entry.name},{entry.country}"),
            }
            country_alias = COUNTRY_ALIASES.get(normalize_place_name(entry.country))
            if country_alias:
                keys.add(normalize_place_name(f"{entry.name},{country_alias}"))

            for key in keys:
                city_db.setdefault(key, []).append(entry)
    return city_db


def resolve_place(
    name: str,
    city_db: dict[str, list[CityEntry]],
    city_db_path: pathlib.Path = CITY_DB_PATH,
) -> GroundPoint:
    stripped = name.strip()
    coordinate_match = re.fullmatch(r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*", stripped)
    if coordinate_match:
        lat = float(coordinate_match.group(1))
        lon = float(coordinate_match.group(2))
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            return GroundPoint(name=f"{lat:.4f}, {lon:.4f}", latitude_deg=lat, longitude_deg=lon)
    normalized = normalize_place_name(stripped)
    parts = [part.strip() for part in stripped.split(",") if part.strip()]
    if len(parts) == 2:
        city_key = normalize_place_name(parts[0])
        country_key = normalize_place_name(parts[1])
        aliased_country = COUNTRY_ALIASES.get(country_key, country_key)
        normalized = normalize_place_name(f"{parts[0]},{aliased_country}")

    matches = city_db.get(normalized, [])
    if len(matches) == 1:
        entry = matches[0]
        return GroundPoint(name=stripped, latitude_deg=entry.latitude_deg, longitude_deg=entry.longitude_deg)
    if len(matches) > 1:
        raise SystemExit(f"Ambiguous place '{name}'. Specify 'City, Country'.")

    if len(parts) == 1:
        matches = city_db.get(normalize_place_name(parts[0]), [])
        if len(matches) == 1:
            entry = matches[0]
            return GroundPoint(name=stripped, latitude_deg=entry.latitude_deg, longitude_deg=entry.longitude_deg)
        if len(matches) > 1:
            raise SystemExit(f"Ambiguous place '{name}'. Specify 'City, Country'.")
    raise SystemExit(
        f"Unknown place '{name}'. Use a city from {city_db_path} or pass coordinates as 'lat,lon'."
    )


def load_config(config_path: pathlib.Path) -> ViewerConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise SystemExit(f"Config file must contain a JSON object: {config_path}")

    required = ["place_a", "place_b", "constellation_a", "constellation_b"]
    missing = [key for key in required if not isinstance(payload.get(key), str) or not payload.get(key).strip()]
    if missing:
        raise SystemExit(f"Config file is missing required string field(s): {', '.join(missing)}")

    settings = PathViewerSettings.from_payload(payload, config_path)

    constellation_a = (config_path.parent / payload["constellation_a"]).resolve()
    constellation_b = (config_path.parent / payload["constellation_b"]).resolve()
    if not constellation_a.exists():
        raise SystemExit(f"Constellation A file not found from config: {constellation_a}")
    if not constellation_b.exists():
        raise SystemExit(f"Constellation B file not found from config: {constellation_b}")
    constellation_ixp = None
    raw_ixp = payload.get("constellation_ixp")
    if isinstance(raw_ixp, str) and raw_ixp.strip():
        constellation_ixp = (config_path.parent / raw_ixp).resolve()
        if not constellation_ixp.exists():
            raise SystemExit(f"IXP constellation file not found from config: {constellation_ixp}")
    return ViewerConfig(
        place_a=payload["place_a"].strip(),
        place_b=payload["place_b"].strip(),
        constellation_a=constellation_a,
        constellation_b=constellation_b,
        constellation_ixp=constellation_ixp,
        settings=settings,
    )


def vector_sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def vector_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vector_norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(vector_dot(a, a))


def distance_km(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return vector_norm(vector_sub(a, b))


def elevation_deg(ground_pos: tuple[float, float, float], sat_pos: tuple[float, float, float]) -> float:
    up = ground_pos
    line = vector_sub(sat_pos, ground_pos)
    numerator = vector_dot(line, up)
    denominator = vector_norm(line) * vector_norm(up)
    if denominator == 0:
        return -90.0
    sin_elev = clamp(numerator / denominator, -1.0, 1.0)
    return math.degrees(math.asin(sin_elev))


def build_satellites(
    shells: list[ShellDefinition],
    constellation_role: str,
) -> tuple[list[Satellite], dict[int, list[int]]]:
    satellites: list[Satellite] = []
    shell_offsets: dict[int, list[int]] = {}
    next_index = 0
    for shell_index, shell in enumerate(shells):
        indices: list[int] = []
        for plane_index in range(shell.num_planes):
            for slot_index in range(shell.sats_per_plane):
                label = f"{shell.shell_id}:P{plane_index:02d}:S{slot_index:03d}"
                satellites.append(
                    Satellite(
                        index=next_index,
                        node_id=f"sat:{constellation_role}:{next_index}",
                        constellation_role=constellation_role,
                        constellation_label=shell.dataset_label,
                        shell_index=shell_index,
                        shell=shell,
                        plane_index=plane_index,
                        slot_index=slot_index,
                        label=label,
                    )
                )
                indices.append(next_index)
                next_index += 1
        shell_offsets[shell_index] = indices
    return satellites, shell_offsets


def load_constellations(config: ViewerConfig) -> list[LoadedConstellation]:
    loaded: list[LoadedConstellation] = []
    entries: list[tuple[str, pathlib.Path | None]] = [("a", config.constellation_a)]
    if config.constellation_b != config.constellation_a:
        entries.append(("b", config.constellation_b))
    entries.append(("ixp", config.constellation_ixp))
    for role, path in entries:
        if path is None:
            continue
        shells, isl_range_km = load_shells(path, config.settings.default_isl_range_km)
        loaded.append(LoadedConstellation(role=role, path=path, shells=shells, isl_range_km=isl_range_km))
    return loaded


def candidate_neighbor_indices(sat: Satellite, satellites_by_key: dict[tuple[int, int, int], int]) -> list[int]:
    shell = sat.shell
    neighbors = []
    offsets = [
        (0, 1),
        (0, -1),
        (1, 0),
        (-1, 0),
        (1, 1),
        (-1, -1),
        (1, -1),
        (-1, 1),
    ]
    for plane_delta, slot_delta in offsets:
        plane = (sat.plane_index + plane_delta) % shell.num_planes
        slot = (sat.slot_index + slot_delta) % shell.sats_per_plane
        key = (sat.shell_index, plane, slot)
        neighbor = satellites_by_key.get(key)
        if neighbor is not None:
            neighbors.append(neighbor)
    return neighbors


def dijkstra(adjacency: dict[str, list[tuple[str, float]]], start: str, goal: str) -> tuple[float, list[str]]:
    queue: list[tuple[float, str]] = [(0.0, start)]
    distances = {start: 0.0}
    previous: dict[str, str] = {}

    while queue:
        current_distance, node = heapq.heappop(queue)
        if node == goal:
            break
        if current_distance > distances.get(node, float("inf")):
            continue
        for neighbor, weight in adjacency.get(node, []):
            candidate = current_distance + weight
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate, neighbor))

    if goal not in distances:
        return float("inf"), []

    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return distances[goal], path


def path_cost(adjacency: dict[str, list[tuple[str, float]]], path: list[str]) -> float:
    if len(path) < 2:
        return float("inf")
    total = 0.0
    for left, right in zip(path, path[1:]):
        edge_weight = None
        for neighbor, weight in adjacency.get(left, []):
            if neighbor == right:
                edge_weight = weight
                break
        if edge_weight is None:
            return float("inf")
        total += edge_weight
    return total


class ConstellationPathViewer:
    def __init__(
        self,
        root: tk.Tk,
        ground_a: GroundPoint,
        ground_b: GroundPoint,
        constellations: list[LoadedConstellation],
        same_constellation_mode: bool,
        settings: PathViewerSettings,
        run_label: str,
    ) -> None:
        self.root = root
        self.ground_a = ground_a
        self.ground_b = ground_b
        self.settings = settings
        self.constellations = {constellation.role: constellation for constellation in constellations}
        self.satellites_by_role: dict[str, list[Satellite]] = {}
        self.satellites_by_node_id: dict[str, Satellite] = {}
        self.satellites_by_role_key: dict[str, dict[tuple[int, int, int], str]] = {}
        self.neighbor_map: dict[str, list[str]] = {}
        self.constellation_ranges_km = {constellation.role: constellation.isl_range_km for constellation in constellations}
        self.same_constellation_mode = same_constellation_mode
        self.conservative_switch_threshold = settings.conservative_switch_threshold
        self.active_path: list[str] = []

        for constellation in constellations:
            satellites, _ = build_satellites(constellation.shells, constellation.role)
            self.satellites_by_role[constellation.role] = satellites
            lookup = {
                (sat.shell_index, sat.plane_index, sat.slot_index): sat.node_id
                for sat in satellites
            }
            self.satellites_by_role_key[constellation.role] = lookup
            for sat in satellites:
                self.satellites_by_node_id[sat.node_id] = sat
            self.neighbor_map.update(
                {
                    sat.node_id: [
                        neighbor_id
                        for neighbor_id in (
                            lookup.get((sat.shell_index, (sat.plane_index + plane_delta) % sat.shell.num_planes, (sat.slot_index + slot_delta) % sat.shell.sats_per_plane))
                            for plane_delta, slot_delta in (
                                (0, 1),
                                (0, -1),
                                (1, 0),
                                (-1, 0),
                                (1, 1),
                                (-1, -1),
                                (1, -1),
                                (-1, 1),
                            )
                        )
                        if neighbor_id is not None
                    ]
                    for sat in satellites
                }
            )

        self.satellites = [sat for role in ("a", "b", "ixp") for sat in self.satellites_by_role.get(role, [])]

        self.time_seconds = 0.0
        self.time_scale = settings.initial_time_scale
        self.last_tick = None
        self.is_playing = settings.autoplay
        self.yaw = math.radians(settings.initial_yaw_deg)
        self.pitch = math.radians(settings.initial_pitch_deg)
        self.zoom = settings.initial_zoom
        self.drag_start: tuple[int, int] | None = None
        self.earth_texture: tk.PhotoImage | None = None
        self.earth_texture_tiles: list[tuple[float, float, float, float, str]] = []
        self.last_route_signature: tuple[str, ...] | None = None
        self.last_path_change_time_seconds = 0.0
        self.last_logged_interval_index = -1
        self.log_path = self._create_log_file(settings.log_dir, run_label)

        self.route_status_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.time_scale_var = tk.DoubleVar(value=self.time_scale)
        self.processing_delay_var = tk.StringVar(value=f"{settings.default_inter_processing_delay_us:g}")
        self.show_earth_var = tk.BooleanVar(value=settings.show_earth)

        self.root.title(settings.window_title)
        self.root.geometry(settings.window_geometry)
        self.root.minsize(settings.min_window_width, settings.min_window_height)

        self._load_earth_texture()
        self._build_ui()
        self.play_button.configure(text="Pause" if self.is_playing else "Play")
        self._schedule_tick()

    def _create_log_file(self, log_dir: pathlib.Path, run_label: str) -> pathlib.Path:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_path = log_dir / f"{timestamp}-{slugify(run_label)}.csv"
        with log_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "simulation_time_seconds",
                    "end_to_end_delay_ms",
                    "num_satellites_in_path_a",
                    "num_satellites_in_path_b",
                    "ixp_satellite_index",
                    "last_path_change_time_seconds",
                ]
            )
        return log_path

    def _update_path_change_state(self, path: list[str]) -> None:
        route_signature = tuple(path)
        if self.last_route_signature is None:
            self.last_route_signature = route_signature
            self.last_path_change_time_seconds = self.time_seconds
            return
        if route_signature != self.last_route_signature:
            self.last_route_signature = route_signature
            self.last_path_change_time_seconds = self.time_seconds

    def _append_log_row(self, route_state: dict) -> None:
        current_interval_index = int(self.time_seconds // self.settings.log_interval_seconds)
        if current_interval_index <= self.last_logged_interval_index:
            return
        delay_ms = route_state["total_delay_ms"] if route_state["path"] else -1.0
        satellites_in_path_a = len(route_state["route_satellites_by_role"]["a"])
        satellites_in_path_b = len(route_state["route_satellites_by_role"]["b"])
        with self.log_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            for interval_index in range(self.last_logged_interval_index + 1, current_interval_index + 1):
                simulation_time_seconds = interval_index * self.settings.log_interval_seconds
                writer.writerow(
                    [
                        f"{simulation_time_seconds:.6f}",
                        f"{delay_ms:.6f}",
                        satellites_in_path_a,
                        satellites_in_path_b,
                        route_state["ixp_satellite_index"],
                        f"{self.last_path_change_time_seconds:.6f}",
                    ]
                )
        self.last_logged_interval_index = current_interval_index

    def _load_earth_texture(self) -> None:
        earth_texture_path = self.settings.earth_texture_path
        if earth_texture_path is None or not earth_texture_path.exists():
            return
        try:
            self.earth_texture = tk.PhotoImage(file=str(earth_texture_path))
        except tk.TclError:
            self.earth_texture = None
            return

        width = self.earth_texture.width()
        height = self.earth_texture.height()
        tiles: list[tuple[float, float, float, float, str]] = []
        for lat0 in range(-90, 90, self.settings.earth_texture_step_deg):
            lat1 = min(90, lat0 + self.settings.earth_texture_step_deg)
            lat_center = (lat0 + lat1) / 2.0
            for lon0 in range(-180, 180, self.settings.earth_texture_step_deg):
                lon1 = lon0 + self.settings.earth_texture_step_deg
                lon_center = (lon0 + lon1) / 2.0
                x = int(((lon_center + 180.0) / 360.0) * (width - 1))
                y = int(((90.0 - lat_center) / 180.0) * (height - 1))
                color = self._photo_color_to_hex(self.earth_texture.get(x, y))
                tiles.append((lat0, lat1, lon0, lon1, color))
        self.earth_texture_tiles = tiles

    @staticmethod
    def _photo_color_to_hex(value: object) -> str:
        if isinstance(value, tuple) and len(value) >= 3:
            r, g, b = (int(value[0]), int(value[1]), int(value[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
        if isinstance(value, str) and value.startswith("#"):
            return value
        if isinstance(value, str):
            parts = value.split()
            if len(parts) >= 3:
                r, g, b = (int(parts[0]), int(parts[1]), int(parts[2]))
                return f"#{r:02x}{g:02x}{b:02x}"
        return "#40637c"

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.configure("Viewer.TFrame", background="#f4f1ea")
        style.configure("Viewer.TLabel", background="#f4f1ea")

        outer = ttk.Frame(self.root, padding=12, style="Viewer.TFrame")
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        controls = ttk.Frame(outer, padding=(0, 0, 12, 0), style="Viewer.TFrame")
        controls.grid(row=0, column=0, sticky="nsw")

        title = f"{self.ground_a.name} -> {self.ground_b.name}"
        ttk.Label(controls, text=title, style="Viewer.TLabel", wraplength=320).pack(anchor="w")
        ttk.Label(
            controls,
            text=(
                f"Constellations: {', '.join(role.upper() for role in self.constellations.keys())} | "
                f"Satellites: {len(self.satellites)}"
            ),
            style="Viewer.TLabel",
            wraplength=320,
        ).pack(anchor="w", pady=(6, 12))

        ttk.Label(controls, text="Time Scale (sim hours/sec)", style="Viewer.TLabel").pack(anchor="w")
        ttk.Scale(
            controls,
            from_=0.0,
            to=120.0,
            variable=self.time_scale_var,
            orient=tk.HORIZONTAL,
            command=self._update_time_scale,
        ).pack(fill=tk.X, pady=(2, 6))

        playback_row = ttk.Frame(controls, style="Viewer.TFrame")
        playback_row.pack(fill=tk.X)
        self.play_button = ttk.Button(playback_row, text="Pause", command=self._toggle_play)
        self.play_button.pack(side=tk.LEFT)
        ttk.Button(
            playback_row,
            text="Step +5 min",
            command=lambda: self._step_time(self.settings.step_seconds_small),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            playback_row,
            text="Step +30 min",
            command=lambda: self._step_time(self.settings.step_seconds_large),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(playback_row, text="Reset View", command=self._reset_view).pack(side=tk.RIGHT)

        ttk.Label(controls, text="ISL Processing Delay (us)", style="Viewer.TLabel").pack(anchor="w", pady=(12, 0))
        delay_row = ttk.Frame(controls, style="Viewer.TFrame")
        delay_row.pack(fill=tk.X, pady=(2, 0))
        delay_entry = ttk.Entry(delay_row, textvariable=self.processing_delay_var, width=12)
        delay_entry.pack(side=tk.LEFT)
        delay_entry.bind("<Return>", lambda _: self._redraw())
        delay_entry.bind("<FocusOut>", lambda _: self._redraw())
        ttk.Label(delay_row, text="Applied per satellite-to-satellite hop", style="Viewer.TLabel", wraplength=200).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Checkbutton(
            controls,
            text="Show Earth globe",
            variable=self.show_earth_var,
            command=self._redraw,
        ).pack(anchor="w", pady=(12, 0))

        ttk.Label(controls, textvariable=self.summary_var, style="Viewer.TLabel", wraplength=320).pack(anchor="w", pady=(12, 6))
        ttk.Label(controls, textvariable=self.route_status_var, style="Viewer.TLabel", wraplength=320).pack(anchor="w")

        legend_lines = [
            "Orange: constellation A path",
            "Cyan: constellation B path",
            "Magenta: IXP bridge path",
            "Amber: ground endpoints",
            "Dim blue-gray: inactive satellites",
            "Drag to rotate, scroll to zoom",
        ]
        ttk.Label(controls, text="\n".join(legend_lines), style="Viewer.TLabel", wraplength=320).pack(anchor="w", pady=(12, 0))

        canvas_frame = ttk.Frame(outer, style="Viewer.TFrame")
        canvas_frame.grid(row=0, column=1, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#091018", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag_view)
        self.canvas.bind("<MouseWheel>", self._zoom_view)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_view(event, delta_override=120))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_view(event, delta_override=-120))

    def _schedule_tick(self) -> None:
        self.root.after(33, self._tick)

    def _tick(self) -> None:
        now = time.monotonic()
        if self.last_tick is None:
            self.last_tick = now
        if self.is_playing:
            elapsed = now - self.last_tick
            self.time_seconds += elapsed * self.time_scale * SECONDS_PER_HOUR
            self._redraw()
        self.last_tick = now
        self._schedule_tick()

    def _update_time_scale(self, _: str) -> None:
        self.time_scale = float(self.time_scale_var.get())
        self._redraw()

    def _toggle_play(self) -> None:
        self.is_playing = not self.is_playing
        self.play_button.configure(text="Pause" if self.is_playing else "Play")
        self._redraw()

    def _step_time(self, delta_seconds: float) -> None:
        self.time_seconds += delta_seconds
        self._redraw()

    def _reset_view(self) -> None:
        self.yaw = math.radians(self.settings.initial_yaw_deg)
        self.pitch = math.radians(self.settings.initial_pitch_deg)
        self.zoom = self.settings.initial_zoom
        self._redraw()

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_start = (event.x, event.y)

    def _drag_view(self, event: tk.Event) -> None:
        if self.drag_start is None:
            self.drag_start = (event.x, event.y)
            return
        dx = event.x - self.drag_start[0]
        dy = event.y - self.drag_start[1]
        self.drag_start = (event.x, event.y)
        self.yaw += dx * self.settings.drag_sensitivity
        pitch_limit = math.radians(self.settings.pitch_limit_deg)
        self.pitch = clamp(self.pitch - dy * self.settings.drag_sensitivity, -pitch_limit, pitch_limit)
        self._redraw()

    def _zoom_view(self, event: tk.Event, delta_override: int | None = None) -> None:
        delta = delta_override if delta_override is not None else event.delta
        if delta == 0:
            return
        factor = self.settings.zoom_factor if delta > 0 else 1.0 / self.settings.zoom_factor
        self.zoom = clamp(self.zoom * factor, self.settings.zoom_min, self.settings.zoom_max)
        self._redraw()

    def _earth_grid_segments(self) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        segments = []
        for lat_deg in range(-60, 61, 30):
            lat = math.radians(lat_deg)
            points = []
            for lon_deg in range(0, 361, 12):
                lon = math.radians(lon_deg)
                x = EARTH_RADIUS_KM * math.cos(lat) * math.cos(lon)
                y = EARTH_RADIUS_KM * math.cos(lat) * math.sin(lon)
                z = EARTH_RADIUS_KM * math.sin(lat)
                points.append((x, y, z))
            segments.extend(zip(points, points[1:]))
        for lon_deg in range(0, 360, 30):
            lon = math.radians(lon_deg)
            points = []
            for lat_deg in range(-90, 91, 8):
                lat = math.radians(lat_deg)
                x = EARTH_RADIUS_KM * math.cos(lat) * math.cos(lon)
                y = EARTH_RADIUS_KM * math.cos(lat) * math.sin(lon)
                z = EARTH_RADIUS_KM * math.sin(lat)
                points.append((x, y, z))
            segments.extend(zip(points, points[1:]))
        return segments

    def _draw_earth_globe(
        self,
        width: int,
        height: int,
        camera_distance: float,
        scale: float,
    ) -> None:
        center = project_point(0.0, 0.0, 0.0, width, height, camera_distance, scale)
        if center is None:
            return
        radius_px = (scale * EARTH_RADIUS_KM) / camera_distance
        cx, cy, _ = center

        # Layered fill gives the sphere a readable shape under the map texture.
        layers = [
            (1.0, "#17324a"),
            (0.92, "#1b4261"),
            (0.82, "#205070"),
        ]
        for fraction, fill in layers:
            r = radius_px * fraction
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="")

        self.canvas.create_oval(
            cx - radius_px,
            cy - radius_px,
            cx + radius_px,
            cy + radius_px,
            outline="#5e87a1",
            width=1,
        )

        if self.earth_texture_tiles:
            render_tiles: list[tuple[float, list[float], str]] = []
            for lat0, lat1, lon0, lon1, fill in self.earth_texture_tiles:
                center_rotated = rotate_point(*geodetic_to_ecef((lat0 + lat1) / 2.0, (lon0 + lon1) / 2.0), yaw=self.yaw, pitch=self.pitch)
                if center_rotated[2] < -EARTH_RADIUS_KM * self.settings.earth_texture_hidden_line_threshold:
                    continue
                corners = [
                    geodetic_to_ecef(lat0, lon0),
                    geodetic_to_ecef(lat0, lon1),
                    geodetic_to_ecef(lat1, lon1),
                    geodetic_to_ecef(lat1, lon0),
                ]
                polygon_points: list[float] = []
                visible_vertices = 0
                for corner in corners:
                    rotated = rotate_point(*corner, yaw=self.yaw, pitch=self.pitch)
                    if rotated[2] >= -EARTH_RADIUS_KM * self.settings.earth_texture_visible_vertex_threshold:
                        visible_vertices += 1
                    projected = project_point(*rotated, width, height, camera_distance, scale)
                    if projected is None:
                        polygon_points = []
                        break
                    polygon_points.extend((projected[0], projected[1]))
                if visible_vertices >= 2 and len(polygon_points) == 8:
                    render_tiles.append((center_rotated[2], polygon_points, fill))

            render_tiles.sort()
            for _, polygon_points, fill in render_tiles:
                self.canvas.create_polygon(polygon_points, fill=fill, outline="")
        else:
            for polygon in CONTINENT_POLYGONS:
                projected_points = []
                visible_count = 0
                for lat_deg, lon_deg in polygon:
                    point = geodetic_to_ecef(lat_deg, lon_deg)
                    rotated = rotate_point(*point, yaw=self.yaw, pitch=self.pitch)
                    if rotated[2] >= -EARTH_RADIUS_KM * self.settings.continent_visible_vertex_threshold:
                        visible_count += 1
                    projected = project_point(*rotated, width, height, camera_distance, scale)
                    if projected is not None:
                        projected_points.extend((projected[0], projected[1]))
                if visible_count >= max(3, len(polygon) // 3) and len(projected_points) >= 6:
                    self.canvas.create_polygon(
                        projected_points,
                        fill="#597e52",
                        outline="#8caf76",
                        width=1,
                        smooth=True,
                    )

        for start, end in self._earth_grid_segments():
            rotated_start = rotate_point(*start, yaw=self.yaw, pitch=self.pitch)
            rotated_end = rotate_point(*end, yaw=self.yaw, pitch=self.pitch)
            if (
                rotated_start[2] < -EARTH_RADIUS_KM * self.settings.earth_grid_hidden_line_threshold
                and rotated_end[2] < -EARTH_RADIUS_KM * self.settings.earth_grid_hidden_line_threshold
            ):
                continue
            p0 = project_point(*rotated_start, width, height, camera_distance, scale)
            p1 = project_point(*rotated_end, width, height, camera_distance, scale)
            if p0 is None or p1 is None:
                continue
            self.canvas.create_line(p0[0], p0[1], p1[0], p1[1], fill="#2d5873", width=self.settings.earth_grid_line_width)

    def _processing_delay_seconds(self) -> tuple[float, str]:
        raw_value = self.processing_delay_var.get().strip()
        try:
            value_us = float(raw_value)
        except ValueError:
            value_us = self.settings.default_inter_processing_delay_us
            self.processing_delay_var.set(f"{self.settings.default_inter_processing_delay_us:g}")
        value_us = max(0.0, value_us)
        return value_us / 1_000_000.0, f"{value_us:g}"

    def _ground_link_weight(self, distance_km: float, elevation_deg_value: float) -> float:
        # Prefer high-elevation satellites for access links so the route does not fan out
        # sideways near the horizon when a near-overhead satellite is available.
        elevation_factor = max(math.sin(math.radians(elevation_deg_value)), 0.05)
        return distance_km / (elevation_factor ** self.settings.ground_link_elevation_preference)

    def _add_ground_access_edges(
        self,
        adjacency: dict[str, list[tuple[str, float]]],
        edge_delays_ms: dict[tuple[str, str], float],
        visible_from_ground: dict[str, list[tuple[str, float, float]]],
        sat_positions: dict[str, tuple[float, float, float]],
        ground_positions: dict[str, tuple[float, float, float]],
        ground_key: str,
        allowed_roles: set[str],
        direction: str = "bidirectional",
    ) -> None:
        ground_pos = ground_positions[ground_key]
        for role in allowed_roles:
            for sat in self.satellites_by_role.get(role, []):
                sat_pos = sat_positions[sat.node_id]
                elev = elevation_deg(ground_pos, sat_pos)
                if elev < self.settings.min_elevation_deg:
                    continue
                link_distance = distance_km(ground_pos, sat_pos)
                route_weight = self._ground_link_weight(link_distance, elev)
                link_delay_ms = (link_distance / LIGHT_SPEED_KM_S) * 1000.0
                visible_from_ground[ground_key].append((sat.node_id, link_distance, elev))
                if direction in ("bidirectional", "ground_to_sat"):
                    adjacency.setdefault(ground_key, []).append((sat.node_id, route_weight))
                    edge_delays_ms[(ground_key, sat.node_id)] = link_delay_ms
                if direction in ("bidirectional", "sat_to_ground"):
                    adjacency.setdefault(sat.node_id, []).append((ground_key, route_weight))
                    edge_delays_ms[(sat.node_id, ground_key)] = link_delay_ms

    def _add_intra_constellation_edges(
        self,
        adjacency: dict[str, list[tuple[str, float]]],
        edge_delays_ms: dict[tuple[str, str], float],
        sat_positions: dict[str, tuple[float, float, float]],
        role: str,
        processing_delay_seconds: float,
    ) -> None:
        seen_edges: set[tuple[str, str]] = set()
        max_range_km = self.constellation_ranges_km[role]
        for sat in self.satellites_by_role.get(role, []):
            adjacency.setdefault(sat.node_id, [])
            for neighbor_node_id in self.neighbor_map.get(sat.node_id, []):
                edge = tuple(sorted((sat.node_id, neighbor_node_id)))
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                hop_distance = distance_km(sat_positions[sat.node_id], sat_positions[neighbor_node_id])
                if hop_distance > max_range_km:
                    continue
                adjacency[sat.node_id].append((neighbor_node_id, hop_distance))
                adjacency.setdefault(neighbor_node_id, []).append((sat.node_id, hop_distance))
                hop_delay_ms = ((hop_distance / LIGHT_SPEED_KM_S) + processing_delay_seconds) * 1000.0
                edge_delays_ms[(sat.node_id, neighbor_node_id)] = hop_delay_ms
                edge_delays_ms[(neighbor_node_id, sat.node_id)] = hop_delay_ms

    def _add_ixp_bridge_edges(
        self,
        adjacency: dict[str, list[tuple[str, float]]],
        edge_delays_ms: dict[tuple[str, str], float],
        sat_positions: dict[str, tuple[float, float, float]],
        processing_delay_seconds: float,
    ) -> None:
        if "ixp" not in self.constellations:
            return
        ixp_range = self.constellation_ranges_km["ixp"]
        for ixp_sat in self.satellites_by_role.get("ixp", []):
            adjacency.setdefault(ixp_sat.node_id, [])
            for sat in self.satellites_by_role.get("a", []):
                hop_distance = distance_km(sat_positions[ixp_sat.node_id], sat_positions[sat.node_id])
                if hop_distance > min(ixp_range, self.constellation_ranges_km.get("a", ixp_range)):
                    continue
                hop_delay_ms = ((hop_distance / LIGHT_SPEED_KM_S) + processing_delay_seconds) * 1000.0
                adjacency.setdefault(sat.node_id, []).append((ixp_sat.node_id, hop_distance))
                edge_delays_ms[(sat.node_id, ixp_sat.node_id)] = hop_delay_ms

            for sat in self.satellites_by_role.get("b", []):
                hop_distance = distance_km(sat_positions[ixp_sat.node_id], sat_positions[sat.node_id])
                if hop_distance > min(ixp_range, self.constellation_ranges_km.get("b", ixp_range)):
                    continue
                hop_delay_ms = ((hop_distance / LIGHT_SPEED_KM_S) + processing_delay_seconds) * 1000.0
                adjacency[ixp_sat.node_id].append((sat.node_id, hop_distance))
                edge_delays_ms[(ixp_sat.node_id, sat.node_id)] = hop_delay_ms

    def _inter_constellation_bridge_weight(self, hop_distance: float, sat_a: Satellite, sat_b: Satellite) -> float:
        # When constellations bridge directly, prefer higher-orbit satellites as the exchange points.
        all_bridge_altitudes = [
            sat.shell.altitude_km
            for role in ("a", "b")
            for sat in self.satellites_by_role.get(role, [])
        ]
        reference_altitude = max(all_bridge_altitudes) if all_bridge_altitudes else max(sat_a.shell.altitude_km, sat_b.shell.altitude_km, 1.0)
        altitude_bias = max(sat_a.shell.altitude_km, sat_b.shell.altitude_km) / max(reference_altitude, 1.0)
        return hop_distance / (1.0 + 0.75 * altitude_bias)

    def _add_direct_constellation_bridge_edges(
        self,
        adjacency: dict[str, list[tuple[str, float]]],
        edge_delays_ms: dict[tuple[str, str], float],
        sat_positions: dict[str, tuple[float, float, float]],
        processing_delay_seconds: float,
    ) -> None:
        if "a" not in self.constellations or "b" not in self.constellations:
            return
        bridge_range_km = min(
            self.constellation_ranges_km.get("a", self.settings.default_isl_range_km),
            self.constellation_ranges_km.get("b", self.settings.default_isl_range_km),
        )
        for sat_a in self.satellites_by_role.get("a", []):
            adjacency.setdefault(sat_a.node_id, [])
            for sat_b in self.satellites_by_role.get("b", []):
                hop_distance = distance_km(sat_positions[sat_a.node_id], sat_positions[sat_b.node_id])
                if hop_distance > bridge_range_km:
                    continue
                hop_weight = self._inter_constellation_bridge_weight(hop_distance, sat_a, sat_b)
                adjacency[sat_a.node_id].append((sat_b.node_id, hop_weight))
                hop_delay_ms = ((hop_distance / LIGHT_SPEED_KM_S) + processing_delay_seconds) * 1000.0
                edge_delays_ms[(sat_a.node_id, sat_b.node_id)] = hop_delay_ms

    def _compute_route_state(self) -> dict:
        sat_positions = {
            sat.node_id: satellite_position(sat.shell, sat.plane_index, sat.slot_index, self.time_seconds)
            for sat in self.satellites
        }
        processing_delay_seconds, processing_delay_label = self._processing_delay_seconds()

        ground_positions = {
            "ground_a": self.ground_a.position,
            "ground_b": self.ground_b.position,
        }

        visible_from_ground: dict[str, list[tuple[str, float, float]]] = {"ground_a": [], "ground_b": []}
        adjacency: dict[str, list[tuple[str, float]]] = {"ground_a": [], "ground_b": []}
        edge_delays_ms: dict[tuple[str, str], float] = {}

        if self.same_constellation_mode:
            self._add_ground_access_edges(
                adjacency,
                edge_delays_ms,
                visible_from_ground,
                sat_positions,
                ground_positions,
                "ground_a",
                {"a"},
            )
            self._add_ground_access_edges(
                adjacency,
                edge_delays_ms,
                visible_from_ground,
                sat_positions,
                ground_positions,
                "ground_b",
                {"a"},
            )
            self._add_intra_constellation_edges(adjacency, edge_delays_ms, sat_positions, "a", processing_delay_seconds)
        else:
            self._add_ground_access_edges(
                adjacency,
                edge_delays_ms,
                visible_from_ground,
                sat_positions,
                ground_positions,
                "ground_a",
                {"a"},
                direction="ground_to_sat",
            )
            self._add_ground_access_edges(
                adjacency,
                edge_delays_ms,
                visible_from_ground,
                sat_positions,
                ground_positions,
                "ground_b",
                {"b"},
                direction="sat_to_ground",
            )
            self._add_intra_constellation_edges(adjacency, edge_delays_ms, sat_positions, "a", processing_delay_seconds)
            self._add_intra_constellation_edges(adjacency, edge_delays_ms, sat_positions, "b", processing_delay_seconds)
            if "ixp" in self.constellations:
                self._add_ixp_bridge_edges(adjacency, edge_delays_ms, sat_positions, processing_delay_seconds)
            else:
                self._add_direct_constellation_bridge_edges(adjacency, edge_delays_ms, sat_positions, processing_delay_seconds)

        candidate_total_distance, candidate_path = dijkstra(adjacency, "ground_a", "ground_b")
        current_path_cost = path_cost(adjacency, self.active_path) if self.active_path else float("inf")
        use_current_path = False
        if self.active_path and math.isfinite(current_path_cost) and candidate_path:
            threshold_factor = 1.0 - self.conservative_switch_threshold
            use_current_path = candidate_total_distance > current_path_cost * threshold_factor
        elif self.active_path and math.isfinite(current_path_cost) and not candidate_path:
            use_current_path = True

        if use_current_path:
            total_distance = current_path_cost
            path = list(self.active_path)
        else:
            total_distance = candidate_total_distance
            path = candidate_path
            self.active_path = list(path)
        if not path:
            self.active_path = []

        route_satellites: list[str] = []
        route_segments = []
        total_delay_ms = 0.0
        first_uplink_distance_km = None
        first_uplink_elevation_deg = None
        route_satellites_by_role = {"a": [], "b": [], "ixp": []}
        ixp_satellite_index = -1
        if path:
            for left, right in zip(path, path[1:]):
                route_segments.append((left, right))
                total_delay_ms += edge_delays_ms.get((left, right), 0.0)
            route_satellites = [node for node in path if node.startswith("sat:")]
            for node_id in route_satellites:
                sat = self.satellites_by_node_id[node_id]
                route_satellites_by_role[sat.constellation_role].append(node_id)
                if sat.constellation_role == "ixp":
                    ixp_satellite_index = sat.index
            if ixp_satellite_index == -1:
                for left, right in zip(path, path[1:]):
                    if not (left.startswith("sat:") and right.startswith("sat:")):
                        continue
                    left_sat = self.satellites_by_node_id[left]
                    right_sat = self.satellites_by_node_id[right]
                    if left_sat.constellation_role != right_sat.constellation_role:
                        ixp_satellite_index = left_sat.index
                        break
            if len(path) >= 2 and path[0] == "ground_a" and path[1].startswith("sat:"):
                first_satellite_node_id = path[1]
                for sat_node_id, link_distance, elev in visible_from_ground["ground_a"]:
                    if sat_node_id == first_satellite_node_id:
                        first_uplink_distance_km = link_distance
                        first_uplink_elevation_deg = elev
                        break
        self._update_path_change_state(path)

        return {
            "sat_positions": sat_positions,
            "ground_positions": ground_positions,
            "visible_from_ground": visible_from_ground,
            "path": path,
            "route_satellites": route_satellites,
            "route_satellites_by_role": route_satellites_by_role,
            "route_segments": route_segments,
            "total_distance": total_distance,
            "total_delay_ms": total_delay_ms,
            "processing_delay_label_us": processing_delay_label,
            "first_uplink_distance_km": first_uplink_distance_km,
            "first_uplink_elevation_deg": first_uplink_elevation_deg,
            "ixp_satellite_index": ixp_satellite_index,
        }

    def _redraw(self) -> None:
        width = max(self.canvas.winfo_width(), 10)
        height = max(self.canvas.winfo_height(), 10)
        self.canvas.delete("all")

        if not self.satellites:
            self.summary_var.set("No renderable satellites found in the chosen constellation file.")
            self.route_status_var.set("Missing shell layout or inclination metadata.")
            return

        route_state = self._compute_route_state()
        self._append_log_row(route_state)
        sat_positions = route_state["sat_positions"]
        ground_positions = route_state["ground_positions"]
        route_satellites = set(route_state["route_satellites"])
        route_satellites_by_role = {
            role: set(route_state["route_satellites_by_role"][role])
            for role in ("a", "b", "ixp")
        }
        route_segments = route_state["route_segments"]
        visible_count = len(route_state["visible_from_ground"]["ground_a"]) + len(route_state["visible_from_ground"]["ground_b"])

        max_radius = max(max(vector_norm(pos) for pos in sat_positions.values()), EARTH_RADIUS_KM)
        camera_distance = (max_radius * self.settings.camera_distance_multiplier) / self.zoom
        scale = min(width, height) * self.settings.scale_fill_ratio * camera_distance / (max_radius * self.settings.scale_divisor)

        projected_points: dict[str, tuple[float, float, float]] = {}

        if self.show_earth_var.get():
            self._draw_earth_globe(width, height, camera_distance, scale)
        else:
            for start, end in self._earth_grid_segments():
                rotated_start = rotate_point(*start, yaw=self.yaw, pitch=self.pitch)
                rotated_end = rotate_point(*end, yaw=self.yaw, pitch=self.pitch)
                p0 = project_point(*rotated_start, width, height, camera_distance, scale)
                p1 = project_point(*rotated_end, width, height, camera_distance, scale)
                if p0 is None or p1 is None:
                    continue
                self.canvas.create_line(p0[0], p0[1], p1[0], p1[1], fill="#18344d", width=self.settings.earth_grid_line_width)

        render_satellites = []
        for sat in self.satellites:
            rotated = rotate_point(*sat_positions[sat.node_id], yaw=self.yaw, pitch=self.pitch)
            projected = project_point(*rotated, width, height, camera_distance, scale)
            if projected is None:
                continue
            projected_points[sat.node_id] = projected
            is_active = sat.node_id in route_satellites
            if sat.node_id in route_satellites_by_role["a"]:
                fill = "#f4a261"
            elif sat.node_id in route_satellites_by_role["b"]:
                fill = "#65d6ce"
            elif sat.node_id in route_satellites_by_role["ixp"]:
                fill = "#d16dff"
            else:
                fill = "#283744"
            radius = self.settings.satellite_radius_active if is_active else self.settings.satellite_radius_inactive
            render_satellites.append((projected[2], projected[0], projected[1], radius, fill))

        for key, ground_pos in ground_positions.items():
            rotated = rotate_point(*ground_pos, yaw=self.yaw, pitch=self.pitch)
            projected = project_point(*rotated, width, height, camera_distance, scale)
            if projected is not None:
                projected_points[key] = projected

        render_satellites.sort()
        for _, x, y, radius, fill in render_satellites:
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=fill, outline="")

        for segment_start, segment_end in route_segments:
            p0 = projected_points.get(segment_start)
            p1 = projected_points.get(segment_end)
            if p0 is None or p1 is None:
                continue
            segment_color = "#6ef2e8"
            if segment_start.startswith("sat:") and segment_end.startswith("sat:"):
                start_role = self.satellites_by_node_id[segment_start].constellation_role
                end_role = self.satellites_by_node_id[segment_end].constellation_role
                if "ixp" in (start_role, end_role):
                    segment_color = "#d16dff"
                elif start_role == "a" and end_role == "a":
                    segment_color = "#f4a261"
                elif start_role == "b" and end_role == "b":
                    segment_color = "#65d6ce"
                else:
                    segment_color = "#d16dff"
            elif segment_end.startswith("sat:"):
                sat_role = self.satellites_by_node_id[segment_end].constellation_role
                segment_color = "#f4a261" if sat_role == "a" else "#65d6ce"
            elif segment_start.startswith("sat:"):
                sat_role = self.satellites_by_node_id[segment_start].constellation_role
                segment_color = "#f4a261" if sat_role == "a" else "#65d6ce"
            self.canvas.create_line(p0[0], p0[1], p1[0], p1[1], fill=segment_color, width=self.settings.route_line_width)

        for ground_key, label in (("ground_a", self.ground_a.name), ("ground_b", self.ground_b.name)):
            projected = projected_points.get(ground_key)
            if projected is None:
                continue
            x, y, _ = projected
            self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#ffbe0b", outline="#fff1b8", width=1)
            self.canvas.create_text(x + 10, y - 10, text=label, fill="#fff6d5", anchor="sw", font=("TkDefaultFont", 10, "bold"))

        self.canvas.create_text(
            18,
            18,
            anchor="nw",
            fill="#f5f7fa",
            font=("TkDefaultFont", 11, "bold"),
            text="Dynamic route view: non-route satellites are dimmed",
        )

        if route_state["path"]:
            hop_count = max(len(route_state["path"]) - 3, 0)
            path_labels = []
            for node in route_state["path"]:
                if node == "ground_a":
                    path_labels.append(self.ground_a.name)
                elif node == "ground_b":
                    path_labels.append(self.ground_b.name)
                else:
                    sat = self.satellites_by_node_id[node]
                    path_labels.append(f"{sat.constellation_role.upper()}:{sat.label}")
            first_uplink_summary = "First uplink: unavailable"
            if route_state["first_uplink_distance_km"] is not None and route_state["first_uplink_elevation_deg"] is not None:
                first_uplink_summary = (
                    f"First uplink: {route_state['first_uplink_distance_km']:.0f} km at "
                    f"{route_state['first_uplink_elevation_deg']:.1f} deg elevation"
                )
            self.summary_var.set(
                f"Viewing {len(self.satellites)} satellites | Path A/B/IXP: "
                f"{len(route_satellites_by_role['a'])}/{len(route_satellites_by_role['b'])}/{len(route_satellites_by_role['ixp'])} | "
                f"Visible access options: {visible_count} | Log: {self.log_path.name}"
            )
            self.route_status_var.set(
                f"Route length: {route_state['total_distance']:.0f} km | ISL hops: {hop_count} | "
                f"Tx delay: {route_state['total_delay_ms']:.3f} ms | "
                f"ISL proc: {route_state['processing_delay_label_us']} us/hop | "
                f"Sim time: {self.time_seconds / SECONDS_PER_HOUR:.2f} h\n"
                f"{first_uplink_summary} | "
                f"Path: {' -> '.join(path_labels[:8])}{' -> ...' if len(path_labels) > 8 else ''}"
            )
        else:
            self.summary_var.set(
                f"Viewing {len(self.satellites)} satellites | Path A/B/IXP: 0/0/0 | Visible access options: {visible_count} | Log: {self.log_path.name}"
            )
            self.route_status_var.set(
                f"No end-to-end path at sim time {self.time_seconds / SECONDS_PER_HOUR:.2f} h. "
                f"Configured ISL processing delay: {route_state['processing_delay_label_us']} us/hop. "
                f"Check shell metadata, endpoint visibility, or ISL range."
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a dynamic satellite path between two places.")
    parser.add_argument("config", nargs="?", help="Path to a JSON config file")
    parser.add_argument(
        "--emtpy-config",
        "--empty-config",
        dest="empty_config",
        metavar="FILENAME",
        help="Create a config file populated with all supported fields and current defaults, then exit",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate the config file and print resolved endpoint coordinates without opening the GUI",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.empty_config:
        output_path = pathlib.Path(args.empty_config).resolve()
        write_default_config(output_path)
        print(f"Wrote default config to {output_path}")
        return

    if not args.config:
        raise SystemExit("A config path is required unless --emtpy-config is used.")

    config_path = pathlib.Path(args.config).resolve()
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    config = load_config(config_path)
    city_db = load_city_db(config.settings.city_db_path)
    constellations = load_constellations(config)
    ground_a = resolve_place(config.place_a, city_db, config.settings.city_db_path)
    ground_b = resolve_place(config.place_b, city_db, config.settings.city_db_path)

    if args.validate_config:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "place_a": {
                        "name": ground_a.name,
                        "latitude_deg": ground_a.latitude_deg,
                        "longitude_deg": ground_a.longitude_deg,
                    },
                    "place_b": {
                        "name": ground_b.name,
                        "latitude_deg": ground_b.latitude_deg,
                        "longitude_deg": ground_b.longitude_deg,
                    },
                    "constellation_a": str(config.constellation_a),
                    "constellation_b": str(config.constellation_b),
                    "constellation_ixp": str(config.constellation_ixp) if config.constellation_ixp else None,
                    "settings": config.settings.to_json_dict(),
                    "renderable_shells": {
                        constellation.role: len(constellation.shells)
                        for constellation in constellations
                    },
                },
                indent=2,
            )
        )
        return

    run_label = f"{ground_a.name}-to-{ground_b.name}"
    root = tk.Tk()
    viewer = ConstellationPathViewer(
        root,
        ground_a,
        ground_b,
        constellations,
        same_constellation_mode=(config.constellation_a == config.constellation_b),
        settings=config.settings,
        run_label=run_label,
    )
    viewer._redraw()
    root.mainloop()


if __name__ == "__main__":
    main()
