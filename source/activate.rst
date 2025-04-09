.. _activate:

Activate
========

The ``activate`` command is used to activate a drone with a token. This enables the drone to connect to the SkyHub network and start receiving commands.

Usage
-----

.. code-block:: bash

   skycore activate <Drone Token>

Parameters
---------

* ``<Drone Token>``: The activation token for the drone (required)

Example
-------

.. code-block:: bash

   skycore activate 1234567890

How It Works
------------

The activation process includes the following steps:

1. Contacts the activation server with the provided token
2. Downloads and configures the VPN connection
3. Sets up Docker credentials for accessing the container registry
4. Downloads the Docker Compose configuration
5. Starts the necessary containers

The drone will be connected to the SkyHub network and ready to receive commands after successful activation.

Environment Variables
--------------------

* ``STAGE``: Sets the environment to connect to (default: ``prod``)

To use a different environment:

.. code-block:: bash

   STAGE=dev skycore activate <Drone Token>

Troubleshooting
--------------

Common issues:

* **Connection Error**: Ensure the Drone has internet connectivity
* **Authentication Failure**: Verify the token is correct and hasn't expired
* **VPN Connection Failure**: Check if WireGuard is installed and properly configured
* **Docker Issues**: Ensure Docker and Docker Compose are installed and running 