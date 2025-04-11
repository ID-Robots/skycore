#!/bin/bash

# Ensure we're running with root privileges
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root. Please run with sudo."
    exit 1
fi

# Set colors for output
GREEN='\e[32m'
RED='\e[31m'
YELLOW='\e[33m'
NC='\e[0m'

# Check if bats is installed
if ! command -v bats >/dev/null 2>&1; then
    echo -e "${RED}Error: Bats is not installed. Please install it with 'apt-get install bats'.${NC}"
    exit 1
fi

# Find all .bats files in the tests directory (excluding test_helper)
BATS_FILES=$(find "$(dirname "$0")" -name "*.bats" | grep -v "test_helper")

# Check if we found any test files
if [[ -z "$BATS_FILES" ]]; then
    echo -e "${YELLOW}No Bats test files found.${NC}"
    exit 0
fi

echo -e "${YELLOW}Found the following Bats test files:${NC}"
echo "$BATS_FILES"
echo

# Run each test file
FAILED=0
for test_file in $BATS_FILES; do
    echo -e "${YELLOW}Running tests in $test_file...${NC}"
    if bats "$test_file"; then
        echo -e "${GREEN}Tests in $test_file passed!${NC}"
    else
        echo -e "${RED}Tests in $test_file failed!${NC}"
        FAILED=1
    fi
    echo
done

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}All Bats tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some Bats tests failed.${NC}"
    exit 1
fi 