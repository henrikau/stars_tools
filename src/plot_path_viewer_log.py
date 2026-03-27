#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Plot path-viewer CSV logs.

Usage:
    python3 STARS/examples/plot_path_viewer_log.py STARS/examples/logs/<run>.csv
    python3 STARS/examples/plot_path_viewer_log.py STARS/examples/logs/<run>.csv --output plot.png
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot a path-viewer CSV logfile.")
    parser.add_argument("logfile", help="Path to a CSV logfile produced by constellation_path_viewer.py")
    parser.add_argument("--output", help="Optional output image path. If omitted, the plot is shown interactively.")
    return parser.parse_args()


def load_rows(csv_path: pathlib.Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    args = parse_args()
    csv_path = pathlib.Path(args.logfile).resolve()
    if not csv_path.exists():
        raise SystemExit(f"Logfile not found: {csv_path}")

    try:
        import matplotlib.pyplot as plt
        from matplotlib.ticker import MaxNLocator
    except ImportError as exc:
        raise SystemExit(
            "matplotlib is required for plotting. Install it in the Python environment used for this repo."
        ) from exc

    rows = load_rows(csv_path)
    if not rows:
        raise SystemExit(f"No data rows found in {csv_path}")

    simulation_time = [float(row["simulation_time_seconds"]) for row in rows]
    end_to_end_delay = [float(row["end_to_end_delay_ms"]) for row in rows]
    satellites_in_path_a = [int(float(row["num_satellites_in_path_a"])) for row in rows]
    satellites_in_path_b = [int(float(row.get("num_satellites_in_path_b", 0) or 0)) for row in rows]
    ixp_indices = [int(float(row.get("ixp_satellite_index", -1) or -1)) for row in rows]
    path_change_times = sorted(
        {
            float(row["last_path_change_time_seconds"])
            for row in rows
            if "last_path_change_time_seconds" in row and row["last_path_change_time_seconds"] != ""
        }
    )

    fig, ax_delay = plt.subplots(figsize=(12, 6))
    ax_satellites = ax_delay.twinx()

    ax_delay.plot(
        simulation_time,
        end_to_end_delay,
        color="#2a9d8f",
        linewidth=2.2,
        label="End-to-end delay",
    )
    if len(simulation_time) > 1:
        min_spacing = min(
            current - previous
            for previous, current in zip(simulation_time, simulation_time[1:])
            if current > previous
        )
        bar_width = min_spacing * 0.80
    else:
        bar_width = 12.0

    has_ixp = any(ixp_index != -1 for ixp_index in ixp_indices)
    if has_ixp:
        ax_satellites.bar(
            simulation_time,
            satellites_in_path_a,
            width=bar_width,
            color="#e76f51",
            alpha=0.18,
            label="Constellation A satellites",
            align="center",
        )
        ax_satellites.bar(
            simulation_time,
            satellites_in_path_b,
            width=bar_width,
            bottom=satellites_in_path_a,
            color="#457b9d",
            alpha=0.18,
            label="Constellation B satellites",
            align="center",
        )
    else:
        ax_satellites.bar(
            simulation_time,
            satellites_in_path_a,
            width=bar_width,
            color="#e76f51",
            alpha=0.18,
            label="Satellites in path",
            align="center",
        )

    ax_delay.set_title(csv_path.stem.replace("-", " "))
    ax_delay.set_xlabel("Simulation time (s)")
    ax_delay.set_ylabel("End-to-end delay (ms)", color="#2a9d8f")
    ax_satellites.set_ylabel("Satellites in path", color="#e76f51")
    ax_delay.tick_params(axis="y", labelcolor="#2a9d8f")
    ax_satellites.tick_params(axis="y", labelcolor="#e76f51")
    ax_satellites.yaxis.set_major_locator(MaxNLocator(integer=True))
    satellite_axis_max = max(a + b for a, b in zip(satellites_in_path_a, satellites_in_path_b)) if has_ixp else max(satellites_in_path_a)
    ax_satellites.set_ylim(0, max(1.0, satellite_axis_max * 1.2))
    ax_delay.grid(True, axis="both", color="#d9dde3", linewidth=0.8, alpha=0.9)
    half_width = bar_width / 2.0
    ax_delay.set_xlim(min(simulation_time) - half_width, max(simulation_time) + half_width)

    change_marker_x = []
    change_marker_y = []
    for change_time in path_change_times:
        nearest_index = min(range(len(simulation_time)), key=lambda index: abs(simulation_time[index] - change_time))
        change_marker_x.append(simulation_time[nearest_index])
        change_marker_y.append(end_to_end_delay[nearest_index])

    if change_marker_x:
        ax_delay.plot(
            change_marker_x,
            change_marker_y,
            linestyle="None",
            marker="o",
            markersize=6,
            markerfacecolor="#ffffff",
            markeredgecolor="#264653",
            markeredgewidth=1.3,
            label="Path update",
        )

    delay_handles, delay_labels = ax_delay.get_legend_handles_labels()
    satellite_handles, satellite_labels = ax_satellites.get_legend_handles_labels()
    ax_delay.legend(delay_handles + satellite_handles, delay_labels + satellite_labels, loc="upper right")

    fig.subplots_adjust(bottom=0.20, right=0.86)
    fig.tight_layout()

    if args.output:
        output_path = pathlib.Path(args.output).resolve()
        fig.savefig(output_path, dpi=160)
        print(output_path)
        return

    plt.show()


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)
