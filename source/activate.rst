.. _activate:

Activate
========

The ``activate`` command is used to activate a drone with a token. This enables the drone to connect to the SkyHub network and start receiving commands.

Usage
-----

.. code-block:: bash

   skycore activate [options] <Drone Token>

Parameters
----------

* ``<Drone Token>``: The activation token for the drone (required)
* ``--token, -t <token>``: Alternative way to specify the activation token
* ``--services, -s <list>``: Comma-separated list of services to start (default: all services)
  
Available services:

* ``drone-mavros``: ROS2 bridge for the flight controller
* ``camera-proxy``: Video streaming service
* ``mavproxy``: MAVLink proxy for the flight controller
* ``ws_proxy``: WebSocket proxy for telemetry

Examples
--------

Basic activation (starts all services):

.. code-block:: bash

   skycore activate 1234567890

Start only specific services:

.. code-block:: bash

   skycore activate --token 1234567890 --services drone-mavros,mavproxy

How It Works
------------

The activation process includes the following steps:

1. Contacts the activation server with the provided token
2. Downloads and configures the VPN connection
3. Sets up Docker credentials for accessing the container registry
4. Downloads the Docker Compose configuration
5. Starts the selected services (or all services by default)
6. Creates a configuration file at ``~/skycore.conf``
7. Grants Docker permissions to the current user

The drone will be connected to the SkyHub network and ready to receive commands after successful activation.

Configuration File
------------------

During activation, SkyCore creates a configuration file at ``/home/skycore/skycore.conf`` that contains:

* Activation status
* The token used for activation
* The list of services that were activated
* Activation timestamp

This file is used by the ``up`` command to restart the same services after a reboot.

Managing Services
-----------------

SkyCore provides commands to manage the Docker services after activation:

* ``skycore up``: Start the services listed in the configuration file
* ``skycore down``: Stop all Docker services

.. code-block:: bash

   # Start services from the configuration
   skycore up

   # Stop all services
   skycore down

Environment Variables
---------------------

* ``STAGE``: Sets the environment to connect to (default: ``prod``)

To use a different environment:

.. code-block:: bash

   STAGE=dev skycore activate <Drone Token>

Troubleshooting
---------------

Common issues:

* **Connection Error**: Ensure the Drone has internet connectivity
* **Authentication Failure**: Verify the token is correct and hasn't expired
* **VPN Connection Failure**: Check if WireGuard is installed and properly configured
* **Docker Issues**: Ensure Docker and Docker Compose are installed and running 