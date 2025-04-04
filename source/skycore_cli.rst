SkyCore CLI Tool
===============

The SkyCore CLI is a command-line interface for managing navigation sources and related operations for a drone or robot using ArduPilot. It provides functionality for switching between GPS and SLAM navigation, setting parameters, monitoring position, and performing various system operations.

Installation
-----------

The SkyCore CLI tool is included in the SkyCore installer. No additional installation is required.

Dependencies
-----------

The tool requires the following Python dependencies:

* ``requests`` - For HTTP communications
* ``pymavlink`` - For MAVLink communications with ArduPilot

Missing dependencies will be detected when you run the tool, and you'll be prompted to install them.

Usage
-----

To start the CLI tool in interactive mode::

    ./skycore_cli.py

To execute a specific command directly::

    ./skycore_cli.py <command> [args]

Available Commands
-----------------

Navigation Source Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``gps`` - Switch to GPS navigation
* ``slam`` - Switch to SLAM navigation
* ``status`` - Show current navigation source

Position and Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

* ``ekf`` - Set EKF origin and home position to 0,0,0
* ``custom_ekf`` - Set EKF origin and home position with custom coordinates
* ``monitor`` - Monitor position for 30 seconds

Communication
~~~~~~~~~~~~

* ``listen`` - Listen for MAVLink messages from Pixhawk
* ``recent_msgs`` - Show the last 30 Pixhawk messages

System Operations
~~~~~~~~~~~~~~~

* ``reboot`` - Reboot ArduPilot
* ``full_restart`` - Perform a full system restart including ArduPilot and SLAM container
* ``clean_sd`` - Clean the SD card
* ``reset_params`` - Reset parameters to default values

Parameter Management
~~~~~~~~~~~~~~~~~~

* ``get_param`` - Get a parameter value
* ``set_param`` - Set a parameter value
* ``export_params`` - Export all parameters to a file

Examples
--------

Switch to SLAM Navigation
~~~~~~~~~~~~~~~~~~~~~~~~

To switch from GPS to SLAM-based navigation::

    ./skycore_cli.py slam

Export All Parameters
~~~~~~~~~~~~~~~~~~~

To export all ArduPilot parameters to a file::

    ./skycore_cli.py export_params my_params.txt

Set Custom EKF Origin
~~~~~~~~~~~~~~~~~~~

To set a custom EKF origin and home position, use the interactive mode::

    ./skycore_cli.py custom_ekf

You'll be prompted to enter latitude, longitude, and altitude values.

Perform a Full System Restart
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To perform a complete system restart, including ArduPilot and the SLAM container::

    ./skycore_cli.py full_restart

Troubleshooting
--------------

Connection Issues
~~~~~~~~~~~~~~~

If the tool cannot connect to ArduPilot, check that:

1. The Pixhawk or flight controller is properly connected to your computer
2. You have the necessary permissions to access the serial port
3. No other application is currently using the MAVLink connection

To identify available connection methods, the tool tries multiple common configurations:

* Serial ports: ``/dev/ttyACM0``, ``/dev/ttyACM1``, ``/dev/ttyUSB0``, ``/dev/ttyUSB1``
* UDP connections: ``udpin:127.0.0.1:14550``, ``udpin:127.0.0.1:14551``, etc.

Missing Dependencies
~~~~~~~~~~~~~~~~~~

If you see an error about missing dependencies:

1. Allow the tool to install them automatically when prompted
2. Or install them manually using pip::

    pip install pymavlink requests 