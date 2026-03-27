![STARS banner](graphics/banner.png)

# STARS Tools

Small standalone tools for inspecting constellation metadata and route behavior.

This repository supports the [STARS project](https://www.sintef.no/en/projects/2026/stars-space-based-topology-and-routing-study/), "Space-based Topology And Routing Study", led by SINTEF. The project explores the feasibility of inter-domain routing algorithms in space-based networks and the convergence of terrestrial and space networks.

This repository is intentionally not a production codebase. The tools here should be treated as quick-and-dirty "back-o-the-napkin" PoC/demonstrators used to visualize or inspect a specific use case or problem.

The mission of this repository is simple:
- keep small tools that are easy to tweak
- support informed guessing
- make specific routing or topology questions easier to inspect visually

Do not use simulation results from these tools to drive actual technical, operational, or commercial decisions under any circumstances.

Files:
- `src/constellation_path_viewer.py`: interactive end-to-end path viewer
- `src/constellation_viewer.py`: simple shell/orbit viewer
- `src/plot_path_viewer_log.py`: plot CSV logs from the path viewer

All Python files in this directory are released under `MPL-2.0`.

**Quick Start**
Install Python dependencies:
```bash
python3 -m pip install -r requirements.txt
```

Main tool:
```bash
python3 src/constellation_path_viewer.py config/oslo_auckland_starlink.json
```

Generate a full config:
```bash
python3 src/constellation_path_viewer.py --emtpy-config config/my_route.json
```

Validate a config:
```bash
python3 src/constellation_path_viewer.py config/oslo_auckland_starlink.json --validate-config
```

Run a mixed-constellation route:
```bash
python3 src/constellation_path_viewer.py config/nyc_london.json
```

Plot a saved run:
```bash
python3 src/plot_path_viewer_log.py logs/<run>.csv
```

Inspect shell definitions directly:
```bash
python3 src/constellation_viewer.py
```

**Requirements**
```bash
python3 --version
```

`tkinter` is required for the viewers. `matplotlib` is only required for log plotting.

**Constellation Path Viewer**
This is the main tool. It computes a dynamic route between two ground endpoints and renders:
- visible ground access opportunities
- active satellite path through constellation A, B, and optional IXP relay
- route delay and hop count over simulation time
- CSV logs for later plotting

Interpretation:
- useful for rough comparison, intuition, and exploratory reasoning
- not a validated network simulator
- not suitable for decision support

Useful configs:
- `config/oslo_auckland_starlink.json`
- `config/telesat-trd-ta.json`
- `config/nyc_london.json`

The generated config defaults to:
- `Trondheim, Norway`
- `Te Aroha, New Zealand`
- `Telesat Lightspeed`

Config parameters:
- see [CONFIG_PARAMS.md](/home/henrikau/dev/STARS/tools/CONFIG_PARAMS.md)

Path viewer controls:
- drag: rotate
- mouse wheel: zoom
- `Pause`: stop simulation time
- `Step +5 min`, `Step +30 min`: advance time manually
- `Reset View`: restore initial camera

The viewer writes a CSV log for each run to `logs/` by default.

**Data Notes**
- `data/major-cities.csv` is the built-in city database for named endpoints.
- Endpoints can also be passed as literal coordinates such as `"63.4305,10.3951"`.
- Constellation JSON paths in configs are resolved relative to the config file.
- The data and defaults are chosen for convenience, not for rigorous modeling fidelity.

**Scope and Non-Goals**
- These tools are demonstrators, not scientific instruments.
- Results are approximate and should be read as informed guesses.
- If a result matters, validate it elsewhere with proper models, assumptions, and review.

**Typical Workflow**
```bash
python3 src/constellation_path_viewer.py --emtpy-config config/experiment.json
python3 src/constellation_path_viewer.py config/experiment.json --validate-config
python3 src/constellation_path_viewer.py config/experiment.json
python3 src/plot_path_viewer_log.py logs/<latest-run>.csv
```

**Other Tools**
Plot a saved run:
```bash
python3 src/plot_path_viewer_log.py logs/20260327-153722-trondheim-norway-to-te-aroha-new-zealand.csv
python3 src/plot_path_viewer_log.py logs/<run>.csv --output plot.png
```

Inspect shell definitions directly:
```bash
python3 src/constellation_viewer.py
```

`constellation_viewer.py` is useful for checking shell counts, estimated plane layouts, and orbital spacing. It does not compute end-to-end routes.

**Layout**
```text
config/   example configs
data/     constellation JSON files and city database
logs/     CSV logs written by the path viewer
src/      Python entrypoints
```
