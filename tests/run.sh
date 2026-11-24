#!/usr/bin/env bash
# Lance tous les tests : client Go (build, vet, tests) puis hub Python (tests de bout en bout).
# Usage : tests/run.sh            tout
#         tests/run.sh hub        seulement le hub
#         tests/run.sh go         seulement le client Go
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"
if [[ "$what" == all || "$what" == go ]]; then
  echo "== Go : build, vet, tests"
  go build -o /dev/null . && go vet ./... && go test ./...
fi
if [[ "$what" == all || "$what" == hub ]]; then
  echo "== Hub : tests de bout en bout (démarrent un vrai hub jetable)"
  (cd tests && python3 -W ignore -m unittest discover -s . -p "test_*.py")
fi
