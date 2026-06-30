#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt


EVENT_MARKER = {
    "route_add": "o",
    "route_withdraw": "x",
    "selected_path_change": "s",
    "policy_change": "D",
    "originated_route": "^",
}


@dataclass
class Disturbance:
    event_id: str
    time_s: float
    label: str


@dataclass
class EventRow:
    time_s: float
    router_id: str
    asn: str
    event_type: str
    prefix: str
    nexthop: str
    as_path: str
    peer: str
    source_context: str


def load_schedule(schedule_path: str) -> Tuple[float, List[Disturbance]]:
    with open(schedule_path, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    if "measurement" not in schedule or "convergence_quiet_time_s" not in schedule["measurement"]:
        raise RuntimeError("schedule.json missing measurement.convergence_quiet_time_s")

    quiet_time_s = float(schedule["measurement"]["convergence_quiet_time_s"])

    disturbances: List[Disturbance] = []
    for event in schedule.get("events", []):
        etype = event.get("type", "")
        if etype in {"bgp_weight", "link_delay"}:
            disturbances.append(
                Disturbance(
                    event_id=str(event.get("id", "")),
                    time_s=float(event.get("time", 0.0)),
                    label=str(event.get("label", event.get("id", ""))),
                )
            )

    disturbances.sort(key=lambda d: d.time_s)
    return quiet_time_s, disturbances


def load_events(events_csv: str) -> List[EventRow]:
    rows: List[EventRow] = []
    with open(events_csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = [
            "simulated_time",
            "router_id",
            "asn",
            "event_type",
            "prefix",
            "nexthop",
            "as_path",
            "peer",
            "source_context",
        ]
        for key in required:
            if key not in reader.fieldnames:
                raise RuntimeError(f"Missing CSV column: {key}")

        for r in reader:
            rows.append(
                EventRow(
                    time_s=float(r["simulated_time"]),
                    router_id=r["router_id"],
                    asn=r["asn"],
                    event_type=r["event_type"],
                    prefix=r["prefix"],
                    nexthop=r["nexthop"],
                    as_path=r["as_path"],
                    peer=r["peer"],
                    source_context=r["source_context"],
                )
            )

    rows.sort(key=lambda e: e.time_s)
    return rows


def stable_color(as_path: str) -> str:
    if not as_path:
        return "#666666"
    if as_path == "6":
        return "#00008b"  # dark blue
    digest = hashlib.sha1(as_path.encode("utf-8")).hexdigest()
    hue = int(digest[:2], 16) / 255.0
    sat = 0.65
    val = 0.85
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    

def plot_end_time(rows: List[EventRow], disturbances: List[Disturbance]) -> float:
    end_time = max([r.time_s for r in rows] + [d.time_s for d in disturbances] + [0.0])
    return end_time


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value.strip().lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "no-route"


def choose_prefix(rows: List[EventRow], preferred: Optional[str]) -> str:
    if preferred:
        return preferred

    route_adds = [r for r in rows if r.event_type == "route_add" and r.prefix]
    if not route_adds:
        raise RuntimeError("No route_add events found and no --prefix provided")

    counts: Dict[str, int] = {}
    for r in route_adds:
        counts[r.prefix] = counts.get(r.prefix, 0) + 1

    return max(counts.items(), key=lambda kv: kv[1])[0]


def first_seen_metrics(prefix_rows: List[EventRow]) -> List[Tuple[str, str, float]]:
    first_by_router_path: Dict[Tuple[str, str], float] = {}
    for r in prefix_rows:
        if r.event_type != "route_add":
            continue
        key = (r.router_id, r.as_path)
        if key not in first_by_router_path:
            first_by_router_path[key] = r.time_s

    out = [(router, path, t) for (router, path), t in first_by_router_path.items()]
    out.sort(key=lambda x: (x[0], x[2], x[1]))
    return out


def withdraw_counts(prefix_rows: List[EventRow]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in prefix_rows:
        if r.event_type == "route_withdraw":
            counts[r.router_id] = counts.get(r.router_id, 0) + 1
    return counts


def as_path_change_counts(prefix_rows: List[EventRow]) -> Dict[str, int]:
    by_router: Dict[str, List[EventRow]] = {}
    for r in prefix_rows:
        if r.event_type == "route_add":
            by_router.setdefault(r.router_id, []).append(r)

    result: Dict[str, int] = {}
    for router, rows in by_router.items():
        rows.sort(key=lambda e: e.time_s)
        changes = 0
        last_path: Optional[str] = None
        for r in rows:
            if last_path is None:
                last_path = r.as_path
                continue
            if r.as_path != last_path:
                changes += 1
                last_path = r.as_path
        result[router] = changes

    return result


def convergence_proxy_rows(
    disturbances: List[Disturbance],
    all_rows: List[EventRow],
    prefix_rows: List[EventRow],
    quiet_time_s: float,
) -> List[Dict[str, str]]:
    selected_events = [r for r in prefix_rows if r.event_type == "selected_path_change"]
    use_selected = len(selected_events) > 0

    output: List[Dict[str, str]] = []
    for i, d in enumerate(disturbances):
        t0 = d.time_s
        t1 = disturbances[i + 1].time_s if i + 1 < len(disturbances) else float("inf")

        if use_selected:
            relevant = [r for r in selected_events if t0 <= r.time_s < t1]
            metric_type = "selected_path_convergence"
        else:
            relevant = [
                r
                for r in prefix_rows
                if r.event_type in {"route_add", "route_withdraw"} and t0 <= r.time_s < t1
            ]
            metric_type = "route_event_quiet_time_proxy"

        first_event = min((r.time_s for r in relevant), default=None)
        last_event = max((r.time_s for r in relevant), default=None)

        if first_event is None:
            duration = ""
            final_time = ""
            observed = "0"
        else:
            duration = f"{(last_event - t0):.6f}"
            final_time = f"{last_event:.6f}"
            observed = str(len(relevant))

        output.append(
            {
                "disturbance_id": d.event_id,
                "disturbance_label": d.label,
                "disturbance_time_s": f"{t0:.6f}",
                "quiet_time_s": f"{quiet_time_s:.6f}",
                "metric_type": metric_type,
                "first_event_time_s": "" if first_event is None else f"{first_event:.6f}",
                "final_event_time_s": final_time,
                "convergence_duration_s": duration,
                "observed_event_count": observed,
            }
        )

    return output


def write_csv(path: str, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def plot_propagation(
    output_path: Optional[str],
    prefix_rows: List[EventRow],
    disturbances: List[Disturbance],
) -> None:
    routers = sorted({r.router_id for r in prefix_rows})
    if not routers:
        return

    y_index = {router: i for i, router in enumerate(routers)}

    fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)

    # Track unique event types and paths to create independent legends
    unique_events = set()
    unique_paths = set()

    for r in prefix_rows:
        marker = EVENT_MARKER.get(r.event_type, ".")
        color = stable_color(r.as_path)
        
        unique_events.add(r.event_type)
        unique_paths.add(r.as_path)

        ax.scatter(r.time_s, y_index[r.router_id], marker=marker, color=color, s=40, alpha=0.9)

    for d in disturbances:
        ax.axvline(d.time_s, linestyle="--", linewidth=0.8, color="#888888", alpha=0.7)

    ax.set_yticks(range(len(routers)))
    ax.set_yticklabels(routers)
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Router ID")
    ax.set_title("BGP Route Event Propagation")
    ax.grid(axis="x", alpha=0.2)
    
    ax.set_xlim(left=0, right=plot_end_time(prefix_rows, disturbances))
    
    from matplotlib.lines import Line2D
    
    # Event types legend (black markers)
    event_handles = [
        Line2D([0], [0], marker=EVENT_MARKER.get(ev, "."), color='w', markerfacecolor='black', markeredgecolor='black', markersize=8, label=ev)
        for ev in sorted(unique_events)
    ]
    event_legend = ax.legend(handles=event_handles, loc="upper right", title="Event Types", bbox_to_anchor=(1, 1))
    ax.add_artist(event_legend)

    # AS paths legend (colored circles)
    path_handles = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor=stable_color(p), markeredgecolor='none', markersize=8, label=p if p else "No Route")
        for p in sorted(unique_paths)
    ]
    ax.legend(handles=path_handles, loc="center left", bbox_to_anchor=(1.02, 0.5), title="AS Paths")

    if output_path is not None:
        fig.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
    else:
        plt.show()


def plot_timeline(output_path: Optional[str], prefix_rows: List[EventRow], disturbances: List[Disturbance]) -> None:
    routers = sorted({r.router_id for r in prefix_rows})
    if not routers:
        return

    y_index = {router: i for i, router in enumerate(routers)}

    fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)

    unique_paths = set()

    for r in prefix_rows:
        if r.event_type != "route_add":
            continue
        color = stable_color(r.as_path)
        unique_paths.add(r.as_path)
        ax.scatter(r.time_s, y_index[r.router_id], marker="s", color=color, s=35, alpha=0.9)

    for d in disturbances:
        ax.axvline(d.time_s, linestyle="--", linewidth=0.8, color="#888888", alpha=0.7)

    ax.set_yticks(range(len(routers)))
    ax.set_yticklabels(routers)
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Router ID")
    ax.set_title("AS_PATH Timeline (route_add events)")
    ax.grid(axis="x", alpha=0.2)

    ax.set_xlim(left=0, right=plot_end_time(prefix_rows, disturbances))

    from matplotlib.lines import Line2D
    path_handles = [
        Line2D([0], [0], marker='s', color='w', markerfacecolor=stable_color(p), markeredgecolor='none', markersize=8, label=p if p else "No Route")
        for p in sorted(unique_paths)
    ]
    ax.legend(handles=path_handles, loc="center left", bbox_to_anchor=(1.02, 0.5), title="AS Paths")

    if output_path is not None:
        fig.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
    else:
        plt.show()


def plot_as1_convergence(output_path: Optional[str], prefix_rows: List[EventRow], disturbances: List[Disturbance]) -> None:
    # Filter for AS1 route additions indicating selected paths over time
    as1_rows = [r for r in prefix_rows if r.router_id == "1.1.1.1" and r.event_type == "route_add"]
    
    fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)
    
    if as1_rows:
        unique_paths = sorted({r.as_path for r in as1_rows})
        y_index = {p: i for i, p in enumerate(unique_paths)}
        
        times = [r.time_s for r in as1_rows]
        paths = [y_index[r.as_path] for r in as1_rows]
        
        # Extend the last state to the end of the simulation based on disturbances
        end_time = plot_end_time(prefix_rows, disturbances)
        times.append(end_time)
        paths.append(paths[-1])
        
        # Step plot shows what path is currently selected at any given time
        ax.step(times, paths, where="post", color="black", linewidth=1.5, alpha=0.5)
        
        for r in as1_rows:
            color = stable_color(r.as_path)
            ax.scatter(r.time_s, y_index[r.as_path], marker="o", color=color, s=80, zorder=5)
            
        ax.set_yticks(range(len(unique_paths)))
        ax.set_yticklabels([p if p else "No Route" for p in unique_paths])
    else:
        ax.text(0.5, 0.5, "No route_add events found for AS 1", ha="center", va="center", fontsize=14)
        
    for d in disturbances:
        ax.axvline(d.time_s, linestyle="--", linewidth=0.8, color="#888888", alpha=0.7)
        
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Selected AS Path")
    ax.set_title("Path Convergence for Route 6 viewed from AS 1 (1.1.1.1)")
    ax.grid(axis="y", alpha=0.5)
    
    ax.set_xlim(left=0, right=plot_end_time(prefix_rows, disturbances))
    
    if output_path is not None:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()

def plot_as1_convergence_delay(output_path: Optional[str], prefix_rows: List[EventRow], disturbances: List[Disturbance]) -> None:
    # Filter for AS1 route additions 
    as1_rows = [r for r in prefix_rows if r.router_id == "1.1.1.1" and r.event_type == "route_add"]
    
    fig, ax = plt.subplots(figsize=(13, 6.8), constrained_layout=True)
    
    times = []
    delays_ms = []
    colors = []
    
    path_delays = {"2 6": [], "2 5 6": [], "other": []}
    
    for i, d in enumerate(disturbances):
        t_start = d.time_s
        t_end = disturbances[i+1].time_s if i+1 < len(disturbances) else float('inf')
        
        # Find the FIRST route_add for AS1 after the disturbance
        relevant_events = [r for r in as1_rows if t_start <= r.time_s < t_end]
        times.append(t_start)
        
        if relevant_events:
            first_event = relevant_events[-1] # use the last route_add to indicate final convergence
            # Wait, the user asked for how long it takes to converge.
            # usually the last event before it settles or just use relevant_events[-1]
            delay_ms = (first_event.time_s - t_start) * 1000.0
            delays_ms.append(delay_ms)
            
            p = first_event.as_path
            if p == "2 6":
                colors.append(stable_color("2 6"))
                path_delays["2 6"].append(delay_ms)
            elif p == "2 5 6":
                colors.append(stable_color("2 5 6"))
                path_delays["2 5 6"].append(delay_ms)
            else:
                colors.append(stable_color(p))
                path_delays["other"].append(delay_ms)
        else:
            delays_ms.append(0.0)
            colors.append("gray")
            
    end_time = plot_end_time(prefix_rows, disturbances)
    bar_width = max(1.0, end_time * 0.012)
    ax.bar(times, delays_ms, width=bar_width, color=colors, alpha=0.8)
    
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Convergence Delay (ms)")
    ax.set_xlim(left=0, right=end_time)

    ax.grid(True, linestyle="--", alpha=0.6)
    
    # Calculate statistics and keep them outside the data area as a compact subtitle.
    import numpy as np
    stats_parts = []
    for p_key, p_name in [("2 6", "Path 2 6"), ("2 5 6", "Path 2 5 6")]:
        d_vals = path_delays[p_key]
        if d_vals:
            stats_parts.append(
                f"{p_name}: min {min(d_vals):.1f} ms, max {max(d_vals):.1f} ms, "
                f"avg {np.mean(d_vals):.1f} ms, std {np.std(d_vals):.1f} ms"
            )
        else:
            stats_parts.append(f"{p_name}: no events")
    
    if path_delays["other"]:
        d_vals = path_delays["other"]
        stats_parts.append(
            f"Other: min {min(d_vals):.1f} ms, max {max(d_vals):.1f} ms, "
            f"avg {np.mean(d_vals):.1f} ms, std {np.std(d_vals):.1f} ms"
        )

    subtitle = " | ".join(stats_parts)
    ax.set_title(
        "AS 1 Convergence Time per Weight Disturbance\n" + subtitle,
        fontsize=11,
        pad=10,
    )
    
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=stable_color('2 6'), alpha=0.8, label='Converged to Path: 2 6'),
        Patch(facecolor=stable_color('2 5 6'), alpha=0.8, label='Converged to Path: 2 5 6'),
        Patch(facecolor=stable_color('other'), alpha=0.8, label='Converged to other'),
        Patch(facecolor='gray', alpha=0.8, label='No Event (Timeout)')
    ]
    ax.legend(handles=legend_elements, loc="upper right", framealpha=0.9)
            
    if output_path is not None:
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
    else:
        plt.show()


def plot_as1_convergence_delay_boxplot(
    output_dir: Optional[str],
    prefix_rows: List[EventRow],
    disturbances: List[Disturbance],
) -> List[str]:
    as1_rows = [r for r in prefix_rows if r.router_id == "1.1.1.1" and r.event_type == "route_add"]

    path_delays: Dict[str, List[float]] = {}
    for i, d in enumerate(disturbances):
        t_start = d.time_s
        t_end = disturbances[i + 1].time_s if i + 1 < len(disturbances) else float("inf")
        relevant_events = [r for r in as1_rows if t_start <= r.time_s < t_end]
        if not relevant_events:
            continue

        final_event = relevant_events[-1]
        delay_ms = (final_event.time_s - t_start) * 1000.0
        path_label = final_event.as_path if final_event.as_path else "No Route"
        path_delays.setdefault(path_label, []).append(delay_ms)

    output_paths: List[str] = []

    if not path_delays:
        fig, ax = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
        subtitle = "No AS1 route_add events after disturbances"
        ax.text(0.5, 0.5, subtitle, ha="center", va="center", transform=ax.transAxes, fontsize=13)
        ax.set_axis_off()
        ax.set_title("AS 1 Convergence Delay Distribution\n" + subtitle, fontsize=11, pad=10)
        if output_dir is not None:
            output_path = os.path.join(output_dir, "as1-convergence-delay-boxplot-no-events.png")
            fig.savefig(output_path, dpi=150)
            output_paths.append(output_path)
            plt.close(fig)
        else:
            plt.show()
        return output_paths

    import numpy as np

    for path in sorted(path_delays):
        delays = path_delays[path]
        fig, ax = plt.subplots(figsize=(8, 5.5), constrained_layout=True)
        box = ax.boxplot(
            [delays],
            labels=[path],
            patch_artist=True,
            showmeans=True,
            meanline=True,
            widths=0.55,
        )

        for patch in box["boxes"]:
            patch.set_facecolor(stable_color(path if path != "No Route" else ""))
            patch.set_alpha(0.65)

        for element in ["whiskers", "caps", "medians", "means"]:
            for artist in box[element]:
                artist.set_color("#222222")

        subtitle = (
            f"n={len(delays)} | min {min(delays):.1f} ms, max {max(delays):.1f} ms, "
            f"avg {np.mean(delays):.1f} ms, std {np.std(delays):.1f} ms"
        )

        ax.set_xlabel("Converged AS Path at AS1")
        ax.set_ylabel("Convergence Delay (ms)")
        ax.set_title(f"AS 1 Convergence Delay Distribution: {path}\n{subtitle}", fontsize=11, pad=10)
        ax.grid(axis="y", linestyle="--", alpha=0.55)

        if output_dir is not None:
            output_path = os.path.join(
                output_dir,
                f"as1-convergence-delay-boxplot-{safe_filename(path)}.png",
            )
            fig.savefig(output_path, dpi=150)
            output_paths.append(output_path)
            plt.close(fig)
        else:
            plt.show()

    return output_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze and plot BGP AS_PATH convergence events")
    parser.add_argument("--topology", required=True, help="Path to topology.json")
    parser.add_argument("--schedule", required=True, help="Path to schedule.json")
    parser.add_argument("--events", required=True, help="Path to bgp-events.csv")
    parser.add_argument("--output-dir", default=None, help="Output directory for plots and metrics (interactive if omitted)")
    parser.add_argument("--prefix", default=None, help="Optional prefix to analyze (default: most frequent route_add prefix)")
    args = parser.parse_args()

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    quiet_time_s, disturbances = load_schedule(args.schedule)
    rows = load_events(args.events)
    prefix = choose_prefix(rows, args.prefix)
    prefix_rows = [r for r in rows if r.prefix == prefix]

    if not prefix_rows:
        raise RuntimeError(f"No events found for prefix {prefix}")

    first_seen = first_seen_metrics(prefix_rows)
    withdraw_by_router = withdraw_counts(prefix_rows)
    path_changes_by_router = as_path_change_counts(prefix_rows)
    convergence = convergence_proxy_rows(disturbances, rows, prefix_rows, quiet_time_s)

    if args.output_dir:
        propagation_png = os.path.join(args.output_dir, "bgp-event-propagation.png")
        timeline_png = os.path.join(args.output_dir, "aspath-timeline.png")
        as1_convergence_png = os.path.join(args.output_dir, "as1-path-convergence.png")
        as1_delay_png = os.path.join(args.output_dir, "as1-convergence-delay.png")
        convergence_csv = os.path.join(args.output_dir, "aspath-convergence.csv")
        first_seen_csv = os.path.join(args.output_dir, "aspath-first-seen.csv")
    else:
        propagation_png = timeline_png = as1_convergence_png = None
        as1_delay_png = convergence_csv = first_seen_csv = None

    plot_propagation(propagation_png, prefix_rows, disturbances)
    plot_timeline(timeline_png, prefix_rows, disturbances)
    plot_as1_convergence(as1_convergence_png, prefix_rows, disturbances)
    plot_as1_convergence_delay(as1_delay_png, prefix_rows, disturbances)
    as1_delay_boxplot_paths = plot_as1_convergence_delay_boxplot(
        args.output_dir,
        prefix_rows,
        disturbances,
    )

    if args.output_dir:
        write_csv(
            convergence_csv,
            convergence,
            [
                "disturbance_id",
                "disturbance_label",
                "disturbance_time_s",
                "quiet_time_s",
                "metric_type",
                "first_event_time_s",
                "final_event_time_s",
                "convergence_duration_s",
                "observed_event_count",
            ],
        )

        write_csv(
            first_seen_csv,
            [
                {
                    "router_id": router,
                    "as_path": as_path,
                    "first_seen_time_s": f"{t:.6f}",
                    "withdraw_count": str(withdraw_by_router.get(router, 0)),
                    "as_path_change_count": str(path_changes_by_router.get(router, 0)),
                }
                for router, as_path, t in first_seen
            ],
            ["router_id", "as_path", "first_seen_time_s", "withdraw_count", "as_path_change_count"],
        )

    metric_type = convergence[0]["metric_type"] if convergence else "route_event_quiet_time_proxy"

    print(f"[ASPATH][PLOT] prefix={prefix}")
    print(f"[ASPATH][PLOT] quiet_time_s={quiet_time_s:.6f} (from schedule.json)")
    print(f"[ASPATH][PLOT] metric_type={metric_type}")
    if args.output_dir:
        print(f"[ASPATH][PLOT] propagation_plot={propagation_png}")
        print(f"[ASPATH][PLOT] timeline_plot={timeline_png}")
        for path in as1_delay_boxplot_paths:
            print(f"[ASPATH][PLOT] as1_delay_boxplot={path}")
        print(f"[ASPATH][PLOT] convergence_csv={convergence_csv}")
        print(f"[ASPATH][PLOT] first_seen_csv={first_seen_csv}")


if __name__ == "__main__":
    main()
