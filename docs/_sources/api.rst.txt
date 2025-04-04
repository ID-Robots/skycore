API Reference
=============

Core Module
-----------

.. code-block:: python

   class skycore.Core

Main class for interacting with the SkyCore system.

.. code-block:: python

   Core.__init__(debug=False, log_level='WARNING', max_workers=None)

Creates a new Core instance.

Parameters:
   - **debug** (*bool*) – Enable debug mode
   - **log_level** (*str*) – Logging level
   - **max_workers** (*int*) – Maximum number of worker threads

Methods
~~~~~~~

.. code-block:: python

   Core.start()

Start the core system.

.. code-block:: python

   Core.shutdown()

Gracefully shut down the core system.

.. code-block:: python

   Core.on(event_name)

Decorator for registering event handlers.

Parameters:
   - **event_name** (*str*) – Name of the event to listen for

.. code-block:: python

   Core.process(data)

Process the given data through the system.

Parameters:
   - **data** (*dict*) – Data to process

Utilities
---------

.. code-block:: python

   skycore.utils.configure_logging(level='INFO')

Configure the logging system.

Parameters:
   - **level** (*str*) – Logging level 