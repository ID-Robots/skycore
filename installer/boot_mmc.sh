#!/bin/bash
#
# set extlinux to boot from /dev/mmcblk0p1

# 1. Create and mount /mnt/mmc
sudo mkdir -p /mnt/mmc
sudo mount -t ext4 /dev/mmcblk0p1 /mnt/mmc

# 2. Path to extlinux.conf on the mounted partition
EXTLINUX_CFG="/mnt/mmc/boot/extlinux/extlinux.conf"

if [ -f "$EXTLINUX_CFG" ]; then
    sudo sed -i 's|root=/dev/nvme0n1p1|root=/dev/mmcblk0p1|g' "$EXTLINUX_CFG"
    echo "Updated $EXTLINUX_CFG to use /dev/mmcblk0p1 as the root device."
    sudo umount /mnt/mmc
else
    echo "extlinux.conf not found in $EXTLINUX_CFG!"
fi
