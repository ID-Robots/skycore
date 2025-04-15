#!/bin/bash

# Switches the default root device from /dev/mmcblk0p1 to /dev/nvme0n1p1 in extlinux.conf

if [ -f /boot/extlinux/extlinux.conf ]; then
    sudo sed -i 's|root=/dev/mmcblk0p1|root=/dev/nvme0n1p1|g' /boot/extlinux/extlinux.conf
    echo "Updated root device to /dev/nvme0n1p1 in /boot/extlinux/extlinux.conf."
else
    echo "Error: extlinux.conf not found in /boot/extlinux/"
fi
