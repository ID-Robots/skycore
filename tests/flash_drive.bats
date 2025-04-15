#!/usr/bin/env bats

load 'test_helper/bats-support/load'
load 'test_helper/bats-assert/load'

# Helper function to create test environment - optimized for speed
setup() {
    # Create a temporary directory for test files
    TEST_DIR=$(mktemp -d)
    
    # Create source and target test block device files - reduced to 10MB
    dd if=/dev/zero of="$TEST_DIR/source_device" bs=1M count=10 2>/dev/null
    dd if=/dev/zero of="$TEST_DIR/target_device" bs=1M count=10 2>/dev/null
    
    # Create loop devices
    SOURCE_LOOP=$(sudo losetup -f "$TEST_DIR/source_device" --show)
    TARGET_LOOP=$(sudo losetup -f "$TEST_DIR/target_device" --show)
    
    # Create partition table and partition on source device
    echo 'label: dos
start=2048, type=83' | sudo sfdisk "$SOURCE_LOOP" 2>/dev/null
    
    # Ensure kernel recognizes the new partition table
    sudo partprobe "$SOURCE_LOOP" 2>/dev/null
    
    # Format the partition with a small filesystem
    sudo mkfs.ext4 -F "${SOURCE_LOOP}p1" 2>/dev/null
    
    # Create minimal test data (avoid mounting when possible)
    MOUNT_POINT="$TEST_DIR/source_mount"
    mkdir -p "$MOUNT_POINT"
    sudo mount "${SOURCE_LOOP}p1" "$MOUNT_POINT"
    echo "test" | sudo tee "$MOUNT_POINT/test_file.txt" > /dev/null
    sudo umount "$MOUNT_POINT"
    
    # Create a directory to hold partition images
    IMAGE_DIR="$TEST_DIR/images"
    mkdir -p "$IMAGE_DIR"
    
    # Create partition table backup
    sudo sfdisk -d "$SOURCE_LOOP" > "$IMAGE_DIR/jetson_nvme_partitions.sfdisk" 2>/dev/null
    
    # Create block device info
    sudo blkid "$SOURCE_LOOP"* > "$IMAGE_DIR/jetson_nvme_blkinfo.txt" 2>/dev/null || true
    
    # Create partition image using a faster setting - set proper buffer size
    sudo partclone.ext4 -c -s "${SOURCE_LOOP}p1" -o "$IMAGE_DIR/jetson_nvme_p1.img" -b 2>/dev/null
}

# Helper function to clean up test resources
teardown() {
    # Unmount any partitions that might still be mounted
    for mp in "$TEST_DIR/source_mount" "$TEST_DIR/target_mount"; do
        if mountpoint -q "$mp" 2>/dev/null; then
            sudo umount "$mp" || true
        fi
    done
    
    # Detach loop devices
    if [ -n "$SOURCE_LOOP" ]; then
        sudo losetup -d "$SOURCE_LOOP" 2>/dev/null || true
    fi
    if [ -n "$TARGET_LOOP" ]; then
        sudo losetup -d "$TARGET_LOOP" 2>/dev/null || true
    fi
    
    # Remove test directory
    if [ -n "$TEST_DIR" ]; then
        sudo rm -rf "$TEST_DIR" || true
    fi
    
    # Clean up any leftover in-memory directories
    sudo rm -rf /dev/shm/test-extract-dir 2>/dev/null || true
    sudo rm -rf /dev/shm/test-flash-*.sh 2>/dev/null || true
}

@test "flash_drive should fail without target device" {
    # Supply "1" to pass the image selection prompt before failing due to missing target
    run bash -c "echo 1 | sudo ./installer/sc.sh flash"
    assert_failure
    assert_output --partial "No target device specified"
}

@test "flash_drive should fail with non-existent target device" {
    # Include a specific image to avoid the selection menu
    run sudo ./installer/sc.sh flash --target /dev/nonexistent --image test-image.tar.gz
    assert_failure
    assert_output --partial "does not exist or is not a block device"
}

@test "flash_drive should fail with non-existent input directory" {
    # Include a specific image to avoid the selection menu
    run sudo ./installer/sc.sh flash --target "$TARGET_LOOP" --input /nonexistent/dir
    assert_failure
    assert_output --partial "Input directory /nonexistent/dir does not exist"
}

@test "flash_drive should restore partition table and images" {
    # Skip confirmation prompts
    run bash -c "echo y | sudo ./installer/sc.sh flash --target '$TARGET_LOOP' --input '$IMAGE_DIR'"
    
    # Diagnostic output
    echo "Exit status: $status"
    echo "Output: $output"
    
    assert_success
    
    # Verify partition was created on target
    run sudo fdisk -l "$TARGET_LOOP"
    assert_success
    assert_output --partial "${TARGET_LOOP}p1"
    
    # Mount and verify data
    VERIFY_MOUNT="$TEST_DIR/target_mount"
    mkdir -p "$VERIFY_MOUNT"
    run sudo mount "${TARGET_LOOP}p1" "$VERIFY_MOUNT"
    assert_success
    
    # Check test file exists and has correct content
    run cat "$VERIFY_MOUNT/test_file.txt"
    assert_success
    assert_output "test"
    
    # Cleanup
    sudo umount "$VERIFY_MOUNT"
}

@test "flash_drive should handle mounted partitions" {
    # Create a partition on target for mounting
    echo 'label: dos
start=2048, type=83' | sudo sfdisk "$TARGET_LOOP"
    sudo partprobe "$TARGET_LOOP"
    sudo mkfs.ext4 "${TARGET_LOOP}p1"
    
    # Mount the partition
    MOUNT_POINT="$TEST_DIR/target_mount"
    mkdir -p "$MOUNT_POINT"
    sudo mount "${TARGET_LOOP}p1" "$MOUNT_POINT"
    
    # Verify it's mounted initially (store mount status first)
    MOUNT_STATUS=$(sudo mount | grep -c "${TARGET_LOOP}p1" || true)
    echo "Initial mount count: $MOUNT_STATUS"
    [ "$MOUNT_STATUS" -gt 0 ] || (echo "ERROR: Partition not mounted initially" && exit 1)
    
    # Run flash with 'y' to both prompts (unmount confirmation and flash confirmation)
    run bash -c "echo -e 'y\ny' | sudo ./installer/sc.sh flash --target '$TARGET_LOOP' --input '$IMAGE_DIR'"
    
    # We only care that the command runs successfully, not about restoring the exact file contents
    assert_success
    
    # Success if we get here - the test was only checking that mounted partitions are handled
    # without errors during the flash process
}

@test "list_block_devices should show available block devices" {
    # Run the list command and capture its output
    output=$(sudo TERM=dumb ./installer/sc.sh list)
    
    # Check that the command succeeded
    [ $? -eq 0 ]
    
    # Check that the output contains the expected header
    echo "$output" | grep -q "Available block devices:"
    
    # Check that the output contains the expected column headers from lsblk
    echo "$output" | grep -q "NAME"
    echo "$output" | grep -q "SIZE"
    echo "$output" | grep -q "TYPE"
    echo "$output" | grep -q "MOUNTPOINT"
}


@test "download_image should reuse existing archive when FROM_S3=true and file exists" {
    # Create mock test environment
    export FROM_S3=true
    export S3_BUCKET="s3://test-bucket"
    export IMAGE_NAME="test-image.tar.gz"
    export ARCHIVE_FILE="/tmp/test-image.tar.gz"
    
    # Create a temp file to simulate existing archive
    touch "$ARCHIVE_FILE"
    
    # Run the download_image function
    run bash -c "source ./installer/sc.sh && download_image"
    
    # Clean up
    rm -f "$ARCHIVE_FILE"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it detected and reused the existing archive
    assert_output --partial "Archive already exists at $ARCHIVE_FILE"
    assert_output --partial "Reusing existing archive"
    
    # Clean up environment variables
    unset FROM_S3 S3_BUCKET IMAGE_NAME ARCHIVE_FILE
}

@test "download_image should download from S3 when FROM_S3=true and file doesn't exist" {
    # Create mock test environment
    export FROM_S3=true
    export S3_BUCKET="s3://test-bucket"
    export IMAGE_NAME="test-image.tar.gz"
    export ARCHIVE_FILE="/tmp/nonexistent-test-image.tar.gz"
    
    # Create mock for aws command
    function aws() {
        echo "Mock aws $@"
        # Create the output file to simulate successful download
        touch "$ARCHIVE_FILE"
        return 0
    }
    export -f aws
    
    # Run the download_image function
    run bash -c "source ./installer/sc.sh && download_image"
    
    # Clean up
    rm -f "$ARCHIVE_FILE"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it attempted to download the archive
    assert_output --partial "Downloading archive from S3"
    assert_output --partial "Mock aws s3 cp ${S3_BUCKET}/${IMAGE_NAME} ${ARCHIVE_FILE} --no-sign-request"
    assert_output --partial "Archive downloaded successfully"
    
    # Clean up environment variables and mocks
    unset FROM_S3 S3_BUCKET IMAGE_NAME ARCHIVE_FILE
    unset -f aws
}

@test "download_image should use local source when FROM_S3=false" {
    # Create mock test environment
    export FROM_S3=false
    
    # Run the download_image function
    run bash -c "source ./installer/sc.sh && download_image"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it used the local source
    assert_output --partial "Using local source instead of downloading from S3"
    
    # Clean up environment variables
    unset FROM_S3
}

@test "extract_image should use existing input directory when INPUT_DIR is set" {
    # Create mock environment with INPUT_DIR
    export INPUT_DIR="/tmp/test-input-dir"
    export TMP_EXTRACT_DIR="/tmp/test-extract-dir"
    
    # Create the directory to ensure it exists for the test
    mkdir -p "$INPUT_DIR"
    
    # Run the extract_image function
    run bash -c "source ./installer/sc.sh && extract_image"
    
    # Clean up
    rmdir "$INPUT_DIR"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it used the existing directory
    assert_output --partial "Using existing directory: $INPUT_DIR"
    
    # Clean up environment variables
    unset INPUT_DIR TMP_EXTRACT_DIR
}

@test "extract_image should reuse existing extracted files when available" {
    # Create mock environment without INPUT_DIR but with existing extracted files
    export TMP_EXTRACT_DIR="/tmp/test-extract-dir"
    unset INPUT_DIR
    
    # Create directory and required files
    mkdir -p "$TMP_EXTRACT_DIR"
    touch "$TMP_EXTRACT_DIR/jetson_nvme_partitions.sfdisk"
    mkdir -p "$TMP_EXTRACT_DIR/images"
    touch "$TMP_EXTRACT_DIR/images/jetson_nvme_p1.img"
    
    # Run the extract_image function
    run bash -c "source ./installer/sc.sh && extract_image"
    
    # Clean up
    rm -f "$TMP_EXTRACT_DIR/jetson_nvme_partitions.sfdisk"
    rm -f "$TMP_EXTRACT_DIR/images/jetson_nvme_p1.img"
    rmdir "$TMP_EXTRACT_DIR/images"
    rmdir "$TMP_EXTRACT_DIR"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it reused the existing extracted files
    assert_output --partial "Found existing extracted files in: $TMP_EXTRACT_DIR"
    assert_output --partial "Reusing existing extracted files"
    
    # Clean up environment variables
    unset TMP_EXTRACT_DIR
}

@test "extract_image should extract archive when no existing files are found" {
    # Create mock environment without INPUT_DIR and without existing extracted files
    export TMP_EXTRACT_DIR="/tmp/test-extract-dir"
    export ARCHIVE_FILE="/tmp/test-archive.tar.gz"
    unset INPUT_DIR
    
    # Create a mock archive file
    mkdir -p /tmp/temp_archive_contents
    touch /tmp/temp_archive_contents/test_file
    tar -czf "$ARCHIVE_FILE" -C /tmp/temp_archive_contents .
    rm -rf /tmp/temp_archive_contents
    
    # Create mock for tar command to avoid actual extraction
    function tar() {
        echo "Mock tar $@"
        # Create the directory to simulate successful extraction
        mkdir -p "$TMP_EXTRACT_DIR"
        return 0
    }
    export -f tar
    
    # Run the extract_image function
    run bash -c "source ./installer/sc.sh && extract_image"
    
    # Clean up
    rmdir "$TMP_EXTRACT_DIR" 2>/dev/null || true
    rm -f "$ARCHIVE_FILE"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it attempted to extract the archive
    assert_output --partial "Extracting archive to temporary directory: $TMP_EXTRACT_DIR"
    assert_output --partial "Archive extracted successfully"
    
    # Clean up environment variables and mocks
    unset TMP_EXTRACT_DIR ARCHIVE_FILE
    unset -f tar
}

@test "check_mounted_partitions should continue when no partitions are mounted" {
    # Set up test environment
    export TARGET_DEVICE="/dev/test_device"
    
    # Mock lsblk to report no partitions
    function lsblk() {
        echo "test_device"
    }
    export -f lsblk
    
    # Mock grep to simulate no mounted partitions
    function grep() {
        if [[ "$1" == "-q" && "$3" == *"test_device"* ]]; then
            return 1  # Nothing mounted
        fi
        /bin/grep "$@"  # Call real grep for other cases
    }
    export -f grep
    
    # Run the function
    run bash -c "source ./installer/sc.sh && check_mounted_partitions"
    
    # Check that it succeeded
    assert_success
    
    # Check output indicates checking for mounted partitions
    assert_output --partial "Checking for mounted partitions on $TARGET_DEVICE"
    # Check that no warning about mounted partitions appears
    refute_output --partial "Warning:"
    refute_output --partial "currently mounted"
    
    # Clean up
    unset TARGET_DEVICE
    unset -f lsblk grep
}

@test "check_mounted_partitions should detect and unmount partitions when user confirms" {
    # Set up test environment
    export TARGET_DEVICE="/dev/test_device"
    
    # Define cleanup function but don't export it
    function cleanup() { 
        echo "Mocked cleanup"
    }
    export -f cleanup
    
    # Mock lsblk to report one partition
    function lsblk() {
        echo "test_device1"
    }
    export -f lsblk
    
    # Mock mount to simulate the partition is mounted
    function mount() {
        echo "/dev/test_device1 on /mnt type ext4"
    }
    export -f mount
    
    # Mock grep to simulate mounted partition
    function grep() {
        if [[ "$1" == "-q" && "$3" == *"test_device1"* ]]; then
            return 0  # Partition is mounted
        elif [[ "$1" == "-v" ]]; then
            echo "test_device1"  # Return the partition name
        else
            /bin/grep "$@"  # Call real grep for other cases
        fi
    }
    export -f grep
    
    # Mock the sed command
    function sed() {
        echo "/dev/test_device1"
    }
    export -f sed
    
    # Mock umount to simulate successful unmounting
    function umount() {
        echo "Unmounting $1"
        return 0
    }
    export -f umount
    
    # Mock read to simulate user confirming unmount with 'y'
    function read() {
        if [[ "$1" == "UNMOUNT_CONFIRM" ]]; then
            eval "$1='y'"
        else
            builtin read "$@"
        fi
    }
    export -f read
    
    # Run the function
    run bash -c "source ./installer/sc.sh && check_mounted_partitions"
    
    # Check that it succeeded
    assert_success
    
    # Check output indicates checking for mounted partitions
    assert_output --partial "Checking for mounted partitions on $TARGET_DEVICE"
    # Verify it found mounted partitions
    assert_output --partial "Warning: /dev/test_device1 is currently mounted"
    # Verify it asked for confirmation and unmounted
    assert_output --partial "Proceed with unmounting?"
    assert_output --partial "Unmounting /dev/test_device1"
    
    # Clean up
    unset TARGET_DEVICE
    unset -f lsblk mount grep sed umount read cleanup
}

@test "check_mounted_partitions should exit when user cancels unmounting" {
    # Set up test environment
    export TARGET_DEVICE="/dev/test_device"
    
    # Create temp script to test exit behavior
    cat << 'EOF' > /tmp/test_exit.sh
#!/bin/bash
source ./installer/sc.sh

# Mock cleanup function
cleanup() {
    echo "Cleanup called"
}

# Mock exit function to avoid actually exiting
exit() {
    echo "Exit called with code: $1"
    return 0
}

# Call the function to test
check_mounted_partitions
EOF
    chmod +x /tmp/test_exit.sh
    
    # Mock lsblk to report one partition
    function lsblk() {
        echo "test_device1"
    }
    export -f lsblk
    
    # Mock mount to simulate the partition is mounted
    function mount() {
        echo "/dev/test_device1 on /mnt type ext4"
    }
    export -f mount
    
    # Mock grep to simulate mounted partition
    function grep() {
        if [[ "$1" == "-q" && "$3" == *"test_device1"* ]]; then
            return 0  # Partition is mounted
        elif [[ "$1" == "-v" ]]; then
            echo "test_device1"  # Return the partition name
        else
            /bin/grep "$@"  # Call real grep for other cases
        fi
    }
    export -f grep
    
    # Mock the sed command
    function sed() {
        echo "/dev/test_device1"
    }
    export -f sed
    
    # Mock read to simulate user canceling unmount with 'n'
    function read() {
        if [[ "$1" == "UNMOUNT_CONFIRM" ]]; then
            eval "$1='n'"
        else
            builtin read "$@"
        fi
    }
    export -f read
    
    # Run the function via our temporary script
    run bash -c "export -f lsblk mount grep sed read && /tmp/test_exit.sh"
    
    # Clean up
    rm -f /tmp/test_exit.sh
    
    # Check output indicates checking for mounted partitions
    assert_output --partial "Checking for mounted partitions on /dev/test_device"
    # Verify it found mounted partitions
    assert_output --partial "Warning: /dev/test_device1 is currently mounted"
    # Verify it asked for confirmation
    assert_output --partial "Proceed with unmounting?"
    # Verify it called cleanup and exit
    assert_output --partial "Cleanup called"
    assert_output --partial "Exit called with code: 0"
    assert_output --partial "Operation cancelled"
    
    # Clean up
    unset TARGET_DEVICE
    unset -f lsblk mount grep sed read
}

@test "cleanup should remove temporary files" {
    # Set up test environment
    TMP_EXTRACT_DIR="/dev/shm/test-extract-dir"
    
    # Clean up from previous tests
    rm -rf "$TMP_EXTRACT_DIR" 2>/dev/null || true
    
    mkdir -p "$TMP_EXTRACT_DIR"
    touch "$TMP_EXTRACT_DIR/test_file"
    
    # Run the cleanup function with proper variable passing
    run bash -c "export TMP_EXTRACT_DIR=\"$TMP_EXTRACT_DIR\" && source ./installer/sc.sh && cleanup"
    
    # Check that the function succeeded
    assert_success
    
    # Check that it attempted to clean up temporary files
    assert_output --partial "Cleaning up temporary files"
    assert_output --partial "Cleanup completed"
    
    # Just check if directory was removed - don't try to remove it yourself
    [ ! -d "$TMP_EXTRACT_DIR" ]
}

@test "flash_drive should handle image selection menu correctly" {
    # Provide invalid selection to verify error message
    run bash -c "echo 3 | sudo ./installer/sc.sh flash"
    assert_failure
    assert_output --partial "Please select an image to flash:"
    assert_output --partial "1) Jetson Orion Nano 8GB - Jetpack 6.2"
    assert_output --partial "2) Legacy Jetson Nano 4GB - Jetpack 4.6"
    assert_output --partial "Invalid selection. Exiting."
    
    # Provide valid selection to verify it is accepted
    # This should still fail but because of missing target
    run bash -c "echo 2 | sudo ./installer/sc.sh flash"
    assert_failure
    assert_output --partial "No target device specified"
} 