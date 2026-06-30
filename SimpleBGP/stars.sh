#!/bin/bash
set -e
BDIR=$(dirname $(readlink -f ${BASH_SOURCE[0]}))
pushd ${BDIR} > /dev/null
echo "${BDIR}"

usage() {
	echo "Usage: $0 --ns3-dir PATH"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
	--ns3-dir)
	    if [[ $# -lt 2 || "$2" == --* ]]; then
		echo "Missing value for --ns3-dir"
		usage
		popd > /dev/null
		exit 1
	    fi
	    NS3_DIR=$(readlink -f "$2")
	    shift 2
	    ;;
	--ns3-dir=*)
	    NS3_DIR=$(readlink -f "${1#*=}")
	    shift
	    ;;
	--help|-h)
	    usage
	    popd > /dev/null
	    exit 0
	    ;;
	*)
	    echo "Unknown option: $1"
	    usage
	    popd > /dev/null
	    exit 1
	    ;;
    esac
done

test -d "${NS3_DIR}" || { echo -ne "Need a valid path to NS-3 dev dir.\n\n"; usage; exit 1; }

# Sync STARS example sources/headers used by bgp-minimal-example.
for f in bgp-minimal-*.cc bgp-minimal-*.h ns3helper-*.h; do
    [[ -f "$f" ]] || continue
    cp -v "$f" "${NS3_DIR}/src/bgp/examples/."
done

# Always refresh wscript so build wiring stays in sync with STARS/bgp-minimal/wscript.
cp -v "wscript" "${NS3_DIR}/src/bgp/examples/."
pushd ${NS3_DIR} > /dev/null
./waf --run bgp-minimal-example
popd > /dev/null
popd > /dev/null
