#!/usr/bin/env python3
import argparse
import json
import math
import os
from typing import Dict, List, Optional, Tuple


Point = Tuple[float, float]
LinkLabel = Dict[str, object]
SOURCE_COLOR = "#009E73"
DESTINATION_COLOR = "#0072B2"
DEFAULT_NODE_FACE = "#f0f4f8"
DEFAULT_NODE_EDGE = "#243b53"


def as_sort_key(as_entry: Dict[str, object]) -> Tuple[int, str]:
    as_id = str(as_entry.get("id", ""))
    asn = as_entry.get("asn")
    if isinstance(asn, int):
        return asn, as_id
    return 10**9, as_id


def load_topology(path: str) -> Dict[str, object]:
    with open(path, "r", encoding="utf-8") as f:
        topology = json.load(f)

    ases = topology.get("ases")
    links = topology.get("links")
    if not isinstance(ases, list):
        raise RuntimeError("topology.json missing list field: ases")
    if not isinstance(links, list):
        raise RuntimeError("topology.json missing list field: links")

    as_ids = {str(as_entry.get("id")) for as_entry in ases}
    for link in links:
        endpoints = link.get("endpoints") if isinstance(link, dict) else None
        if not isinstance(endpoints, list) or len(endpoints) != 2:
            raise RuntimeError(f"Link {link.get('id', '<unknown>')} must have exactly two endpoints")
        missing = [endpoint for endpoint in endpoints if endpoint not in as_ids]
        if missing:
            raise RuntimeError(f"Link {link.get('id', '<unknown>')} references unknown AS: {missing}")

    return topology


def circular_layout(as_ids: List[str], radius: float = 1.0) -> Dict[str, Point]:
    if not as_ids:
        return {}

    positions: Dict[str, Point] = {}
    # Put the first AS at the top and proceed clockwise.
    start_angle = math.pi / 2
    step = 2 * math.pi / len(as_ids)
    for i, as_id in enumerate(as_ids):
        angle = start_angle - i * step
        positions[as_id] = (radius * math.cos(angle), radius * math.sin(angle))
    return positions


def label_position(p1: Point, p2: Point, offset: float = 0.12) -> Point:
    mx = (p1[0] + p2[0]) / 2
    my = (p1[1] + p2[1]) / 2
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return mx, my

    nx = -dy / length
    ny = dx / length
    # Keep labels biased away from the center of the circle.
    if mx * nx + my * ny < 0:
        nx = -nx
        ny = -ny
    if math.hypot(mx, my) < 0.2:
        offset *= 1.6

    return mx + nx * offset, my + ny * offset


def resolve_label_collisions(labels: List[LinkLabel], min_distance: float = 0.22) -> None:
    for _ in range(80):
        changed = False
        for i in range(len(labels)):
            for j in range(i + 1, len(labels)):
                x1 = float(labels[i]["x"])
                y1 = float(labels[i]["y"])
                x2 = float(labels[j]["x"])
                y2 = float(labels[j]["y"])
                dx = x2 - x1
                dy = y2 - y1
                distance = math.hypot(dx, dy)
                if distance >= min_distance:
                    continue

                if distance == 0:
                    angle = (i + j + 1) * math.pi / 5
                    dx = math.cos(angle)
                    dy = math.sin(angle)
                    distance = 1.0

                push = (min_distance - distance) / 2
                ux = dx / distance
                uy = dy / distance
                labels[i]["x"] = x1 - ux * push
                labels[i]["y"] = y1 - uy * push
                labels[j]["x"] = x2 + ux * push
                labels[j]["y"] = y2 + uy * push
                changed = True

        if not changed:
            break


def validate_as_id(as_id: Optional[str], as_ids: List[str], option_name: str) -> None:
    if as_id is None:
        return
    if as_id not in as_ids:
        valid = ", ".join(as_ids)
        raise RuntimeError(f"{option_name} must reference a known AS ID: {as_id}. Valid AS IDs: {valid}")


def plot_topology(
    topology: Dict[str, object],
    output_path: Optional[str],
    title: Optional[str],
    show: bool,
    source: Optional[str],
    destination: Optional[str],
) -> None:
    ases = sorted(topology["ases"], key=as_sort_key)
    as_ids = [str(as_entry["id"]) for as_entry in ases]
    validate_as_id(source, as_ids, "--source")
    validate_as_id(destination, as_ids, "--destination")

    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle

    positions = circular_layout(as_ids)

    node_count = max(1, len(as_ids))
    fig_size = max(6.0, min(11.0, 1.25 * node_count))
    fig, ax = plt.subplots(figsize=(fig_size, fig_size), constrained_layout=True)

    labels: List[LinkLabel] = []

    for link in topology["links"]:
        endpoint_a, endpoint_b = [str(endpoint) for endpoint in link["endpoints"]]
        p1 = positions[endpoint_a]
        p2 = positions[endpoint_b]

        ax.plot(
            [p1[0], p2[0]],
            [p1[1], p2[1]],
            color="#52606d",
            linewidth=1.9,
            alpha=0.9,
            zorder=1,
        )

        capacity = str(link.get("capacity", "?"))
        delay = str(link.get("delay", "?"))
        lx, ly = label_position(p1, p2)
        labels.append({"x": lx, "y": ly, "text": f"{capacity}\n{delay}"})

    resolve_label_collisions(labels)

    for label in labels:
        ax.text(
            float(label["x"]),
            float(label["y"]),
            str(label["text"]),
            ha="center",
            va="center",
            fontsize=8.5,
            color="#102a43",
            bbox={
                "boxstyle": "round,pad=0.22",
                "facecolor": "white",
                "edgecolor": "#bcccdc",
                "linewidth": 0.7,
                "alpha": 0.95,
            },
            zorder=3,
        )

    node_radius = 0.14 if node_count <= 12 else 0.11
    for as_id in as_ids:
        x, y = positions[as_id]
        is_source = as_id == source
        is_destination = as_id == destination
        facecolor = DEFAULT_NODE_FACE
        edgecolor = DEFAULT_NODE_EDGE
        linewidth = 1.8
        text_color = "#102a43"

        if is_source:
            facecolor = SOURCE_COLOR
            edgecolor = SOURCE_COLOR
            linewidth = 2.4
            text_color = "white"
        if is_destination:
            facecolor = DESTINATION_COLOR
            edgecolor = DESTINATION_COLOR
            linewidth = 2.4
            text_color = "white"
        if is_source and is_destination:
            facecolor = SOURCE_COLOR
            edgecolor = DESTINATION_COLOR
            linewidth = 4.0

        circle = Circle(
            (x, y),
            node_radius,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            zorder=4,
        )
        ax.add_patch(circle)
        ax.text(
            x,
            y,
            as_id,
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold",
            color=text_color,
            zorder=5,
        )

    legend_handles = []
    if source:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor=SOURCE_COLOR,
                markeredgecolor=SOURCE_COLOR,
                markersize=10,
                label=f"Source: {source}",
            )
        )
    if destination:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor=DESTINATION_COLOR,
                markeredgecolor=DESTINATION_COLOR,
                markersize=10,
                label=f"Destination: {destination}",
            )
        )
    if legend_handles:
        ax.legend(handles=legend_handles, loc="lower center", ncol=len(legend_handles), frameon=False)

    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_xlim(-1.35, 1.35)
    ax.set_ylim(-1.35, 1.35)
    ax.set_title(title or "AS Topology", fontsize=14, pad=12)

    if output_path:
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        fig.savefig(output_path, dpi=180, bbox_inches="tight")
        print(f"[TOPOLOGY][PLOT] output={output_path}")

    if show or not output_path:
        plt.show()
    else:
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize an AS topology JSON file")
    parser.add_argument("--topology", default=None, help="Path to topology.json")
    parser.add_argument("--output", default="topology.png", help="Output image path")
    parser.add_argument("--title", default=None, help="Optional plot title")
    parser.add_argument("--show", action="store_true", help="Show the plot interactively")
    parser.add_argument("--source", default=None, help="Source AS ID, for example as1")
    parser.add_argument("--destination", default=None, help="Destination AS ID, for example as6")
    args = parser.parse_args()

    topology_path = args.topology or "topology.json"
    output_path = args.output if args.topology else None

    try:
        topology = load_topology(topology_path)
        plot_topology(topology, output_path, args.title, args.show, args.source, args.destination)
    except RuntimeError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
