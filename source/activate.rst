.. _activate:

Activate
========

The ``activate`` command is used to activate a drone with a token. This enables the drone to connect to the SkyHub network and start receiving commands.

Usage
-----

.. code-block:: bash

   skycore activate --token <Drone Token> [options]

Parameters
----------

* ``--token, -t <token>``: The activation token for the drone (required)
* ``--services, -s <list>``: Comma-separated list of services to start (default: drone-mavros,mavproxy)
  
Available services:

* ``drone-mavros``: ROS2 bridge for the flight controller
* ``camera-proxy``: Video streaming service
* ``mavproxy``: MAVLink proxy for the flight controller
* ``ws_proxy``: WebSocket proxy for telemetry

Examples
--------

Basic activation (starts default services: drone-mavros and mavproxy):

.. code-block:: bash

   skycore activate --token 1234567890

Start all available services:

.. code-block:: bash

   skycore activate --token 1234567890 --services drone-mavros,camera-proxy,mavproxy,ws_proxy

Start only specific services:

.. code-block:: bash

   skycore activate --token 1234567890 --services camera-proxy,ws_proxy

How It Works
------------

The activation process includes the following steps:

1. Contacts the activation server with the provided token
2. Downloads and configures the VPN connection
3. Sets up Docker credentials for accessing the container registry
4. Downloads the Docker Compose configuration
5. Starts the selected services (defaults to drone-mavros and mavproxy)
6. Creates a configuration file at ``~/skycore.conf``
7. Grants Docker permissions to the current user

The drone will be connected to the SkyHub network and ready to receive commands after successful activation.

Configuration File
------------------

During activation, SkyCore creates a configuration file at ``/home/skycore/skycore.conf`` that contains:

* ``activated``: Current activation status (true/false)
* ``token``: The token used for activation
* ``services``: Comma-separated list of activated services
* ``activation_date``: Timestamp of when the drone was activated

Example ``skycore.conf``:

.. code-block:: yaml

    activated: true
    token: 4773854478
    services: drone-mavros,mavproxy
    activation_date: 2025-04-10 15:39:05

This file is used by the ``up`` command to restart the same services after a reboot. You can manually edit the ``services`` line to change which services will be started by the ``up`` command.

.. note::
   The configuration file is automatically created during activation, but you can modify it later to adjust which services should be managed by the ``up`` command.

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

   STAGE=dev skycore activate --token <Drone Token>

Troubleshooting
---------------

Common issues:

* **Connection Error**: Ensure the Drone has internet connectivity
* **Authentication Failure**: Verify the token is correct and hasn't expired
* **VPN Connection Failure**: Check if WireGuard is installed and properly configured
* **Docker Issues**: Ensure Docker and Docker Compose are installed and running 