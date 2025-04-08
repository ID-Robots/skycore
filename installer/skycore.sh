#!/bin/bash

echo -e "\e[1;36m"
echo "███████ ██   ██ ██    ██  ██████  ██████  ██████  ███████"
echo "██      ██  ██   ██  ██  ██      ██    ██ ██   ██ ██      "
echo "███████ █████     ████   ██      ██    ██ ██████  █████   "
echo "     ██ ██  ██     ██    ██      ██    ██ ██   ██ ██      "
echo "███████ ██   ██    ██     ██████  ██████  ██   ██ ███████ "
echo "Made with love by IDRobots"
echo "Docs: https://id-robots.github.io/skycore/"
echo ""
echo "En Taro Tassadar! Prismatic core online."
echo ""
echo -e "\e[0m"

# Color Definitions
GREEN='\e[32m'
CYAN='\e[36m'
YELLOW='\e[33m'
RED='\e[31m'
BLUE='\e[34m'
PURPLE='\e[35m'
NC='\e[0m' # No Color

# Clone drive functionality
clone_drive() {
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[✖]${NC} This script must be run as root" 
        exit 1
    fi

    # Default values
    COMPRESS=false
    OUTPUT_DIR="$(pwd)"
    DEBUG=false
    CREATE_ARCHIVE=false
    SOURCE_DEVICE=""

    # Parse clone command arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source|-s)
                SOURCE_DEVICE="$2"
                shift 2
                ;;
            --compress|-c)
                COMPRESS=true
                shift
                ;;
            --output|-o)
                OUTPUT_DIR="$2"
                shift 2
                ;;
            --debug|-d)
                DEBUG=true
                shift
                ;;
            --archive|-a)
                CREATE_ARCHIVE=true
                ARCHIVE_NAME="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: skycore clone --source SOURCE_DEVICE [options]"
                echo "  --source, -s: Source device (e.g., /dev/nvme0n1 or /dev/sda)"
                echo "  --compress, -c: Compress the image files"
                echo "  --output, -o: Output directory for image files (default: current directory)"
                echo "  --debug, -d: Enable debug mode (verbose output)"
                echo "  --archive, -a: Create archive of backup (provide archive name without extension)"
                echo "Example: skycore clone --source /dev/nvme0n1 --compress --output /tmp/backup"
                exit 0
                ;;
            *)
                echo -e "${RED}[✖]${NC} Unknown option: $1"
                echo "Use 'skycore clone --help' for usage information"
                exit 1
                ;;
        esac
    done

    # Check if required arguments are provided
    if [ -z "$SOURCE_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} No source device specified. Use --source to specify the device."
        echo "Use 'skycore clone --help' for usage information"
        exit 1
    fi

    # Check if source device exists
    if [ ! -b "$SOURCE_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} Error: Source device $SOURCE_DEVICE does not exist or is not a block device."
        exit 1
    fi

    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"

    # Display detected devices and ask for confirmation
    echo "================= IMAGE CREATION SUMMARY ================="
    echo -e "${YELLOW}[⋯]${NC} Source device: $SOURCE_DEVICE"
    lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT "$SOURCE_DEVICE"
    echo ""
    echo -e "${YELLOW}[⋯]${NC} Image files will be saved to: $OUTPUT_DIR"
    echo -e "${YELLOW}[⋯]${NC} Compression: $([ "$COMPRESS" = true ] && echo "Enabled" || echo "Disabled")"
    echo -e "${YELLOW}[⋯]${NC} Debug mode: $([ "$DEBUG" = true ] && echo "Enabled" || echo "Disabled")"
    if [ "$CREATE_ARCHIVE" = true ]; then
        echo -e "${YELLOW}[⋯]${NC} Archive creation: Enabled (${ARCHIVE_NAME}.tar.gz)"
    fi
    echo "===================================================="
    echo ""
    echo -n "Do you want to continue? (y/N): "
    read CONFIRM

    if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
        echo -e "${YELLOW}[⋯]${NC} Operation cancelled."
        exit 0
    fi

    # Step 1: Check if partclone is installed
    if ! command -v partclone.dd &> /dev/null; then
        echo -e "${RED}[✖]${NC} Error: partclone is not installed. Please install it with:"
        echo "  sudo apt install partclone"
        exit 1
    fi

    # Get list of source partitions with full paths - properly formatted
    SOURCE_BASE=$(basename "$SOURCE_DEVICE")
    SOURCE_PARTITIONS=$(find /dev -name "${SOURCE_BASE}[0-9]*" | sort)

    # Display the partitions we found
    echo -e "${YELLOW}[⋯]${NC} Found partitions to clone:"
    echo "$SOURCE_PARTITIONS"
    echo -e "${YELLOW}[⋯]${NC} Total: $(echo "$SOURCE_PARTITIONS" | wc -l) partitions"

    # Check for mounted partitions on source device
    MOUNTED=false
    for part in $SOURCE_PARTITIONS; do
        if mount | grep -q "$part"; then
            echo -e "${YELLOW}[⋯]${NC} Warning: $part is currently mounted. It will be unmounted."
            MOUNTED=true
        fi
    done

    if [ "$MOUNTED" = true ]; then
        echo -n "Proceed with unmounting? (y/N): "
        read UNMOUNT_CONFIRM
        if [[ "$UNMOUNT_CONFIRM" != "y" && "$UNMOUNT_CONFIRM" != "Y" ]]; then
            echo -e "${YELLOW}[⋯]${NC} Operation cancelled."
            exit 0
        fi
        
        # Unmount all partitions from source
        for part in $SOURCE_PARTITIONS; do
            if mount | grep -q "$part"; then
                echo -e "${YELLOW}[⋯]${NC} Unmounting $part"
                umount "$part"
            fi
        done
    fi

    # Step 2: Backup the partition table
    echo -e "${YELLOW}[⋯]${NC} Backing up partition table from $SOURCE_DEVICE"
    PARTITION_TABLE="$OUTPUT_DIR/jetson_nvme_partitions.sfdisk"
    sfdisk -d "$SOURCE_DEVICE" > "$PARTITION_TABLE"
    echo -e "${GREEN}[✔]${NC} Partition table saved to $PARTITION_TABLE"

    # Save block device info for reference
    blkid "$SOURCE_DEVICE"* > "$OUTPUT_DIR/jetson_nvme_blkinfo.txt" 2>/dev/null || true
    echo -e "${GREEN}[✔]${NC} Block device info saved to $OUTPUT_DIR/jetson_nvme_blkinfo.txt"

    # Step 3: Clone each partition
    echo -e "${YELLOW}[⋯]${NC} Starting partition cloning..."

    for part in $SOURCE_PARTITIONS; do
        part_name=$(basename "$part")
        part_num=$(echo "$part_name" | grep -o '[0-9]*$')
        
        # Skip if part_num is empty (e.g., for whole disk devices)
        if [ -z "$part_num" ]; then
            echo -e "${YELLOW}[⋯]${NC} Skipping $part - not a partition"
            continue
        fi
        
        # Determine filesystem type
        fs_type=$(lsblk -no FSTYPE "$part")
        if [ -z "$fs_type" ]; then
            fs_type="dd"  # Use dd mode for unknown filesystem types
        fi
        
        echo -e "${YELLOW}[⋯]${NC} Cloning partition $part (filesystem: $fs_type)"
        
        # Set appropriate partclone command based on filesystem
        case $fs_type in
            ext4)
                PARTCLONE_CMD="partclone.ext4"
                ;;
            vfat|fat32|fat16)
                PARTCLONE_CMD="partclone.vfat"
                ;;
            ntfs)
                PARTCLONE_CMD="partclone.ntfs"
                ;;
            xfs)
                PARTCLONE_CMD="partclone.xfs"
                ;;
            *)
                PARTCLONE_CMD="partclone.dd"
                ;;
        esac
        
        # Prepare output filename
        img_file="$OUTPUT_DIR/jetson_nvme_p${part_num}.img"
        
        # Clone the partition, with or without compression
        if [ "$COMPRESS" = true ]; then
            echo -e "${YELLOW}[⋯]${NC} Using compression for $part"
            if command -v lz4 &> /dev/null; then
                $PARTCLONE_CMD -c -s "$part" | lz4 > "${img_file}.lz4"
                echo -e "${GREEN}[✔]${NC} Partition $part cloned to ${img_file}.lz4"
            else
                $PARTCLONE_CMD -c -s "$part" | gzip > "${img_file}.gz"
                echo -e "${GREEN}[✔]${NC} Partition $part cloned to ${img_file}.gz"
            fi
        else
            $PARTCLONE_CMD -c -s "$part" -o "$img_file"
            echo -e "${GREEN}[✔]${NC} Partition $part cloned to $img_file"
        fi
    done

    # Sync to ensure all writes are completed
    sync

    echo -e "${GREEN}[✔]${NC} Image creation completed successfully!"
    echo -e "${YELLOW}[⋯]${NC} All partition images are saved in $OUTPUT_DIR"

    # Step 4: Create archive if requested
    if [ "$CREATE_ARCHIVE" = true ]; then
        echo -e "${YELLOW}[⋯]${NC} Creating archive ${ARCHIVE_NAME}.tar.gz..."
        
        # Create a manifest file with metadata
        MANIFEST="$OUTPUT_DIR/manifest.txt"
        echo "Jetson Backup Manifest" > "$MANIFEST"
        echo "Created: $(date)" >> "$MANIFEST"
        echo "Source Device: $SOURCE_DEVICE" >> "$MANIFEST"
        echo "Compression: $([ "$COMPRESS" = true ] && echo "Enabled" || echo "Disabled")" >> "$MANIFEST"
        echo "" >> "$MANIFEST"
        echo "Device Information:" >> "$MANIFEST"
        lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT "$SOURCE_DEVICE" >> "$MANIFEST"
        echo "" >> "$MANIFEST"
        echo "Files included:" >> "$MANIFEST"
        ls -lh "$OUTPUT_DIR" >> "$MANIFEST"
        
        # Create the archive (use current directory to avoid including full path)
        current_dir=$(pwd)
        cd "$OUTPUT_DIR" || exit 1
        tar czf "${ARCHIVE_NAME}.tar.gz" ./*
        cd "$current_dir" || exit 1
        
        echo -e "${GREEN}[✔]${NC} Archive created at $OUTPUT_DIR/${ARCHIVE_NAME}.tar.gz"
    fi

    echo ""
    echo -e "${YELLOW}[⋯]${NC} Use 'skycore flash' to restore these images to a target drive."

    if [ "$DEBUG" = true ]; then
        set +x  # Disable debug output
    fi
}

# Flash drive functionality
flash_drive() {
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[✖]${NC} This script must be run as root" 
        exit 1
    fi

    # Default values
    TARGET_DEVICE=""
    S3_BUCKET="s3://jetson-nano-ub-20-bare"
    IMAGE_NAME="orion-nano-8gb-jp6.2.tar.gz"
    TMP_DIR="/tmp/skycore-orion-flash"
    ARCHIVE_FILE=""
    ARCHIVE_PATH=""
    TMP_EXTRACT_DIR="${TMP_DIR}/extracted"
    INPUT_DIR=""
    FROM_S3=true

    # Parse flash command arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --target|-t)
                TARGET_DEVICE="$2"
                shift 2
                ;;
            --bucket|-b)
                S3_BUCKET="$2"
                shift 2
                ;;
            --image|-i)
                IMAGE_NAME="$2"
                shift 2
                ;;
            --archive|-a)
                FROM_S3=false
                ARCHIVE_PATH="$2"
                shift 2
                ;;
            --input|-d)
                FROM_S3=false
                INPUT_DIR="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: skycore flash --target TARGET_DEVICE [options]"
                echo "  --target, -t: Target device (e.g., /dev/nvme1n1 or /dev/sdb)"
                echo "  --bucket, -b: S3 bucket URL (default: ${S3_BUCKET})"
                echo "  --image, -i: Image name to download from S3 (default: ${IMAGE_NAME})"
                echo "  --archive, -a: Use local archive file instead of downloading from S3"
                echo "  --input, -d: Use local directory with partition images instead of archive"
                echo ""
                echo "Examples:"
                echo "  skycore flash --target /dev/sdb"
                echo "  skycore flash --target /dev/sdb --bucket s3://custom-bucket --image custom-image.tar.gz"
                echo "  skycore flash --target /dev/sdb --archive /path/to/backup.tar.gz"
                echo "  skycore flash --target /dev/sdb --input /path/to/backup_dir"
                exit 0
                ;;
            *)
                echo -e "${RED}[✖]${NC} Unknown option: $1"
                echo "Use 'skycore flash --help' for usage information"
                exit 1
                ;;
        esac
    done

    # Check if required arguments are provided
    if [ -z "$TARGET_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} No target device specified. Use --target to specify the device."
        echo "Use 'skycore flash --help' for usage information"
        exit 1
    fi

    # Check for both archive and input dir
    if [ -n "$ARCHIVE_PATH" ] && [ -n "$INPUT_DIR" ]; then
        echo -e "${RED}[✖]${NC} Error: Cannot specify both --archive and --input options."
        echo "Use 'skycore flash --help' for usage information"
        exit 1
    fi

    # Set archive file path if downloading from S3
    if [ "$FROM_S3" = true ]; then
        ARCHIVE_FILE="${TMP_DIR}/${IMAGE_NAME}"
    else
        if [ -n "$ARCHIVE_PATH" ]; then
            # Check if archive file exists
            if [ ! -f "$ARCHIVE_PATH" ]; then
                echo -e "${RED}[✖]${NC} Error: Archive file $ARCHIVE_PATH does not exist."
                exit 1
            fi
            ARCHIVE_FILE="$ARCHIVE_PATH"
        elif [ -n "$INPUT_DIR" ]; then
            # Check if input directory exists
            if [ ! -d "$INPUT_DIR" ]; then
                echo -e "${RED}[✖]${NC} Error: Input directory $INPUT_DIR does not exist."
                exit 1
            fi
        else
            echo -e "${RED}[✖]${NC} Error: No source specified. Use --bucket and --image or --archive or --input."
            echo "Use 'skycore flash --help' for usage information"
            exit 1
        fi
    fi

    # Check if target device exists
    if [ ! -b "$TARGET_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} Error: Target device $TARGET_DEVICE does not exist or is not a block device."
        exit 1
    fi

    # Create temporary directories
    mkdir -p "$TMP_DIR"
    mkdir -p "$TMP_EXTRACT_DIR"

    # Display available block devices
    list_block_devices() {
        echo -e "${YELLOW}[⋯]${NC} Available block devices:"
        lsblk -o NAME,SIZE,TYPE,MOUNTPOINT
    }

    # Install dependencies
    install_dependencies() {
        echo -e "${YELLOW}[⋯]${NC} Checking for required dependencies..."
        apt-get update -y
        apt-get install -y python3-pip util-linux gawk coreutils parted e2fsprogs xz-utils partclone

        # Check if AWS CLI is installed (only if downloading from S3)
        if [ "$FROM_S3" = true ]; then
            echo -e "${YELLOW}[⋯]${NC} Checking if AWS CLI is installed..."
            if ! command -v aws >/dev/null 2>&1; then
                echo -e "${YELLOW}[⋯]${NC} AWS CLI not found. Installing AWS CLI via pip..."
                pip3 install awscli || {
                    echo -e "${RED}[✖]${NC} Failed to install AWS CLI."
                    exit 1
                }
            else
                echo -e "${GREEN}[✔]${NC} AWS CLI is already installed."
            fi
        fi
    }

    # Download the image from S3
    download_image() {
        if [ "$FROM_S3" = true ]; then
            if [ -f "$ARCHIVE_FILE" ]; then
                echo -e "${GREEN}[✔]${NC} Archive already exists at $ARCHIVE_FILE."
                echo -e "${YELLOW}[⋯]${NC} Reusing existing archive."
            else
                echo -e "${YELLOW}[⋯]${NC} Downloading archive from S3..."
                IMAGE_S3_URI="${S3_BUCKET}/${IMAGE_NAME}"
                aws s3 cp "$IMAGE_S3_URI" "$ARCHIVE_FILE" --no-sign-request || {
                    echo -e "${RED}[✖]${NC} Failed to download the image ${IMAGE_NAME} from ${S3_BUCKET}."
                    exit 1
                }
                echo -e "${GREEN}[✔]${NC} Archive downloaded successfully."
            fi
        else
            echo -e "${GREEN}[✔]${NC} Using local source instead of downloading from S3."
        fi
    }

    # Extract the image
    extract_image() {
        # If we're using an input directory directly, skip extraction
        if [ -n "$INPUT_DIR" ]; then
            echo -e "${GREEN}[✔]${NC} Using existing directory: $INPUT_DIR"
            # Set TMP_EXTRACT_DIR to the input directory for consistent processing
            TMP_EXTRACT_DIR="$INPUT_DIR"
            return
        fi

        echo -e "${YELLOW}[⋯]${NC} Extracting archive to temporary directory: $TMP_EXTRACT_DIR"
        # Clean extraction directory first
        rm -rf "$TMP_EXTRACT_DIR"/*
        mkdir -p "$TMP_EXTRACT_DIR"
        
        # Extract the archive
        tar -xzf "$ARCHIVE_FILE" -C "$TMP_EXTRACT_DIR"
        echo -e "${GREEN}[✔]${NC} Archive extracted successfully."
    }

    # Check for mounted partitions on target device
    check_mounted_partitions() {
        echo -e "${YELLOW}[⋯]${NC} Checking for mounted partitions on $TARGET_DEVICE..."
        TARGET_PARTITIONS=$(lsblk -no NAME "$TARGET_DEVICE" | grep -v "$(basename "$TARGET_DEVICE")" | sed "s/^/\/dev\//")

        MOUNTED=false
        for part in $TARGET_PARTITIONS; do
            if mount | grep -q "$part"; then
                echo -e "${YELLOW}[⋯]${NC} Warning: $part is currently mounted. It will be unmounted."
                MOUNTED=true
            fi
        done

        if [ "$MOUNTED" = true ]; then
            echo -n "Proceed with unmounting? (y/N): "
            read UNMOUNT_CONFIRM
            if [[ "$UNMOUNT_CONFIRM" != "y" && "$UNMOUNT_CONFIRM" != "Y" ]]; then
                echo -e "${YELLOW}[⋯]${NC} Operation cancelled."
                cleanup
                exit 0
            fi
            
            # Unmount all partitions from target
            for part in $TARGET_PARTITIONS; do
                if mount | grep -q "$part"; then
                    echo -e "${YELLOW}[⋯]${NC} Unmounting $part"
                    umount "$part"
                fi
            done
        fi
    }

    # Flash the device
    flash_device_with_images() {
        # Check if partition table file exists
        PARTITION_TABLE="$TMP_EXTRACT_DIR/jetson_nvme_partitions.sfdisk"
        if [ ! -f "$PARTITION_TABLE" ]; then
            echo -e "${RED}[✖]${NC} Error: Partition table file not found in the extracted archive."
            cleanup
            exit 1
        fi

        # Display confirmation
        echo "================= FLASH DRIVE SUMMARY ================="
        echo -e "${YELLOW}[⋯]${NC} Target device: $TARGET_DEVICE"
        lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT "$TARGET_DEVICE"
        echo ""
        
        if [ "$FROM_S3" = true ]; then
            echo -e "${YELLOW}[⋯]${NC} Source image: $IMAGE_NAME from $S3_BUCKET"
        elif [ -n "$ARCHIVE_PATH" ]; then
            echo -e "${YELLOW}[⋯]${NC} Source archive: $ARCHIVE_PATH"
        else
            echo -e "${YELLOW}[⋯]${NC} Source directory: $INPUT_DIR"
        fi
        
        if [ -f "$TMP_EXTRACT_DIR/manifest.txt" ]; then
            echo "--- Archive Manifest ---"
            head -n 10 "$TMP_EXTRACT_DIR/manifest.txt"
            echo "------------------------"
        fi
        
        echo "===================================================="
        echo ""
        echo -e "${RED}WARNING: All data on $TARGET_DEVICE will be permanently lost!${NC}"
        echo -n "Do you want to continue? (y/N): "
        read CONFIRM

        if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
            echo -e "${YELLOW}[⋯]${NC} Operation cancelled."
            cleanup
            exit 0
        fi

        # Step 1: Restore the partition table to the target drive
        echo -e "${YELLOW}[⋯]${NC} Preparing target drive $TARGET_DEVICE"
        echo -e "${YELLOW}[⋯]${NC} Restoring partition table to $TARGET_DEVICE"
        sfdisk "$TARGET_DEVICE" < "$PARTITION_TABLE"
        echo -e "${GREEN}[✔]${NC} Partition table restored."

        # Force kernel to re-read partition table
        partprobe "$TARGET_DEVICE"
        sleep 2  # Give the system time to recognize new partition layout

        # Step 2: Get list of images to restore
        echo -e "${YELLOW}[⋯]${NC} Looking for partition images in the extracted archive"
        IMAGE_FILES=$(find "$TMP_EXTRACT_DIR" -name "jetson_nvme_p*.img*" | sort)

        if [ -z "$IMAGE_FILES" ]; then
            echo -e "${RED}[✖]${NC} Error: No partition image files found in the source."
            cleanup
            exit 1
        fi

        echo -e "${GREEN}[✔]${NC} Found $(echo "$IMAGE_FILES" | wc -l) partition image(s)"

        # Step 3: Restore partition images to the target drive
        echo -e "${YELLOW}[⋯]${NC} Starting partition restoration..."

        for img_file in $IMAGE_FILES; do
            # Extract partition number from filename
            base_name=$(basename "$img_file")
            if [[ "$base_name" =~ p([0-9]+)\.img ]]; then
                part_num="${BASH_REMATCH[1]}"
            elif [[ "$base_name" =~ p([0-9]+)\.img\.(gz|lz4) ]]; then
                part_num="${BASH_REMATCH[1]}"
            else
                echo -e "${YELLOW}[⋯]${NC} Warning: Could not extract partition number from $base_name, skipping"
                continue
            fi
            
            # Determine target partition
            target_base=$(basename "$TARGET_DEVICE")
            # Check if target device name ends with a number
            if [[ "$target_base" =~ [0-9]$ ]]; then
                target_part="${TARGET_DEVICE}p${part_num}"
            else
                target_part="${TARGET_DEVICE}${part_num}"
            fi
            
            # Skip if target partition doesn't exist
            if [ ! -b "$target_part" ]; then
                echo -e "${YELLOW}[⋯]${NC} Warning: Target partition $target_part does not exist. Skipping."
                continue
            fi
            
            # Determine filesystem type from the partition filename or blkinfo
            fs_type=""
            # First try to extract it from the blkinfo file if available
            if [ -f "$TMP_EXTRACT_DIR/jetson_nvme_blkinfo.txt" ]; then
                fs_info=$(grep -E "/dev/[a-zA-Z0-9]+${part_num}:" "$TMP_EXTRACT_DIR/jetson_nvme_blkinfo.txt" | grep -o "TYPE=\"[^\"]*\"" | cut -d'"' -f2)
                if [ -n "$fs_info" ]; then
                    fs_type="$fs_info"
                fi
            fi
            
            # If we couldn't determine the type from blkinfo, check the image file
            if [ -z "$fs_type" ]; then
                if [[ "$base_name" == *"ext4"* ]]; then
                    fs_type="ext4"
                elif [[ "$base_name" == *"vfat"* || "$base_name" == *"fat"* ]]; then
                    fs_type="vfat"
                elif [[ "$base_name" == *"ntfs"* ]]; then
                    fs_type="ntfs"
                elif [[ "$base_name" == *"xfs"* ]]; then
                    fs_type="xfs"
                else
                    fs_type="dd"  # Default to dd mode if we can't determine
                fi
            fi
            
            # Set appropriate partclone command based on filesystem
            case $fs_type in
                ext4|ext3|ext2)
                    PARTCLONE_CMD="partclone.ext4"
                    ;;
                vfat|fat32|fat16|fat12)
                    PARTCLONE_CMD="partclone.vfat"
                    ;;
                ntfs)
                    PARTCLONE_CMD="partclone.ntfs"
                    ;;
                xfs)
                    PARTCLONE_CMD="partclone.xfs"
                    ;;
                *)
                    PARTCLONE_CMD="partclone.dd"
                    ;;
            esac
            
            echo -e "${YELLOW}[⋯]${NC} Restoring partition to $target_part (filesystem: $fs_type)"
            
            # Restore the partition, with or without decompression
            if [[ "$img_file" == *.lz4 ]]; then
                echo -e "${YELLOW}[⋯]${NC} Decompressing and restoring from $img_file"
                lz4 -d -c "$img_file" | $PARTCLONE_CMD -r -s - -o "$target_part"
            elif [[ "$img_file" == *.gz ]]; then
                echo -e "${YELLOW}[⋯]${NC} Decompressing and restoring from $img_file"
                gzip -d -c "$img_file" | $PARTCLONE_CMD -r -s - -o "$target_part"
            else
                echo -e "${YELLOW}[⋯]${NC} Restoring from $img_file"
                $PARTCLONE_CMD -r -s "$img_file" -o "$target_part"
            fi
            
            echo -e "${GREEN}[✔]${NC} Partition image $img_file restored to $target_part"
        done

        # Sync to ensure all writes are completed
        sync
        echo -e "${GREEN}[✔]${NC} Flashing completed successfully!"
    }

    # Cleanup function
    cleanup() {
        echo -e "${YELLOW}[⋯]${NC} Cleaning up temporary files..."
        # Only remove the extraction directory if we created it
        if [ -z "$INPUT_DIR" ]; then
            rm -rf "$TMP_EXTRACT_DIR"
        fi
        echo -e "${GREEN}[✔]${NC} Cleanup completed."
    }

    # Main execution flow
    echo -e "${CYAN}"
    echo "███████ ██   ██ ██    ██  ██████  ██████  ██████  ███████"
    echo "██      ██  ██   ██  ██  ██      ██    ██ ██   ██ ██     "
    echo "███████ █████     ████   ██      ██    ██ ██████  █████  "
    echo "     ██ ██  ██     ██    ██      ██    ██ ██   ██ ██     "
    echo "███████ ██   ██    ██     ██████  ██████  ██   ██ ███████"
    echo "Made with love by IDRobots"
    echo "https://skyhub.ai"
    echo -e "${NC}"
    
    echo -e "${YELLOW}[⋯]${NC} SKYCORE Flash tool starting..."
    
    list_block_devices
    install_dependencies
    download_image
    extract_image
    check_mounted_partitions
    flash_device_with_images
    cleanup
    
    echo -e "${GREEN}[✔]${NC} The target drive $TARGET_DEVICE now contains the flashed image."
    echo ""
    echo -e "${YELLOW}[⋯]${NC} To use this drive as a bootable device in a Jetson:"
    echo "1. Power off the Jetson"
    echo "2. Install the flashed drive in the Jetson"
    echo "3. Power on the Jetson and verify it boots correctly"
}

# Activate drone functionality
activate_drone() {
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[✖]${NC} This script must be run as root" 
        exit 1
    fi

    # Check if token is provided
    if [ $# -lt 1 ]; then
        echo -e "${RED}[✖]${NC} No drone token provided. Use token parameter to specify the token."
        echo "Usage: skycore activate <Drone Token>"
        exit 1
    fi

    TOKEN=$1

    # read a STAGE environment variable
    STAGE=${STAGE:-prod}
    
    echo -e "${YELLOW}[⋯]${NC} Activating drone with token on $STAGE environment..."
    
    # Make a curl request and store the JSON response
    echo -e "${YELLOW}[⋯]${NC} Contacting activation server..."
    response=$(curl --connect-timeout 15 --max-time 15 https://$STAGE.skyhub.ai:5000/api/v1/drone/activate -H "token: $TOKEN")

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Curl request failed"
        exit 1
    fi

    # Use jq to extract nested values from the JSON response
    vpn_url=$(echo "$response" | jq -r '.vpn')

    if [ -z "$vpn_url" ]; then
        echo -e "${RED}[✖]${NC} No download link found in the response"
        exit 1
    fi

    echo -e "${YELLOW}[⋯]${NC} Downloading VPN configuration..."
    curl -o /etc/wireguard/wg0.conf "$vpn_url"
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to download Drone VPN file"
        exit 1
    fi

    echo -e "${YELLOW}[⋯]${NC} Enabling and starting VPN service..."
    systemctl enable wg-quick@wg0
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to enable wg-quick service"
        exit 1
    fi

    systemctl restart wg-quick@wg0 || systemctl start wg-quick@wg0
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to start wg-quick service"
        exit 1
    fi

    echo -e "${GREEN}[✔]${NC} VPN connection established"
    
    username=$(echo "$response" | jq -r '.username')
    password=$(echo "$response" | jq -r '.password')
    repository=$(echo "$response" | jq -r '.repository')

    echo -e "${YELLOW}[⋯]${NC} Logging in to Docker registry..."
    docker login -u $username -p $password $repository
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to login to Docker registry"
        exit 1
    fi

    systemctl enable docker

    echo -e "${YELLOW}[⋯]${NC} Downloading Docker Compose configuration..."
    compose=$(echo "$response" | jq -r '.compose')
    curl --connect-timeout 15 --max-time 15 -o docker-compose.yml "$compose"
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to download Docker Compose file"
        exit 1
    fi

    # Set permissions
    chown skycore docker-compose.yml
    chown -R skycore /home/skycore
    chmod -R 755 /home/skycore

    echo -e "${YELLOW}[⋯]${NC} Starting Docker containers..."
    docker compose pull
    docker compose up -d

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to start Docker containers"
        exit 1
    fi

    echo -e "${GREEN}[✔]${NC} Drone activation is complete."
}

sudo cp skycore.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/skycore.sh
sudo ln -sf /usr/local/bin/skycore.sh /usr/local/bin/skycore


if [[ "$1" == "cli" ]]; then
    echo "Starting SkyCore CLI..."
    python3 "skycore_cli.py"

elif [[ "$1" == "clone" ]]; then
    # Shift to remove the "clone" argument
    shift
    clone_drive "$@"

elif [[ "$1" == "flash" ]]; then
    # Shift to remove the "flash" argument
    shift
    flash_drive "$@"

elif [[ "$1" == "activate" ]]; then
    # Shift to remove the "activate" argument
    shift
    activate_drone "$@"

elif [[ "$1" == "help" ]]; then
    echo "Available commands:"
    echo "  skycore cli       - Start the SkyCore CLI"
    echo "  skycore clone     - Clone a device to image files"
    echo "  skycore flash     - Flash image files to a device"
    echo "  skycore activate  - Activate a drone with a token"
    echo "  skycore help      - Show this help message"
    
    echo ""
    echo "For more information on a specific command, use --help:"
    echo "  skycore clone --help"
    echo "  skycore flash --help"
    echo "  skycore activate <token>"
else
    echo "Usage: skycore [command]"
    echo "Use 'skycore help' for a list of available commands"
    exit 1
fi
