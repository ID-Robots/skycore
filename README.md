# SkyCore

SkyCore CLI - A powerful command-line interface for managing your SkyHub devices.

## Documentation

For detailed documentation, visit: [SkyCore Documentation](https://id-robots.github.io/skycore/getting_started.html)

## Getting Started

### SkyHub Registration

1. Register for SkyHub at [https://skyhub.ai/register](https://skyhub.ai/register)
2. Verify your email address
3. Log in to access the SkyHub dashboard

### Installation

SSH into your Jetson device and install SkyCore CLI:

```bash
curl -sL https://skyhub.ai/sc.tar.gz | tar xz && sudo bash skycore.sh
```

### Vehicle Registration

Add a new vehicle to SkyHub by visiting: [https://skyhub.ai/home?dialog=app-create-drone-dialog](https://skyhub.ai/home?dialog=app-create-drone-dialog)

### Drone Activation

Activate your drone with the following command:

```bash
sudo skycore activate --token <drone_token>
```

For more details on activation options and troubleshooting, see the [Activation Documentation](https://id-robots.github.io/skycore/activate.html).

### Cloning Drives

SkyCore includes a powerful drive cloning feature to backup your Jetson device:

```bash
sudo skycore clone --source /dev/nvme0n1 [options]
```

Common options:

- `--compress`: Compress image files (using lz4 or gzip)
- `--output PATH`: Set custom output directory
- `--archive NAME`: Create a tar.gz archive of all partitions

Example (create a compressed backup archive):

```bash
sudo skycore clone --source /dev/nvme0n1 --compress --archive my_jetson_backup
```

To restore a backup to a new drive:

```bash
sudo skycore flash --target /dev/sdX --archive /path/to/my_jetson_backup.tar.gz
```

For more details, see the [Cloning Documentation](https://id-robots.github.io/skycore/clone.html).

### Flashing Drives

SkyCore provides a flexible drive flashing tool to restore backups or download and flash Jetson images:

```bash
sudo skycore flash --target /dev/sdX [options]
```

Common options:

- `--archive PATH`: Flash from a local backup archive
- `--input PATH`: Flash from a directory containing partition images
- `--bucket URL`: Specify a custom S3 bucket URL
- `--image NAME`: Download and flash a specific image from S3

Examples:

Download and flash the default Orion Nano image:

```bash
sudo skycore flash --target /dev/sdX
```

Flash from a local backup archive:

```bash
sudo skycore flash --target /dev/sdX --archive /path/to/backup.tar.gz
```

Download a custom image from S3:

```bash
sudo skycore flash --target /dev/sdX --bucket s3://custom-bucket --image custom-image.tar.gz
```

For more details, see the [Flashing Documentation](https://id-robots.github.io/skycore/flash.html).

## Service Management

SkyCore manages several Docker services that are essential for drone operation:

### Available Services

- `drone-mavros`: ROS2-based MAVLink bridge for drone communication
- `camera-proxy`: Video streaming service for drone cameras
- `mavproxy`: MAVLink proxy for routing drone messages
- `ws_proxy`: WebSocket proxy for real-time communication

### Managing Services

Start specific services (after activation):
```bash
sudo skycore activate --token <drone_token> --services drone-mavros,mavproxy
```

Start all configured services:
```bash
sudo skycore up
```

Stop all running services:
```bash
sudo skycore down
```

Service configuration is stored in `/home/skycore/skycore.conf` after activation. You can modify this file to change which services are managed by the `up` command.

## Sphinx Documentation Update

### Installing Documentation Dependencies

The documentation system requires several Python packages. You can install them using:

```bash
pip3 install -r requirements-docs.txt
```

Required packages are listed in `requirements-docs.txt` and include:
- Sphinx and extensions
- Read the Docs theme
- MyST Parser for Markdown support
- Additional Sphinx plugins for enhanced functionality

### Building Documentation

To build the HTML documentation:

```bash
make html
```

### Viewing Documentation

To view the built documentation:

```bash
xdg-open build/html/index.html
```

## Support

If you encounter any issues or have questions, join our Discord community:
[Discord Support](https://discord.com/invite/aDJJ8GqqQc)

## License

© Copyright 2025, ID Robots.
