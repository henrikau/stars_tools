# OrbitSimulator

Python tools for rough constellation orbit visualization, dynamic path inspection, and log plotting.

This directory is part of the STARS tools repository. It is a demonstrator workspace, not a validated network simulator. Use it for intuition, sanity checks, and visual inspection only.

All commands below assume you are running them from this `OrbitSimulator/` directory.

**Getting Started**
Check Python:
```bash
python3 --version
```

Install the Python dependencies from `requirements.txt`:
```bash
python3 -m pip install -r requirements.txt
```

**Files**
- `src/constellation_path_viewer.py`: interactive end-to-end path viewer
- `src/constellation_viewer.py`: simple shell and orbit viewer
- `src/plot_path_viewer_log.py`: plot CSV logs from the path viewer
- `src/plot_ping_log.py`: plot latency and TTL from ping text logs
- `CONFIG_PARAMS.md`: configuration field reference for the path viewer
- `config/`: example route and constellation configs
- `data/`: constellation shell definitions and the city database

Python source files in this directory are released under `MPL-2.0`.

**Quick Start**
Run the main path viewer:
```bash
python3 src/constellation_path_viewer.py config/oslo_auckland_starlink.json
```

Generate a full config with defaults:
```bash
python3 src/constellation_path_viewer.py --empty-config config/my_route.json
```

Validate a config without opening the GUI:
```bash
python3 src/constellation_path_viewer.py config/oslo_auckland_starlink.json --validate-config
```

Run a mixed-constellation route:
```bash
python3 src/constellation_path_viewer.py config/nyc_london.json
```

Plot a saved path-viewer run:
```bash
python3 src/plot_path_viewer_log.py logs/<run>.csv
```

Plot a ping log:
```bash
python3 src/plot_ping_log.py ../ping.aut.ac.nz.txt --title "AUT ping" --output aut-ping.png
```

Inspect shell definitions directly:
```bash
python3 src/constellation_viewer.py
```

**Requirements**
`tkinter` is required for the interactive viewers. `matplotlib` is listed in `requirements.txt` and is required for log plotting.

**Constellation Path Viewer**
`constellation_path_viewer.py` computes a dynamic route between two ground endpoints and renders:
- visible ground access opportunities
- active satellite path through constellation A, constellation B, and optional IXP relay
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
- `config/trondheim_auckland_starlink.json`

The generated config defaults to:
- `Trondheim, Norway`
- `Te Aroha, New Zealand`
- `Telesat Lightspeed`

Config parameters are documented in [CONFIG_PARAMS.md](CONFIG_PARAMS.md).

Path viewer controls:
- drag: rotate
- mouse wheel: zoom
- `Pause`: stop simulation time
- `Step +5 min`, `Step +30 min`: advance time manually
- `Reset View`: restore initial camera

The viewer writes CSV logs to `logs/` by default.

**Data Notes**
- `data/major-cities.csv` is the built-in city database for named endpoints.
- Endpoints can also be passed as literal coordinates such as `"63.4305,10.3951"`.
- Constellation JSON paths in configs are resolved relative to the config file.
- The data and defaults are chosen for convenience, not for rigorous modeling fidelity.

**Typical Workflow**
```bash
python3 src/constellation_path_viewer.py --empty-config config/experiment.json
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

Plot a ping log:
```bash
python3 src/plot_ping_log.py ../ping.aut.ac.nz.txt
python3 src/plot_ping_log.py ../ping.aut.ac.nz.txt --title "AUT ping" --output aut-ping.png
```

Inspect shell definitions directly:
```bash
python3 src/constellation_viewer.py
```

`constellation_viewer.py` is useful for checking shell counts, estimated plane layouts, and orbital spacing. It does not compute end-to-end routes.

**Scope and Non-Goals**
- These tools are demonstrators, not scientific instruments.
- Results are approximate and should be read as informed guesses.
- If a result matters, validate it elsewhere with proper models, assumptions, and review.
