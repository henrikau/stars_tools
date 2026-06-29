![STARS banner](graphics/banner.png)

# STARS Tools

Small standalone tools and NS-3 simulator experiments for inspecting constellation metadata and route behavior.

This repository supports the [STARS project](https://www.sintef.no/en/projects/2026/stars-space-based-topology-and-routing-study/), "Space-based Topology And Routing Study", led by SINTEF. The project explores the feasibility of inter-domain routing algorithms in space-based networks and the convergence of terrestrial and space networks.

This repository is intentionally not a production codebase. The tools here should be treated as quick-and-dirty "back-of-the-napkin" PoC/demonstrators used to visualize or inspect a specific use case or problem.

The mission of this repository is simple:
- keep small tools that are easy to tweak
- support informed guessing
- make specific routing or topology questions easier to inspect visually

Do not use simulation results from these tools to drive actual technical, operational, or commercial decisions under any circumstances.

**Repository Layout**
- `OrbitSimulator/`: Python constellation viewers and plotting tools for rough orbit, path, and latency inspection. See [OrbitSimulator/README.md](OrbitSimulator/README.md).
- Future standalone NS-3 simulators should live in their own top-level subdirectories with local build and run instructions.

Each subdirectory is intended to be self-contained. Start with the README in the tool or simulator directory you want to use.
