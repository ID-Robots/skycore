#!/bin/bash

GREEN='\e[32m'
CYAN='\e[36m'
YELLOW='\e[33m'
RED='\e[31m'
BLUE='\e[34m'
PURPLE='\e[35m'
NC='\e[0m'

print_banner() {
    echo -e "${CYAN}"
    echo "███████ ██   ██ ██    ██  ██████  ██████  ██████  ███████"
    echo "██      ██  ██   ██  ██  ██      ██    ██ ██   ██ ██     "
    echo "███████ █████     ████   ██      ██    ██ ██████  █████  "
    echo "     ██ ██  ██     ██    ██      ██    ██ ██   ██ ██     "
    echo "███████ ██   ██    ██     ██████  ██████  ██   ██ ███████"
    echo "Made with love by IDRobots"
    echo "Docs: https://id-robots.github.io/skycore/"
    echo -e "${NC}"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}[✖]${NC} This script must be run as root"
        exit 1
    fi
}

install_wireguard() {
    echo -e "${YELLOW}[⋯]${NC} Installing WireGuard..."

    apt-get update -y
    apt-get install -y wireguard wireguard-tools

    if modprobe wireguard 2>/dev/null; then
        echo -e "${GREEN}[✔]${NC} WireGuard kernel module is available."
        return 0
    fi

    echo -e "${YELLOW}[⋯]${NC} WireGuard kernel module not available. Setting up userspace implementation..."

    echo -e "${YELLOW}[⋯]${NC} Installing latest Go..."
    cd /tmp
    GO_VERSION="1.22.1"
    GO_PACKAGE="go${GO_VERSION}.linux-arm64.tar.gz"
    curl -sLO "https://go.dev/dl/${GO_PACKAGE}"

    if [ ! -f "${GO_PACKAGE}" ]; then
        echo -e "${RED}[✖]${NC} Failed to download Go. Using fallback method..."
        GO_PACKAGE="go1.22.0.linux-arm64.tar.gz"
        curl -sLO "https://go.dev/dl/${GO_PACKAGE}"
    fi

    rm -rf /usr/local/go
    tar -C /usr/local -xzf "${GO_PACKAGE}"

    echo 'export PATH=$PATH:/usr/local/go/bin' >/etc/profile.d/golang.sh
    chmod +x /etc/profile.d/golang.sh

    GO_BIN="/usr/local/go/bin/go"
    echo -e "${GREEN}[✔]${NC} Latest Go installed at /usr/local/go: $($GO_BIN version)"

    echo -e "${YELLOW}[⋯]${NC} Building wireguard-go..."
    cd /tmp
    rm -rf wireguard-go*

    git clone https://git.zx2c4.com/wireguard-go
    cd wireguard-go

    if ! PATH="/usr/local/go/bin:$PATH" make; then
        echo -e "${YELLOW}[⋯]${NC} Failed to build latest wireguard-go. Trying stable release..."
        cd /tmp
        rm -rf wireguard-go
        curl -sLO https://git.zx2c4.com/wireguard-go/snapshot/wireguard-go-0.0.20230223.tar.xz
        tar -xf wireguard-go-0.0.20230223.tar.xz
        cd wireguard-go-0.0.20230223

        if ! PATH="/usr/local/go/bin:$PATH" make; then
            echo -e "${RED}[✖]${NC} Failed to build wireguard-go. Trying older compatible version..."
            cd /tmp
            rm -rf wireguard-go*
            curl -sLO https://git.zx2c4.com/wireguard-go/snapshot/wireguard-go-0.0.20220316.tar.xz
            tar -xf wireguard-go-0.0.20220316.tar.xz
            cd wireguard-go-0.0.20220316
            PATH="/usr/local/go/bin:$PATH" make
        fi
    fi

    PATH="/usr/local/go/bin:$PATH" make install

    mkdir -p /etc/systemd/system/wg-quick@wg0.service.d/
    echo -e '[Service]\nEnvironment="WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go"' >/etc/systemd/system/wg-quick@wg0.service.d/override.conf
    systemctl daemon-reload

    if command -v wireguard-go >/dev/null 2>&1; then
        echo -e "${GREEN}[✔]${NC} WireGuard userspace implementation installed: $(wireguard-go --version 2>&1 || echo 'version unavailable')"
    else
        echo -e "${RED}[✖]${NC} Failed to install wireguard-go. VPN functionality may be limited."
    fi

    echo -e "${YELLOW}[⋯]${NC} Note: To use the new Go version in your current shell, run: source /etc/profile.d/golang.sh"
}

clone_drive() {
    check_root

    COMPRESS=false
    OUTPUT_DIR="$(pwd)"
    DEBUG=false
    CREATE_ARCHIVE=false
    SOURCE_DEVICE=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
        --source | -s)
            SOURCE_DEVICE="$2"
            shift 2
            ;;
        --compress | -c)
            COMPRESS=true
            shift
            ;;
        --output | -o)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --debug | -d)
            DEBUG=true
            shift
            ;;
        --archive | -a)
            CREATE_ARCHIVE=true
            ARCHIVE_NAME="$2"
            shift 2
            ;;
        --help | -h)
            echo "Usage: skycore clone --source SOURCE_DEVICE [options]"
            echo "  --source, -s: Source device (e.g. /dev/sda)"
            echo "  --compress, -c: Compress the image files"
            echo "  --output, -o: Output directory for image files (default: current directory)"
            echo "  --debug, -d: Enable debug mode (verbose output)"
            echo "  --archive, -a: Create archive of backup (provide archive name without extension)"
            echo "Example: skycore clone --source /dev/sda --compress --output /tmp/backup"
            exit 0
            ;;
        *)
            echo -e "${RED}[✖]${NC} Unknown option: $1"
            echo "Use 'skycore clone --help' for usage information"
            exit 1
            ;;
        esac
    done

    if [ -z "$SOURCE_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} No source device specified. Use --source to specify the device."
        echo "Use 'skycore clone --help' for usage information"
        exit 1
    fi

    if [ ! -b "$SOURCE_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} Error: Source device $SOURCE_DEVICE does not exist or is not a block device."
        exit 1
    fi

    mkdir -p "$OUTPUT_DIR"

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

    if ! command -v partclone.dd &>/dev/null; then
        echo -e "${RED}[✖]${NC} Error: partclone is not installed. Please install it with:"
        echo "  sudo apt install partclone"
        exit 1
    fi

    SOURCE_BASE=$(basename "$SOURCE_DEVICE")
    SOURCE_PARTITIONS=$(find /dev -name "${SOURCE_BASE}[0-9]*" | sort)

    echo -e "${YELLOW}[⋯]${NC} Found partitions to clone:"
    echo "$SOURCE_PARTITIONS"
    echo -e "${YELLOW}[⋯]${NC} Total: $(echo "$SOURCE_PARTITIONS" | wc -l) partitions"

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

        for part in $SOURCE_PARTITIONS; do
            if mount | grep -q "$part"; then
                echo -e "${YELLOW}[⋯]${NC} Unmounting $part"
                umount "$part"
            fi
        done
    fi

    echo -e "${YELLOW}[⋯]${NC} Backing up partition table from $SOURCE_DEVICE"
    PARTITION_TABLE="$OUTPUT_DIR/jetson_nvme_partitions.sfdisk"
    sfdisk -d "$SOURCE_DEVICE" >"$PARTITION_TABLE"
    echo -e "${GREEN}[✔]${NC} Partition table saved to $PARTITION_TABLE"

    blkid "$SOURCE_DEVICE"* >"$OUTPUT_DIR/jetson_nvme_blkinfo.txt" 2>/dev/null || true
    echo -e "${GREEN}[✔]${NC} Block device info saved to $OUTPUT_DIR/jetson_nvme_blkinfo.txt"

    echo -e "${YELLOW}[⋯]${NC} Starting partition cloning..."

    for part in $SOURCE_PARTITIONS; do
        part_name=$(basename "$part")
        part_num=$(echo "$part_name" | grep -o '[0-9]*$')

        if [ -z "$part_num" ]; then
            echo -e "${YELLOW}[⋯]${NC} Skipping $part - not a partition"
            continue
        fi

        fs_type=$(lsblk -no FSTYPE "$part")
        if [ -z "$fs_type" ]; then
            fs_type="dd"
        fi

        echo -e "${YELLOW}[⋯]${NC} Cloning partition $part (filesystem: $fs_type)"

        case $fs_type in
        ext4)
            PARTCLONE_CMD="partclone.ext4"
            if ! command -v partclone.ext4 &>/dev/null; then
                echo -e "${YELLOW}[⋯]${NC} partclone.ext4 not found, falling back to partclone.dd"
                PARTCLONE_CMD="partclone.dd"
            fi
            ;;
        vfat | fat32 | fat16)
            PARTCLONE_CMD="partclone.vfat"
            if ! command -v partclone.vfat &>/dev/null; then
                echo -e "${YELLOW}[⋯]${NC} partclone.vfat not found, falling back to partclone.dd"
                PARTCLONE_CMD="partclone.dd"
            fi
            ;;
        ntfs)
            PARTCLONE_CMD="partclone.ntfs"
            if ! command -v partclone.ntfs &>/dev/null; then
                echo -e "${YELLOW}[⋯]${NC} partclone.ntfs not found, falling back to partclone.dd"
                PARTCLONE_CMD="partclone.dd"
            fi
            ;;
        xfs)
            PARTCLONE_CMD="partclone.xfs"
            if ! command -v partclone.xfs &>/dev/null; then
                echo -e "${YELLOW}[⋯]${NC} partclone.xfs not found, falling back to partclone.dd"
                PARTCLONE_CMD="partclone.dd"
            fi
            ;;
        *)
            PARTCLONE_CMD="partclone.dd"
            ;;
        esac

        # Verify partclone.dd is actually available
        if ! command -v "$PARTCLONE_CMD" &>/dev/null; then
            echo -e "${RED}[✖]${NC} Error: $PARTCLONE_CMD not found. Please install partclone."
            exit 1
        fi

        img_file="$OUTPUT_DIR/jetson_nvme_p${part_num}.img"

        if [ "$COMPRESS" = true ]; then
            echo -e "${YELLOW}[⋯]${NC} Using compression for $part"
            if command -v lz4 &>/dev/null; then
                echo -e "${YELLOW}[⋯]${NC} Running: $PARTCLONE_CMD -c -s $part | lz4 > ${img_file}.lz4"
                if ! $PARTCLONE_CMD -c -s "$part" | lz4 >"${img_file}.lz4"; then
                    echo -e "${RED}[✖]${NC} Failed to clone $part with $PARTCLONE_CMD"
                    exit 1
                fi
                echo -e "${GREEN}[✔]${NC} Partition $part cloned to ${img_file}.lz4"
            else
                echo -e "${YELLOW}[⋯]${NC} Running: $PARTCLONE_CMD -c -s $part | gzip > ${img_file}.gz"
                if ! $PARTCLONE_CMD -c -s "$part" | gzip >"${img_file}.gz"; then
                    echo -e "${RED}[✖]${NC} Failed to clone $part with $PARTCLONE_CMD"
                    exit 1
                fi
                echo -e "${GREEN}[✔]${NC} Partition $part cloned to ${img_file}.gz"
            fi
        else
            echo -e "${YELLOW}[⋯]${NC} Running: $PARTCLONE_CMD -s $part -o $img_file"
            if ! $PARTCLONE_CMD -s "$part" -o "$img_file"; then
                echo -e "${RED}[✖]${NC} Failed to clone $part with $PARTCLONE_CMD"
                exit 1
            fi
            echo -e "${GREEN}[✔]${NC} Partition $part cloned to $img_file"
        fi
    done

    sync

    echo -e "${GREEN}[✔]${NC} Image creation completed successfully!"
    echo -e "${YELLOW}[⋯]${NC} All partition images are saved in $OUTPUT_DIR"

    if [ "$CREATE_ARCHIVE" = true ]; then
        echo -e "${YELLOW}[⋯]${NC} Creating archive ${ARCHIVE_NAME}.tar.gz..."

        MANIFEST="$OUTPUT_DIR/manifest.txt"
        echo "Jetson Backup Manifest" >"$MANIFEST"
        echo "Created: $(date)" >>"$MANIFEST"
        echo "Source Device: $SOURCE_DEVICE" >>"$MANIFEST"
        echo "Compression: $([ "$COMPRESS" = true ] && echo "Enabled" || echo "Disabled")" >>"$MANIFEST"
        echo "" >>"$MANIFEST"
        echo "Device Information:" >>"$MANIFEST"
        lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT "$SOURCE_DEVICE" >>"$MANIFEST"
        echo "" >>"$MANIFEST"
        echo "Files included:" >>"$MANIFEST"
        ls -lh "$OUTPUT_DIR" >>"$MANIFEST"

        current_dir=$(pwd)
        cd "$OUTPUT_DIR" || exit 1
        tar czf "${ARCHIVE_NAME}.tar.gz" ./*
        cd "$current_dir" || exit 1

        echo -e "${GREEN}[✔]${NC} Archive created at $OUTPUT_DIR/${ARCHIVE_NAME}.tar.gz"
    fi

    echo ""
    echo -e "${YELLOW}[⋯]${NC} Use 'skycore flash' to restore these images to a target drive."

    if [ "$DEBUG" = true ]; then
        set +x
    fi
}

flash_drive() {
    check_root

    TARGET_DEVICE=""
    S3_BUCKET="s3://jetson-nano-ub-20-bare"
    IMAGE_NAME="orion-nano-8gb-jp6.2.tar.gz"
    TMP_DIR="/tmp/skycore-orion-flash"
    ARCHIVE_FILE=""
    ARCHIVE_PATH=""
    TMP_EXTRACT_DIR="${TMP_DIR}/extracted"
    INPUT_DIR=""
    FROM_S3=true
    IMAGE_SELECTED=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
        --target | -t)
            TARGET_DEVICE="$2"
            shift 2
            ;;
        --bucket | -b)
            S3_BUCKET="$2"
            shift 2
            ;;
        --image | -i)
            IMAGE_NAME="$2"
            IMAGE_SELECTED=true
            shift 2
            ;;
        --archive | -a)
            FROM_S3=false
            ARCHIVE_PATH="$2"
            shift 2
            ;;
        --input | -d)
            FROM_S3=false
            INPUT_DIR="$2"
            shift 2
            ;;
        --help | -h)
            echo "Usage: skycore flash --target TARGET_DEVICE [options]"
            echo "  --target, -t: Target device (e.g., /dev/nvme1n1 or /dev/sdb)"
            echo "  --bucket, -b: S3 bucket URL (default: ${S3_BUCKET})"
            echo "  --image, -i: Image name to download from S3 (default: selection menu)"
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

    # If no image was selected and we're using S3, show the selection menu
    if [ "$FROM_S3" = true ] && [ "$IMAGE_SELECTED" = false ]; then
        echo -e "${YELLOW}[⋯]${NC} Please select an image to flash:"
        echo "1) Jetson Orion Nano 8GB - Jetpack 6.2"
        echo "2) Legacy Jetson Nano 4GB - Jetpack 4.6"
        echo -n "Enter selection number: "
        read selection
        
        case $selection in
            1)
                IMAGE_NAME="orion-nano-8gb-jp6.2.tar.gz"
                echo -e "${GREEN}[✔]${NC} Selected: Jetson Orion Nano 8GB - Jetpack 6.2"
                ;;
            2)
                IMAGE_NAME="jetson-nano-sd-4gb-jp4.6.tar.gz"
                echo -e "${GREEN}[✔]${NC} Selected: Legacy Jetson Nano 4GB - Jetpack 4.6"
                ;;
            *)
                echo -e "${RED}[✖]${NC} Invalid selection. Exiting."
                exit 1
                ;;
        esac
    fi

    if [ -z "$TARGET_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} No target device specified. Use --target to specify the device."
        echo "Use 'skycore flash --help' for usage information"
        exit 1
    fi

    if [ -n "$ARCHIVE_PATH" ] && [ -n "$INPUT_DIR" ]; then
        echo -e "${RED}[✖]${NC} Error: Cannot specify both --archive and --input options."
        echo "Use 'skycore flash --help' for usage information"
        exit 1
    fi

    if [ "$FROM_S3" = true ]; then
        ARCHIVE_FILE="${TMP_DIR}/${IMAGE_NAME}"
    else
        if [ -n "$ARCHIVE_PATH" ]; then
            if [ ! -f "$ARCHIVE_PATH" ]; then
                echo -e "${RED}[✖]${NC} Error: Archive file $ARCHIVE_PATH does not exist."
                exit 1
            fi
            ARCHIVE_FILE="$ARCHIVE_PATH"
        elif [ -n "$INPUT_DIR" ]; then
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

    if [ ! -b "$TARGET_DEVICE" ]; then
        echo -e "${RED}[✖]${NC} Error: Target device $TARGET_DEVICE does not exist or is not a block device."
        exit 1
    fi

    mkdir -p "$TMP_DIR"
    mkdir -p "$TMP_EXTRACT_DIR"

    print_banner
    echo -e "${YELLOW}[⋯]${NC} SKYCORE Flash tool starting..."

    list_block_devices
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

list_block_devices() {
    echo -e "${YELLOW}[⋯]${NC} Available block devices:"
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT
}

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

extract_image() {
    if [ -n "$INPUT_DIR" ]; then
        echo -e "${GREEN}[✔]${NC} Using existing directory: $INPUT_DIR"
        TMP_EXTRACT_DIR="$INPUT_DIR"
        return
    fi

    if [ -d "$TMP_EXTRACT_DIR" ] && [ -f "$TMP_EXTRACT_DIR/jetson_nvme_partitions.sfdisk" ] && [ "$(find "$TMP_EXTRACT_DIR" -name "jetson_nvme_p*.img*" | wc -l)" -gt 0 ]; then
        echo -e "${GREEN}[✔]${NC} Found existing extracted files in: $TMP_EXTRACT_DIR"
        echo -e "${YELLOW}[⋯]${NC} Reusing existing extracted files."
        return
    fi

    # Only reach here if we need to extract
    echo -e "${YELLOW}[⋯]${NC} Extracting archive to temporary directory: $TMP_EXTRACT_DIR"
    mkdir -p "$TMP_EXTRACT_DIR"
    tar -xzf "$ARCHIVE_FILE" -C "$TMP_EXTRACT_DIR"
    echo -e "${GREEN}[✔]${NC} Archive extracted successfully."
}

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

        for part in $TARGET_PARTITIONS; do
            if mount | grep -q "$part"; then
                echo -e "${YELLOW}[⋯]${NC} Unmounting $part"
                umount "$part"
            fi
        done
    fi
}

flash_device_with_images() {
    PARTITION_TABLE="$TMP_EXTRACT_DIR/jetson_nvme_partitions.sfdisk"
    if [ ! -f "$PARTITION_TABLE" ]; then
        echo -e "${RED}[✖]${NC} Error: Partition table file not found in the extracted archive."
        cleanup
        exit 1
    fi

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

    echo -e "${YELLOW}[⋯]${NC} Preparing target drive $TARGET_DEVICE"
    echo -e "${YELLOW}[⋯]${NC} Restoring partition table to $TARGET_DEVICE"
    sfdisk "$TARGET_DEVICE" <"$PARTITION_TABLE"
    echo -e "${GREEN}[✔]${NC} Partition table restored."

    partprobe "$TARGET_DEVICE"
    sleep 2

    echo -e "${YELLOW}[⋯]${NC} Looking for partition images in the extracted archive"
    IMAGE_FILES=$(find "$TMP_EXTRACT_DIR" -name "jetson_nvme_p*.img*" | sort)

    if [ -z "$IMAGE_FILES" ]; then
        echo -e "${RED}[✖]${NC} Error: No partition image files found in the source."
        cleanup
        exit 1
    fi

    echo -e "${GREEN}[✔]${NC} Found $(echo "$IMAGE_FILES" | wc -l) partition image(s)"
    echo -e "${YELLOW}[⋯]${NC} Starting partition restoration..."

    for img_file in $IMAGE_FILES; do
        base_name=$(basename "$img_file")
        if [[ "$base_name" =~ p([0-9]+)\.img ]]; then
            part_num="${BASH_REMATCH[1]}"
        elif [[ "$base_name" =~ p([0-9]+)\.img\.(gz|lz4) ]]; then
            part_num="${BASH_REMATCH[1]}"
        else
            echo -e "${YELLOW}[⋯]${NC} Warning: Could not extract partition number from $base_name, skipping"
            continue
        fi

        target_base=$(basename "$TARGET_DEVICE")
        if [[ "$target_base" =~ [0-9]$ ]]; then
            target_part="${TARGET_DEVICE}p${part_num}"
        else
            target_part="${TARGET_DEVICE}${part_num}"
        fi

        if [ ! -b "$target_part" ]; then
            echo -e "${YELLOW}[⋯]${NC} Warning: Target partition $target_part does not exist. Skipping."
            continue
        fi

        fs_type=""
        if [ -f "$TMP_EXTRACT_DIR/jetson_nvme_blkinfo.txt" ]; then
            fs_info=$(grep -E "/dev/[a-zA-Z0-9]+${part_num}:" "$TMP_EXTRACT_DIR/jetson_nvme_blkinfo.txt" | grep -o "TYPE=\"[^\"]*\"" | cut -d'"' -f2)
            if [ -n "$fs_info" ]; then
                fs_type="$fs_info"
            fi
        fi

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
                fs_type="dd"
            fi
        fi

        case $fs_type in
        ext4 | ext3 | ext2)
            PARTCLONE_CMD="partclone.ext4"
            ;;
        vfat | fat32 | fat16 | fat12)
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

        if [[ "$img_file" == *.lz4 ]]; then
            echo -e "${YELLOW}[⋯]${NC} Decompressing and restoring from $img_file"
            if [[ "$PARTCLONE_CMD" == "partclone.dd" ]]; then
                lz4 -d -c "$img_file" | $PARTCLONE_CMD -s - -o "$target_part"
            else
                lz4 -d -c "$img_file" | $PARTCLONE_CMD -r -s - -o "$target_part"
            fi
        elif [[ "$img_file" == *.gz ]]; then
            echo -e "${YELLOW}[⋯]${NC} Decompressing and restoring from $img_file"
            if [[ "$PARTCLONE_CMD" == "partclone.dd" ]]; then
                gzip -d -c "$img_file" | $PARTCLONE_CMD -s - -o "$target_part"
            else
                gzip -d -c "$img_file" | $PARTCLONE_CMD -r -s - -o "$target_part"
            fi
        else
            echo -e "${YELLOW}[⋯]${NC} Restoring from $img_file"
            if [[ "$PARTCLONE_CMD" == "partclone.dd" ]]; then
                $PARTCLONE_CMD -s "$img_file" -o "$target_part"
            else
                $PARTCLONE_CMD -r -s "$img_file" -o "$target_part"
            fi
        fi

        echo -e "${GREEN}[✔]${NC} Partition image $img_file restored to $target_part"
    done

    sync
    echo -e "${GREEN}[✔]${NC} Flashing completed successfully!"
}

cleanup() {
    echo -e "${YELLOW}[⋯]${NC} Cleaning up temporary files..."
    if [ -z "$INPUT_DIR" ]; then
        rm -rf "$TMP_EXTRACT_DIR"
    fi
    echo -e "${GREEN}[✔]${NC} Cleanup completed."
}

activate_drone() {
    check_root

    TOKEN=""
    # Set default services to drone-mavros and mavproxy
    SERVICES="drone-mavros,mavproxy"

    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
        --token | -t)
            TOKEN="$2"
            shift 2
            ;;
        --services | -s)
            SERVICES="$2"
            shift 2
            ;;
        *)
            # If no flag is provided, assume it's the token (for backward compatibility)
            if [ -z "$TOKEN" ]; then
                TOKEN="$1"
            fi
            shift
            ;;
        esac
    done

    if [ -z "$TOKEN" ]; then
        echo -e "${RED}[✖]${NC} No drone token provided. Use --token parameter to specify the token."
        echo "Usage: skycore activate --token <Drone Token> [--services <service1,service2,...]"
        exit 1
    fi

    STAGE=${STAGE:-prod}

    echo -e "${YELLOW}[⋯]${NC} Activating drone with token on $STAGE environment..."

    echo -e "${YELLOW}[⋯]${NC} Contacting activation server..."
    response=$(curl --connect-timeout 15 --max-time 15 https://$STAGE.skyhub.ai:5000/api/v1/drone/activate -H "token: $TOKEN")

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Curl request failed"
        exit 1
    fi

    vpn_url=$(echo "$response" | jq -r '.vpn')

    if [ -z "$vpn_url" ]; then
        echo -e "${RED}[✖]${NC} No download link found in the response"
        exit 1
    fi

    if ! command -v wg >/dev/null 2>&1; then
        echo -e "${YELLOW}[⋯]${NC} WireGuard is not installed. Installing..."
        install_wireguard
    fi

    # Wait a bit before requesting the configuration file
    echo -e "${YELLOW}[⋯]${NC} Waiting for network stabilization..."
    sleep 3

    # Now download VPN configuration after ensuring WireGuard is working
    echo -e "${YELLOW}[⋯]${NC} Downloading VPN configuration..."
    curl -o /etc/wireguard/wg0.conf "$vpn_url"
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to download Drone VPN file"
        exit 1
    fi

    # Validate the configuration file - check if it's XML instead of WireGuard config
    if grep -q "<?xml" /etc/wireguard/wg0.conf; then
        echo -e "${RED}[✖]${NC} Invalid WireGuard configuration file (XML detected)"
        echo -e "${YELLOW}[⋯]${NC} Content of downloaded file:"
        head -n 5 /etc/wireguard/wg0.conf
        echo -e "${YELLOW}[⋯]${NC} The download URL may be expired or invalid."
        echo -e "${YELLOW}[⋯]${NC} Please try activating again with a new token."
        exit 1
    fi

    # Validate the configuration has required WireGuard sections
    if ! grep -q "\[Interface\]" /etc/wireguard/wg0.conf; then
        echo -e "${RED}[✖]${NC} Invalid WireGuard configuration file (missing [Interface] section)"
        echo -e "${YELLOW}[⋯]${NC} Content of downloaded file:"
        head -n 5 /etc/wireguard/wg0.conf
        exit 1
    fi

    echo -e "${YELLOW}[⋯]${NC} Enabling and starting VPN service..."
    systemctl enable wg-quick@wg0
    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to enable wg-quick service"
        exit 1
    fi

    systemctl stop wg-quick@wg0 >/dev/null 2>&1
    sleep 2 # Short pause to ensure service has completely stopped

    if ! systemctl start wg-quick@wg0; then
        echo -e "${RED}[✖]${NC} Failed to start WireGuard service. Please check the configuration."
        systemctl status wg-quick@wg0
        exit 1
    fi

    # Wait for the VPN connection to establish
    echo -e "${YELLOW}[⋯]${NC} Waiting for VPN connection to establish..."
    sleep 5

    # Verify VPN connection
    if ! wg show wg0 >/dev/null 2>&1; then
        echo -e "${RED}[✖]${NC} VPN connection failed to establish."
        systemctl status wg-quick@wg0
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

    chown skycore docker-compose.yml
    chown -R skycore /home/skycore
    chmod -R 755 /home/skycore

    echo -e "${YELLOW}[⋯]${NC} Starting Docker containers..."
    docker compose pull

    # If specific services are specified, start only those
    if [ -n "$SERVICES" ]; then
        echo -e "${YELLOW}[⋯]${NC} Starting selected services: $SERVICES"
        # Convert comma-separated list to space-separated for docker compose
        SERVICES_LIST=${SERVICES//,/ }
        docker compose up -d $SERVICES_LIST
    else
        echo -e "${YELLOW}[⋯]${NC} Starting all services"
        docker compose up -d
    fi

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to start Docker containers"
        exit 1
    fi

    # Create configuration file
    echo -e "${YELLOW}[⋯]${NC} Creating configuration file..."
    CONFIG_FILE="/home/skycore/skycore.conf"

    # Prepare services string for config
    if [ -n "$SERVICES" ]; then
        SERVICES_CONFIG="$SERVICES"
    else
        # If all services were started, list them all
        SERVICES_CONFIG="drone-mavros,camera-proxy,mavproxy,ws_proxy"
    fi

    # Write to config file
    cat >"$CONFIG_FILE" <<EOF
activated: true
token: $TOKEN
services: $SERVICES_CONFIG
activation_date: $(date +"%Y-%m-%d %H:%M:%S")
EOF

    # Set permissions
    chown skycore:skycore "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE" # Only owner can read/write

    echo -e "${GREEN}[✔]${NC} Configuration saved to $CONFIG_FILE"

    # Grant Docker permissions to user
    echo -e "${YELLOW}[⋯]${NC} Granting Docker permissions to the current user..."
    # Get the current user (if running with sudo)
    CURRENT_USER=${SUDO_USER:-$(whoami)}

    # Skip if already root
    if [ "$CURRENT_USER" != "root" ]; then
        if getent group docker | grep -q "\b${CURRENT_USER}\b"; then
            echo -e "${GREEN}[✔]${NC} User $CURRENT_USER already has Docker permissions"
        else
            usermod -aG docker $CURRENT_USER
            echo -e "${GREEN}[✔]${NC} User $CURRENT_USER added to the docker group"
            echo -e "${YELLOW}[⋯]${NC} You may need to log out and log back in for the changes to take effect"
            echo -e "${YELLOW}[⋯]${NC} Or run 'newgrp docker' in your terminal to apply permissions immediately"
        fi
    fi

    echo -e "${GREEN}[✔]${NC} Drone activation is complete."
}

# Install skycore to the system
SCRIPT_PATH=$(readlink -f "$0")
INSTALL_PATH="/usr/local/bin/sc.sh"

# Function to install skycore to the system
install_skycore() {
    echo -e "${YELLOW}[⋯]${NC} Installing skycore to $INSTALL_PATH..."
    
    if [ "$SCRIPT_PATH" == "$INSTALL_PATH" ]; then
        echo -e "${GREEN}[✔]${NC} skycore is already installed at $INSTALL_PATH"
        return
    fi
    
    # Install dependencies
    echo -e "${YELLOW}[⋯]${NC} Installing required dependencies..."
    apt-get update -y
    apt-get install -y python3-pip util-linux gawk coreutils parted e2fsprogs xz-utils partclone jq libxml2-dev libxslt1-dev python3-dev git \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
    gstreamer1.0-alsa gstreamer1.0-libav gstreamer1.0-rtsp nvidia-l4t-gstreamer nvidia-l4t-multimedia \
    nvidia-l4t-multimedia-utils nvidia-l4t-jetson-multimedia-api

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

    # Create the directory if it doesn't exist
    INSTALL_DIR=$(dirname "$INSTALL_PATH")
    sudo mkdir -p "$INSTALL_DIR"
    
    sudo cp "$SCRIPT_PATH" "$INSTALL_PATH"
    sudo chmod +x "$INSTALL_PATH"

    # Copy skycore_cli.py alongside the main script if present
    CLI_SOURCE_PATH="$(dirname "$SCRIPT_PATH")/skycore_cli.py"
    CLI_INSTALL_PATH="/usr/local/bin/skycore_cli.py"
    if [ -f "$CLI_SOURCE_PATH" ]; then
        echo -e "${YELLOW}[⋯]${NC} Installing skycore_cli.py to $CLI_INSTALL_PATH"
        sudo cp "$CLI_SOURCE_PATH" "$CLI_INSTALL_PATH"
        sudo chmod +x "$CLI_INSTALL_PATH"
    else
        echo -e "${YELLOW}[⋯]${NC} skycore_cli.py not found next to sc.sh; skipping CLI install"
    fi

    # Create symlink in the same directory using direct path
    SYMLINK_PATH="${INSTALL_DIR}/skycore"
    # Use a direct target without any path transformation
    sudo ln -sf "$INSTALL_PATH" "$SYMLINK_PATH"
    
    echo -e "${GREEN}[✔]${NC} skycore installed successfully at $INSTALL_PATH"
    echo -e "${GREEN}[✔]${NC} Created symlink at $SYMLINK_PATH"
    
    # Set up TTY rules automatically as part of installation
    echo ""
    echo -e "${YELLOW}[⋯]${NC} Setting up TTY device permission rules..."
    
    # Look for common TTY devices
    TTY_DEVICES=$(find /dev -name "tty*" | grep -E 'ttyS|ttyTHS|ttyUSB|ttyACM' | head -1)
    
    if [ -n "$TTY_DEVICES" ]; then
        # Use the first available TTY device
        setup_tty_rules "$TTY_DEVICES"
    else
        # No devices found, create generic rules
        echo -e "${YELLOW}[⋯]${NC} No TTY devices currently connected."
        echo -e "${YELLOW}[⋯]${NC} Creating generic TTY permission rules..."
        
        RULE_FILE="/etc/udev/rules.d/99-tty-permissions.rules"
        echo 'SUBSYSTEM=="tty", MODE="0666", GROUP="dialout"' > "$RULE_FILE"
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="2341", MODE="0666", GROUP="dialout"' >> "$RULE_FILE"  # Arduino
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="26ac", MODE="0666", GROUP="dialout"' >> "$RULE_FILE"  # Pixhawk/3DR
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="10c4", MODE="0666", GROUP="dialout"' >> "$RULE_FILE"  # CP210x
        echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="0403", MODE="0666", GROUP="dialout"' >> "$RULE_FILE"  # FTDI
        
        echo -e "${GREEN}[✔]${NC} Generic rule file created at $RULE_FILE"
        
        # Reload rules
        echo -e "${YELLOW}[⋯]${NC} Reloading udev rules..."
        udevadm control --reload-rules
        udevadm trigger
        
        echo -e "${GREEN}[✔]${NC} TTY permission rules have been set up with generic rules."
        echo -e "${YELLOW}[⋯]${NC} Run 'skycore tty-setup <device>' after connecting devices for specific rules."
    fi
    
    # Clean up installation files from current directory
    echo ""
    echo -e "${YELLOW}[⋯]${NC} Cleaning up installation files..."
    
    # Get the directory where the script was run from
    INSTALL_DIR=$(dirname "$SCRIPT_PATH")
    
    # Only clean up if we're not already in the target installation directory
    if [ "$INSTALL_DIR" != "/usr/local/bin" ]; then
        # Remove sc.sh from current directory
        if [ -f "$INSTALL_DIR/sc.sh" ]; then
            rm -f "$INSTALL_DIR/sc.sh"
            echo -e "${GREEN}[✔]${NC} Removed temporary sc.sh"
        fi
        
        # Remove skycore_cli.py from current directory
        if [ -f "$INSTALL_DIR/skycore_cli.py" ]; then
            rm -f "$INSTALL_DIR/skycore_cli.py"
            echo -e "${GREEN}[✔]${NC} Removed temporary skycore_cli.py"
        fi
    fi
    
    echo ""
    echo -e "${GREEN}[✔]${NC} Installation complete! You can now use 'skycore' command from anywhere."
}

# Function to start services listed in skycore.conf
skycore_up() {
    # Check if config file exists
    CONFIG_FILE="/home/skycore/skycore.conf"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}[✖]${NC} Configuration file not found: $CONFIG_FILE"
        echo -e "${YELLOW}[⋯]${NC} Run 'skycore activate' first to set up the drone"
        exit 1
    fi

    # Read services from config file
    SERVICES=$(grep "services:" "$CONFIG_FILE" | cut -d':' -f2 | tr -d ' ')

    # Check if services were found in config
    if [ -z "$SERVICES" ]; then
        echo -e "${RED}[✖]${NC} No services defined in $CONFIG_FILE"
        exit 1
    fi

    # Convert comma-separated list to space-separated for docker compose
    SERVICES_LIST=${SERVICES//,/ }

    echo -e "${YELLOW}[⋯]${NC} Starting services: $SERVICES"
    docker compose up -d $SERVICES_LIST

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to start services"
        exit 1
    fi

    echo -e "${GREEN}[✔]${NC} Services started successfully"
}

# Function to stop all Docker services
skycore_down() {
    echo -e "${YELLOW}[⋯]${NC} Stopping all Docker services..."

    # Check if docker-compose.yml exists
    if [ ! -f "docker-compose.yml" ]; then
        echo -e "${RED}[✖]${NC} docker-compose.yml not found"
        echo -e "${YELLOW}[⋯]${NC} Run 'skycore activate' first to set up the drone"
        exit 1
    fi

    docker compose down

    if [ $? -ne 0 ]; then
        echo -e "${RED}[✖]${NC} Failed to stop services"
        exit 1
    fi

    echo -e "${GREEN}[✔]${NC} All services stopped successfully"
}

# Function to handle utility commands
utils_command() {
    local subcommand="$1"

    case "$subcommand" in
        boot_mmc)
            boot_mmc
            ;;
        boot_nvme)
            boot_nvme
            ;;
        *)
            echo -e "${RED}[✖]${NC} Unknown utility command: $subcommand"
            echo "Available utility commands:"
            echo "  boot_mmc  - Update extlinux.conf to boot from SD card"
            echo "  boot_nvme - Update extlinux.conf to boot from NVMe drive"
            ;;
    esac
}

# Function to configure system to boot from SD card
boot_mmc() {
    echo -e "${YELLOW}[⋯]${NC} Configuring system to boot from SD card..."
    
    # 1. Create and mount /mnt/mmc
    sudo mkdir -p /mnt/mmc
    if ! sudo mount -t ext4 /dev/mmcblk0p1 /mnt/mmc; then
        echo -e "${RED}[✖]${NC} Failed to mount /dev/mmcblk0p1. Is the SD card inserted properly?"
        return 1
    fi

    # 2. Path to extlinux.conf on the mounted partition
    EXTLINUX_CFG="/mnt/mmc/boot/extlinux/extlinux.conf"

    if [ -f "$EXTLINUX_CFG" ]; then
        # Change the root device
        sudo sed -i 's|root=/dev/nvme0n1p1|root=/dev/mmcblk0p1|g' "$EXTLINUX_CFG"
        
        # Add the kernel parameters if not already present
        if ! grep -q "pci=nomsi" "$EXTLINUX_CFG"; then
            sudo sed -i '/^[[:space:]]*APPEND/ s/$/ pci=nomsi pcie_aspm=off/' "$EXTLINUX_CFG"
        fi
        
        echo -e "${GREEN}[✔]${NC} Updated $EXTLINUX_CFG to use /dev/mmcblk0p1 as the root device."
        echo -e "${GREEN}[✔]${NC} Added NVMe optimization parameters: pci=nomsi pcie_aspm=off"
        sudo umount /mnt/mmc
        echo -e "${GREEN}[✔]${NC} The system will now boot from SD card on next reboot."
    else
        echo -e "${RED}[✖]${NC} extlinux.conf not found in $EXTLINUX_CFG!"
        sudo umount /mnt/mmc
        return 1
    fi
}

# Function to configure system to boot from NVMe drive
boot_nvme() {
    echo -e "${YELLOW}[⋯]${NC} Configuring system to boot from NVMe drive..."
    
    if [ -f /boot/extlinux/extlinux.conf ]; then
        # First change the root device
        sudo sed -i 's|root=/dev/mmcblk0p1|root=/dev/nvme0n1p1|g' /boot/extlinux/extlinux.conf
        
        # Then add the kernel parameters if not already present
        if ! grep -q "pci=nomsi" /boot/extlinux/extlinux.conf; then
            sudo sed -i '/^[[:space:]]*APPEND/ s/$/ pci=nomsi pcie_aspm=off/' /boot/extlinux/extlinux.conf
        fi
        
        echo -e "${GREEN}[✔]${NC} Updated root device to /dev/nvme0n1p1 in /boot/extlinux/extlinux.conf."
        echo -e "${GREEN}[✔]${NC} Added NVMe optimization parameters: pci=nomsi pcie_aspm=off"
        echo -e "${GREEN}[✔]${NC} The system will now boot from NVMe drive on next reboot."
    else
        echo -e "${RED}[✖]${NC} Error: extlinux.conf not found in /boot/extlinux/"
        return 1
    fi
}

# Function to set up TTY device permission rules
setup_tty_rules() {
    check_root

    echo -e "${YELLOW}[⋯]${NC} Setting up TTY device permission rules..."
    
    # Check if specific device path was provided
    DEVICE_PATH="/dev/ttyUSB0"
    if [[ $# -gt 0 ]]; then
        DEVICE_PATH="$1"
    fi
    
    # Check if device exists
    if [ ! -e "$DEVICE_PATH" ]; then
        echo -e "${RED}[✖]${NC} Device $DEVICE_PATH does not exist."
        echo -e "${YELLOW}[⋯]${NC} Available TTY devices:"
        find /dev -name "tty*" | grep -E 'ttyS|ttyTHS|ttyUSB|ttyACM'
        echo -e "${YELLOW}[⋯]${NC} Please connect your device or specify a valid device path."
        return 1
    fi
    
    # Get vendor and product IDs
    echo -e "${YELLOW}[⋯]${NC} Detecting vendor and product IDs for $DEVICE_PATH..."
    VENDOR_ID=$(udevadm info -a -n "$DEVICE_PATH" | grep '{idVendor}' -m 1 | awk -F'"' '{print $2}')
    PRODUCT_ID=$(udevadm info -a -n "$DEVICE_PATH" | grep '{idProduct}' -m 1 | awk -F'"' '{print $2}')
    
    if [ -z "$VENDOR_ID" ] || [ -z "$PRODUCT_ID" ]; then
        echo -e "${RED}[✖]${NC} Could not detect vendor or product IDs."
        echo -e "${YELLOW}[⋯]${NC} Creating generic rule for all TTY devices instead."
        
        RULE_FILE="/etc/udev/rules.d/99-tty-permissions.rules"
        echo 'SUBSYSTEM=="tty", MODE="0666", GROUP="dialout"' > "$RULE_FILE"
    else
        echo -e "${GREEN}[✔]${NC} Detected: Vendor ID=$VENDOR_ID, Product ID=$PRODUCT_ID"
        
        # Create rule file
        RULE_FILE="/etc/udev/rules.d/99-usb-permissions.rules"
        echo "SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"$VENDOR_ID\", ATTRS{idProduct}==\"$PRODUCT_ID\", MODE=\"0666\", GROUP=\"dialout\"" > "$RULE_FILE"
    fi
    
    echo -e "${GREEN}[✔]${NC} Rule file created at $RULE_FILE"
    
    # Reload rules
    echo -e "${YELLOW}[⋯]${NC} Reloading udev rules..."
    udevadm control --reload-rules
    udevadm trigger
    
    echo -e "${GREEN}[✔]${NC} TTY permission rules have been set up."
    echo -e "${YELLOW}[⋯]${NC} Disconnect and reconnect your device for changes to take effect."
}

# Function to set up video streaming service
setup_video_service() {
    check_root

    # Use absolute path instead of relative
    SCRIPT_PATH="/home/skycore/video.sh"
    TARGET_IP="${1:-192.168.144.25}"
    TARGET_PORT="${2:-5010}"
    
    echo -e "${YELLOW}[⋯]${NC} Setting up video streaming service..."
    echo -e "${YELLOW}[⋯]${NC} Using RTSP source: rtsp://${TARGET_IP}:8554/main.264"
    echo -e "${YELLOW}[⋯]${NC} Streaming to UDP port: ${TARGET_PORT}"
    
    # Create the video script file
    echo -e "${YELLOW}[⋯]${NC} Creating video script at $SCRIPT_PATH..."
    
    cat > "$SCRIPT_PATH" << EOF
#!/bin/bash
gst-launch-1.0 -e \\
    rtspsrc location=rtsp://${TARGET_IP}:8554/main.264 latency=50 drop-on-latency=true ! \\
    rtph264depay ! h264parse ! \\
    nvv4l2decoder enable-max-performance=1 disable-dpb=1 ! \\
    video/x-raw\\(memory:NVMM\\),format=NV12 ! \\
    nvvidconv ! \\
    video/x-raw,format=I420 ! \\
    videorate max-rate=25 ! \\
    x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=15 bframes=0 ! \\
    h264parse config-interval=1 ! \\
    video/x-h264,stream-format=byte-stream,alignment=au ! \\
    udpsink host=127.0.0.1 port=${TARGET_PORT} sync=false
EOF

    # Make script executable
    chmod +x "$SCRIPT_PATH"
    chown skycore:skycore "$SCRIPT_PATH"
    
    # Create systemd service file
    SERVICE_FILE="/etc/systemd/system/skycore-video.service"
    
    echo -e "${YELLOW}[⋯]${NC} Creating systemd service file at $SERVICE_FILE..."
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=SkyCore Video Streaming Service
After=network.target

[Service]
Type=simple
ExecStartPre=/bin/sleep 10
ExecStart=$SCRIPT_PATH
Restart=on-failure
RestartSec=10
User=skycore
Group=skycore

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd to recognize new service
    echo -e "${YELLOW}[⋯]${NC} Reloading systemd..."
    systemctl daemon-reload
    
    # Enable service to start on boot
    echo -e "${YELLOW}[⋯]${NC} Enabling video service to start on boot..."
    systemctl enable skycore-video.service
    

    echo -e "${YELLOW}[⋯]${NC} Starting video service..."
    systemctl start skycore-video.service
    
    # Check service status
    sleep 2
    if systemctl is-active --quiet skycore-video.service; then
        echo -e "${GREEN}[✔]${NC} Video service started successfully"
    else
        echo -e "${RED}[✖]${NC} Failed to start video service"
        echo -e "${YELLOW}[⋯]${NC} Check logs with: systemctl status skycore-video.service"
    fi
    
    echo -e "${GREEN}[✔]${NC} Video service has been set up and will run on boot"
    echo -e "${YELLOW}[⋯]${NC} You can control it with:"
    echo -e "  - systemctl start skycore-video.service"
    echo -e "  - systemctl stop skycore-video.service"
    echo -e "  - systemctl restart skycore-video.service"
}

# Function to set up video storage service
setup_video_storage_service() {
    check_root

    # Use the updated video_storage_encoder_with_audio.sh script
    SOURCE_SCRIPT_PATH="$(dirname "$0")/video_encoders/video_storage_encoder_with_audio.sh"
    SCRIPT_PATH="/home/skycore/video_storage_encoder_with_audio.sh"
    OUTPUT_DIR="${1:-/home/skycore/videos}"
    TARGET_IP="${2:-192.168.144.25}"
    
    echo -e "${YELLOW}[⋯]${NC} Setting up video storage service with audio support..."
    echo -e "${YELLOW}[⋯]${NC} Using RTSP source: rtsp://${TARGET_IP}:8554/main.264"
    echo -e "${YELLOW}[⋯]${NC} Saving recordings to: ${OUTPUT_DIR}"
    echo -e "${YELLOW}[⋯]${NC} Audio support: Will receive audio from audio_encoder.sh via UDP port 5011"
    echo -e "${YELLOW}[⋯]${NC} HLS segment duration (target-duration): 60 seconds"
    echo -e "${YELLOW}[⋯]${NC} HLS playlist length (segments per playlist file): 60 segments"
    echo -e "${YELLOW}[⋯]${NC} HLS max files on disk: Unlimited (max-files=0)"
    echo -e "${YELLOW}[⋯]${NC} Playlist file generation: New playlist file every 60 minutes"
    
    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"
    chown skycore:skycore "$OUTPUT_DIR"
    
    # Create the enhanced video storage script with audio support
    echo -e "${YELLOW}[⋯]${NC} Creating enhanced video storage script at $SCRIPT_PATH..."
    
    cat > "$SCRIPT_PATH" << EOF
#!/bin/bash

# Set output directory for video storage
OUTPUT_DIR="${OUTPUT_DIR}"
# Create directory if it doesn't exist
mkdir -p \$OUTPUT_DIR

# Log file for recording status
LOG_FILE="\$OUTPUT_DIR/recording_log.txt"

# Function to log messages
log_message() {
    echo "\$(date +"%Y-%m-%d %H:%M:%S") - \$1" >> "\$LOG_FILE"
    echo "\$1"
}

# Function to check if audio encoder is running and providing audio stream
check_audio_encoder() {
    # Check if audio_encoder.sh is running
    if pgrep -f "audio_encoder.sh" > /dev/null; then
        log_message "Audio encoder is running - will use UDP audio stream on port 5011"
        return 0
    else
        log_message "Warning: Audio encoder is not running. Audio will be disabled."
        return 1
    fi
}

# Function to run GStreamer with logging
run_gstreamer_with_logging() {
    local timestamp=\$1
    local audio_available=\$2
    
    if [ \$audio_available -eq 0 ]; then
        log_message "Recording with audio from UDP stream (port 5011)"
        # Enhanced pipeline with audio support (video + UDP audio stream)
        timeout 3630 gst-launch-1.0 -e \\
            mpegtsmux name=mux ! \\
                hlssink playlist-root=file://\$OUTPUT_DIR \\
                         target-duration=60 playlist-length=60 max-files=0 \\
                         playlist-location="\$OUTPUT_DIR/\${timestamp}_playlist.m3u8" \\
                         location="\$OUTPUT_DIR/\${timestamp}_segment_%05d.ts" \\
            rtspsrc location=rtsp://${TARGET_IP}:8554/main.264 latency=50 drop-on-latency=true ! \\
                rtph264depay ! h264parse ! \\
                avdec_h264 ! videoconvert ! \\
                x264enc speed-preset=veryfast bitrate=12000 key-int-max=50 bframes=0 ! \\
                h264parse config-interval=1 ! \\
                queue max-size-buffers=100 max-size-time=1000000000 ! \\
                mux. \\
            udpsrc port=5011 caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=111" ! \\
                rtpopusdepay ! opusdec ! \\
                audioconvert ! audioresample ! \\
                audio/x-raw,rate=48000,channels=2 ! \\
                queue max-size-buffers=200 max-size-time=2000000000 ! \\
                avenc_aac bitrate=128000 ! aacparse ! mux. &
    else
        log_message "Recording video only (no audio device available)"
        # Video-only pipeline using software encoding
        timeout 3630 gst-launch-1.0 -e \\
            rtspsrc location=rtsp://${TARGET_IP}:8554/main.264 latency=50 drop-on-latency=true ! \\
            rtph264depay ! h264parse ! \\
            avdec_h264 ! videoconvert ! \\
            x264enc speed-preset=veryfast bitrate=12000 key-int-max=50 bframes=0 ! \\
            h264parse config-interval=1 ! \\
            queue max-size-buffers=100 max-size-time=1000000000 ! \\
            mpegtsmux ! \\
            hlssink playlist-root=file://\$OUTPUT_DIR \\
            target-duration=60 \\
            playlist-length=60 \\
            max-files=0 \\
            playlist-location="\$OUTPUT_DIR/\${timestamp}_playlist.m3u8" \\
            location="\$OUTPUT_DIR/\${timestamp}_segment_%05d.ts" &
    fi
    
    local gst_pid=\$!
    
    # Keep track of logged files to avoid duplicates
    local logged_files_list="/tmp/logged_segments_\${timestamp}.txt"
    touch "\$logged_files_list"
    
    # Monitor for new .ts files while GStreamer is running
    while kill -0 \$gst_pid 2>/dev/null; do
        # Find all current .ts files for this timestamp
        for ts_file in "\$OUTPUT_DIR"/\${timestamp}_segment_*.ts; do
            if [ -f "\$ts_file" ]; then
                local filename=\$(basename "\$ts_file")
                # Check if we've already logged this file
                if ! grep -q "^\$filename\$" "\$logged_files_list" 2>/dev/null; then
                    log_message "Created segment file: \$filename"
                    echo "\$filename" >> "\$logged_files_list"
                fi
            fi
        done
        sleep 2
    done
    
    # Clean up the temporary file
    rm -f "\$logged_files_list"
    
    wait \$gst_pid
    return \$?
}

log_message "Starting HLS recording with audio support and 60-minute playlist rotation"

# Check for audio encoder availability
check_audio_encoder
AUDIO_AVAILABLE=\$?

# Main recording loop - runs indefinitely
while true; do
    # Generate timestamp for this hour's recording
    TIMESTAMP=\$(date +%Y%m%d_%H%M%S)
    
    log_message "Creating new playlist: \${TIMESTAMP}_playlist.m3u8"
    
    # Run GStreamer with logging
    run_gstreamer_with_logging "\$TIMESTAMP" \$AUDIO_AVAILABLE
    
    # Check if gst-launch exited due to an error
    EXIT_CODE=\$?
    if [ \$EXIT_CODE -ne 0 ] && [ \$EXIT_CODE -ne 124 ]; then
        # Exit code 124 means timeout completed normally
        log_message "Error: gst-launch exited with code \$EXIT_CODE. Waiting 10 seconds before retry."
        sleep 10
    else
        if [ \$AUDIO_AVAILABLE -eq 0 ]; then
            log_message "60-minute recording with UDP audio completed successfully"
        else
            log_message "60-minute recording (video only) completed successfully"
        fi
        # Small pause between recordings
        sleep 2
    fi
done
EOF

    # Make script executable
    chmod +x "$SCRIPT_PATH"
    chown skycore:skycore "$SCRIPT_PATH"
    
    # Create systemd service file
    SERVICE_FILE="/etc/systemd/system/skycore-video-storage.service"
    
    echo -e "${YELLOW}[⋯]${NC} Creating systemd service file at $SERVICE_FILE..."
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=SkyCore Video Storage Service with Audio Support
After=network.target sound.target
# Optional dependency on audio service - will start after audio if available
After=skycore-audio.service

[Service]
Type=simple
ExecStartPre=/bin/sleep 15
ExecStart=$SCRIPT_PATH
Restart=on-failure
RestartSec=10
User=skycore
Group=skycore
# Add audio group for potential audio access
SupplementaryGroups=audio

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd to recognize new service
    echo -e "${YELLOW}[⋯]${NC} Reloading systemd..."
    systemctl daemon-reload
    
    # Enable service to start on boot
    echo -e "${YELLOW}[⋯]${NC} Enabling video storage service to start on boot..."
    systemctl enable skycore-video-storage.service
    
    echo -e "${YELLOW}[⋯]${NC} Starting video storage service..."
    systemctl start skycore-video-storage.service
    
    # Check service status
    sleep 2
    if systemctl is-active --quiet skycore-video-storage.service; then
        echo -e "${GREEN}[✔]${NC} Video storage service started successfully"
    else
        echo -e "${RED}[✖]${NC} Failed to start video storage service"
        echo -e "${YELLOW}[⋯]${NC} Check logs with: systemctl status skycore-video-storage.service"
    fi
    
    echo -e "${GREEN}[✔]${NC} Video storage service has been set up and will run on boot"
    echo -e "${YELLOW}[⋯]${NC} Recordings will be saved to: ${OUTPUT_DIR}"
    echo -e "${YELLOW}[⋯]${NC} Recording logs will be saved to: ${OUTPUT_DIR}/recording_log.txt"
    echo -e "${YELLOW}[⋯]${NC} Audio support: Start audio-service first for audio recording"
    echo -e "${YELLOW}[⋯]${NC} You can control the service with:"
    echo -e "  - systemctl start skycore-video-storage.service"
    echo -e "  - systemctl stop skycore-video-storage.service"
    echo -e "  - systemctl restart skycore-video-storage.service"
    echo -e "  - journalctl -u skycore-video-storage.service -f  (view logs)"
    
    echo ""
    echo -e "${YELLOW}[⋯]${NC} For audio recording, also set up the audio service:"
    echo -e "  skycore audio-service"
}

# Function to set up audio streaming service
setup_audio_service() {
    check_root

    SCRIPT_PATH="/home/skycore/audio_encoder.sh"
    TARGET_PORT="${1:-5011}"
    
    echo -e "${YELLOW}[⋯]${NC} Setting up audio streaming service..."
    echo -e "${YELLOW}[⋯]${NC} Streaming audio to UDP port: ${TARGET_PORT}"
    echo -e "${YELLOW}[⋯]${NC} Looking for ReSpeaker audio device..."
    
    # Create the audio encoder script file
    echo -e "${YELLOW}[⋯]${NC} Creating audio encoder script at $SCRIPT_PATH..."
    
    cat > "$SCRIPT_PATH" << 'EOF'
#!/bin/bash

# Function to find ReSpeaker audio device
find_respeaker_device() {
    CARD_NUMBER=$(arecord -l | grep -i respeaker | head -1 | sed 's/card \([0-9]\).*/\1/')
    if [ -z "$CARD_NUMBER" ]; then
        echo "Warning: No ReSpeaker device found. Audio will be disabled." >&2
        return 1
    else
        echo "Found ReSpeaker at card $CARD_NUMBER" >&2
        echo $CARD_NUMBER
        return 0
    fi
}

# Log function for service output
log_message() {
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $1"
}

log_message "Starting audio encoder service..."

# Check for ReSpeaker device
RESPEAKER_CARD=$(find_respeaker_device | tail -n 1)
AUDIO_AVAILABLE=$?

# Audio pipeline (if ReSpeaker available)
if [ $AUDIO_AVAILABLE -eq 0 ]; then
    log_message "Adding audio stream from ReSpeaker (card $RESPEAKER_CARD) on port TARGET_PORT_PLACEHOLDER"
    
    # Main audio streaming loop with restart capability
    while true; do
        gst-launch-1.0 -e \
            alsasrc device=hw:$RESPEAKER_CARD,0 do-timestamp=true ! \
            audio/x-raw,format=S16LE,rate=16000,channels=6 ! \
            audioconvert ! audioresample ! \
            audio/x-raw,rate=48000,channels=2 ! \
            opusenc bitrate=128000 ! \
            rtpopuspay pt=111 ! \
            udpsink host=127.0.0.1 port=TARGET_PORT_PLACEHOLDER sync=false
        
        # Check exit status
        EXIT_CODE=$?
        if [ $EXIT_CODE -ne 0 ]; then
            log_message "Audio pipeline exited with code $EXIT_CODE. Restarting in 5 seconds..."
            sleep 5
        else
            log_message "Audio pipeline stopped normally"
            break
        fi
    done
else
    log_message "No ReSpeaker audio device found - audio encoder disabled"
    log_message "Service will keep running but audio streaming is inactive"
    
    # Keep the service running even without audio device
    while true; do
        sleep 60
        log_message "Audio service running (no device detected)"
    done
fi
EOF

    # Replace the placeholder with actual port
    sed -i "s/TARGET_PORT_PLACEHOLDER/${TARGET_PORT}/g" "$SCRIPT_PATH"

    # Make script executable
    chmod +x "$SCRIPT_PATH"
    chown skycore:skycore "$SCRIPT_PATH"
    
    # Create systemd service file
    SERVICE_FILE="/etc/systemd/system/skycore-audio.service"
    
    echo -e "${YELLOW}[⋯]${NC} Creating systemd service file at $SERVICE_FILE..."
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=SkyCore Audio Streaming Service
After=network.target sound.target

[Service]
Type=simple
ExecStart=$SCRIPT_PATH
Restart=on-failure
RestartSec=10
User=skycore
Group=skycore
# Add audio group for ALSA access
SupplementaryGroups=audio

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd to recognize new service
    echo -e "${YELLOW}[⋯]${NC} Reloading systemd..."
    systemctl daemon-reload
    
    # Enable service to start on boot
    echo -e "${YELLOW}[⋯]${NC} Enabling audio service to start on boot..."
    systemctl enable skycore-audio.service
    
    # Start the service
    echo -e "${YELLOW}[⋯]${NC} Starting audio service..."
    systemctl start skycore-audio.service
    
    # Check service status
    sleep 3
    if systemctl is-active --quiet skycore-audio.service; then
        echo -e "${GREEN}[✔]${NC} Audio service started successfully"
    else
        echo -e "${RED}[✖]${NC} Failed to start audio service"
        echo -e "${YELLOW}[⋯]${NC} Check logs with: systemctl status skycore-audio.service"
        echo -e "${YELLOW}[⋯]${NC} Check logs with: journalctl -u skycore-audio.service -f"
    fi
    
    echo -e "${GREEN}[✔]${NC} Audio service has been set up and will run on boot"
    echo -e "${YELLOW}[⋯]${NC} Audio will be streamed to UDP port: ${TARGET_PORT}"
    echo -e "${YELLOW}[⋯]${NC} You can control the service with:"
    echo -e "  - systemctl start skycore-audio.service"
    echo -e "  - systemctl stop skycore-audio.service"
    echo -e "  - systemctl restart skycore-audio.service"
    echo -e "  - journalctl -u skycore-audio.service -f  (view logs)"
}

# Function to update SkyCore to the latest version
update_skycore() {
    echo -e "${YELLOW}[⋯]${NC} Checking for latest SkyCore release..."

    TMP_DIR=$(mktemp -d /tmp/skycore-update-XXXXXX)
    ARCHIVE_URL="https://skyhub.ai/sc.tar.gz"

    echo -e "${YELLOW}[⋯]${NC} Downloading and extracting archive from $ARCHIVE_URL"
    if ! curl -sL "$ARCHIVE_URL" | tar -xz -C "$TMP_DIR"; then
        echo -e "${RED}[✖]${NC} Failed to download or extract SkyCore archive"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    if [ ! -f "$TMP_DIR/sc.sh" ]; then
        echo -e "${RED}[✖]${NC} sc.sh not found in the downloaded archive"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    echo -e "${YELLOW}[⋯]${NC} Running installer from the new release..."
    # Run installer with sudo to ensure required privileges for package installation and file copying
    if sudo bash "$TMP_DIR/sc.sh" install; then
        echo -e "${GREEN}[✔]${NC} SkyCore updated successfully"
    else
        echo -e "${RED}[✖]${NC} SkyCore update failed"
        rm -rf "$TMP_DIR"
        exit 1
    fi

    # Cleanup
    rm -rf "$TMP_DIR"
}

if [[ "$1" == "cli" ]]; then
    echo "Starting SkyCore CLI..."
    python3 "/usr/local/bin/skycore_cli.py"

elif [[ "$1" == "clone" ]]; then
    # Shift to remove the "clone" argument
    shift
    clone_drive "$@"

elif [[ "$1" == "flash" ]]; then
    # Shift to remove the "flash" argument
    shift
    flash_drive "$@"

elif [[ "$1" == "install" ]]; then
    # Install skycore to the system
    install_skycore

elif [[ "$1" == "update" ]]; then
    # Download and install the latest version of skycore
    update_skycore

elif [[ "$1" == "activate" ]]; then
    # Shift to remove the "activate" argument
    shift
    activate_drone "$@"

elif [[ "$1" == "up" ]]; then
    # Start services from config
    skycore_up

elif [[ "$1" == "down" ]]; then
    # Stop all Docker services
    skycore_down

elif [[ "$1" == "list" ]]; then
    # List available block devices
    list_block_devices

elif [[ "$1" == "utils" ]]; then
    # Shift to remove the "utils" argument
    shift
    utils_command "$@"

elif [[ "$1" == "tty-setup" ]]; then
    # Setup TTY device rules
    shift
    setup_tty_rules "$@"

elif [[ "$1" == "video-service" ]]; then
    # Setup video streaming service
    shift
    setup_video_service "$@"

elif [[ "$1" == "video-storage-service" ]]; then
    # Setup video storage service
    shift
    setup_video_storage_service "$@"

elif [[ "$1" == "audio-service" ]]; then
    # Setup audio streaming service
    shift
    setup_audio_service "$@"

elif [[ "$1" == "help" ]]; then
    echo "Available commands:"
    echo "  skycore cli       - Start the SkyCore CLI"
    echo "  skycore clone     - Clone a device to image files"
    echo "  skycore flash     - Flash image files to a device"
    echo "  skycore list      - List available block devices"
    echo "  skycore activate  - Activate a drone with a token"
    echo "    Options:"
    echo "      --token, -t <token>     - Specify the activation token"
    echo "      --services, -s <list>   - Comma-separated list of services to start"
    echo "                              (default: drone-mavros,mavproxy)"
    echo "                              (available: drone-mavros,camera-proxy,mavproxy,ws_proxy)"
    echo "  skycore up        - Start services listed in skycore.conf"
    echo "  skycore down      - Stop all Docker services"
    echo "  skycore install   - Install skycore to the system"
    echo "  skycore update    - Update skycore to the latest version"
    echo "  skycore tty-setup - Set up TTY device permission rules"
    echo "  skycore video-service [ip] [port] - Set up video streaming service to run on boot"
    echo "  skycore video-storage-service [output_dir] [ip] - Set up video storage service to run on boot"
    echo "  skycore audio-service [port] - Set up audio streaming service to run on boot"
    echo "  skycore utils     - Run utility commands"
    echo "    Available utilities:"
    echo "      boot_mmc      - Configure system to boot from SD card"
    echo "      boot_nvme     - Configure system to boot from NVMe drive"
    echo "  skycore install-wireguard  - Install WireGuard on the system"
    echo "  skycore help      - Show this help message"

    echo ""
    echo "For more information on a specific command, use --help:"
    echo "  skycore clone --help"
    echo "  skycore flash --help"
    echo "  skycore activate --help"

else
    # No arguments or unknown command - show help
    print_banner
    echo "Available commands:"
    echo "  skycore cli       - Start the SkyCore CLI"
    echo "  skycore clone     - Clone a device to image files"
    echo "  skycore flash     - Flash image files to a device"
    echo "  skycore list      - List available block devices"
    echo "  skycore activate  - Activate a drone with a token"
    echo "    Options:"
    echo "      --token, -t <token>     - Specify the activation token"
    echo "      --services, -s <list>   - Comma-separated list of services to start"
    echo "                              (default: drone-mavros,mavproxy)"
    echo "                              (available: drone-mavros,camera-proxy,mavproxy,ws_proxy)"
    echo "  skycore up        - Start services listed in skycore.conf"
    echo "  skycore down      - Stop all Docker services"
    echo "  skycore install   - Install skycore to the system"
    echo "  skycore update    - Update skycore to the latest version"
    echo "  skycore tty-setup - Set up TTY device permission rules"
    echo "  skycore video-service [ip] [port] - Set up video streaming service to run on boot"
    echo "  skycore video-storage-service [output_dir] [ip] - Set up video storage service to run on boot"
    echo "  skycore audio-service [port] - Set up audio streaming service to run on boot"
    echo "  skycore utils     - Run utility commands"
    echo "    Available utilities:"
    echo "      boot_mmc      - Configure system to boot from SD card"
    echo "      boot_nvme     - Configure system to boot from NVMe drive"
    echo "  skycore install-wireguard  - Install WireGuard on the system"
    echo "  skycore help      - Show this help message"

    echo ""
    echo "For more information on a specific command, use --help:"
    echo "  skycore clone --help"
    echo "  skycore flash --help"
    echo "  skycore activate --help"
fi
