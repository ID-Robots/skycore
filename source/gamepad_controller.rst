Setup Gamepad Controller
=======================

SkyHub Supports controlling the vehicles with Gamepad. The system was tested with Play Station 4 and Play Station 5 controllers, but other controllers supporting the `Browser Gamepad API <https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API/Using_the_Gamepad_API>`_ will work.

Connection Steps
---------------

1. Pair the controller to the phone, tablet, or PC
2. Test if the gamepad is detected on `https://hardwaretester.com/gamepad <https://hardwaretester.com/gamepad>`_
3. Login in SkyHub: `https://skyhub.ai <https://skyhub.ai/#/home>`_
4. Select a vehicle from the web interface and move any gamepad button to connect the gamepad. A web socket connection will be established to the selected drone.
5. Enter MANUAL/LOITER mode for Vehicle control.

.. figure:: https://idrobots.com/wp-content/uploads/2025/01/ps5-1024x458.png
   :alt: PlayStation controller with SkyHub
   :width: 100%

   PlayStation controller connected to SkyHub interface

Button Mappings For Rover
------------------------

* **Triangle (△)** - Guided Mode
* **Circle (○)** - Auto Mode
* **Cross (×)** - Lights
* **Square (□)** - Manual Mode
* **Up / Down / Left / Right** - Camera gimble
* **L1** - Take Photo
* **R1** - Toggle Recording Video
* **L2** - Throttle Backward
* **R2** - Throttle Forward
* **Left Stick** - Left / Right
* **Right Stick** - Nothing 
* **Right Options** - Arm / Disarm
* **Left Options** - Camera point forward

Button Mappings For Drone
------------------------

* **Triangle (△)** - Guided Mode
* **Circle (○)** - Auto Mode
* **Cross (×)** - Nothing
* **Square (□)** - Loiter mode
* **Up / Down / Left / Right** - Camera gimble
* **L1** - Take Photo
* **R1** - Toggle Recording Video
* **L2** - Nothing
* **R2** - Nothing
* **Left Stick** - Throttle Control
* **Right Stick** - Attitude Control
* **Right Options** - Arm / Disarm
* **Left Options** - Camera point forward 