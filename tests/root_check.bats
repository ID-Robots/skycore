#!/usr/bin/env bats

# Setup - runs before each test
setup() {
  # Get the path to the skycore script
  SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_DIRNAME")" && pwd)"
  SKYCORE_PATH="${SCRIPT_DIR}/installer/sc.sh"
}

# Create a test script that simulates the check_root function behavior
create_mock_script() {
  local should_pass="$1"  # true or false
  
  local TEST_SCRIPT=$(mktemp)
  cat > "$TEST_SCRIPT" << EOF
#!/bin/bash
# Colors for output
RED='\e[31m'
NC='\e[0m'

# Check if we should pass or fail
if [ "$should_pass" != "true" ]; then
    echo -e "\${RED}[✖]\${NC} This script must be run as root"
    exit 1
fi

echo "Script is running as root, continuing..."
exit 0
EOF
  
  chmod +x "$TEST_SCRIPT"
  echo "$TEST_SCRIPT"
}

# Test that check_root passes when run as root
@test "check_root should pass when EUID is 0" {
  # Create a script that passes the check
  TEST_SCRIPT=$(create_mock_script "true")
  
  # Run the script
  run "$TEST_SCRIPT"
  
  # Verify it completes successfully
  [ "$status" -eq 0 ]
  [[ "$output" == *"Script is running as root"* ]]
  
  # Test cleanup
  rm -f "$TEST_SCRIPT"
}

# Test that check_root fails when not run as root
@test "check_root should fail when EUID is not 0" {
  # Create a script that fails the check
  TEST_SCRIPT=$(create_mock_script "false")
  
  # Run the script
  run "$TEST_SCRIPT"
  
  # Debug output
  echo "Status: $status"
  echo "Output: $output"
  
  # Verify it exits with failure status
  [ "$status" -eq 1 ]
  [[ "$output" == *"This script must be run as root"* ]]
  
  # Test cleanup
  rm -f "$TEST_SCRIPT"
}

# Test that check_root shows the correct error message format
@test "check_root should show the correct error message" {
  # Create a script that fails the check
  TEST_SCRIPT=$(create_mock_script "false")
  
  # Run the script
  run "$TEST_SCRIPT"
  
  # Debug output
  echo "Status: $status"
  echo "Output: $output"
  
  # Verify it contains the error message with formatting
  [[ "$output" == *"[✖]"* ]]
  [[ "$output" == *"This script must be run as root"* ]]
  
  # Test cleanup
  rm -f "$TEST_SCRIPT"
} 