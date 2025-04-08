=================
Cloning Drives
=================

Overview
---------

The SkyCore system includes a powerful drive cloning feature that allows you to create backups of your Jetson Orin partitions. This tool uses partclone to efficiently clone partitions and can compress images to save space.

With the clone functionality, you can:

* Create backups of all partitions from a source device
* Compress images to save storage space
* Create archives for easy transfer or storage
* Optionally upload backups to S3 for cloud storage
* Create bootable clone drives for Jetson Orin devices

Requirements
------------

* SkyCore installed on your system
* Root privileges (sudo)
* partclone package installed
* Optional: lz4 or gzip for compression
* Optional: AWS CLI for S3 upload functionality

Basic Usage
-----------

The basic syntax for cloning a drive is:

.. code-block:: bash

   sudo skycore clone --source /dev/sdX [options]

Where ``/dev/sdX`` is the source drive you want to clone (e.g., ``/dev/sda``, ``/dev/nvme0n1``).

Command Line Options
-------------------

.. list-table::
   :widths: 20 10 70
   :header-rows: 1

   * - Option
     - Short Form
     - Description
   * - ``--source PATH``
     - ``-s PATH``
     - Source device to clone (e.g., ``/dev/nvme0n1``, ``/dev/sda``)
   * - ``--compress``
     - ``-c``
     - Enable compression for image files
   * - ``--output DIR``
     - ``-o DIR``
     - Output directory for image files (default: current directory)
   * - ``--debug``
     - ``-d``
     - Enable debug mode (verbose output)
   * - ``--archive NAME``
     - ``-a NAME``
     - Create archive of backup (provide name without extension)
   * - ``--upload``
     - ``-u``
     - Upload archive to S3 after creation (requires AWS CLI configured)
   * - ``--bucket URL``
     - ``-b URL``
     - S3 bucket URL for upload (e.g., ``s3://bucket-name``)
   * - ``--help``
     - ``-h``
     - Display help information

Examples
--------

1. Basic clone - clone a drive to the current directory:

   .. code-block:: bash

      sudo skycore clone --source /dev/sda

2. Clone with compression to a specific directory:

   .. code-block:: bash

      sudo skycore clone --source /dev/nvme0n1 --compress --output /tmp/backup

3. Clone and create an archive for easy transfer:

   .. code-block:: bash

      sudo skycore clone --source /dev/sda --compress --archive jetson_backup

4. Clone, archive, and upload to S3:

   .. code-block:: bash

      sudo skycore clone --source /dev/sda --compress --archive jetson_backup --upload --bucket s3://my-backups

Cloning Process
--------------

When you run the clone command, SkyCore will:

1. Check if the source device exists and has valid partitions
2. Display information about the detected partitions
3. Unmount any mounted partitions (with your permission)
4. Back up the partition table
5. Clone each partition using the appropriate partclone variant based on filesystem type
6. Optionally compress the images using lz4 or gzip
7. Optionally create a tarball with all images and metadata
8. Optionally upload the archive to S3

The clone process creates the following files in the output directory:

* ``jetson_nvme_partitions.sfdisk`` - Partition table backup
* ``jetson_nvme_blkinfo.txt`` - Block device information
* ``jetson_nvme_p1.img`` - Image of partition 1 (or with .lz4/.gz extension if compressed)
* ``jetson_nvme_p2.img`` - Image of partition 2
* ...and so on for each partition

If archive creation is enabled, an additional tarball will be created containing all these files.

Restoring Clone Images
---------------------

To restore a cloned drive, use the flash command:

.. code-block:: bash

   sudo skycore flash --target /dev/sdX --input /path/to/backup

See the Flash Drive documentation for more details on restoring images.

Troubleshooting
--------------

**Error: Device not found**

Make sure the source device exists and is accessible by running:

.. code-block:: bash

   lsblk

**Error: partclone not installed**

Install the partclone package:

.. code-block:: bash

   sudo apt install partclone

**Compression errors**

If you encounter errors with compression, install the required utilities:

.. code-block:: bash

   sudo apt install lz4 gzip

**S3 upload errors**

If S3 upload fails, check:

1. AWS CLI is installed and configured
2. You have appropriate permissions to write to the bucket
3. The bucket exists and is accessible

.. code-block:: bash

   # Install AWS CLI
   pip install awscli
   
   # Configure AWS credentials
   aws configure 