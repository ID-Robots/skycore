Getting Started
===============

Welcome to SkyCore! This guide will help you install and get started with SkyCore.

SkyHub Registration
-------------------

Before you begin, you'll need to create a SkyHub account:

1. Register for SkyHub at `https://skyhub.ai/register <https://skyhub.ai/register>`_
2. Verify your email address
3. Log in to access the SkyHub dashboard

Installation
------------

SSH into your Jetson device and install SkyCore CLI:

.. code-block:: bash

   curl -sL https://skyhub.ai/sc.tar.gz | tar xz && sudo bash skycore.sh

Drive Flashing
--------------

To download and flash a Jetson Orin image to a drive:

.. code-block:: bash

   sudo skycore flash --target /dev/sdX

Where ``/dev/sdX`` is your target drive (e.g., ``/dev/sda`` or ``/dev/nvme0n1``).

This command will:

1. Download the latest Orion Nano image from our S3 repository
2. Flash the image to your target drive
3. Create all required partitions with proper filesystem types

You can customize the source and other options:

.. code-block:: bash

   sudo skycore flash --target /dev/sdX --bucket s3://custom-bucket --image custom-image.tar.gz

For more options and details, see the :doc:`flash` documentation.

Vehicle Registration
--------------------

Add a new vehicle to SkyHub by visiting:
https://skyhub.ai/home?dialog=app-create-drone-dialog

Drone Activation
----------------

Activate your drone with the following command:

.. code-block:: bash

   sudo skycore activate <drone_token>

.. figure:: https://idrobots.com/wp-content/uploads/2024/12/image-1-1024x653.png
   :alt: Drone activation screen
   :width: 100%

   Drone activation screen in SkyHub

For more details on activation options and troubleshooting, see the :doc:`activate` documentation.

Important Notes
---------------

1. Ensure you have a stable internet connection before running the commands.
2. Run all commands with appropriate privileges (use ``sudo`` where required).

Support
-------

If you encounter any issues or have questions, contact our support team:

* **Discord:** https://discord.com/invite/aDJJ8GqqQc

Happy inventing with SkyHub! 