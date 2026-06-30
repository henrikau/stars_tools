# STARS Experiments

STARS is the canonical edit location for custom BGP simulation experiments in this repository.

Do not edit files in src/bgp/examples directly. Those files are synced artifacts copied from STARS by stars.sh.

## Structure

- bgp-minimal/
  - README.md: example-specific behavior, knobs, and verification notes.
  - wscript: example build wiring synced into src/bgp/examples.
  - bgp-minimal-example.cc: simulation entrypoint.
  - bgp-minimal-scenario.h/.cc: scenario orchestration and event scheduling.
  - bgp-minimal-state.h: shared scenario runtime state.
  - ns3helper-network.h: link/interface utility helpers.
  - bgp-minimal-example.drawio: topology diagram.

## Workflow

1. Make edits under STARS/bgp-minimal/.
2. Sync and run with:

```bash
./stars.sh
```

This command copies the minimal example files into src/bgp/examples/, refreshes wscript, and runs bgp-minimal-example.
