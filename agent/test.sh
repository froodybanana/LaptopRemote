#!/bin/bash
# Deploys the agent and runs its tests on the laptop. Run from anywhere on the PC.
# Arguments are passed to unittest, e.g. tests.test_server; without any the whole suite runs.
set -e
host=${LAPTOPREMOTE_HOST:?set LAPTOPREMOTE_HOST to user@laptop}
bash "$(dirname "$0")/deploy.sh"
sleep 2  # connections in quick succession get reset by the laptop's sshd
if [ $# -eq 0 ]; then set -- discover -s tests; fi
ssh -o BatchMode=yes "$host" "cd ~/laptopremote/agent && python3 -W ignore -m unittest $*"
