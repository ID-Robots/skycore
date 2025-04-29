# File: services/depth/simple_move_back_rc.py

import time
import sys
import argparse
import logging
from pymavlink import mavutil

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
# Original distance/speed used only for duration calculation
DISTANCE_TO_MOVE_M = 0.20 # Target distance (positive for calculation)
MOVE_SPEED_MPS = 0.20     # Target speed (positive for calculation)
MOVE_DURATION_S = DISTANCE_TO_MOVE_M / MOVE_SPEED_MPS

# --- RC Override Constants ---
BACKWARD_PWM = 1400    # Slower PWM value for backward throttle (closer to 1500 neutral)
STEERING_PWM = 1500    # PWM value for neutral steering (1000-2000)
NEUTRAL_THROTTLE_PWM = 1500 # PWM value for neutral throttle
THROTTLE_CHAN_IDX = 2  # Channel 3 index (0-based)
STEERING_CHAN_IDX = 3  # Channel 4 index (0-based)
NUM_CHANNELS = 8       # Number of RC channels to override

def send_rc_override_command(connection, channels):
    """Sends an RC_CHANNELS_OVERRIDE command."""
    target_system = connection.target_system
    target_component = connection.target_component

    # Ensure channels list has the correct length, filling with 0 (or 1500 if preferred for unused)
    rc_values = list(channels) + [0] * (NUM_CHANNELS - len(channels))

    try:
        connection.mav.rc_channels_override_send(
            target_system,
            target_component,
            *rc_values # Send the channel values
        )
        # Truncate for logging if too long
        log_values = rc_values[:8]
        if len(rc_values) > 8:
            log_values.append("...")
        logging.info(f"Sent rc_channels_override: {log_values}")
    except Exception as e:
        logging.error(f"Error sending rc_channels_override command: {e}")

def main():
    parser = argparse.ArgumentParser(description="Send a command to move the vehicle backward slowly using RC_CHANNELS_OVERRIDE (PWM 1400).")
    parser.add_argument('--connect', type=str, default="/dev/ttyUSB0", help="MAVLink connection string (e.g., /dev/ttyUSB0, udp:127.0.0.1:14550)")
    parser.add_argument('--baudrate', type=int, default=230400, help="MAVLink baud rate (for serial connections)")
    args = parser.parse_args()

    connection = None
    try:
        # --- Connect to MAVLink ---
        logging.info(f"Connecting to MAVLink via: {args.connect} at {args.baudrate} baud")
        extra_kwargs = {}
        if 'udp' in args.connect or 'tcp' in args.connect:
             extra_kwargs = {'source_system': 255} # Use a GCS source system ID
        elif 'tty' in args.connect or 'dev' in args.connect:
             extra_kwargs = {'source_system': 255, 'baud': args.baudrate}

        connection = mavutil.mavlink_connection(args.connect, **extra_kwargs)

        # --- Wait for Heartbeat ---
        logging.info("Waiting for heartbeat...")
        connection.wait_heartbeat(timeout=10)
        if connection.target_system == 0:
            logging.error("Heartbeat not received. Check connection & baud rate.")
            sys.exit(1)
        logging.info(f"Heartbeat received from system {connection.target_system}, component {connection.target_component}")

        # --- Check Vehicle State (Basic) ---
        msg = connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
        if not msg:
            logging.error("Did not receive HEARTBEAT.")
            sys.exit(1)

        is_armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        mode_id = msg.custom_mode
        mode_name = connection.mode_mapping().get(mode_id, f"UNKNOWN({mode_id})")

        if not is_armed:
            logging.error("Vehicle is DISARMED. Please ARM the vehicle first.")
            sys.exit(1)
        else:
             logging.info(f"Vehicle is ARMED in mode: {mode_name}")

        # --- Set Mode to MANUAL ---
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
                # Wait briefly for mode change to potentially propagate
                time.sleep(1)
                # Check mode again (optional, but good practice)
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

        logging.warning("RC_CHANNELS_OVERRIDE typically requires MANUAL mode, but might work in others.")
        logging.warning("Ensure ARMING_CHECK is properly configured (recommended: 1) before relying on this.")

        # --- Prepare RC Commands ---
        neutral_cmd = [0] * NUM_CHANNELS
        neutral_cmd[THROTTLE_CHAN_IDX] = NEUTRAL_THROTTLE_PWM
        neutral_cmd[STEERING_CHAN_IDX] = STEERING_PWM

        backward_cmd = list(neutral_cmd) # Start with neutral
        backward_cmd[THROTTLE_CHAN_IDX] = BACKWARD_PWM

        release_cmd = [0] * NUM_CHANNELS # Command to release override

        # --- Send Movement Command ---
        logging.info(f"Commanding backward movement (PWM: {BACKWARD_PWM} on Ch{THROTTLE_CHAN_IDX+1}) for {MOVE_DURATION_S:.2f} seconds.")
        send_rc_override_command(connection, backward_cmd)

        # --- Wait for duration ---
        time.sleep(MOVE_DURATION_S)

        # --- Send Stop Command (Neutral Throttle/Steering) ---
        logging.info(f"Sending STOP command (Neutral PWM: {NEUTRAL_THROTTLE_PWM} on Ch{THROTTLE_CHAN_IDX+1}).")
        send_rc_override_command(connection, neutral_cmd)

        # --- Wait briefly ---
        logging.info("Waiting 1 second after stop.")
        time.sleep(1)

        # --- Release RC Override ---
        # Send 0 to all channels to release override
        logging.info("Releasing RC Override (sending 0 to all channels).")
        send_rc_override_command(connection, release_cmd)
        time.sleep(0.2)

    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        if connection:
            # Send release command again just in case
            try:
                logging.info("Sending final RC Override release command.")
                release_cmd = [0] * NUM_CHANNELS
                send_rc_override_command(connection, release_cmd)
                time.sleep(0.1)
            except Exception as final_e:
                logging.warning(f"Error sending final release command: {final_e}") # Warning as it might fail if connection closed
            logging.info("Closing MAVLink connection.")
            connection.close()

if __name__ == "__main__":
    main()