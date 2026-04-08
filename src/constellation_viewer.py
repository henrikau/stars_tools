#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Visualize constellation shell definitions in a simple 3D viewer.

The app scans `data/*.json` for shell-style constellation definitions,
builds synthetic circular-orbit satellite slots from the shell metadata, and
renders the result with tkinter.
"""

from __future__ import annotations

import json
import math
import pathlib
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


SCRIPT_PATH = pathlib.Path(__file__).resolve()
EARTH_RADIUS_KM = 6371.0
EARTH_MU_M3_S2 = 3.986004418e14
SECONDS_PER_HOUR = 3600.0


def find_project_root(start: pathlib.Path | None = None) -> pathlib.Path:
    search_start = (start or SCRIPT_PATH).resolve()
    for candidate in (search_start, *search_start.parents):
        if (candidate / "data").is_dir():
            return candidate
    raise SystemExit(
        f"Could not locate project root from {search_start}. Expected to find a data directory in a parent directory."
    )


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class ShellDefinition:
    dataset_id: str
    dataset_label: str
    section_key: str
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

    @property
    def display_name(self) -> str:
        suffix = "" if self.exact_layout else " (estimated layout)"
        return (
            f"{self.dataset_label} / {self.section_label} / {self.shell_label}"
            f" [{self.satellite_count} sats]{suffix}"
        )


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


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


def load_shells(data_dir: pathlib.Path) -> list[ShellDefinition]:
    shells: list[ShellDefinition] = []

    for json_path in sorted(data_dir.glob("*.json")):
        with json_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        dataset_label = json_path.stem.replace("-", " ").title()
        dataset_id = json_path.stem

        for section_key, section_value in payload.items():
            if not isinstance(section_value, dict):
                continue
            section_shells = section_value.get("shells")
            if not isinstance(section_shells, list):
                continue

            section_label = section_value.get("description") or section_key.replace("_", " ").title()

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
                        dataset_id=dataset_id,
                        dataset_label=dataset_label,
                        section_key=section_key,
                        section_label=str(section_label),
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

    return shells


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


class ConstellationViewer:
    palette = [
        "#4e79a7",
        "#f28e2b",
        "#e15759",
        "#76b7b2",
        "#59a14f",
        "#edc948",
        "#b07aa1",
        "#ff9da7",
        "#9c755f",
        "#bab0ab",
    ]

    def __init__(self, root: tk.Tk, shells: list[ShellDefinition]) -> None:
        self.root = root
        self.shells = shells
        self.filtered_shells = list(shells)
        self.time_seconds = 0.0
        self.time_scale = 30.0
        self.last_tick_ms = None
        self.is_playing = True
        self.yaw = math.radians(-25.0)
        self.pitch = math.radians(18.0)
        self.zoom = 1.0
        self.drag_start: tuple[int, int] | None = None

        self.dataset_var = tk.StringVar(value="All datasets")
        self.search_var = tk.StringVar()
        self.selection_label_var = tk.StringVar(value="")
        self.viewing_count_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")
        self.time_scale_var = tk.DoubleVar(value=self.time_scale)

        self.root.title("STARS Constellation Viewer")
        self.root.geometry("1380x860")
        self.root.minsize(1100, 700)

        self._build_ui()
        self._refresh_shell_list()
        self._schedule_tick()

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

        ttk.Label(controls, text="Dataset", style="Viewer.TLabel").pack(anchor="w")
        datasets = ["All datasets"] + sorted({shell.dataset_label for shell in self.shells})
        dataset_menu = ttk.OptionMenu(controls, self.dataset_var, self.dataset_var.get(), *datasets, command=lambda _: self._refresh_shell_list())
        dataset_menu.pack(fill=tk.X, pady=(2, 10))

        ttk.Label(controls, text="Filter", style="Viewer.TLabel").pack(anchor="w")
        search_entry = ttk.Entry(controls, textvariable=self.search_var)
        search_entry.pack(fill=tk.X, pady=(2, 10))
        search_entry.bind("<KeyRelease>", lambda _: self._refresh_shell_list())

        ttk.Label(controls, text="Constellations", style="Viewer.TLabel").pack(anchor="w")
        self.shell_listbox = tk.Listbox(
            controls,
            height=22,
            width=46,
            selectmode=tk.EXTENDED,
            exportselection=False,
            bg="#fffaf2",
            fg="#222222",
            selectbackground="#30475e",
            selectforeground="#ffffff",
        )
        self.shell_listbox.pack(fill=tk.BOTH, expand=False)
        self.shell_listbox.bind("<<ListboxSelect>>", lambda _: self._redraw())

        button_row = ttk.Frame(controls, style="Viewer.TFrame")
        button_row.pack(fill=tk.X, pady=(10, 10))
        ttk.Button(button_row, text="All", command=self._select_all_shells).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Clear", command=self._clear_shell_selection).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_row, text="Reset View", command=self._reset_view).pack(side=tk.RIGHT)

        ttk.Label(controls, text="Time Scale (sim hours/sec)", style="Viewer.TLabel").pack(anchor="w")
        speed_scale = ttk.Scale(
            controls,
            from_=0.0,
            to=240.0,
            variable=self.time_scale_var,
            orient=tk.HORIZONTAL,
            command=self._update_time_scale,
        )
        speed_scale.pack(fill=tk.X, pady=(2, 6))

        playback_row = ttk.Frame(controls, style="Viewer.TFrame")
        playback_row.pack(fill=tk.X)
        self.play_button = ttk.Button(playback_row, text="Pause", command=self._toggle_play)
        self.play_button.pack(side=tk.LEFT)
        ttk.Button(playback_row, text="Step +10 min", command=lambda: self._step_time(600.0)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(playback_row, text="Step +1 hr", command=lambda: self._step_time(SECONDS_PER_HOUR)).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(controls, textvariable=self.viewing_count_var, wraplength=320, style="Viewer.TLabel").pack(anchor="w", pady=(12, 2))
        ttk.Label(controls, textvariable=self.selection_label_var, wraplength=320, style="Viewer.TLabel").pack(anchor="w", pady=(12, 6))
        ttk.Label(controls, textvariable=self.status_var, wraplength=320, style="Viewer.TLabel").pack(anchor="w")

        canvas_frame = ttk.Frame(outer, style="Viewer.TFrame")
        canvas_frame.grid(row=0, column=1, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, bg="#101820", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag_view)
        self.canvas.bind("<MouseWheel>", self._zoom_view)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_view(event, delta_override=120))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_view(event, delta_override=-120))

    def _refresh_shell_list(self) -> None:
        previous_selection = {self.filtered_shells[index].display_name for index in self.shell_listbox.curselection()}
        selected_dataset = self.dataset_var.get().strip().lower()
        query = self.search_var.get().strip().lower()

        self.filtered_shells = []
        for shell in self.shells:
            if selected_dataset != "all datasets" and shell.dataset_label.lower() != selected_dataset:
                continue
            haystack = " ".join(
                [
                    shell.dataset_label,
                    shell.section_label,
                    shell.shell_label,
                    shell.shell_id,
                    shell.notes,
                ]
            ).lower()
            if query and query not in haystack:
                continue
            self.filtered_shells.append(shell)

        self.shell_listbox.delete(0, tk.END)
        for shell in self.filtered_shells:
            self.shell_listbox.insert(tk.END, shell.display_name)

        if self.filtered_shells:
            restored = False
            for index, shell in enumerate(self.filtered_shells):
                if shell.display_name in previous_selection:
                    self.shell_listbox.selection_set(index)
                    restored = True
            if not restored:
                self.shell_listbox.selection_set(0)
        self._redraw()

    def _selected_shells(self) -> list[ShellDefinition]:
        selection = self.shell_listbox.curselection()
        return [self.filtered_shells[index] for index in selection if 0 <= index < len(self.filtered_shells)]

    def _select_all_shells(self) -> None:
        self.shell_listbox.selection_set(0, tk.END)
        self._redraw()

    def _clear_shell_selection(self) -> None:
        self.shell_listbox.selection_clear(0, tk.END)
        self._redraw()

    def _reset_view(self) -> None:
        self.yaw = math.radians(-25.0)
        self.pitch = math.radians(18.0)
        self.zoom = 1.0
        self._redraw()

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

    def _start_drag(self, event: tk.Event) -> None:
        self.drag_start = (event.x, event.y)

    def _drag_view(self, event: tk.Event) -> None:
        if self.drag_start is None:
            self.drag_start = (event.x, event.y)
            return
        dx = event.x - self.drag_start[0]
        dy = event.y - self.drag_start[1]
        self.drag_start = (event.x, event.y)
        self.yaw += dx * 0.008
        self.pitch = clamp(self.pitch - dy * 0.008, math.radians(-89.0), math.radians(89.0))
        self._redraw()

    def _zoom_view(self, event: tk.Event, delta_override: int | None = None) -> None:
        delta = delta_override if delta_override is not None else event.delta
        if delta == 0:
            return
        factor = 1.1 if delta > 0 else 1.0 / 1.1
        self.zoom = clamp(self.zoom * factor, 0.25, 12.0)
        self._redraw()

    def _schedule_tick(self) -> None:
        self.root.after(33, self._tick)

    def _tick(self) -> None:
        now_ms = time.monotonic()
        if self.last_tick_ms is None:
            self.last_tick_ms = now_ms
        if self.is_playing:
            elapsed_seconds = now_ms - self.last_tick_ms
            self.time_seconds += elapsed_seconds * self.time_scale * SECONDS_PER_HOUR
            self._redraw()
        self.last_tick_ms = now_ms
        self._schedule_tick()

    def _shell_color(self, shell: ShellDefinition, index: int) -> str:
        return self.palette[index % len(self.palette)]

    def _earth_grid_segments(self) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        segments = []
        latitudes = range(-60, 61, 30)
        longitudes = range(0, 360, 30)
        for lat_deg in latitudes:
            lat = math.radians(lat_deg)
            points = []
            for lon_deg in range(0, 361, 12):
                lon = math.radians(lon_deg)
                x = EARTH_RADIUS_KM * math.cos(lat) * math.cos(lon)
                y = EARTH_RADIUS_KM * math.cos(lat) * math.sin(lon)
                z = EARTH_RADIUS_KM * math.sin(lat)
                points.append((x, y, z))
            segments.extend(zip(points, points[1:]))

        for lon_deg in longitudes:
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

    def _redraw(self) -> None:
        width = max(self.canvas.winfo_width(), 10)
        height = max(self.canvas.winfo_height(), 10)
        self.canvas.delete("all")

        selected_shells = self._selected_shells()
        if not selected_shells:
            self.viewing_count_var.set("Viewing: 0 satellites")
            self.selection_label_var.set("Select one or more shell definitions to render.")
            self.status_var.set("No satellites selected.")
            return

        max_radius = max(orbital_radius_km(shell) for shell in selected_shells)
        camera_distance = (max_radius * 3.2) / self.zoom
        viewport_span = math.sqrt(width * height)
        scale = viewport_span * 0.9 * 3.2 / 4.5

        for start, end in self._earth_grid_segments():
            rotated_start = rotate_point(*start, yaw=self.yaw, pitch=self.pitch)
            rotated_end = rotate_point(*end, yaw=self.yaw, pitch=self.pitch)
            p0 = project_point(*rotated_start, width, height, camera_distance, scale)
            p1 = project_point(*rotated_end, width, height, camera_distance, scale)
            if p0 is None or p1 is None:
                continue
            self.canvas.create_line(p0[0], p0[1], p1[0], p1[1], fill="#274c77", width=1)

        render_points = []
        total_satellites = 0
        for shell_index, shell in enumerate(selected_shells):
            color = self._shell_color(shell, shell_index)
            for plane_index in range(shell.num_planes):
                for slot_index in range(shell.sats_per_plane):
                    total_satellites += 1
                    point = satellite_position(shell, plane_index, slot_index, self.time_seconds)
                    rotated = rotate_point(*point, yaw=self.yaw, pitch=self.pitch)
                    projected = project_point(*rotated, width, height, camera_distance, scale)
                    if projected is None:
                        continue
                    render_points.append((projected[2], projected[0], projected[1], color))

        render_points.sort()
        point_radius = clamp(2.0 * self.zoom, 1.5, 4.0)
        for _, x, y, color in render_points:
            self.canvas.create_oval(
                x - point_radius,
                y - point_radius,
                x + point_radius,
                y + point_radius,
                fill=color,
                outline="",
            )

        self.canvas.create_text(
            18,
            18,
            anchor="nw",
            fill="#f5f7fa",
            font=("TkDefaultFont", 11, "bold"),
            text="Drag to orbit view, scroll to zoom",
        )

        selection_summary = f"{len(selected_shells)} shell(s), {total_satellites} satellite slots"
        self.viewing_count_var.set(f"Viewing: {total_satellites} satellites")
        self.selection_label_var.set(selection_summary)

        periods = [orbital_period_seconds(shell) / 60.0 for shell in selected_shells]
        note_suffix = ""
        if any(not shell.exact_layout for shell in selected_shells):
            note_suffix = " Estimated plane/slot counts are marked in the list."
        self.status_var.set(
            f"Sim time: {self.time_seconds / SECONDS_PER_HOUR:.2f} h | "
            f"Scale: {self.time_scale:.1f} sim h/s | "
            f"Orbital period range: {min(periods):.1f}-{max(periods):.1f} min."
            f"{note_suffix}"
        )


def main() -> None:
    shells = load_shells(DATA_DIR)
    if not shells:
        raise SystemExit(f"No shell definitions found in {DATA_DIR}")

    root = tk.Tk()
    viewer = ConstellationViewer(root, shells)
    viewer._redraw()
    root.mainloop()


if __name__ == "__main__":
    main()
