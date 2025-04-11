#!/bin/bash

# Colors for output
GREEN='\e[32m'
RED='\e[31m'
YELLOW='\e[33m'
NC='\e[0m'

# Track overall test status
TEST_STATUS=0

# List of tests that have been migrated to Bats and should be skipped
MIGRATED_TESTS=("test_banner.sh")

# Run a test script and track its status
run_test_script() {
    local test_script="$1"
    local test_name=$(basename "$test_script")
    
    # Skip tests that have been migrated to Bats
    for migrated in "${MIGRATED_TESTS[@]}"; do
        if [ "$test_name" = "$migrated" ]; then
            echo -e "\n${YELLOW}[⋯]${NC} Skipping migrated test: ${test_name} (now using Bats version)"
            return 0
        fi
    done
    
    echo -e "\n${YELLOW}[⋯]${NC} Running test script: ${test_name}"
    
    if bash "$test_script"; then
        echo -e "${GREEN}[✔]${NC} Test script passed: ${test_name}"
    else
        echo -e "${RED}[✖]${NC} Test script failed: ${test_name}"
        TEST_STATUS=1
    fi
}

# Get all test scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_SCRIPTS=$(find "$SCRIPT_DIR" -name "test_*.sh" -type f | sort)

# Run all test scripts
echo "=== SKYCORE TEST SUITE ==="
echo "Found $(echo "$TEST_SCRIPTS" | wc -l) test scripts to run"

for script in $TEST_SCRIPTS; do
    run_test_script "$script"
done

# Report overall result
if [ $TEST_STATUS -eq 0 ]; then
    echo -e "\n${GREEN}[✔]${NC} All test scripts passed!"
else
    echo -e "\n${RED}[✖]${NC} Some test scripts failed!"
fi

exit $TEST_STATUS 