# File: services/depth/simple_rotate_left_manual.py # Renamed conceptually

import time
import sys
import argparse
import logging
from pymavlink import mavutil

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
ROTATION_DURATION_S = 2.0 # Duration to rotate

# --- Manual Control Constants ---
LEFT_STEER_VALUE = -500     # Steering value for left rotation (-1000 to 1000)
NEUTRAL_THROTTLE_VALUE = 0  # Throttle value (-1000 to 1000)
NEUTRAL_STEER_VALUE = 0     # Neutral steering value
COMMAND_LOOP_RATE_HZ = 20   # Send commands at this rate to maintain control

def send_manual_control_command(connection, throttle_z, steering_y):
    """Sends a MANUAL_CONTROL command (using y for steering, z for throttle)."""
    target_system = connection.target_system
    target_component = connection.target_component
    try:
        # ArduPilot Rover typically maps:
        # z -> Throttle (-1000 to 1000)
        # y -> Steering (-1000 to 1000)
        connection.mav.manual_control_send(
            target_system,
            0,                  # x: pitch (usually ignored)
            int(steering_y),    # y: roll/steering
            int(throttle_z),    # z: throttle
            0,                  # r: yaw (usually ignored if y is steering)
            0                   # buttons bitmask
        )
        # Log only when sending non-neutral commands to reduce spam
        if throttle_z != 0 or steering_y != 0:
            logging.debug(f"Sent manual_control: Z(Thr)={throttle_z}, Y(Steer)={steering_y}")
    except Exception as e:
        logging.error(f"Error sending manual_control command: {e}")

def main():
    parser = argparse.ArgumentParser(description=f"Send a command to rotate the vehicle left using MANUAL_CONTROL (Steering: {LEFT_STEER_VALUE}).")
    parser.add_argument('--connect', type=str, default="/dev/ttyUSB0", help="MAVLink connection string (e.g., /dev/ttyUSB0, udp:127.0.0.1:14550)")
    parser.add_argument('--baudrate', type=int, default=230400, help="MAVLink baud rate (for serial connections)")
    parser.add_argument('--duration', type=float, default=ROTATION_DURATION_S, help="Duration to rotate in seconds")
    args = parser.parse_args()

    rotation_duration = args.duration
    connection = None
    try:
        # --- Connect to MAVLink ---
        logging.info(f"Connecting to MAVLink via: {args.connect} at {args.baudrate} baud")
        extra_kwargs = {}
        if 'udp' in args.connect or 'tcp' in args.connect:
             extra_kwargs = {'source_system': 255}
        elif 'tty' in args.connect or 'dev' in args.connect:
             extra_kwargs = {'source_system': 255, 'baud': args.baudrate}
        connection = mavutil.mavlink_connection(args.connect, **extra_kwargs)

        # --- Wait for Heartbeat ---
        logging.info("Waiting for heartbeat...")
        connection.wait_heartbeat(timeout=10)
        if connection.target_system == 0:
            raise ConnectionError("Heartbeat not received. Check MAVLink connection & baud rate.")
        logging.info(f"Heartbeat received from system {connection.target_system}, component {connection.target_component}")

        # --- Check Vehicle State (Basic) ---
        msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
        if not msg:
            raise TimeoutError("Did not receive HEARTBEAT after connection.")
        is_armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        mode_id = msg.custom_mode
        mode_name = connection.mode_mapping().get(mode_id, f"UNKNOWN({mode_id})")
        if not is_armed:
            raise RuntimeError("Vehicle is DISARMED. Please ARM the vehicle first.")
        logging.info(f"Vehicle is ARMED in mode: {mode_name}")

        # --- Set Mode to MANUAL (Still recommended) ---
        target_mode = 'MANUAL'
        if mode_name != target_mode:
            logging.info(f"Attempting to set mode to {target_mode}...")
            mode_id = connection.mode_mapping().get(target_mode)
            if mode_id is not None:
                connection.mav.set_mode_send(
                    connection.target_system,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                    mode_id
                )
                time.sleep(1)
                msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
                if msg:
                    new_mode_id = msg.custom_mode
                    new_mode_name = connection.mode_mapping().get(new_mode_id, f"UNKNOWN({new_mode_id})")
                    if new_mode_name == target_mode:
                        logging.info(f"Mode successfully changed to {new_mode_name}.")
                    else:
                        logging.warning(f"Mode change command sent, but vehicle is now in {new_mode_name}.")
                else:
                    logging.warning("Did not receive confirmation heartbeat after mode change attempt.")
            else:
                logging.error(f"Mode {target_mode} is not supported by this firmware.")
        else:
            logging.info(f"Vehicle already in {target_mode} mode.")

        logging.warning("Ensure ARMING_CHECK is properly configured (recommended: 1).")

        # --- Send Rotation Command Loop ---
        logging.info(f"Commanding left rotation (Steering: {LEFT_STEER_VALUE}) for {rotation_duration:.2f} seconds at {COMMAND_LOOP_RATE_HZ} Hz.")
        start_time = time.time()
        while time.time() < start_time + rotation_duration:
            send_manual_control_command(connection, throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=LEFT_STEER_VALUE)
            time.sleep(1.0 / COMMAND_LOOP_RATE_HZ)

        # --- Send Stop Command (Neutral Throttle/Steering) ---
        logging.info(f"Sending STOP command (Neutral Throttle/Steering).")
        # Send stop command for a short duration to ensure it's received
        stop_start_time = time.time()
        while time.time() < stop_start_time + 0.5: # Send stop for 0.5s
             send_manual_control_command(connection, throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
             time.sleep(1.0 / COMMAND_LOOP_RATE_HZ)

        # --- Wait briefly ---
        logging.info("Waiting 0.5 second after stop.")
        time.sleep(0.5)

    except ConnectionError as ce:
        logging.error(f"MAVLink Error: {ce}")
    except TimeoutError as te:
        logging.error(f"MAVLink Error: {te}")
    except RuntimeError as rte:
        logging.error(f"Runtime Error: {rte}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        import traceback
        logging.error(traceback.format_exc())

    finally:
        if connection:
             # Send stop command again just in case
            try:
                logging.info("Sending final STOP command.")
                send_manual_control_command(connection, throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                time.sleep(0.2)
            except Exception as final_e:
                logging.warning(f"Error sending final stop command: {final_e}")
            logging.info("Closing MAVLink connection.")
            connection.close()

if __name__ == "__main__":
    main()