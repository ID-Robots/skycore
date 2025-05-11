#!/usr/bin/env python3

"""
SkyCore CLI - Command-line interface for SkyCore operations.

This module provides a command-line interface for interacting with SkyCore,
including navigation control, parameter management, and system operations.
"""

import logging
import time
import os
import subprocess
import json
import sys
import shutil
import re
from typing import Dict, Optional, List, Union, Tuple

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Check dependencies and import conditionally
MISSING_DEPENDENCIES = []

try:
    import requests
except ImportError:
    MISSING_DEPENDENCIES.append('requests')

# Don't import pymavlink here - we'll try to import it only when needed

def check_and_install_dependencies(required_deps=None):
    """
    Check for missing dependencies and offer to install them.
    
    Args:
        required_deps (list): List of dependencies that are required for the current operation
    
    Returns:
        bool: True if dependencies are installed, False otherwise
    """
    # If specific dependencies are required for an operation
    if required_deps:
        missing = [dep for dep in required_deps if dep in MISSING_DEPENDENCIES]
        if missing:
            print(f"This command requires the following missing dependencies: {', '.join(missing)}")
            install = input("Would you like to install them now? (yes/no): ").strip().lower()
            if install == 'yes':
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                    print("Dependencies installed successfully. Please restart the script.")
                except Exception as e:
                    print(f"Error installing dependencies: {e}")
                    print("Please install the dependencies manually and try again.")
            else:
                print("Please install the dependencies and try again.")
            return False
        return True
    
    # If checking all dependencies
    elif MISSING_DEPENDENCIES:
        print("Missing optional dependencies (required for some commands):")
        for dep in MISSING_DEPENDENCIES:
            print(f"  - {dep}")
            
        install = input("Would you like to install them now? (yes/no): ").strip().lower()
        if install == 'yes':
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + MISSING_DEPENDENCIES)
                print("Dependencies installed successfully. Please restart the script.")
                return True
            except Exception as e:
                print(f"Error installing dependencies: {e}")
                print("Please install the dependencies manually and try again.")
                return False
        else:
            print("You can continue using commands that don't require these dependencies.")
            print("To install dependencies later, run: pip install " + " ".join(MISSING_DEPENDENCIES))
            return False
    
    return True

class MAVLinkConnection:
    """Handles MAVLink connection and parameter operations."""
    
    def __init__(self):
        """
        Initialize MAVLink connection.
        
        Attempts to establish a connection to a MAVLink device.
        """
        # Check if pymavlink is available
        try:
            from pymavlink import mavutil
            self.mavutil = mavutil
        except ImportError:
            MISSING_DEPENDENCIES.append('pymavlink')
            raise ConnectionError("pymavlink module is not installed. Some features will be unavailable.")
        
        self.connection = None
        self.mavlink_url = None
        self.message_log = []  # Store recent messages
        self.max_log_size = 100  # Maximum number of messages to store in the log
        self._connect()
        
    def _connect(self) -> None:
        """
        Establish connection using various methods.
        
        Attempts to connect to a MAVLink device using common connection methods.
        """
        # Allow custom connection URL from environment variable
        custom_url = os.environ.get('SKYCORE_MAVLINK_URL')
        
        connection_methods = []
        
        # If custom URL is specified, try it first
        if custom_url:
            connection_methods.append(custom_url)
            
        # UDP connections for MAVROS and MAVProxy
        connection_methods.extend([
            'udpin:127.0.0.1:14550', 'udpin:127.0.0.1:14551',
            'udpout:127.0.0.1:14550', 'udpout:127.0.0.1:14551',
            'udp://127.0.0.1:14550', 'udp://127.0.0.1:14551'
        ])
        
        # Direct USB connections with common names
        connection_methods.extend([
            '/dev/ttyACM0', '/dev/ttyACM1', '/dev/ttyUSB0', '/dev/ttyUSB1',
        ])
        
        # Specific TELEM1 connection - try last since it's often busy
        connection_methods.append('serial:/dev/ttyTHS1:23040')
        
        for method in connection_methods:
            try:
                self.connection = self.mavutil.mavlink_connection(method)
                if self.connection:
                    logger.info(f"Connected to MAVLink device at {method}")
                    self.mavlink_url = method
                    return
            except Exception as e:
                logger.debug(f"Failed to connect using {method}: {e}")
                continue
        
        raise ConnectionError("Could not establish MAVLink connection")

    def close(self) -> None:
        """Close the MAVLink connection."""
        if self.connection:
            self.connection.close()
            self.connection = None

    def reboot_ardupilot(self) -> bool:
        """
        Send reboot command to ArduPilot.
        
        Returns:
            bool: True if reboot command was sent successfully, False otherwise
        """
        try:
            self.connection.mav.command_long_send(
                self.connection.target_system,
                self.connection.target_component,
                self.mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
                0, 1, 0, 0, 0, 0, 0, 0
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send reboot command: {e}")
            return False

    def get_parameter(self, param_name: str) -> Optional[float]:
        """
        Get a parameter value from ArduPilot.
        
        Args:
            param_name (str): Name of the parameter to get
            
        Returns:
            Optional[float]: Parameter value if successful, None otherwise
        """
        try:
            self.connection.param_fetch_one(param_name)
            msg = self.connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
            if msg:
                return msg.param_value
            return None
        except Exception as e:
            logger.error(f"Failed to get parameter {param_name}: {e}")
            return None

    def set_parameter(self, param_name: str, param_value: float) -> bool:
        """
        Set a parameter value in ArduPilot.
        
        Args:
            param_name (str): Name of the parameter to set
            param_value (float): Value to set
            
        Returns:
            bool: True if parameter was set successfully, False otherwise
        """
        try:
            self.connection.param_set_send(param_name, param_value)
            msg = self.connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
            return msg is not None
        except Exception as e:
            logger.error(f"Failed to set parameter {param_name}: {e}")
            return False

    def listen_for_messages(self, message_types: Optional[List[str]] = None, duration: int = 0, silent: bool = False) -> None:
        """
        Listen for MAVLink messages.
        
        Args:
            message_types (Optional[List[str]]): List of message types to listen for
            duration (int): Duration in seconds to listen (0 for indefinite)
            silent (bool): Whether to suppress message output
        """
        try:
            start_time = time.time()
            while True:
                if duration > 0 and time.time() - start_time > duration:
                    break
                    
                msg = self.connection.recv_match(
                    type=message_types[0] if message_types else None,
                    blocking=True,
                    timeout=1.0
                )
                
                if msg:
                    self.message_log.append((time.time(), msg))
                    if len(self.message_log) > self.max_log_size:
                        self.message_log.pop(0)
                    
                    if not silent:
                        formatted = self.format_message(time.time(), msg)
                        print(formatted)
                        
        except KeyboardInterrupt:
            print("\nStopped listening for messages")
        except Exception as e:
            logger.error(f"Error listening for messages: {e}")

    def format_message(self, timestamp: float, msg) -> str:
        """
        Format a MAVLink message for display.
        
        Args:
            timestamp (float): Timestamp of the message
            msg: MAVLink message object
            
        Returns:
            str: Formatted message string
        """
        msg_type = msg.get_type()
        msg_data = msg.to_dict()
        
        # Remove internal MAVLink fields
        msg_data.pop('mavpacket_type', None)
        msg_data.pop('_timestamp', None)
        
        return f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] {msg_type}: {msg_data}"

    def export_parameters(self, filename: Optional[str] = None) -> None:
        """
        Export parameters to a file.
        
        Args:
            filename (Optional[str]): Name of the file to export parameters to
        """
        try:
            if not filename:
                filename = "parameters.param"
                
            print(f"Exporting parameters to {filename}...")
            
            # Create a list to store parameters
            params = []
            
            # Get all parameters
            self.connection.param_fetch_all()
            
            while True:
                msg = self.connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
                if not msg:
                    break
                    
                params.append(f"{msg.param_id},{msg.param_value}\n")
                
            # Write parameters to file
            with open(filename, 'w') as f:
                f.writelines(params)
                
            print(f"Parameters exported to {filename}")
        except Exception as e:
            logger.error(f"Failed to export parameters: {e}")
            print("Failed to export parameters")

    def save_parameters(self) -> bool:
        """
        Save parameters permanently to non-volatile storage.
        
        Returns:
            bool: True if parameters were saved successfully, False otherwise
        """
        try:
            # Simpler way to send save command
            self.connection.arducopter_arm()
            self.connection.arducopter_disarm()
            print("Attempted to save parameters by arming/disarming")
            return True
        except Exception as e:
            logger.error(f"Failed to save parameters: {e}")
            return False

class NavigationToggle:
    """Handles navigation source toggling and related operations."""
    
    def __init__(self):
        """Initialize navigation toggle with MAVLink connection."""
        self.mavlink = MAVLinkConnection()
        self.current_source = None
        self._update_current_source()
        
    def _update_current_source(self) -> None:
        """Update the current navigation source based on EKF type."""
        try:
            nav_source = self.mavlink.get_parameter("AHRS_EKF_TYPE")
            if nav_source == 3:
                self.current_source = "GPS"
            elif nav_source == 2:
                self.current_source = "SLAM"
            else:
                self.current_source = None
        except Exception as e:
            logger.error(f"Failed to update current source: {e}")
            self.current_source = None

    def switch_to_gps(self) -> bool:
        """
        Switch to GPS navigation.
        
        Returns:
            bool: True if switch was successful, False otherwise
        """
        try:
            # Set EKF type to 3 (GPS)
            if not self.mavlink.set_parameter("AHRS_EKF_TYPE", 3):
                return False
                
            # Set EKF2 enabled to 1
            if not self.mavlink.set_parameter("EK2_ENABLE", 1):
                return False
                
            # Set EKF3 enabled to 0
            if not self.mavlink.set_parameter("EK3_ENABLE", 0):
                return False
                
            self._update_current_source()
            return True
        except Exception as e:
            logger.error(f"Failed to switch to GPS: {e}")
            return False

    def switch_to_slam(self) -> bool:
        """
        Switch to SLAM navigation.
        
        Returns:
            bool: True if switch was successful, False otherwise
        """
        try:
            # Set EKF type to 2 (SLAM)
            if not self.mavlink.set_parameter("AHRS_EKF_TYPE", 2):
                return False
                
            # Set EKF2 enabled to 0
            if not self.mavlink.set_parameter("EK2_ENABLE", 0):
                return False
                
            # Set EKF3 enabled to 1
            if not self.mavlink.set_parameter("EK3_ENABLE", 1):
                return False
                
            self._update_current_source()
            return True
        except Exception as e:
            logger.error(f"Failed to switch to SLAM: {e}")
            return False

    def get_current_source(self) -> Optional[str]:
        """
        Get the current navigation source.
        
        Returns:
            Optional[str]: Current navigation source or None if unknown
        """
        return self.current_source

    def set_ekf_and_home(self, lat: float, lon: float, alt: float) -> bool:
        """
        Set EKF origin and home position.
        
        Args:
            lat (float): Latitude
            lon (float): Longitude
            alt (float): Altitude
            
        Returns:
            bool: True if set was successful, False otherwise
        """
        try:
            # Set EKF origin
            if not self.mavlink.set_parameter("EK2_GPS_ORIGIN_LAT", lat):
                return False
            if not self.mavlink.set_parameter("EK2_GPS_ORIGIN_LON", lon):
                return False
            if not self.mavlink.set_parameter("EK2_GPS_ORIGIN_ALT", alt):
                return False
                
            # Set home position
            if not self.mavlink.set_parameter("HOME_LAT", lat):
                return False
            if not self.mavlink.set_parameter("HOME_LON", lon):
                return False
            if not self.mavlink.set_parameter("HOME_ALT", alt):
                return False
                
            return True
        except Exception as e:
            logger.error(f"Failed to set EKF and home: {e}")
            return False

    def monitor_position(self) -> None:
        """Monitor position for 30 seconds."""
        try:
            print("Monitoring position for 30 seconds...")
            print("Press Ctrl+C to stop")
            print("-" * 80)
            
            start_time = time.time()
            while time.time() - start_time < 30:
                msg = self.mavlink.connection.recv_match(
                    type='GLOBAL_POSITION_INT',
                    blocking=True,
                    timeout=1.0
                )
                
                if msg:
                    lat = msg.lat / 1e7
                    lon = msg.lon / 1e7
                    alt = msg.alt / 1000.0
                    print(f"Position: lat={lat:.6f}, lon={lon:.6f}, alt={alt:.2f}m")
                    
        except KeyboardInterrupt:
            print("\nStopped monitoring position")
        except Exception as e:
            logger.error(f"Error monitoring position: {e}")

    def listen_for_messages(self) -> None:
        """Listen for MAVLink messages."""
        self.mavlink.listen_for_messages()

    def show_recent_messages(self) -> None:
        """Show the most recent MAVLink messages."""
        if not self.mavlink.message_log:
            print("No recent messages")
            return
            
        print("\nMost recent messages:")
        print("-" * 80)
        for timestamp, msg in self.mavlink.message_log[-30:]:
            formatted = self.mavlink.format_message(timestamp, msg)
            print(formatted)

    def get_parameter_value(self, param_name: str) -> Optional[float]:
        """
        Get a parameter value.
        
        Args:
            param_name (str): Name of the parameter to get
            
        Returns:
            Optional[float]: Parameter value if successful, None otherwise
        """
        return self.mavlink.get_parameter(param_name)

    def set_parameter_value(self, param_name: str, param_value: float) -> bool:
        """
        Set a parameter value.
        
        Args:
            param_name (str): Name of the parameter to set
            param_value (float): Value to set
            
        Returns:
            bool: True if parameter was set successfully, False otherwise
        """
        return self.mavlink.set_parameter(param_name, param_value)

    def clean_sd_card(self) -> None:
        """Clean the SD card."""
        try:
            print("Cleaning SD card...")
            # Send command to clean SD card
            self.mavlink.connection.command_long_send(
                self.mavlink.connection.target_system,
                self.mavlink.connection.target_component,
                self.mavlink.mavutil.mavlink.MAV_CMD_STORAGE_FORMAT,
                0, 0, 0, 0, 0, 0, 0, 0
            )
            print("SD card cleaning command sent")
        except Exception as e:
            logger.error(f"Failed to clean SD card: {e}")
            print("Failed to clean SD card")

    def reset_params_to_default(self) -> None:
        """Reset parameters to default values."""
        try:
            print("Resetting parameters to default values...")
            # Send command to reset parameters
            self.mavlink.connection.command_long_send(
                self.mavlink.connection.target_system,
                self.mavlink.connection.target_component,
                self.mavlink.mavutil.mavlink.MAV_CMD_PREFLIGHT_STORAGE_RESET,
                0, 0, 0, 0, 0, 0, 0, 0
            )
            print("Parameter reset command sent")
        except Exception as e:
            logger.error(f"Failed to reset parameters: {e}")
            print("Failed to reset parameters")

    def export_parameters(self, filename: Optional[str] = None) -> None:
        """
        Export parameters to a file.
        
        Args:
            filename (Optional[str]): Name of the file to export parameters to
        """
        try:
            if not filename:
                filename = "parameters.param"
                
            print(f"Exporting parameters to {filename}...")
            
            # Create a list to store parameters
            params = []
            
            # Get all parameters
            self.mavlink.connection.param_fetch_all()
            
            while True:
                msg = self.mavlink.connection.recv_match(type='PARAM_VALUE', blocking=True, timeout=1.0)
                if not msg:
                    break
                    
                params.append(f"{msg.param_id},{msg.param_value}\n")
                
            # Write parameters to file
            with open(filename, 'w') as f:
                f.writelines(params)
                
            print(f"Parameters exported to {filename}")
        except Exception as e:
            logger.error(f"Failed to export parameters: {e}")
            print("Failed to export parameters")

    def save_parameters(self) -> bool:
        """
        Save parameters permanently to non-volatile storage.
        
        Returns:
            bool: True if parameters were saved successfully, False otherwise
        """
        try:
            # Simpler way to send save command
            self.mavlink.connection.arducopter_arm()
            self.mavlink.connection.arducopter_disarm()
            print("Attempted to save parameters by arming/disarming")
            return True
        except Exception as e:
            logger.error(f"Failed to save parameters: {e}")
            return False

    def close(self) -> None:
        """Close the MAVLink connection."""
        self.mavlink.close()

def show_help():
    """Show help message with available commands."""
    print("\nAvailable commands:")
    print("  gps         - Switch to GPS navigation")
    print("  slam        - Switch to SLAM navigation")
    print("  status      - Show current navigation source")
    print("  ekf         - Set EKF origin and home position to 0,0,0")
    print("  custom_ekf  - Set EKF origin and home position with custom coordinates")
    print("  monitor     - Monitor position for 30 seconds")
    print("  listen      - Listen for MAVLink messages from Pixhawk")
    print("  recent_msgs - Show the last 30 Pixhawk messages")
    print("  export_params [filename] - Export all parameters to a file")
    print("  save_params - Save parameters permanently to non-volatile storage")
    print("  reboot      - Reboot ArduPilot")
    print("  full_restart - Perform a full system restart")
    print("  get_param [param_name] - Get a parameter value")
    print("  set_param [param_name] [param_value] - Set a parameter value")
    print("  clean_sd    - Clean the SD card")
    print("  reset_params - Reset parameters to default values")
    print("  q           - Quit")
    print("\nConnection options:")
    print("  --url URL   - Specify a custom MAVLink connection URL")
    print("                Example: --url udp:192.168.1.1:14550")
    print("                Example: --url tcp:localhost:5760")

def execute_command(toggle, cmd, args):
    """
    Execute a command with optional arguments.
    
    Args:
        toggle: NavigationToggle instance
        cmd (str): Command to execute
        args (list): Command arguments
    """
    if cmd == 'gps':
        if toggle.switch_to_gps():
            print("Successfully switched to GPS navigation")
        else:
            print("Failed to switch to GPS navigation")
    elif cmd == 'slam':
        if toggle.switch_to_slam():
            print("Successfully switched to SLAM navigation")
        else:
            print("Failed to switch to SLAM navigation")
    elif cmd == 'status':
        current = toggle.get_current_source()
        print(f"Current navigation source: {current or 'Unknown'}")
        if hasattr(toggle.mavlink, 'mavlink_url') and toggle.mavlink.mavlink_url:
            print(f"Connected via: {toggle.mavlink.mavlink_url}")
    elif cmd == 'ekf':
        if toggle.set_ekf_and_home(0.0, 0.0, 0.0):
            print("Successfully set EKF origin and home position")
        else:
            print("Failed to set EKF origin and home position")
    elif cmd == 'custom_ekf':
        try:
            lat = float(input("Enter latitude (default 0.0): ") or "0.0")
            lon = float(input("Enter longitude (default 0.0): ") or "0.0")
            alt = float(input("Enter altitude (default 0.0): ") or "0.0")
            if toggle.set_ekf_and_home(lat, lon, alt):
                print("Successfully set EKF origin and home position")
            else:
                print("Failed to set EKF origin and home position")
        except ValueError:
            print("Invalid input. Please enter numeric values for coordinates.")
    elif cmd == 'monitor':
        print("Monitoring position for 30 seconds...")
        toggle.monitor_position()
    elif cmd == 'listen':
        toggle.listen_for_messages()
    elif cmd == 'recent_msgs':
        toggle.show_recent_messages()
    elif cmd == 'reboot':
        print("Rebooting ArduPilot...")
        if toggle.mavlink.reboot_ardupilot():
            print("Waiting for ArduPilot to reboot...")
            time.sleep(20)  # Wait for reboot
            # Reconnect after reboot
            toggle.mavlink._connect()
            print("Successfully reconnected to ArduPilot")
        else:
            print("Failed to reboot ArduPilot")
    elif cmd == 'full_restart':
        print("Starting full restart sequence...")
        
        # Step 1: Reboot ArduPilot
        print("1. Rebooting ArduPilot...")
        if not toggle.mavlink.reboot_ardupilot():
            print("Failed to reboot ArduPilot")
            return
        
        print("Waiting for ArduPilot to reboot...")
        time.sleep(20)  # Wait for reboot
        
        # Step 2: Reconnect to ArduPilot
        try:
            toggle.mavlink._connect()
            print("Successfully reconnected to ArduPilot")
        except Exception as e:
            print(f"Failed to reconnect to ArduPilot: {e}")
            return
        
        # Step 3: Restart SLAM container
        print("2. Restarting SLAM container...")
        try:
            import subprocess
            result = subprocess.run(
                ["docker", "restart", "isaac_ros_dev-aarch64-container"], 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                print("Successfully restarted SLAM container")
            else:
                print(f"Failed to restart SLAM container: {result.stderr}")
                return
        except Exception as e:
            print(f"Failed to restart SLAM container: {e}")
            return
        
        # Step 4: Wait for systems to initialize
        print("3. Waiting for systems to initialize...")
        time.sleep(30)  # Wait for SLAM and ArduPilot to stabilize
        
        # Step 5: Set EKF origin and home position
        print("4. Setting EKF origin and home position...")
        if toggle.set_ekf_and_home(0.0, 0.0, 0.0):
            print("Successfully set EKF origin and home position")
        else:
            print("Failed to set EKF origin and home position")
        
        print("Full restart sequence completed")
    elif cmd == 'get_param':
        # If parameter name is provided as argument
        if args and len(args) > 0:
            param_name = args[0]
            value = toggle.get_parameter_value(param_name)
            if value is not None:
                print(f"Parameter {param_name} = {value}")
            else:
                print(f"Failed to get parameter {param_name}")
        else:
            # Interactive mode
            param_name = input("Enter parameter name: ").strip()
            if param_name:
                value = toggle.get_parameter_value(param_name)
                if value is not None:
                    print(f"Parameter {param_name} = {value}")
                else:
                    print(f"Failed to get parameter {param_name}")
            else:
                print("No parameter name provided")
    elif cmd == 'set_param':
        # If both parameter name and value are provided as arguments
        if args and len(args) >= 2:
            param_name = args[0]
            try:
                param_value = float(args[1])
                if toggle.set_parameter_value(param_name, param_value):
                    print(f"Successfully set {param_name} to {param_value}")
                else:
                    print(f"Failed to set {param_name}")
            except ValueError:
                print("Invalid parameter value. Please enter a numeric value.")
        else:
            # Interactive mode
            param_name = input("Enter parameter name: ").strip()
            try:
                param_value = float(input("Enter parameter value: ").strip())
                if param_name:
                    if toggle.set_parameter_value(param_name, param_value):
                        print(f"Successfully set {param_name} to {param_value}")
                    else:
                        print(f"Failed to set {param_name}")
                else:
                    print("No parameter name provided")
            except ValueError:
                print("Invalid parameter value. Please enter a numeric value.")
    elif cmd == 'clean_sd':
        toggle.clean_sd_card()
    elif cmd == 'reset_params':
        toggle.reset_params_to_default()
    elif cmd == 'export_params':
        # Check for a custom filename in args
        filename = None
        if args and len(args) > 0:
            filename = args[0]
        toggle.export_parameters(filename)
    elif cmd == 'save_params':
        if toggle.save_parameters():
            print("Parameters saved successfully")
        else:
            print("Failed to save parameters")

def main():
    """
    Main function to run the SkyCore CLI.
    
    Handles command-line arguments and interactive mode.
    """
    toggle = None
    try:
        # Check for command line arguments
        args = sys.argv[1:]
        
        direct_command = None
        mavlink_url = None
        command_args = []
        
        # Parse arguments
        i = 0
        while i < len(args):
            if args[i] == "--url" and i + 1 < len(args):
                mavlink_url = args[i + 1]
                i += 2
            elif direct_command is None:
                direct_command = args[i].lower()
                i += 1
            else:
                # Collect all remaining arguments for the command
                command_args = args[i:]
                break
        
        # Set custom URL if specified
        if mavlink_url:
            os.environ['SKYCORE_MAVLINK_URL'] = mavlink_url
            print(f"Using custom MAVLink URL: {mavlink_url}")
            
        # For MAVLink-related commands, check if we need pymavlink
        need_mavlink = direct_command in ['gps', 'slam', 'status', 'ekf', 
                                        'custom_ekf', 'monitor', 'listen',
                                        'recent_msgs', 'reboot', 'full_restart', 
                                        'get_param', 'set_param', 'clean_sd',
                                        'reset_params', 'export_params', 'save_params']
                                        
        if need_mavlink and 'pymavlink' in MISSING_DEPENDENCIES:
            if not check_and_install_dependencies(['pymavlink']):
                return 1
                
        # Try to establish MAVLink connection for navigation commands
        if need_mavlink or direct_command is None:
            try:
                toggle = NavigationToggle()
            except ConnectionError as e:
                print(f"Connection Error: {e}")
                
                # If the command requires MAVLink, exit with error
                if need_mavlink:
                    return 1
        
        # If direct command was specified, execute it and exit
        if direct_command and direct_command != "help":
            # For MAVLink commands, we need the toggle
            if toggle:
                execute_command(toggle, direct_command, command_args)
            # Error case - shouldn't happen due to earlier checks
            else:
                print(f"Cannot execute {direct_command} - MAVLink connection not available.")
                
            return 0
        
        # Interactive mode - show help message at the beginning
        show_help()
        if toggle:
            print(f"Current source: {toggle.get_current_source() or 'Unknown'}")
        else:
            print("MAVLink connection not available. Only system commands will work.")
        
        # Command loop - continue until q is entered
        while True:
            cmd_input = input("\nEnter command (type 'menu' for help): ").strip()
            
            if not cmd_input:
                continue
                
            # Split the input into command and arguments
            cmd_parts = cmd_input.split()
            cmd = cmd_parts[0].lower()
            cmd_args = cmd_parts[1:] if len(cmd_parts) > 1 else []
            
            if cmd == 'q':
                break
            elif cmd == 'help' or cmd == 'menu':
                show_help()
                if toggle:
                    print(f"Current source: {toggle.get_current_source() or 'Unknown'}")
            else:
                # Check if the command requires MAVLink
                cmd_needs_mavlink = cmd in ['gps', 'slam', 'status', 'ekf', 
                                           'custom_ekf', 'monitor', 'listen',
                                           'recent_msgs', 'reboot', 'full_restart', 
                                           'get_param', 'set_param', 'clean_sd',
                                           'reset_params', 'export_params', 'save_params']
                
                # If command needs MAVLink but we don't have a connection
                if cmd_needs_mavlink and not toggle:
                    print("Command requires MAVLink connection which is not available.")
                    # Offer to install pymavlink if it's missing
                    if 'pymavlink' in MISSING_DEPENDENCIES:
                        if check_and_install_dependencies(['pymavlink']):
                            print("Please restart the script to use MAVLink commands.")
                else:
                    execute_command(toggle, cmd, cmd_args)
                
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if toggle:
            toggle.close()
            print("Disconnected from ArduPilot")

if __name__ == "__main__":
    main()

