#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")

usage() {
	echo "Usage: NS3_DIR=/path/to/ns-3-dev $0 [--link-config PATH] [--icmp-trace PATH] [--help]"
	echo ""
	echo "Options:"
	echo "  --link-config PATH   Path to d1-d2 link schedule JSON file"
	echo "  --icmp-trace PATH    CSV output path for ICMP RTT samples"
	echo "  --help, -h           Show this help"
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

MINIMAL_ARGS=()

while [[ $# -gt 0 ]]; do
	arg="$1"
	case "$arg" in
		--link-config)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --link-config" >&2
				usage
				exit 1
			fi
			MINIMAL_ARGS+=("--linkConfigPath=$(existing_file_path "$2")")
			shift 2
			;;
		--link-config=*)
			MINIMAL_ARGS+=("--linkConfigPath=$(existing_file_path "${arg#*=}")")
			shift
			;;
		--icmp-trace)
			if [[ $# -lt 2 ]]; then
				echo "Missing value for --icmp-trace" >&2
				usage
				exit 1
			fi
			MINIMAL_ARGS+=("--icmpTracePath=$(absolute_path "$2")")
			shift 2
			;;
		--icmp-trace=*)
			MINIMAL_ARGS+=("--icmpTracePath=$(absolute_path "${arg#*=}")")
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

require_ns3_dir

for f in "${SCRIPT_DIR}"/bgp-minimal-*.cc "${SCRIPT_DIR}"/bgp-minimal-*.h "${SCRIPT_DIR}"/ns3helper-*.h; do
	[[ -f "$f" ]] || continue
	cp "$f" "${NS3_DIR}/src/bgp/examples/."
done
for f in "${SCRIPT_DIR}"/*.json; do
	[[ -f "$f" ]] || continue
	cp "$f" "${NS3_DIR}/src/bgp/examples/."
done

cp "${SCRIPT_DIR}/wscript" "${NS3_DIR}/src/bgp/examples/."

pushd "${NS3_DIR}" > /dev/null
if [[ ${#MINIMAL_ARGS[@]} -gt 0 ]]; then
	./waf --run "bgp-minimal-example ${MINIMAL_ARGS[*]}"
else
	./waf --run bgp-minimal-example
fi
popd > /dev/null
