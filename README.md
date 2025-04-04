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
curl -sL https://skyhub.ai/sc.tar.gz|tar xz && sudo bash skycore.sh
```

### Vehicle Registration

Add a new vehicle to SkyHub by visiting: [https://skyhub.ai/home?dialog=app-create-drone-dialog](https://skyhub.ai/home?dialog=app-create-drone-dialog)

### Drone Activation

Activate your drone with the following command:

```bash
sudo activate.sh <drone_token>
```

## Development

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
