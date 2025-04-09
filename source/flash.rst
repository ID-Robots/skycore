=================
Flashing Drives
=================

Overview
---------

The SkyCore system includes a powerful drive flashing feature that allows you to restore Jetson Orin images to target devices. The flash command can download images from S3 buckets or use locally stored images.

With the flash functionality, you can:

* Download Jetson Orin images directly from S3
* Flash images to a target device such as an SSD or NVMe drive
* Restore previously created backups made with the clone command
* Maintain proper partition structure and filesystem types
* Create bootable drives for Jetson Orin devices

Requirements
------------

* SkyCore installed on your system
* Root privileges (sudo)
* partclone package installed
* Internet connection (for downloading from S3)
* AWS CLI for S3 functionality (auto-installed if missing)
* Target storage device (SSD/NVMe)

Basic Usage
-----------

The basic syntax for flashing a drive is:

.. code-block:: bash

   sudo skycore flash --target TARGET_DEVICE [options]

Where ``TARGET_DEVICE`` is the device you want to flash (e.g., ``/dev/sdb`` or ``/dev/nvme1n1``).

Command Line Options
--------------------

The following options are available for the ``skycore flash`` command:

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Option
     - Description
   * - ``--target``, ``-t``
     - Target device to flash (e.g., /dev/sdb)
   * - ``--bucket``, ``-b``
     - S3 bucket URL (default: s3://jetson-nano-ub-20-bare)
   * - ``--image``, ``-i``
     - Image name to download from S3 (default: orion-nano-8gb-jp6.2.tar.gz)
   * - ``--archive``, ``-a``
     - Use local archive file instead of downloading from S3
   * - ``--input``, ``-d``
     - Use local directory with partition images instead of archive
   * - ``--help``, ``-h``
     - Display help information

Examples
--------

Below are some examples of how to use the flash command:

1. Download and flash the default Orion Nano image to a target device:

   .. code-block:: bash

      sudo skycore flash --target /dev/sdb

2. Download a specific image from a custom S3 bucket:

   .. code-block:: bash

      sudo skycore flash --target /dev/sdb --bucket s3://custom-bucket --image custom-image.tar.gz

3. Use a local archive created by the clone command:

   .. code-block:: bash

      sudo skycore flash --target /dev/sdb --archive /path/to/backup.tar.gz

4. Use a directory with extracted partition images:

   .. code-block:: bash

      sudo skycore flash --target /dev/sdb --input /path/to/backup_dir

Flashing Process
----------------

When you run the flash command, the following steps are performed:

1. The tool checks for required dependencies and installs any missing ones
2. If downloading from S3, the specified image is downloaded (or reused if already present)
3. The archive is extracted to a temporary directory
4. Any mounted partitions on the target device are identified and unmounted
5. The partition table is restored to the target device
6. Each partition image is restored to the correct partition with the appropriate filesystem type
7. Compressed images (.gz or .lz4) are automatically decompressed during restoration

Warning: The flashing process will erase all data on the target device. Make sure you have selected the correct device and have backed up any important data.

Troubleshooting
---------------

Common issues and solutions:

**Cannot access target device**

Error message: ``Error: Target device /dev/XXX does not exist or is not a block device.``

Solution: Make sure the target device is correctly connected and recognized by the system. You can use ``lsblk`` to list available block devices.

**No partition images found**

Error message: ``Error: No partition image files found in the source.``

Solution: Verify that the archive or directory contains valid partition images with the expected naming format (jetson_nvme_p*.img*).

**AWS access issues**

Error message: ``Failed to download the image from S3.``

Solution: If using a private S3 bucket, make sure AWS credentials are properly configured. For public buckets, check the bucket URL and image name for typos.

**Partition table restoration failure**

Error message: ``Error: Failed to restore partition table.``

Solution: Make sure the target device is not in use and has sufficient space. Also verify that the partition table file exists in the extracted archive.

**Permission denied**

Error message: ``This script must be run as root``

Solution: Run the command with sudo privileges. 