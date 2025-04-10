==============
Cloning Drives
==============

Overview
--------

The SkyCore system includes a powerful drive cloning feature that allows you to create backups of your Jetson Orin partitions. This tool uses partclone to efficiently clone partitions and can compress images to save space.

With the clone functionality, you can:

* Create backups of all partitions from a source device
* Compress images to save storage space
* Create archives for easy transfer or storage
* Create bootable clone drives for Jetson Orin devices

Requirements
------------

* SkyCore installed on your system
* Root privileges (sudo)
* partclone package installed
* Optional: lz4 or gzip for compression

Basic Usage
-----------

The basic syntax for cloning a drive is:

.. code-block:: bash

   sudo skycore clone --source SOURCE_DEVICE [options]

Where ``SOURCE_DEVICE`` is the device you want to clone (e.g., ``/dev/nvme0n1`` or ``/dev/sda``).

Command Line Options
--------------------

The following options are available for the ``skycore clone`` command:

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - Option
     - Description
   * - ``--source``, ``-s``
     - Source device to clone (e.g., /dev/nvme0n1)
   * - ``--compress``, ``-c``
     - Compress the image files (using lz4 or gzip)
   * - ``--output``, ``-o``
     - Output directory for image files (default: current directory)
   * - ``--debug``, ``-d``
     - Enable debug mode (verbose output)
   * - ``--archive``, ``-a``
     - Create archive of backup (provide archive name without extension)
   * - ``--help``, ``-h``
     - Display help information

Examples
--------

Below are some examples of how to use the clone command:

1. Clone a drive to the current directory:

   .. code-block:: bash

      sudo skycore clone --source /dev/nvme0n1

2. Clone with compression to a specific directory:

   .. code-block:: bash

      sudo skycore clone --source /dev/sda --compress --output /tmp/my_backup

3. Create a compressed archive:

   .. code-block:: bash

      sudo skycore clone --source /dev/sda --compress --archive my_backup

Cloning Process
---------------

When you run the clone command, the following steps are performed:

1. The tool checks if partclone is installed
2. It identifies all partitions on the source device
3. It unmounts any mounted partitions (with your confirmation)
4. It backs up the partition table from the source device
5. It clones each partition with the appropriate filesystem handler
6. It compresses the images if the --compress option is used
7. It creates an archive if the --archive option is used

Restoring Images
----------------

To restore cloned images to a target drive, use the ``skycore flash`` command:

.. code-block:: bash

   sudo skycore flash --target /dev/sdX --archive /path/to/backup.tar.gz

For more details, see the :doc:`flash` documentation.

Troubleshooting
---------------

Common issues and solutions:

**Cannot access source device**

Error message: ``Error: Source device /dev/XXX does not exist or is not a block device.``

Solution: Make sure the source device is correctly connected and recognized by the system. You can use ``lsblk`` to list available block devices.

**Partclone not installed**

Error message: ``Error: partclone is not installed.``

Solution: Install partclone with ``sudo apt install partclone``.

**Permission denied**

Error message: ``This script must be run as root``

Solution: Run the command with sudo privileges.

**Mounted partitions**

Warning: ``Warning: /dev/sdaX is currently mounted. It will be unmounted.``

Solution: Allow the script to unmount the partitions or manually unmount them before running the command. 