#!/usr/bin/env python3
import argparse
import json
import math
import os
from typing import Dict, List, Optional, Tuple


Point = Tuple[float, float]
ScheduleEvent = Dict[str, object]

ACTIVE_COLOR = "#009E73"
INACTIVE_COLOR = "#D62728"
DELAY_COLOR = "#CC79A7"
STATE_COLOR = "#0072B2"
DEFAULT_LINK_COLOR = "#bcccdc"
SCHEDULED_LINK_COLOR = "#52606d"
ANSI_GREEN = "\033[32m"
ANSI_RED = "\033[31m"
ANSI_RESET = "\033[0m"


def load_json(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def as_sort_key(as_entry: Dict[str, object]) -> Tuple[int, str]:
    as_id = str(as_entry.get("id", ""))
    asn = as_entry.get("asn")
    if isinstance(asn, int):
        return asn, as_id
    return 10**9, as_id


def validate_inputs(topology: Dict[str, object], schedule: Dict[str, object]) -> None:
    if not isinstance(topology.get("ases"), list):
        raise RuntimeError("topology.json missing list field: ases")
    if not isinstance(topology.get("links"), list):
        raise RuntimeError("topology.json missing list field: links")
    if not isinstance(schedule.get("events"), list):
        raise RuntimeError("schedule.json missing list field: events")

    link_ids = {str(link.get("id")) for link in topology["links"] if isinstance(link, dict)}
    for event in schedule["events"]:
        if not isinstance(event, dict):
            raise RuntimeError("schedule event must be an object")
        link_id = event.get("link_id")
        if link_id is None:
            continue
        if str(link_id) not in link_ids:
            raise RuntimeError(f"schedule event references unknown link_id: {link_id}")


def link_sort_key(link: Dict[str, object]) -> Tuple[int, str]:
    value = link.get("initial_bgp_weight")
    if isinstance(value, int):
        return value, str(link.get("id", ""))
    return 10**9, str(link.get("id", ""))


def circular_layout(as_ids: List[str], radius: float = 1.0) -> Dict[str, Point]:
    positions: Dict[str, Point] = {}
    if not as_ids:
        return positions

    start_angle = math.pi / 2
    step = 2 * math.pi / len(as_ids)
    for i, as_id in enumerate(as_ids):
        angle = start_angle - i * step
        positions[as_id] = (radius * math.cos(angle), radius * math.sin(angle))
    return positions


def link_events(schedule: Dict[str, object]) -> List[ScheduleEvent]:
    events = []
    for index, event in enumerate(schedule["events"]):
        if not isinstance(event, dict) or "link_id" not in event:
            continue
        event_type = str(event.get("type", ""))
        if event_type not in {"bgp_weight", "link_state", "link_delay"}:
            continue
        copied = dict(event)
        copied["_order"] = index
        events.append(copied)

    events.sort(key=lambda e: (float(e.get("time", 0.0)), int(e.get("_order", 0))))
    return events


def event_style(event: ScheduleEvent) -> Tuple[str, str, str]:
    event_type = str(event.get("type", ""))
    if event_type == "bgp_weight":
        active = bool(event.get("active", True))
        color = ACTIVE_COLOR if active else INACTIVE_COLOR
        marker = "o" if active else "X"
        label = f"w={event.get('weight', '?')}"
        return color, marker, label
    if event_type == "link_state":
        state = str(event.get("state", "?"))
        color = ACTIVE_COLOR if state == "up" else INACTIVE_COLOR
        marker = "^" if state == "up" else "v"
        return color, marker, state
    if event_type == "link_delay":
        mode = str(event.get("mode", "?"))
        if "delay_ms" in event:
            label = f"{event['delay_ms']}ms"
        elif "increment_ms" in event:
            label = f"+{event['increment_ms']}ms"
        else:
            label = mode
        return DELAY_COLOR, "D", label
    return STATE_COLOR, "s", event_type


def event_summary(event: ScheduleEvent) -> str:
    event_type = str(event.get("type", ""))
    direction = ""
    if event.get("from") and event.get("to"):
        direction = f"{event['from']}->{event['to']} "

    if event_type == "bgp_weight":
        active = "active" if bool(event.get("active", True)) else "inactive"
        return f"{direction}weight={event.get('weight', '?')} ({active})"
    if event_type == "link_state":
        return f"state={event.get('state', '?')}"
    if event_type == "link_delay":
        if "delay_ms" in event:
            return f"delay={event['delay_ms']}ms"
        if "increment_ms" in event:
            return f"delay +{event['increment_ms']}ms every {event.get('dt_s', '?')}s"
    return event_type


def event_state(event: ScheduleEvent) -> str:
    event_type = str(event.get("type", ""))
    if event_type == "bgp_weight":
        return "UP" if bool(event.get("active", True)) else "DOWN"
    if event_type == "link_state":
        return "UP" if str(event.get("state", "")).lower() == "up" else "DOWN"
    return "CHANGE"


def color_for_state(state: str) -> str:
    if state == "UP":
        return ANSI_GREEN
    if state == "DOWN":
        return ANSI_RED
    return ""


def colored(value: str, state: str) -> str:
    color = color_for_state(state)
    if not color:
        return value
    return f"{color}{value}{ANSI_RESET}"


def print_schedule_events(events: List[ScheduleEvent]) -> None:
    print(f"[SCHEDULE][PARSE] events={len(events)}")
    for event in events:
        time_s = float(event.get("time", 0.0))
        link_id = str(event.get("link_id", "<none>"))
        event_id = event.get("id", "<none>")
        event_type = event.get("type", "<unknown>")
        state = event_state(event)
        link_text = colored(f"LINK {link_id}", state)
        state_text = colored(state, state)
        print(
            f"[SCHEDULE][PARSE] "
            f"t={time_s:.3f}s {link_text} {state_text} "
            f"id={event_id} type={event_type} {event_summary(event)}"
        )


def filter_events_by_time(events: List[ScheduleEvent], start: float, end: float) -> List[ScheduleEvent]:
    if end < start:
        raise RuntimeError(f"--end must be greater than or equal to --start ({end} < {start})")
    return [event for event in events if start <= float(event.get("time", 0.0)) <= end]


def group_events_by_link(events: List[ScheduleEvent]) -> Dict[str, List[ScheduleEvent]]:
    events_by_link: Dict[str, List[ScheduleEvent]] = {}
    for event in events:
        events_by_link.setdefault(str(event["link_id"]), []).append(event)
    return events_by_link


def draw_topology_inset(ax, topology: Dict[str, object], scheduled_link_ids: set) -> None:
    from matplotlib.patches import Circle

    ases = sorted(topology["ases"], key=as_sort_key)
    as_ids = [str(as_entry["id"]) for as_entry in ases]
    positions = circular_layout(as_ids)

    for link in topology["links"]:
        endpoint_a, endpoint_b = [str(endpoint) for endpoint in link["endpoints"]]
        p1 = positions[endpoint_a]
        p2 = positions[endpoint_b]
        scheduled = str(link["id"]) in scheduled_link_ids
        ax.plot(
            [p1[0], p2[0]],
            [p1[1], p2[1]],
            color=SCHEDULED_LINK_COLOR if scheduled else DEFAULT_LINK_COLOR,
            linewidth=3.0 if scheduled else 1.2,
            alpha=0.95 if scheduled else 0.55,
            zorder=1,
        )

    for as_id in as_ids:
        x, y = positions[as_id]
        circle = Circle((x, y), 0.12, facecolor="#f0f4f8", edgecolor="#243b53", linewidth=1.3, zorder=2)
        ax.add_patch(circle)
        ax.text(x, y, as_id, ha="center", va="center", fontsize=8, fontweight="bold", color="#102a43", zorder=3)

    ax.set_title("Scheduled Links", fontsize=11)
    ax.set_aspect("equal")
    ax.set_xlim(-1.25, 1.25)
    ax.set_ylim(-1.25, 1.25)
    ax.set_axis_off()


def plot_schedule(
    topology: Dict[str, object],
    schedule: Dict[str, object],
    output_path: Optional[str],
    show: bool,
    start: float,
    end: Optional[float],
) -> None:
    validate_inputs(topology, schedule)
    all_events = link_events(schedule)
    schedule_end = max([float(event.get("time", 0.0)) for event in all_events] + [0.0])
    end_time = schedule_end if end is None else end
    events = filter_events_by_time(all_events, start, end_time)
    print_schedule_events(events)
    link_ids = [str(link["id"]) for link in sorted(topology["links"], key=link_sort_key)]
    y_index = {link_id: i for i, link_id in enumerate(link_ids)}
    all_events_by_link = group_events_by_link(all_events)
    window_events_by_link = group_events_by_link(events)
    scheduled_link_ids = {
        link_id
        for link_id, link_event_list in all_events_by_link.items()
        if any(float(event.get("time", 0.0)) <= end_time for event in link_event_list)
    }
    quiet_time = schedule.get("measurement", {}).get("convergence_quiet_time_s", None)

    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig = plt.figure(figsize=(13, 7.5), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 2.4])
    topo_ax = fig.add_subplot(gs[0, 0])
    ax = fig.add_subplot(gs[0, 1])

    draw_topology_inset(topo_ax, topology, scheduled_link_ids)

    for link_id in link_ids:
        y = y_index[link_id]
        ax.hlines(y, start, end_time, color="#d9e2ec", linewidth=1.0, zorder=0)

    for link in topology["links"]:
        link_id = str(link["id"])
        y = y_index[link_id]
        all_link_events = all_events_by_link.get(link_id, [])
        window_link_events = window_events_by_link.get(link_id, [])
        prior_events = [event for event in all_link_events if float(event.get("time", 0.0)) < start]
        carry_event = prior_events[-1] if prior_events else None
        segment_events = ([carry_event] if carry_event else []) + window_link_events

        if not segment_events:
            continue

        first_window_time = float(window_link_events[0].get("time", 0.0)) if window_link_events else end_time
        if carry_event is None and first_window_time > start:
            initial_weight = link.get("initial_bgp_weight", "?")
            ax.hlines(y, start, first_window_time, color="#9fb3c8", linewidth=4.5, alpha=0.8, zorder=1)
            if len(events) <= 20:
                ax.text(
                    (start + first_window_time) / 2,
                    y + 0.14,
                    f"initial w={initial_weight}",
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                )

        for i, event in enumerate(segment_events):
            event_type = str(event.get("type", ""))
            if event_type not in {"bgp_weight", "link_state"}:
                continue
            segment_start = max(start, float(event.get("time", 0.0)))
            segment_end = (
                min(end_time, float(segment_events[i + 1].get("time", 0.0)))
                if i + 1 < len(segment_events)
                else end_time
            )
            if segment_end <= segment_start:
                continue
            color, _, _ = event_style(event)
            ax.hlines(y, segment_start, segment_end, color=color, linewidth=4.5, alpha=0.85, zorder=1)

    for event in events:
        link_id = str(event["link_id"])
        time_s = float(event.get("time", 0.0))
        y = y_index[link_id]
        color, marker, label = event_style(event)
        ax.scatter(time_s, y, s=80, marker=marker, color=color, edgecolor="white", linewidth=0.8, zorder=3)
        if len(events) <= 20 or str(event.get("type", "")) == "link_delay":
            ax.text(
                time_s,
                y + 0.18,
                label,
                ha="center",
                va="bottom",
                fontsize=7.5,
                color="#102a43",
                zorder=4,
            )

    if quiet_time is not None:
        for event in events:
            quiet_start = float(event.get("time", 0.0))
            quiet_end = min(quiet_start + float(quiet_time), end_time)
            ax.axvspan(quiet_start, quiet_end, color="#f0f4f8", alpha=0.45, zorder=-1)

    ax.set_yticks(range(len(link_ids)))
    ax.set_yticklabels(link_ids)
    ax.set_xlabel("Simulation Time (s)")
    ax.set_ylabel("Topology Link")
    ax.set_xlim(left=start, right=end_time if end_time > start else start + 1)
    ax.set_ylim(-0.7, len(link_ids) - 0.25)
    ax.grid(axis="x", linestyle="--", alpha=0.35)

    legend_handles = [
        Line2D([0], [0], color="#9fb3c8", linewidth=4.5, label="Initial weight"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=ACTIVE_COLOR, markersize=9, label="BGP weight active"),
        Line2D([0], [0], marker="X", color="w", markerfacecolor=INACTIVE_COLOR, markersize=9, label="BGP weight inactive"),
        Line2D([0], [0], marker="D", color="w", markerfacecolor=DELAY_COLOR, markersize=8, label="Link delay"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor=STATE_COLOR, markersize=8, label="Link state"),
    ]
    ax.legend(handles=legend_handles, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3, frameon=False)

    active_links = ", ".join(sorted(scheduled_link_ids)) if scheduled_link_ids else "none"
    description = str(schedule.get("description", ""))
    summary = f"Events: {len(events)} | Scheduled links: {active_links}"
    summary += f" | Window: {start:g}-{end_time:g}s"
    if quiet_time is not None:
        summary += f" | Quiet window: {quiet_time}s"
    ax.set_title("Link Schedule Timeline\n" + summary, fontsize=12)
    fig.suptitle(description or summary, fontsize=13)

    if output_path:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        fig.savefig(output_path, dpi=180, bbox_inches="tight")
        print(f"[SCHEDULE][PLOT] output={output_path}")

    if show or not output_path:
        plt.show()
    else:
        plt.close(fig)

    print(f"[SCHEDULE][PLOT] events={len(events)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize scheduled link changes over time")
    parser.add_argument("--topology", default="topology.json", help="Path to topology.json")
    parser.add_argument("--schedule", default="schedule.json", help="Path to schedule.json")
    parser.add_argument("--output", default=None, help="Output image path; show interactively if omitted")
    parser.add_argument("--show", action="store_true", help="Show the plot interactively after saving")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    parser.add_argument("--end", type=float, default=None, help="End time in seconds; default is the end of the schedule")
    args = parser.parse_args()

    try:
        topology = load_json(args.topology)
        schedule = load_json(args.schedule)
        plot_schedule(topology, schedule, args.output, args.show, args.start, args.end)
    except RuntimeError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
