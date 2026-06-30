#!/usr/bin/env python3
"""Visualize d1-d2 link schedules from d12-links.json as a Gantt chart."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

IcmpSamples = dict[str, list[tuple[float, float]]]
IcmpDrops = list[tuple[float, str]]


def icmp_summary(icmp_samples: IcmpSamples, icmp_drops: IcmpDrops) -> dict[str, float]:
    received = sum(len(points) for points in icmp_samples.values())
    lost = len(icmp_drops)
    sent = received + lost
    loss_rate = (lost / sent * 100.0) if sent else 0.0
    return {
        "sent": sent,
        "received": received,
        "lost": lost,
        "loss_rate": loss_rate,
    }


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return math.nan
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percent / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    weight = rank - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def icmp_rtt_stats(icmp_samples: IcmpSamples) -> dict[str, float]:
    rtts_ms = [rtt * 1000.0 for points in icmp_samples.values() for _time, rtt in points]
    if not rtts_ms:
        return {
            "min": math.nan,
            "max": math.nan,
            "avg": math.nan,
            "stddev": math.nan,
            "p99": math.nan,
        }

    average = sum(rtts_ms) / len(rtts_ms)
    variance = sum((value - average) ** 2 for value in rtts_ms) / len(rtts_ms)
    return {
        "min": min(rtts_ms),
        "max": max(rtts_ms),
        "avg": average,
        "stddev": math.sqrt(variance),
        "p99": percentile(rtts_ms, 99.0),
    }


def format_ms(value: float) -> str:
    if math.isnan(value):
        return "n/a"
    return f"{value:.3f} ms"


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_icmp_samples(path: Path) -> tuple[IcmpSamples, IcmpDrops]:
    samples: IcmpSamples = defaultdict(list)
    drops: IcmpDrops = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"simulated_time", "active_link", "RTT"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required ICMP CSV columns: {', '.join(sorted(missing))}")

        for row in reader:
            status = row.get("status", "received").strip().lower()
            rtt = row.get("RTT", "").strip()
            simulated_time = float(row["simulated_time"])
            active_link = row["active_link"]
            if status == "lost" or not rtt:
                drops.append((simulated_time, active_link))
                continue
            samples[active_link].append((simulated_time, float(rtt)))

    if not samples and not drops:
        raise ValueError(f"No ICMP samples found in {path}")
    return samples, drops


def infer_end_time(
    links: list[dict[str, Any]],
    icmp_samples: IcmpSamples | None = None,
    icmp_drops: IcmpDrops | None = None,
) -> float:
    end_time = 0.0
    for link in links:
        for window in link.get("schedule", []):
            end_time = max(end_time, float(window["down"]))
        for event in link.get("bgp", {}).get("preference_events", []):
            end_time = max(end_time, float(event["time"]))
    if icmp_samples:
        for points in icmp_samples.values():
            for simulated_time, _rtt in points:
                end_time = max(end_time, simulated_time)
    if icmp_drops:
        for simulated_time, _link in icmp_drops:
            end_time = max(end_time, simulated_time)
    return end_time


def bgp_active_windows(link: dict[str, Any], end_time: float) -> list[tuple[float, float, int]]:
    bgp = link.get("bgp", {})
    events = sorted(
        bgp.get("preference_events", []),
        key=lambda event: float(event["time"]),
    )

    windows: list[tuple[float, float, int]] = []
    active = bool(bgp.get("initial_active", bgp.get("initial_weight", 0) > 0))
    weight = int(bgp.get("initial_weight", 0))
    cursor = 0.0

    for event in events:
        event_time = float(event["time"])
        if active and weight > 0 and event_time > cursor:
            windows.append((cursor, event_time, weight))
        cursor = event_time
        active = bool(event.get("active", active))
        weight = int(event.get("weight", weight))

    if active and weight > 0 and end_time > cursor:
        windows.append((cursor, end_time, weight))

    return windows


def plot_links(
    config: dict[str, Any],
    output_path: Path | None,
    icmp_samples: IcmpSamples | None = None,
    icmp_drops: IcmpDrops | None = None,
) -> None:
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "matplotlib is required to render the Gantt chart. "
            "Install it with: python3 -m pip install matplotlib"
        ) from exc

    links = config.get("links", [])
    if not links:
        raise ValueError("No links found in config")

    end_time = infer_end_time(links, icmp_samples, icmp_drops)
    if end_time <= 0:
        raise ValueError("Could not infer a positive end time from the config")

    fig_height = max(2.8, 0.75 * len(links) + 1.4)
    if icmp_samples or icmp_drops:
        fig, axes = plt.subplots(
            2,
            1,
            figsize=(12, fig_height + 3.2),
            sharex=True,
            gridspec_kw={"height_ratios": [max(1.0, len(links) * 0.75), 1.8]},
        )
        ax = axes[0]
        rtt_ax = axes[1]
    else:
        fig, ax = plt.subplots(figsize=(12, fig_height))
        rtt_ax = None

    bar_height = 0.42
    bgp_height = 0.62
    link_colors = {
        "d12_main": "#2563eb",
        "d12_red": "#059669",
        "d12_red0": "#059669",
        "d12_red1": "#7c3aed",
        "d12_red2": "#f59e0b",
        "red1": "#7c3aed",
        "red2": "#f59e0b",
    }
    fallback_colors = ["#0891b2", "#7c3aed", "#f59e0b", "#4b5563", "#0d9488"]

    for row, link in enumerate(links):
        y = len(links) - row - 1

        for window in link.get("schedule", []):
            up = float(window["up"])
            down = float(window["down"])
            delay = window.get("delay_us", {})
            label = f"{delay.get('min', '?')} us"
            ax.broken_barh(
                [(up, down - up)],
                (y - bar_height / 2, bar_height),
                facecolors="#5b8def",
                edgecolors="#244b8f",
                linewidth=1.0,
                zorder=2,
            )
            ax.text(
                up + (down - up) / 2,
                y,
                label,
                ha="center",
                va="center",
                fontsize=8,
                color="white",
                zorder=3,
            )

        for start, end, weight in bgp_active_windows(link, end_time):
            ax.broken_barh(
                [(start, end - start)],
                (y - bgp_height / 2, bgp_height),
                facecolors="#8fd694",
                edgecolors="none",
                alpha=0.32,
                zorder=4,
            )
            ax.text(
                start + (end - start) / 2,
                y + 0.29,
                f"BGP {weight}",
                ha="center",
                va="bottom",
                fontsize=7,
                color="#236b2e",
                zorder=5,
            )

    ax.set_yticks(range(len(links)))
    ax.set_yticklabels(
        [link.get("id", f"link-{idx}") for idx, link in reversed(list(enumerate(links)))]
    )
    ax.set_xlim(0, end_time)
    if rtt_ax is None:
        ax.set_xlabel(f"Time ({config.get('defaults', {}).get('time_unit', 's')})")
    ax.set_title("d1-d2 Link Availability and BGP Preference")
    ax.grid(axis="x", linestyle=":", linewidth=0.8, alpha=0.6)

    ax.legend(
        handles=[
            Patch(facecolor="#5b8def", edgecolor="#244b8f", label="Physical link up"),
            Patch(facecolor="#8fd694", edgecolor="none", alpha=0.32, label="BGP active, weight > 0"),
        ],
        loc="lower right",
    )

    if rtt_ax is not None:
        stats = icmp_rtt_stats(icmp_samples)
        if not math.isnan(stats["p99"]):
            rtt_ax.axhspan(
                0.0,
                stats["p99"],
                facecolor="#facc15",
                alpha=0.2,
                zorder=0,
                label="RTT <= p99",
            )

        for idx, (link, points) in enumerate(sorted(icmp_samples.items())):
            times = [point[0] for point in points]
            rtts_ms = [point[1] * 1000.0 for point in points]
            color = link_colors.get(link, fallback_colors[idx % len(fallback_colors)])
            rtt_ax.scatter(
                times,
                rtts_ms,
                s=10,
                alpha=0.75,
                color=color,
                label=link,
                linewidths=0,
            )

        if icmp_drops:
            drop_times = [point[0] for point in icmp_drops]
            rtt_ax.vlines(
                drop_times,
                0.0,
                0.08,
                transform=rtt_ax.get_xaxis_transform(),
                color="#111827",
                linewidth=1.3,
                alpha=1.0,
                zorder=9,
            )
            rtt_ax.scatter(
                drop_times,
                [0.02] * len(drop_times),
                marker="x",
                s=62,
                alpha=1.0,
                color="#111827",
                linewidths=2.4,
                label="ICMP lost",
                transform=rtt_ax.get_xaxis_transform(),
                zorder=10,
            )

        summary = icmp_summary(icmp_samples, icmp_drops or [])
        title = (
            f"ICMP RTT by Active Link | sent={summary['sent']:.0f}, "
            f"received={summary['received']:.0f}, lost={summary['lost']:.0f} "
            f"({summary['loss_rate']:.2f}%)\n"
            f"min={format_ms(stats['min'])}, avg={format_ms(stats['avg'])}, "
            f"max={format_ms(stats['max'])}, stddev={format_ms(stats['stddev'])}, "
            f"p99={format_ms(stats['p99'])}"
        )

        rtt_ax.set_xlim(0, end_time)
        rtt_ax.set_xlabel(f"Time ({config.get('defaults', {}).get('time_unit', 's')})")
        rtt_ax.set_ylabel("ICMP RTT (ms)")
        rtt_ax.set_title(title)
        rtt_ax.grid(True, linestyle=":", linewidth=0.8, alpha=0.6)
        rtt_ax.legend(title="RTT samples", loc="upper right")

    fig.tight_layout()
    if output_path is None:
        plt.show()
    else:
        fig.savefig(output_path, dpi=160)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        default=Path(__file__).with_name("d12-links.json"),
        type=Path,
        help="Path to d12-links.json",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the chart to this image path instead of opening a window",
    )
    parser.add_argument(
        "--icmp-delay",
        type=Path,
        help="Optional ICMP RTT CSV to plot below the link-status Gantt chart",
    )
    args = parser.parse_args()

    icmp_samples, icmp_drops = load_icmp_samples(args.icmp_delay) if args.icmp_delay else ({}, [])
    plot_links(load_config(args.config), args.output, icmp_samples, icmp_drops)


if __name__ == "__main__":
    main()
