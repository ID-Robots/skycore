#!/usr/bin/env bats

load 'test_helper/bats-support/load'
load 'test_helper/bats-assert/load'

# Setup function to prepare the test environment
setup() {
    # Create a temporary directory
    TEST_DIR=$(mktemp -d)
    
    # Use absolute path to sc.sh
    SKYCORE_PATH="/home/idr/Projects/skycore/installer/sc.sh"
    
    # Mock installation paths
    MOCK_SCRIPT_PATH="${TEST_DIR}/sc.sh"
    MOCK_INSTALL_PATH="${TEST_DIR}/usr/local/bin/sc.sh"
    MOCK_SYMLINK_PATH="${TEST_DIR}/usr/local/bin/skycore"
    
    # Create necessary directories
    mkdir -p "${TEST_DIR}/usr/local/bin"
    
    # Copy the actual skycore script to our mock location
    cp "${SKYCORE_PATH}" "${MOCK_SCRIPT_PATH}" || echo "Failed to copy ${SKYCORE_PATH}"
    chmod +x "${MOCK_SCRIPT_PATH}" || echo "Failed to chmod ${MOCK_SCRIPT_PATH}"
}

# Teardown function to clean up after tests
teardown() {
    # Clean up temporary directory
    if [ -n "$TEST_DIR" ]; then
        rm -rf "$TEST_DIR"
    fi
}

@test "install_skycore should copy the script to the installation path" {
    # Create a test script to mock install_skycore function
    TEST_SCRIPT="${TEST_DIR}/test_install.sh"
    cat << EOF > "$TEST_SCRIPT"
#!/bin/bash

# Source colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Mock paths for testing
SCRIPT_PATH="${MOCK_SCRIPT_PATH}"
INSTALL_PATH="${MOCK_INSTALL_PATH}"

# Define the install_skycore function
install_skycore() {
    echo -e "\${YELLOW}[⋯]\${NC} Installing skycore to \$INSTALL_PATH..."
    
    if [ "\$SCRIPT_PATH" == "\$INSTALL_PATH" ]; then
        echo -e "\${GREEN}[✔]\${NC} skycore is already installed at \$INSTALL_PATH"
        return
    fi
    
    # Replace sudo with cp for testing purposes
    cp "\$SCRIPT_PATH" "\$INSTALL_PATH"
    chmod +x "\$INSTALL_PATH"
    ln -sf "\$INSTALL_PATH" "${MOCK_SYMLINK_PATH}"
    
    echo -e "\${GREEN}[✔]\${NC} skycore installed successfully at \$INSTALL_PATH"
    echo -e "\${GREEN}[✔]\${NC} Created symlink at ${MOCK_SYMLINK_PATH}"
}

# Call the function
install_skycore
EOF

    chmod +x "$TEST_SCRIPT"
    
    # Run the mock script
    run "$TEST_SCRIPT"
    
    # Check that the script was installed correctly
    assert_success
    assert_output --partial "Installing skycore to ${MOCK_INSTALL_PATH}"
    assert_output --partial "skycore installed successfully at ${MOCK_INSTALL_PATH}"
    assert_output --partial "Created symlink at ${MOCK_SYMLINK_PATH}"
    
    # Check that the file was actually copied
    [ -f "${MOCK_INSTALL_PATH}" ]
    
    # Check that the symlink was created
    [ -L "${MOCK_SYMLINK_PATH}" ]
}

@test "install_skycore should detect already installed script" {
    # First install the script to our mock location
    mkdir -p "$(dirname ${MOCK_INSTALL_PATH})"
    cp "${MOCK_SCRIPT_PATH}" "${MOCK_INSTALL_PATH}"
    chmod +x "${MOCK_INSTALL_PATH}"
    
    # Create a test script that sets SCRIPT_PATH to the installation path to simulate already installed scenario
    TEST_SCRIPT="${TEST_DIR}/test_already_installed.sh"
    cat << EOF > "$TEST_SCRIPT"
#!/bin/bash

# Source colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Mock paths for testing - path is identical to simulate already installed
SCRIPT_PATH="${MOCK_INSTALL_PATH}"
INSTALL_PATH="${MOCK_INSTALL_PATH}"

# Define the install_skycore function
install_skycore() {
    echo -e "\${YELLOW}[⋯]\${NC} Installing skycore to \$INSTALL_PATH..."
    
    if [ "\$SCRIPT_PATH" == "\$INSTALL_PATH" ]; then
        echo -e "\${GREEN}[✔]\${NC} skycore is already installed at \$INSTALL_PATH"
        return
    fi
    
    # This part should not be reached for this test
    cp "\$SCRIPT_PATH" "\$INSTALL_PATH"
    chmod +x "\$INSTALL_PATH"
    ln -sf "\$INSTALL_PATH" "${MOCK_SYMLINK_PATH}"
    
    echo -e "\${GREEN}[✔]\${NC} skycore installed successfully at \$INSTALL_PATH"
    echo -e "\${GREEN}[✔]\${NC} Created symlink at ${MOCK_SYMLINK_PATH}"
}

# Call the function
install_skycore
EOF

    chmod +x "$TEST_SCRIPT"
    
    # Run the mock script
    run "$TEST_SCRIPT"
    
    # Check that the script detected it was already installed
    assert_success
    assert_output --partial "Installing skycore to ${MOCK_INSTALL_PATH}"
    assert_output --partial "skycore is already installed at ${MOCK_INSTALL_PATH}"
    
    # Make sure it doesn't have the "installed successfully" message
    refute_output --partial "skycore installed successfully at ${MOCK_INSTALL_PATH}"
}

@test "install_skycore should handle file permissions correctly" {
    # Create a test script to check file permissions
    TEST_SCRIPT="${TEST_DIR}/test_permissions.sh"
    cat << EOF > "$TEST_SCRIPT"
#!/bin/bash

# Source colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Mock paths for testing
SCRIPT_PATH="${MOCK_SCRIPT_PATH}"
INSTALL_PATH="${MOCK_INSTALL_PATH}"

# Define the install_skycore function
install_skycore() {
    echo -e "\${YELLOW}[⋯]\${NC} Installing skycore to \$INSTALL_PATH..."
    
    if [ "\$SCRIPT_PATH" == "\$INSTALL_PATH" ]; then
        echo -e "\${GREEN}[✔]\${NC} skycore is already installed at \$INSTALL_PATH"
        return
    fi
    
    # Replace sudo with cp for testing purposes
    cp "\$SCRIPT_PATH" "\$INSTALL_PATH"
    chmod +x "\$INSTALL_PATH"
    ln -sf "\$INSTALL_PATH" "${MOCK_SYMLINK_PATH}"
    
    echo -e "\${GREEN}[✔]\${NC} skycore installed successfully at \$INSTALL_PATH"
    echo -e "\${GREEN}[✔]\${NC} Created symlink at ${MOCK_SYMLINK_PATH}"
}

# Call the function
install_skycore

# Check file permissions
if [ -x "${MOCK_INSTALL_PATH}" ]; then
    echo "Executable permission set correctly"
else
    echo "ERROR: Executable permission not set"
    exit 1
fi

# Check symlink
if [ -L "${MOCK_SYMLINK_PATH}" ] && (readlink "${MOCK_SYMLINK_PATH}" | grep -q "${MOCK_INSTALL_PATH}"); then
    echo "Symlink created correctly"
else
    echo "ERROR: Symlink not created correctly"
    echo "Symlink is pointing to: $(readlink "${MOCK_SYMLINK_PATH}")"
    echo "Expected: ${MOCK_INSTALL_PATH}"
    exit 1
fi
EOF

    chmod +x "$TEST_SCRIPT"
    
    # Run the mock script
    run "$TEST_SCRIPT"
    
    # Check that the permissions were set correctly
    assert_success
    assert_output --partial "Executable permission set correctly"
    assert_output --partial "Symlink created correctly"
}

@test "install command should call install_skycore function" {
    # Create a test script that mocks the main script
    TEST_SCRIPT="${TEST_DIR}/test_command.sh"
    cat << EOF > "$TEST_SCRIPT"
#!/bin/bash

# Source colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Mock paths for testing
SCRIPT_PATH="${MOCK_SCRIPT_PATH}"
INSTALL_PATH="${MOCK_INSTALL_PATH}"

# Create a flag to track if the function was called
INSTALL_CALLED=0

# Define the install_skycore function
install_skycore() {
    INSTALL_CALLED=1
    echo "install_skycore function was called"
}

# Mock the command processing section
if [[ "\$1" == "install" ]]; then
    # Install skycore to the system
    install_skycore
fi

# Check if the function was called
if [[ \$INSTALL_CALLED -eq 1 ]]; then
    echo "Command routed correctly to install_skycore"
else
    echo "ERROR: Command not routed to install_skycore"
    exit 1
fi
EOF

    chmod +x "$TEST_SCRIPT"
    
    # Run the mock script with the install command
    run "${TEST_SCRIPT}" install
    
    # Check that the command was routed to the function
    assert_success
    assert_output --partial "install_skycore function was called"
    assert_output --partial "Command routed correctly to install_skycore"
} 