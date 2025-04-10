.. _service_management:

Service Management
==================

SkyCore provides commands to manage Docker services that control your drone.

Available Commands
------------------

up
~~

The ``up`` command starts Docker services that are listed in the configuration file.

.. code-block:: bash

   skycore up

How it works:

1. Reads the ``services`` entry from ``/home/skycore/skycore.conf``
2. Starts only the services that were specified during activation
3. Provides output confirming which services were started

This command is useful after a reboot or if the services were stopped.

down
~~~~

The ``down`` command stops all Docker services.

.. code-block:: bash

   skycore down

This completely shuts down all running containers and releases resources.

Examples
--------

Typical workflow:

.. code-block:: bash

   # Activate with specific services
   sudo skycore activate --token 1234567890 --services drone-mavros,mavproxy
   
   # Later, after a reboot
   skycore up  # Starts only drone-mavros and mavproxy
   
   # When finished
   skycore down  # Stops all services

Configuration File
------------------

The ``skycore.conf`` file stores your activation settings and looks like this:

.. code-block:: text

   activated: true
   token: 1234567890
   services: drone-mavros,mavproxy
   activation_date: 2025-04-10 12:05:34

To modify which services start with the ``up`` command, you can:

1. Edit this file manually to change the ``services`` line
2. Rerun activation with different service selections

Troubleshooting
---------------

Common issues:

* **Permission Denied**: Ensure your user is in the docker group or use sudo
* **Missing Configuration File**: Run ``skycore activate`` first to create the configuration
* **No Services Started**: Check that services are correctly listed in skycore.conf 