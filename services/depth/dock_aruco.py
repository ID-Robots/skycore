#!/usr/bin/env python3

# Standard library imports
import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
import traceback
from collections import deque

# Third-party imports
import cv2
import cv2.aruco as aruco
import gi
import numpy as np
import pyrealsense2 as rs
from pymavlink import mavutil

# GStreamer setup
gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

# Configure logging - reduced logging level
logging.basicConfig(
    level=logging.INFO,  # Changed from WARNING to INFO
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# --- Constants ---
# Camera and detection constants
TARGET_DISTANCE_M = 0.20
MARKER_SIZE_CM = 5.2

# Mavlink control constants
BACKWARD_THROTTLE_VALUE = -300
LEFT_STEER_VALUE = -500
RIGHT_STEER_VALUE = 500  # Added right steering value
NEUTRAL_THROTTLE_VALUE = 0
NEUTRAL_STEER_VALUE = 0

# Steering control constants
STEERING_GAIN = -0.5
MIN_STEERING_VALUE = -1000
MAX_STEERING_VALUE = 1000
MIN_STEERING_THRESHOLD = 200  # Minimum steering threshold

# Control loop constants
ROTATION_PWM_OFFSET = 200
SEARCH_STEP_DURATION_S = 1.5
SEARCH_PAUSE_DURATION_S = 1.0
CONTROL_LOOP_RATE_HZ = 10

# --- Stream Factory Class ---
class StreamFactory(GstRtspServer.RTSPMediaFactory):
    """Handles frame processing and streaming for RTSP."""
    def __init__(self, appsink_src='source', **properties):
        super(StreamFactory, self).__init__(**properties)
        self.frame_lock = threading.Lock()
        self.last_frame = None
        self.appsink_src = appsink_src
        self.color_buffer = deque(maxlen=10)
    
    def configure(self, fps, width, height):
        """Configure the stream with specific parameters."""
        self.number_frames = 0
        self.fps = fps
        self.duration = 1 / self.fps * Gst.SECOND
        self.width = width
        self.height = height
        
        # Pipeline with lower bitrate for better compatibility
        self.launch_string = (
            f'appsrc name={self.appsink_src} is-live=true do_timestamp=true block=false format=GST_FORMAT_TIME ' 
            f'caps=video/x-raw,format=RGBA,width={width},height={height},framerate={fps}/1 ' 
            "! videoconvert ! video/x-raw,format=I420 "
            "! x264enc tune=zerolatency bitrate=500 speed-preset=superfast key-int-max=15 "
            '! rtph264pay config-interval=1 name=pay0 pt=96'
        )
        
        self.last_frame = np.zeros((self.height, self.width, 4), dtype=np.uint8).tobytes()
            
    def add_to_buffer(self, frame):
        """Add a frame to the buffer with thread safety."""
        with self.frame_lock:
            self.color_buffer.append(frame)
            
    def get_from_buffer(self):
        """Get a frame from the buffer with thread safety."""
        with self.frame_lock:
            if len(self.color_buffer) == 0:
                raise IndexError("Buffer empty")
            return self.color_buffer.pop()

    def on_need_data(self, src, length):
        """Callback for when GStreamer needs data to send."""
        try:
            frame = self.get_from_buffer()
            data = frame.tobytes()
            self.last_frame = data
        except Exception as e:
            # Using last frame as fallback
            data = self.last_frame
            
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        
        buf.duration = self.duration
        timestamp = self.number_frames * self.duration
        buf.pts = buf.dts = int(timestamp)
        buf.offset = timestamp
        self.number_frames += 1
        
        retval = src.emit('push-buffer', buf)
        if retval != Gst.FlowReturn.OK:
            logging.warning(f"Error pushing buffer to GStreamer: {retval}")
        
        return retval

    def do_create_element(self, url):
        """Create the GStreamer pipeline element."""
        return Gst.parse_launch(self.launch_string)

    def do_configure(self, rtsp_media):
        """Configure the RTSP media."""
        self.number_frames = 0
        consuming_appsrc = rtsp_media.get_element().get_child_by_name(self.appsink_src)
        consuming_appsrc.connect('need-data', self.on_need_data)


class GstServer(GstRtspServer.RTSPServer):
    """RTSP server for streaming video feeds."""
    def __init__(self, rtsp_port='8554', **properties):
        super(GstServer, self).__init__(**properties)
        self.rtsp_port = rtsp_port
        self.set_service(self.rtsp_port)
        
        # Make the server listen on all interfaces, not just localhost
        self.get_mount_points().remove_factory("/")  # Remove default factory if any
        
        self.attach(None)
        logging.info(f"RTSP server created on port {rtsp_port}")
        self.colorized_video = None
        self.normal_video = None
            
    def configure_depth(self, fps, width, height, mount_point):
        """Configure a depth video stream."""
        self.colorized_video = StreamFactory('depth_colorized')
        self.colorized_video.configure(fps, width, height)
        self.get_mount_points().add_factory(mount_point, self.colorized_video)            
        self.colorized_video.set_shared(True)
        return self.colorized_video
        
    def configure_video(self, fps, width, height, mount_point):
        """Configure a normal video stream."""
        self.normal_video = StreamFactory('normal_video')
        self.normal_video.configure(fps, width, height)
        self.get_mount_points().add_factory(mount_point, self.normal_video)            
        self.normal_video.set_shared(True)
        return self.normal_video

# --- Main BackCameraStreamer Class ---
class BackCameraStreamer:
    """Main class that handles camera streaming, ArUco detection, and vehicle control."""
    
    # Product IDs for D400 series
    DS5_PRODUCT_IDS = [
        "0AD1", "0AD2", "0AD3", "0AD4", "0AD5", "0AF6", "0AFE", 
        "0AFF", "0B00", "0B01", "0B03", "0B07", "0B3A", "0B5C"
    ]
    
    # Control states
    STATE_SEARCHING = 0
    STATE_APPROACHING = 1
    STATE_DONE = 2
    
    def __init__(self, serial_number="021222073747"):
        """Initialize the BackCameraStreamer with configuration parameters."""
        # Camera configuration
        self.serial_number = serial_number
        self.device = None
        self.device_id = None
        self.pipe = None
        self.profile = None
        self.depth_width = 640
        self.depth_height = 480
        self.color_width = 640
        self.color_height = 480
        self.fps = 15
        self.depth_scale = 0
        
        # Preset configuration
        self.use_preset = False
        self.preset_file = "./cfg/d4xx-default.json"
        
        # RTSP Configuration
        self.rtsp_port = "8554"
        self.video_mount_point = "/back/video"
        self.depth_mount_point = "/back/depth"
        self.enable_color = True
        self.enable_depth = True
        
        # RTSP server objects
        self.gst_server = None
        self.video_stream = None
        self.depth_stream = None
        self.glib_loop = None
        self.video_thread = None
        
        # Depth processing
        self.colorizer = rs.colorizer()
        self.colorizer.set_option(rs.option.color_scheme, 7)  # White close, black far
        self.colorizer.set_option(rs.option.min_distance, 1.0)
        self.colorizer.set_option(rs.option.max_distance, 2.5)
        
        # Threads
        self.time_to_exit = False
        self.camera_thread = None
        
        # Filters for depth processing
        self.filters = [
            [False, "Decimation Filter",    rs.decimation_filter()],
            [True,  "Threshold Filter",     rs.threshold_filter()],
            [True,  "Depth to Disparity",   rs.disparity_transform(True)],
            [True,  "Spatial Filter",       rs.spatial_filter()],
            [True,  "Temporal Filter",      rs.temporal_filter()],
            [False, "Hole Filling Filter",  rs.hole_filling_filter()],
            [True,  "Disparity to Depth",   rs.disparity_transform(False)]
        ]
        
        # Configure threshold filter
        self.filters[1][2].set_option(rs.option.min_distance, 0.1)
        self.filters[1][2].set_option(rs.option.max_distance, 8.0)
        
        # Build list of filters to apply
        self.filter_to_apply = [f[2] for f in self.filters if f[0]]
        
        # ArUco configuration
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_250)
        self.aruco_params = aruco.DetectorParameters()
        self.target_marker_id = 70
        self.marker_size_cm = 5.2
        self.marker_size_m = self.marker_size_cm / 100.0
        
        # Camera intrinsics (will be populated during connect)
        self.camera_matrix = None
        self.dist_coeffs = None
        
        # MAVLink Attributes
        self.connection = None
        self.mavlink_connect_str = "/dev/ttyUSB0"
        self.mavlink_baudrate = 230400

        # Control State
        self.control_lock = threading.Lock()
        self.target_marker_detected = False
        self.estimated_distance_m = None
        self.estimated_horizontal_error = None
        # Track which side the marker was last seen on
        self.last_marker_side = None  # 'left', 'right', or None
        self.control_thread = None
        self.last_command_time = 0

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.exit_handler)
        signal.signal(signal.SIGTERM, self.exit_handler)
        
        # Parse command line arguments
        self.parse_args()
        
    def parse_args(self):
        """Parse command line arguments."""
        parser = argparse.ArgumentParser(description="Back Camera RTSP Streamer with ArUco Docking Control")
        parser.add_argument('--serial', type=str, default="021222073747", 
                          help="Serial number of the back camera (default: 021222073747)")
        parser.add_argument('--rtsp-port', type=str, default="8554", 
                          help="RTSP port")
        parser.add_argument('--connect', type=str, default=self.mavlink_connect_str, 
                          help="MAVLink connection string (e.g., /dev/ttyUSB0, udpout:127.0.0.1:14777)")
        parser.add_argument('--baudrate', type=int, default=self.mavlink_baudrate, 
                          help="MAVLink baud rate (for serial connections)")
        parser.add_argument('--depth-enable', action=argparse.BooleanOptionalAction, default=True, 
                          help="Enable depth stream")
        parser.add_argument('--color-enable', action=argparse.BooleanOptionalAction, default=True, 
                          help="Enable color stream")
        parser.add_argument('--use-preset', action=argparse.BooleanOptionalAction, default=False, 
                          help="Use preset configuration file")
        parser.add_argument('--preset-file', type=str, default="./cfg/d4xx-default.json", 
                          help="Preset configuration file path")
        
        args = parser.parse_args()
        self.serial_number = args.serial
        self.rtsp_port = args.rtsp_port
        self.mavlink_connect_str = args.connect
        self.mavlink_baudrate = args.baudrate
        self.enable_depth = args.depth_enable
        self.enable_color = args.color_enable
        self.use_preset = args.use_preset
        self.preset_file = args.preset_file
        
        logging.info(f"Configured to use camera with serial: {self.serial_number}")
        logging.info(f"MAVLink Connection: {self.mavlink_connect_str}, Baudrate: {self.mavlink_baudrate}")
    
    def find_device(self):
        """Find a RealSense device with the specified serial number or any compatible device."""
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                ctx = rs.context()
                devices = ctx.query_devices()
                logging.info(f"Searching for device among {len(devices)} found...")
                
                # Log all available devices
                for i, dev in enumerate(devices):
                    try:
                        if dev.supports(rs.camera_info.serial_number) and dev.supports(rs.camera_info.product_id):
                            serial = dev.get_info(rs.camera_info.serial_number)
                            product_id = dev.get_info(rs.camera_info.product_id)
                            name = dev.get_info(rs.camera_info.name) if dev.supports(rs.camera_info.name) else "Unknown"
                            
                            # If specific serial number is requested, check for match
                            if self.serial_number and serial == self.serial_number:
                                if product_id in self.DS5_PRODUCT_IDS:
                                    self.device = dev
                                    self.device_id = serial
                                    logging.info(f"Found device with serial {serial}")
                                    return True
                            # Otherwise, use the first compatible device
                            elif not self.serial_number and product_id in self.DS5_PRODUCT_IDS:
                                self.device = dev
                                self.device_id = serial
                                self.serial_number = serial  # Save for future reference
                                logging.info(f"Using device {i}: Serial={serial}")
                                return True
                    except Exception as e:
                        logging.error(f"Error querying device {i}: {e}")
                
                if self.serial_number:
                    logging.error(f"Could not find device with serial {self.serial_number}")
                else:
                    logging.error("No compatible device found")
                
                retry_count += 1
                time.sleep(2)
                
            except Exception as e:
                logging.error(f"Error finding device: {e}")
                retry_count += 1
                time.sleep(2)
                
        return False
    
    def configure_advanced_settings(self):
        """Apply advanced settings to camera from preset file if enabled."""
        if not self.use_preset or not self.device:
            return False
            
        try:
            if not os.path.isfile(self.preset_file):
                logging.warning(f"Cannot find preset file {self.preset_file}")
                return False
                
            if not self.device.supports(rs.camera_info.product_id):
                logging.warning("Device does not support product_id info")
                return False
                
            advnc_mode = rs.rs400_advanced_mode(self.device)
            if not advnc_mode.is_enabled():
                logging.info("Enabling advanced mode...")
                advnc_mode.toggle_advanced_mode(True)
                # Device will disconnect and reconnect
                time.sleep(5)
                # Need to find the device again
                if not self.find_device():
                    logging.error("Failed to reconnect to device")
                    return False
                advnc_mode = rs.rs400_advanced_mode(self.device)
            
            if not advnc_mode.is_enabled():
                logging.warning("Advanced mode not enabled, skipping preset loading")
                return False
                
            # Load the JSON preset file
            with open(self.preset_file, 'r') as file:
                json_text = file.read().strip()
                
            advnc_mode.load_json(json_text)
            logging.info(f"Applied preset from {self.preset_file}")
            return True
            
        except Exception as e:
            logging.error(f"Error configuring advanced settings: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def connect(self):
        """Connect to the camera and start streaming."""
        try:
            # Create pipeline
            self.pipe = rs.pipeline()
            
            # Configure streams
            config = rs.config()
            if self.device_id:
                config.enable_device(self.device_id)
                
            # Always enable depth stream
            config.enable_stream(
                rs.stream.depth, self.depth_width, self.depth_height, 
                rs.format.z16, self.fps
            )
            
            # Enable color stream if requested
            if self.enable_color:
                config.enable_stream(
                    rs.stream.color, self.color_width, self.color_height, 
                    rs.format.rgba8, self.fps
                )
                
            # Start streaming
            self.profile = self.pipe.start(config)
            
            # Get depth scale
            depth_sensor = self.profile.get_device().first_depth_sensor()
            self.depth_scale = depth_sensor.get_depth_scale()
            logging.info(f"Depth scale is: {self.depth_scale}")
            
            # Get intrinsics if color stream is enabled
            if self.enable_color:
                color_profile = self.profile.get_stream(rs.stream.color).as_video_stream_profile()
                intrinsics = color_profile.get_intrinsics()
                self.camera_matrix = np.array([
                    [intrinsics.fx, 0, intrinsics.ppx],
                    [0, intrinsics.fy, intrinsics.ppy],
                    [0, 0, 1]
                ], dtype=np.float32)
                self.dist_coeffs = np.array(intrinsics.coeffs, dtype=np.float32)
            
            return True
            
        except Exception as e:
            logging.error(f"Error connecting to camera: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def _filter_depth_frame(self, depth_frame):
        """Apply filters to depth frame."""
        filtered_frame = depth_frame
        for f in self.filter_to_apply:
            filtered_frame = f.process(filtered_frame)
        return filtered_frame
    
    def setup_rtsp(self):
        """Initialize RTSP streaming."""
        try:
            # Initialize GStreamer
            Gst.init(None)
            self.gst_server = GstServer(self.rtsp_port)
            
            # Get local IP address for RTSP URL in logs
            local_ip = self.get_local_ip()
            
            # Configure streams based on what's enabled
            if self.enable_color:
                self.video_stream = self.gst_server.configure_video(
                    self.fps, self.color_width, self.color_height, self.video_mount_point
                )
                logging.info(f"RTSP color stream available at: rtsp://{local_ip}:{self.rtsp_port}{self.video_mount_point}")
                
            if self.enable_depth:
                self.depth_stream = self.gst_server.configure_depth(
                    self.fps, self.depth_width, self.depth_height, self.depth_mount_point
                )
                logging.info(f"RTSP depth stream available at: rtsp://{local_ip}:{self.rtsp_port}{self.depth_mount_point}")
                
            # Create and start the GLib main loop
            self.glib_loop = GLib.MainLoop()
            self.video_thread = threading.Thread(target=self.glib_loop.run)
            self.video_thread.daemon = True
            self.video_thread.start()
            
            return True
        except Exception as e:
            logging.error(f"Error setting up RTSP: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def get_local_ip(self):
        """Get local IP address for better URL display in logs."""
        try:
            # This creates a socket that doesn't actually connect
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # This doesn't actually send any packets
            s.connect(('8.8.8.8', 1))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "localhost"
    
    def start_streaming_and_control(self):
        """Start camera processing and control threads."""
        if self.pipe is None:
            logging.error("Cannot start streaming: camera not connected")
            return False
        
        # Start camera thread
        self.time_to_exit = False
        self.camera_thread = threading.Thread(target=self.camera_reader)
        self.camera_thread.daemon = True
        self.camera_thread.start()
        logging.info("Camera streaming started")

        # Check Vehicle State and Set Mode to MANUAL
        if not self.connection:
            logging.error("MAVLink connection not established before state check.")
            return False
        try:
            msg = self.connection.recv_match(type='HEARTBEAT', blocking=True, timeout=5)
            if not msg:
                logging.warning("Did not receive initial HEARTBEAT after MAVLink connect.")
            else:
                is_armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                mode_id = msg.custom_mode
                mode_name = self.connection.mode_mapping().get(mode_id, f"UNKNOWN({mode_id})")

                if not is_armed:
                    logging.error("Vehicle is DISARMED after connect. Please ARM first.")
                else:
                    logging.info(f"Vehicle is ARMED in mode: {mode_name}")

                    target_mode = 'MANUAL'
                    if mode_name != target_mode:
                        logging.info(f"Attempting to set mode to {target_mode}...")
                        mode_id = self.connection.mode_mapping().get(target_mode)
                        if mode_id is not None:
                            self.connection.mav.set_mode_send(
                                self.connection.target_system,
                                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                                mode_id
                            )
                            time.sleep(1)
                            msg_confirm = self.connection.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
                            if msg_confirm:
                                new_mode_id = msg_confirm.custom_mode
                                new_mode_name = self.connection.mode_mapping().get(new_mode_id, f"UNKNOWN({new_mode_id})")
                                logging.info(f"Vehicle now in mode: {new_mode_name}")
                            else:
                                logging.warning("Did not receive confirmation heartbeat after mode change attempt.")
                        else:
                            logging.error(f"Mode {target_mode} is not supported by this firmware.")
        except Exception as mode_ex:
            logging.error(f"Error during initial state check or mode set: {mode_ex}")

        # Start control loop thread
        self.control_thread = threading.Thread(target=self.control_loop)
        self.control_thread.daemon = True
        self.control_thread.start()
        logging.info("Control loop started")

        return True
        
    def camera_reader(self):
        """Main camera processing loop."""
        frames_processed = 0
        last_log_time = time.time()
        
        while not self.time_to_exit:
            try:
                # Wait for new frames
                frames = self.pipe.wait_for_frames()
                if not frames:
                    continue
                frames_processed += 1
                
                # Process depth frame if depth streaming is enabled
                if self.enable_depth and self.depth_stream:
                    depth_frame = frames.get_depth_frame()
                    if depth_frame:
                        filtered_frame = self._filter_depth_frame(depth_frame)
                        depth_colormap = np.asanyarray(self.colorizer.colorize(filtered_frame).get_data())
                        colorized_frame = cv2.cvtColor(depth_colormap, cv2.COLOR_BGR2RGBA)
                        self.depth_stream.add_to_buffer(colorized_frame)
                
                # Process color frame if color streaming is enabled
                if self.enable_color and self.video_stream:
                    color_frame = frames.get_color_frame()
                    if color_frame:
                        color_image_rgba = np.asanyarray(color_frame.get_data())
                        gray_image = cv2.cvtColor(color_image_rgba, cv2.COLOR_RGBA2GRAY)
                        
                        # Detect markers
                        corners, ids, rejectedImgPoints = aruco.detectMarkers(
                            gray_image, self.aruco_dict, parameters=self.aruco_params
                        )
                        
                        # Process detected markers
                        self._process_detected_markers(color_image_rgba, corners, ids)
                        
                        # Add the potentially modified RGBA frame to the RTSP buffer
                        self.video_stream.add_to_buffer(color_image_rgba)
                
            except rs.error as e:
                self.log("WARNING", f"Realsense error: {e}")
                time.sleep(0.01)
            except Exception as e:
                self.log("ERROR", f"Error while reading camera: {e}")
                logging.error(traceback.format_exc())
                # Reset detection state on error
                with self.control_lock:
                    self.target_marker_detected = False
                    self.estimated_distance_m = None
                    self.estimated_horizontal_error = None
                time.sleep(0.1)
    
    def _process_detected_markers(self, color_image_rgba, corners, ids):
        """Process detected ArUco markers in the image."""
        target_found = False
        
        if ids is not None:
            for i, marker_id in enumerate(ids):
                marker_corners = corners[i].reshape((4, 2))
                pts = np.array(marker_corners, np.int32).reshape((-1, 1, 2))
                
                if marker_id == self.target_marker_id:
                    # Draw green rectangle for the target marker
                    cv2.polylines(color_image_rgba, [pts], True, (0, 255, 0, 255), 2) # Green
                    target_found = True
                    
                    # Estimate Pose if intrinsics are available
                    if self.camera_matrix is not None and self.dist_coeffs is not None:
                        rvec, tvec, _ = aruco.estimatePoseSingleMarkers(
                            corners[i], self.marker_size_m, self.camera_matrix, self.dist_coeffs
                        )
                        # Draw axis
                        cv2.drawFrameAxes(color_image_rgba, self.camera_matrix, self.dist_coeffs, rvec, tvec, self.marker_size_m * 0.5)
                        # Log distance (tvec[0][0][2] is the Z distance)
                        distance_m = tvec[0][0][2]
                        # Update shared state
                        with self.control_lock:
                            self.target_marker_detected = True
                            self.estimated_distance_m = distance_m
                            # Calculate horizontal error
                            cx = np.mean(corners[i][0][:, 0]) # Avg X coordinate of corners
                            self.estimated_horizontal_error = (cx - (self.color_width / 2)) / (self.color_width / 2)
                            
                            # Update which side the marker is on
                            if self.estimated_horizontal_error < 0:
                                self.last_marker_side = 'left'
                            else:
                                self.last_marker_side = 'right'
                        break
                else:
                    # Draw blue rectangle for other detected markers
                    cv2.polylines(color_image_rgba, [pts], True, (255, 0, 0, 255), 1) # Blue
        
        # Update detection state if target wasn't found
        if not target_found:
            with self.control_lock:
                self.target_marker_detected = False
                self.estimated_distance_m = None
                self.estimated_horizontal_error = None
                # Note: we do NOT reset last_marker_side here, as we want to remember where it was
    
    def stop(self):
        """Stop all processing and clean up resources."""
        self.time_to_exit = True
        logging.info("Stopping camera and RTSP server...")
        
        # Stop camera processing
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.join(timeout=2)
        
        # Stop pipeline
        if self.pipe:
            try:
                self.pipe.stop()
                logging.info("Camera pipeline stopped")
            except Exception as e:
                logging.error(f"Error stopping pipeline: {e}")
        
        # Stop RTSP server
        if self.glib_loop and self.glib_loop.is_running():
            try:
                self.glib_loop.quit()
                logging.info("RTSP server stopped")
            except Exception as e:
                logging.error(f"Error stopping GLib loop: {e}")
        
        if self.video_thread and self.video_thread.is_alive():
            self.video_thread.join(timeout=2)
        
        # Stop MAVLink connection and release override
        if self.connection:
            try:
                # Send final stop command using manual control
                self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                time.sleep(0.2)
            except Exception as final_e:
                logging.warning(f"Error sending final stop command: {final_e}")
            finally:
                logging.info("Closing MAVLink connection.")
                self.connection.close()
    
    def exit_handler(self, sig, frame):
        """Handle exit signals gracefully."""
        logging.info(f"Caught signal {sig}, shutting down...")
        self.stop()
        sys.exit(0)
                
    def run(self):
        """Main function to start the back camera streamer."""
        self.log("INFO", "Starting Back Camera RTSP Streamer with ArUco Detection", self.STATE_SEARCHING)
        
        # Find device
        if not self.find_device():
            self.log("ERROR", "Failed to find a compatible RealSense device. Exiting.", self.STATE_SEARCHING)
            return False
        
        # Configure advanced settings if enabled
        if self.use_preset:
            if self.configure_advanced_settings():
                self.log("INFO", "Advanced settings applied", self.STATE_SEARCHING)
        
        # Connect to MAVLink FIRST
        self.log("INFO", "Connecting to MAVLink...", self.STATE_SEARCHING)
        try:
            extra_kwargs = {}
            if 'udp' in self.mavlink_connect_str or 'tcp' in self.mavlink_connect_str:
                extra_kwargs = {'source_system': 255}
            elif 'tty' in self.mavlink_connect_str or 'dev' in self.mavlink_connect_str:
                extra_kwargs = {'source_system': 255, 'baud': self.mavlink_baudrate}
            self.connection = mavutil.mavlink_connection(self.mavlink_connect_str, **extra_kwargs)
            self.connection.wait_heartbeat(timeout=10)
            if self.connection.target_system == 0:
                raise ConnectionError("Heartbeat not received. Check MAVLink connection & baud rate.")
            self.log("INFO", f"MAVLink connected to system {self.connection.target_system}", self.STATE_SEARCHING)
        except Exception as mav_ex:
            self.log("ERROR", f"Failed to establish MAVLink connection: {mav_ex}", self.STATE_SEARCHING)
            return False
        
        # Connect to camera
        if not self.connect():
            self.log("ERROR", "Failed to connect to camera. Exiting.", self.STATE_SEARCHING)
            if self.connection: self.connection.close()
            return False
        
        # Setup RTSP streaming
        if not self.setup_rtsp():
            self.log("ERROR", "Failed to setup RTSP streaming. Exiting.", self.STATE_SEARCHING)
            if self.pipe: self.pipe.stop()
            if self.connection: self.connection.close()
            return False
        
        # Start streaming and control threads
        if not self.start_streaming_and_control():
            self.log("ERROR", "Failed to start streaming. Exiting.", self.STATE_SEARCHING)
            self.pipe.stop()
            if self.connection: self.connection.close()
            return False
        
        self.log("INFO", "Back camera streaming and control successfully started", self.STATE_SEARCHING)
        return True

    def send_manual_control_command(self, throttle_z, steering_y):
        """Sends a MANUAL_CONTROL command (using y for steering, z for throttle)."""
        if not self.connection:
            logging.warning("Cannot send manual control command, MAVLink not connected.")
            return

        try:
            self.connection.mav.manual_control_send(
                self.connection.target_system,
                0,                  # x: pitch (usually ignored)
                int(steering_y),    # y: roll/steering
                int(throttle_z),    # z: throttle
                0,                  # r: yaw (usually ignored if y is steering)
                0                   # buttons bitmask
            )
        except Exception as e:
            logging.error(f"Error sending manual_control command: {e}")

    def log(self, level, message, current_state=None):
        """Custom logging method that includes the current state."""
        state_names = {
            self.STATE_SEARCHING: "SEARCHING",
            self.STATE_APPROACHING: "APPROACHING",
            self.STATE_DONE: "DONE"
        }
        
        # Use provided state or get it from instance
        if current_state is None:
            if hasattr(self, 'current_state'):
                current_state = self.current_state
            else:
                current_state = None
        
        state_str = f"[{state_names.get(current_state, 'UNKNOWN')}] "
        
        if level == "INFO":
            logging.info(f"{state_str}{message}")
        elif level == "WARNING":
            logging.warning(f"{state_str}{message}")
        elif level == "ERROR":
            logging.error(f"{state_str}{message}")
        elif level == "DEBUG":
            logging.debug(f"{state_str}{message}")
        else:
            logging.info(f"{state_str}{message}")

    def control_loop(self):
        """Runs the docking/search control logic using manual_control_send."""
        self.log("INFO", f"Control loop starting. Target: {TARGET_DISTANCE_M:.2f}m", self.STATE_SEARCHING)
        is_moving = False
        self.current_state = self.STATE_SEARCHING  # Store current state as instance variable
        current_state = self.current_state
        last_action_desc = ""
        
        # Add state names for clearer logging
        state_names = {
            self.STATE_SEARCHING: "SEARCHING",
            self.STATE_APPROACHING: "APPROACHING",
            self.STATE_DONE: "DONE"
        }
        
        # Log initial state
        self.log("INFO", "="*50)
        self.log("INFO", f"INITIAL STATE: {state_names[current_state]}")
        self.log("INFO", "="*50)
        
        # Track search iterations
        search_rotations = 0

        while not self.time_to_exit:
            try:
                # Initialize command variables for this iteration
                current_action_desc = ""
                target_steering_value = NEUTRAL_STEER_VALUE 
                throttle_command = NEUTRAL_THROTTLE_VALUE
                steering_command = NEUTRAL_STEER_VALUE

                # Read shared state under lock
                with self.control_lock:
                    target_detected = self.target_marker_detected
                    distance_m = self.estimated_distance_m
                    horizontal_error = self.estimated_horizontal_error
                
                # Log detection info at regular intervals
                if target_detected:
                    self.log("INFO", f"Marker detected: distance={distance_m:.3f}m, horizontal_error={horizontal_error:.3f}")
                
                # State Machine Logic
                if current_state == self.STATE_SEARCHING:
                    prev_state = current_state
                    # Pass search_rotations to _handle_searching_state and get back updated count
                    current_state, is_moving, search_rotations = self._handle_searching_state(
                        target_detected, is_moving, current_state, last_action_desc, search_rotations)
                    
                    # Update instance variable
                    self.current_state = current_state
                    
                    # Log state transition
                    if current_state != prev_state:
                        self.log("INFO", "="*50)
                        self.log("INFO", f"STATE CHANGE: {state_names[prev_state]} -> {state_names[current_state]}")
                        self.log("INFO", "="*50)
                    continue

                elif current_state == self.STATE_APPROACHING:
                    prev_state = current_state
                    current_state, is_moving, current_action_desc = self._handle_approaching_state(
                        target_detected, distance_m, is_moving, current_state, current_action_desc, last_action_desc
                    )
                    
                    # Update instance variable
                    self.current_state = current_state
                    
                    # Log state transitions
                    if current_state != prev_state:
                        self.log("INFO", "="*50)
                        self.log("INFO", f"STATE CHANGE: {state_names[prev_state]} -> {state_names[current_state]}")
                        self.log("INFO", "="*50)
                        # Reset search rotations when changing from approaching to searching
                        if current_state == self.STATE_SEARCHING:
                            search_rotations = 0
                            
                    # Skip sending commands here as they're now sent inside _handle_approaching_state
                    if current_state == self.STATE_APPROACHING:
                        continue

                elif current_state == self.STATE_DONE:
                    current_action_desc = "Docking complete. Maintaining position."
                    if current_action_desc != last_action_desc:
                         self.log("INFO", current_action_desc)
                         last_action_desc = current_action_desc
                    if is_moving:
                         self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                         is_moving = False

                # Send calculated throttle/steering for non-approaching states
                if current_state != self.STATE_APPROACHING:
                    # Log only if the action description has changed
                    if current_action_desc and current_action_desc != last_action_desc:
                        self.log("INFO", current_action_desc)
                        last_action_desc = current_action_desc

                    self.send_manual_control_command(throttle_z=throttle_command, steering_y=steering_command)

                time.sleep(1.0 / CONTROL_LOOP_RATE_HZ)

            except Exception as e:
                self.log("ERROR", f"Error in control_loop: {e}")
                logging.error(traceback.format_exc())
                try:
                    self.log("INFO", "Sending STOP command due to control loop error.")
                    is_moving = False 
                    if self.connection:
                        self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                except Exception as stop_e:
                    self.log("ERROR", f"Failed to send stop command after error: {stop_e}")
                time.sleep(0.5)

        self.log("INFO", "Control loop finished.")
    
    def _handle_searching_state(self, target_detected, is_moving, current_state, last_action_desc, search_rotations=0):
        """Handle the searching state in the control loop."""
        if target_detected:
            # Marker found while searching
            self.log("INFO", "Marker found during search. Switching to Approach.")
            self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
            is_moving = False
            current_state = self.STATE_APPROACHING
            time.sleep(0.1)
            return current_state, is_moving, search_rotations
        else:
            # Target still lost -> Perform Search Rotation Step
            # Increment rotation counter
            search_rotations += 1
            
            # Determine rotation direction based on last known marker position
            steer_value = LEFT_STEER_VALUE  # Default direction (counter-clockwise/left)
            
            with self.control_lock:
                if self.last_marker_side == 'right':
                    steer_value = RIGHT_STEER_VALUE
                    self.log("INFO", f"Search rotation #{search_rotations}: Target was last seen on the right. Rotating right.")
                else:
                    self.log("INFO", f"Search rotation #{search_rotations}: Target was last seen on the left or center. Rotating left.")
            
            start_rotate_time = time.time()
            marker_found_during_rotation = False
            
            self.log("INFO", f"Starting rotation #{search_rotations} for {SEARCH_STEP_DURATION_S:.1f} seconds with steer value {steer_value}")
            
            while time.time() < start_rotate_time + SEARCH_STEP_DURATION_S and not self.time_to_exit:
                self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=steer_value)
                time.sleep(1.0 / CONTROL_LOOP_RATE_HZ)

                # Check if marker found by camera thread mid-rotation
                with self.control_lock:
                    if self.target_marker_detected:
                        self.log("INFO", f"Marker found during rotation #{search_rotations}!")
                        marker_found_during_rotation = True
                        break

            # Always stop rotation after the loop
            self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
            is_moving = False
            self.log("INFO", f"Rotation #{search_rotations} complete, stopping rotation")

            # Pause if marker wasn't found during rotation
            if not marker_found_during_rotation:
                self.log("INFO", f"Marker not found after rotation #{search_rotations}, pausing for {SEARCH_PAUSE_DURATION_S:.1f} seconds before next rotation")
                time.sleep(SEARCH_PAUSE_DURATION_S)
            else:
                time.sleep(0.1)
            
            return current_state, is_moving, search_rotations

    def _handle_approaching_state(self, target_detected, distance_m, is_moving, current_state, 
                                current_action_desc, last_action_desc):
        """Handle the approaching state in the control loop."""
        if not target_detected:
            # Marker lost during approach
            current_action_desc = "Marker lost during approach. Returning to Search."
            self.log("INFO", "Marker lost during approach. Switching to SEARCHING state.")
            if is_moving:
                self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                is_moving = False
            current_state = self.STATE_SEARCHING
            time.sleep(0.1)
        elif distance_m is not None:
            # Marker still detected, continue or finish approach
            if distance_m > TARGET_DISTANCE_M:
                # Get horizontal error for steering adjustment
                with self.control_lock:
                    horizontal_error = self.estimated_horizontal_error
                
                # Calculate steering adjustment based on horizontal error
                steering_command = int(horizontal_error * STEERING_GAIN * MAX_STEERING_VALUE)
                steering_command = max(MIN_STEERING_VALUE, min(MAX_STEERING_VALUE, steering_command))
                
                # Apply minimum steering threshold if value is non-zero
                if 0 < abs(steering_command) < MIN_STEERING_THRESHOLD:
                    steering_command = MIN_STEERING_THRESHOLD if steering_command > 0 else -MIN_STEERING_THRESHOLD
                
                # Continue Backward Approach with steering adjustment
                current_action_desc = f"Approaching (Dist: {distance_m:.3f}m > Target: {TARGET_DISTANCE_M:.2f}m, Steering: {steering_command})"
                if current_action_desc != last_action_desc:
                    self.log("INFO", current_action_desc)
                    last_action_desc = current_action_desc
                # Continue backward movement with steering correction
                is_moving = True
                # Apply the commands
                self.log("DEBUG", f"Sending commands: backward={BACKWARD_THROTTLE_VALUE}, steering={steering_command}")
                self.send_manual_control_command(throttle_z=BACKWARD_THROTTLE_VALUE, steering_y=steering_command)
            else:
                # Target Reached
                current_action_desc = f"Target distance reached (Dist: {distance_m:.3f}m). Stopping."
                self.log("INFO", f"TARGET REACHED! Distance: {distance_m:.3f}m ≤ {TARGET_DISTANCE_M:.2f}m - Switching to DONE state")
                if current_action_desc != last_action_desc:
                    self.log("INFO", current_action_desc)
                    last_action_desc = current_action_desc
                if is_moving:
                    self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                    is_moving = False
                current_state = self.STATE_DONE
        else:
            # Target detected but distance is None
            self.log("WARNING", "Target detected but distance is None. Stopping.")
            if is_moving:
                self.send_manual_control_command(throttle_z=NEUTRAL_THROTTLE_VALUE, steering_y=NEUTRAL_STEER_VALUE)
                is_moving = False
        
        return current_state, is_moving, current_action_desc

# --- Main Execution ---
if __name__ == "__main__":
    print("=" * 80)
    print("Back Camera RTSP Streamer with ArUco Detection")
    print("=" * 80)
    
    streamer = BackCameraStreamer()
    print(f"Default camera serial: {streamer.serial_number}")
    print(f"MAVLink: {streamer.mavlink_connect_str} @ {streamer.mavlink_baudrate} baud")
    print("Using ArUco Dictionary: DICT_4X4_250")
    print(f"Target ArUco marker ID: {streamer.target_marker_id} (Green Rectangle)")
    print(f"Target Distance: {TARGET_DISTANCE_M:.2f} m")
    print(f"Backward Throttle: {BACKWARD_THROTTLE_VALUE} (Manual Control)")
    print(f"Left Rotation: {LEFT_STEER_VALUE}, Right Rotation: {RIGHT_STEER_VALUE} (Manual Control)")
    print("Detecting other ArUco markers (Blue Rectangle)")
    print("Run with --help for more options")
    print("=" * 80)
    
    if streamer.run():
        try:
            logging.info("Server running. Press Ctrl+C to exit.")
            while not streamer.time_to_exit:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received, shutting down...")
        finally:
            streamer.stop()
            logging.info("Back camera streamer stopped")
