#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
PROGRAM_NAME="bgp-aspath-convergence-example"

TOPOLOGY_PATH="${SCRIPT_DIR}/topology.json"
SCHEDULE_PATH="${SCRIPT_DIR}/schedule.json"
BGP_TRACE_PATH=""
OUTPUT_DIR=""
ALLOW_PEER_RESET=0
FORCE_PEER_RESET=0

usage() {
	echo "Usage: NS3_DIR=/path/to/ns-3-dev $0 [options]"
	echo ""
	echo "Options:"
	echo "  --topology PATH          Path to topology JSON file"
	echo "  --schedule PATH          Path to schedule JSON file"
	echo "  --bgp-trace PATH         CSV output path for BGP route events"
	echo "  --output-dir PATH        Run output directory"
	echo "  --allow-peer-reset       Allow peer reset fallback after weight updates"
	echo "  --force-peer-reset       Force peer reset after weight updates"
	echo "  --help, -h               Show this help"
}

require_ns3_dir() {
	if [[ -z "${NS3_DIR:-}" ]]; then
		echo "Error: NS3_DIR must point to the ns-3 checkout." >&2
		echo "Example: NS3_DIR=/path/to/ns-3-dev $0" >&2
		exit 1
	fi
	if [[ ! -d "${NS3_DIR}" ]]; then
		echo "Error: NS3_DIR does not exist: ${NS3_DIR}" >&2
		exit 1
	fi
	if [[ ! -x "${NS3_DIR}/waf" ]]; then
		echo "Error: NS3_DIR does not look like an ns-3 checkout with waf: ${NS3_DIR}" >&2
		exit 1
	fi
	if [[ ! -d "${NS3_DIR}/src/bgp/examples" ]]; then
		echo "Error: NS3_DIR is missing src/bgp/examples: ${NS3_DIR}" >&2
		exit 1
	fi
}

absolute_path() {
	local path="$1"
	local parent
	local basename
	parent=$(dirname "$path")
	basename=$(basename "$path")
	if [[ ! -d "$parent" ]]; then
		echo "Error: parent directory does not exist for path: $path" >&2
		exit 1
	fi
	echo "$(cd "$parent" && pwd)/$basename"
}

existing_file_path() {
	local path
	path=$(absolute_path "$1")
	if [[ ! -f "$path" ]]; then
		echo "Error: file does not exist: $1" >&2
		exit 1
	fi
	echo "$path"
}

while [[ $# -gt 0 ]]; do
	arg="$1"
	case "$arg" in
		--topology)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --topology" >&2
				usage
				exit 1
			fi
			TOPOLOGY_PATH="$2"
			shift 2
			;;
		--topology=*)
			TOPOLOGY_PATH="${arg#*=}"
			shift
			;;
		--schedule)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --schedule" >&2
				usage
				exit 1
			fi
			SCHEDULE_PATH="$2"
			shift 2
			;;
		--schedule=*)
			SCHEDULE_PATH="${arg#*=}"
			shift
			;;
		--bgp-trace)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --bgp-trace" >&2
				usage
				exit 1
			fi
			BGP_TRACE_PATH="$2"
			shift 2
			;;
		--bgp-trace=*)
			BGP_TRACE_PATH="${arg#*=}"
			shift
			;;
		--output-dir)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --output-dir" >&2
				usage
				exit 1
			fi
			OUTPUT_DIR="$2"
			shift 2
			;;
		--output-dir=*)
			OUTPUT_DIR="${arg#*=}"
			shift
			;;
		--allow-peer-reset)
			ALLOW_PEER_RESET=1
			shift
			;;
		--force-peer-reset)
			ALLOW_PEER_RESET=1
			FORCE_PEER_RESET=1
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			echo "Unknown option: $arg" >&2
			usage
			exit 1
			;;
	esac
done

TOPOLOGY_PATH=$(existing_file_path "${TOPOLOGY_PATH}")
SCHEDULE_PATH=$(existing_file_path "${SCHEDULE_PATH}")

require_ns3_dir

if [[ -z "${OUTPUT_DIR}" ]]; then
	RUN_LABEL=$(date -u +"%Y%m%dT%H%M%SZ")
	OUTPUT_DIR="${SCRIPT_DIR}/runs/${RUN_LABEL}"
fi
mkdir -p "${OUTPUT_DIR}"
OUTPUT_DIR=$(absolute_path "${OUTPUT_DIR}")

if [[ -z "${BGP_TRACE_PATH}" ]]; then
	BGP_TRACE_PATH="${OUTPUT_DIR}/bgp-events.csv"
fi
BGP_TRACE_PATH=$(absolute_path "${BGP_TRACE_PATH}")

CONVERGENCE_QUIET_TIME="null"
STOP_TIME="null"
if command -v jq > /dev/null; then
	CONVERGENCE_QUIET_TIME=$(jq -r '.measurement.convergence_quiet_time_s // "null"' "${SCHEDULE_PATH}")
	STOP_TIME=$(jq -r '([.events[]?.time] | if length == 0 then 60 else (max + 60) end)' "${SCHEDULE_PATH}")
fi

RESET_POLICY="none"
if [[ "${FORCE_PEER_RESET}" -eq 1 ]]; then
	RESET_POLICY="force-peer-reset"
elif [[ "${ALLOW_PEER_RESET}" -eq 1 ]]; then
	RESET_POLICY="allow-peer-reset"
fi

cp "${SCRIPT_DIR}/bgp-aspath-convergence-example.cc" "${NS3_DIR}/src/bgp/examples/."
cp "${SCRIPT_DIR}/wscript" "${NS3_DIR}/src/bgp/examples/."
cp "${TOPOLOGY_PATH}" "${OUTPUT_DIR}/topology.json"
cp "${SCHEDULE_PATH}" "${OUTPUT_DIR}/schedule.json"

cat > "${OUTPUT_DIR}/run-summary.json" <<EOF
{
  "program": "${PROGRAM_NAME}",
  "topology": "${TOPOLOGY_PATH}",
  "schedule": "${SCHEDULE_PATH}",
  "bgp_trace": "${BGP_TRACE_PATH}",
  "output_dir": "${OUTPUT_DIR}",
  "rng_seed": 12345,
  "rng_run": 1,
  "stop_time_s": ${STOP_TIME},
  "convergence_quiet_time_s": ${CONVERGENCE_QUIET_TIME},
  "peer_reset_policy": "${RESET_POLICY}",
  "allow_peer_reset": ${ALLOW_PEER_RESET},
  "force_peer_reset": ${FORCE_PEER_RESET}
}
EOF

ASPATH_ARGS=(
	"--topologyPath=${TOPOLOGY_PATH}"
	"--schedulePath=${SCHEDULE_PATH}"
	"--bgpTracePath=${BGP_TRACE_PATH}"
	"--outputDir=${OUTPUT_DIR}"
	"--allowPeerReset=${ALLOW_PEER_RESET}"
	"--forcePeerReset=${FORCE_PEER_RESET}"
)

echo "[ASPATH][RUN] output_dir=${OUTPUT_DIR}"
echo "[ASPATH][RUN] bgp_trace=${BGP_TRACE_PATH}"

pushd "${NS3_DIR}" > /dev/null
./waf --run "${PROGRAM_NAME} ${ASPATH_ARGS[*]}"
popd > /dev/null
