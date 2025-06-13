#!/usr/bin/env bats

# Setup - runs before each test
setup() {
  # Create temp files and dirs that tests might need
  BANNER_OUTPUT=$(mktemp)
  
  # Get the path to the skycore script
  SCRIPT_DIR="$(cd "$(dirname "$BATS_TEST_DIRNAME")" && pwd)"
  SKYCORE_PATH="${SCRIPT_DIR}/installer/sc.sh"
}

# Teardown - runs after each test
teardown() {
  # Clean up temporary files
  rm -f "$BANNER_OUTPUT"
}

# Extract the print_banner function from sc.sh
extract_print_banner() {
  local function_def=$(sed -n '/^print_banner()/,/^}/p' "$SKYCORE_PATH")
  
  # Create a temporary script with the function and colors
  local TEST_SCRIPT=$(mktemp)
  cat > "$TEST_SCRIPT" << EOF
#!/bin/bash
# Colors
GREEN='\e[32m'
CYAN='\e[36m'
YELLOW='\e[33m'
RED='\e[31m'
BLUE='\e[34m'
PURPLE='\e[35m'
NC='\e[0m'

# The extracted function
$function_def

# Call the function and capture its output
print_banner
EOF
  
  chmod +x "$TEST_SCRIPT"
  
  # Return the path to the script
  echo "$TEST_SCRIPT"
}

# Test that the banner is displayed correctly
@test "Banner should display correctly" {
  # Extract and run the print_banner function
  TEST_SCRIPT=$(extract_print_banner)
  "$TEST_SCRIPT" > "$BANNER_OUTPUT"
  
  # Test cleanup
  rm -f "$TEST_SCRIPT"
  
  # Verify the ASCII art appears in the output
  run grep "███████" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # Verify the IDRobots credit appears
  run grep "IDRobots" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # Verify the Docs reference appears
  run grep "Docs:" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # Verify a URL is included
  run grep "https://" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # Verify each line of the expected banner structure
  run cat "$BANNER_OUTPUT"
  line_count=$(echo "$output" | wc -l)
  [ "$line_count" -ge 8 ] # At least 8 lines (5 for ASCII art + blank lines + credits + docs)
}

# Test that all color variables are used in the banner
@test "Banner should use color variables" {
  # Extract the print_banner function
  local function_def=$(sed -n '/^print_banner()/,/^}/p' "$SKYCORE_PATH")
  
  # It should use the CYAN color for the banner
  [[ "$function_def" == *"CYAN"* ]]
  
  # It should reset colors after displaying
  [[ "$function_def" == *"NC"* ]]
}

# Test that the banner contains the brand name somewhere
@test "Banner should include branding" {
  TEST_SCRIPT=$(extract_print_banner)
  "$TEST_SCRIPT" > "$BANNER_OUTPUT"
  rm -f "$TEST_SCRIPT"
  
  # The banner should reference SkyCore somehow
  run grep -i "sky" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # Should mention made by IDRobots
  run grep -i "made.*by.*IDRobots" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
}

# Test that the documentation URL is correctly formatted
@test "Banner should contain correct documentation URL" {
  TEST_SCRIPT=$(extract_print_banner)
  "$TEST_SCRIPT" > "$BANNER_OUTPUT"
  rm -f "$TEST_SCRIPT"
  
  # Verify the URL contains the expected domain and path
  run grep -i "https://id-robots.github.io/skycore/" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
  
  # The URL should be on the same line as "Docs:"
  run grep -i "Docs:.*https://id-robots.github.io/skycore/" "$BANNER_OUTPUT"
  [ "$status" -eq 0 ]
} 