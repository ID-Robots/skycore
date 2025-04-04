Getting Started
===============

Welcome to SkyCore! This guide will help you install and get started with SkyCore.

SkyHub Registration
------------------

Before you begin, you'll need to create a SkyHub account:

1. Register for SkyHub at `https://skyhub.ai/register <https://skyhub.ai/register>`_
2. Verify your email address
3. Log in to access the SkyHub dashboard

Installation
-----------

SSH into your Jetson device and install SkyCore CLI:

.. code-block:: bash

   curl -sL https://skyhub.ai/sc.tar.gz | tar xz && sudo bash skycore.sh

SSD Flashing
-----------

To flash SSD from the host Ubuntu system:

1. Connect SSD drive with USB dongle to host PC
2. Run the SSD flash command:

.. code-block:: bash

   skycore ssd -d /dev/sda -i skycore.pcl.xz

Vehicle Registration
-------------------

Add a new vehicle to SkyHub by visiting:
https://skyhub.ai/home?dialog=app-create-drone-dialog

Drone Activation
---------------

Activate your drone with the following command:

.. code-block:: bash

   sudo activate.sh <drone_token>

.. figure:: https://idrobots.com/wp-content/uploads/2024/12/image-1-1024x653.png
   :alt: Drone activation screen
   :width: 100%

   Drone activation screen in SkyHub

Important Notes
--------------

1. Ensure you have a stable internet connection before running the commands.
2. Run all commands with appropriate privileges (use ``sudo`` where required).

Support
------

If you encounter any issues or have questions, contact our support team:

* **Discord:** https://discord.com/invite/aDJJ8GqqQc

Happy inventing with SkyHub! 