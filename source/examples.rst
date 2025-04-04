Examples
========

Basic Examples
-------------

Simple Initialization
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   
   # Create a core instance
   core = skycore.Core()
   
   # Start the core system
   core.start()
   
   # Do some work...
   
   # Shutdown when done
   core.shutdown()

Event Handling
~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   
   core = skycore.Core()
   
   # Register event handlers
   @core.on('data_received')
   def handle_data(data):
       print(f"Received data: {data}")
   
   @core.on('processing_complete')
   def processing_done(result):
       print(f"Processing completed with result: {result}")
   
   # Start the system
   core.start()
   
   # Trigger some events
   core.process({"message": "Hello World"})

Advanced Examples
----------------

Custom Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   import yaml
   
   # Load configuration from file
   with open('config.yaml', 'r') as f:
       config = yaml.safe_load(f)
   
   # Initialize with configuration
   core = skycore.Core.from_config(config)
   
   # Start processing
   core.start()

Distributed Processing
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   
   # Create a distributed core
   core = skycore.DistributedCore(
       nodes=['node1:8000', 'node2:8000', 'node3:8000'],
       role='primary'
   )
   
   # Configure fault tolerance
   core.set_fault_tolerance(retries=3, backup_node='backup:8000')
   
   # Start the distributed system
   core.start()
   
   # Submit work to the distributed system
   result = core.submit_job({
       'task': 'process_image',
       'data': '/path/to/image.jpg',
       'params': {'scale': 0.5, 'format': 'png'}
   })
   
   print(f"Job result: {result}")

Integration Examples
-------------------

Web API Integration
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   from flask import Flask, request, jsonify
   
   app = Flask(__name__)
   core = skycore.Core()
   
   @app.route('/api/process', methods=['POST'])
   def process_data():
       data = request.json
       result = core.process(data)
       return jsonify(result)
   
   if __name__ == '__main__':
       # Start the core system
       core.start()
       
       # Start the web server
       app.run(host='0.0.0.0', port=5000)

Database Integration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import skycore
   import sqlite3
   
   # Create a core with database support
   core = skycore.Core()
   
   # Connect to database
   conn = sqlite3.connect('data.db')
   
   # Register a handler that stores data
   @core.on('store_data')
   def store_in_db(data):
       cursor = conn.cursor()
       cursor.execute(
           "INSERT INTO data (timestamp, value) VALUES (?, ?)",
           (data['timestamp'], data['value'])
       )
       conn.commit()
   
   # Start the system
   core.start()
   
   # Process some data
   core.process({
       'type': 'store_data',
       'timestamp': '2025-01-01T12:00:00',
       'value': 42
   }) 