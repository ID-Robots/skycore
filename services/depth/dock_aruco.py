#!/usr/bin/env python3

import pyrealsense2 as rs
import numpy as np
import signal
import sys
import time
import threading
import os
import logging
import traceback
from collections import deque
import cv2
import cv2.aruco as aruco  # Import aruco module
import gi
import argparse
import socket
from pymavlink import mavutil # Re-import pymavlink

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

# Set up more verbose logging to debug RTSP issues
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# --- Constants ---
TARGET_DISTANCE_M = 0.30 # Target distance from marker (30 cm)
# --- RC Override Constants ---
BACKWARD_PWM = 1400    # Slower PWM value for backward throttle (closer to 1500 neutral)
STEERING_PWM = 1500    # PWM value for neutral steering (1000-2000)
NEUTRAL_THROTTLE_PWM = 1500 # PWM value for neutral throttle
THROTTLE_CHAN_IDX = 2  # Channel 3 index (0-based)
STEERING_CHAN_IDX = 3  # Channel 4 index (0-based)
NUM_CHANNELS = 8       # Number of RC channels to override

# --- Control Loop Constants ---
CONTROL_LOOP_RATE_HZ = 10  # Target control loop frequency
COMMAND_RESEND_INTERVAL_S = 0.5 # Resend RC override every 0.5 seconds

class StreamFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, appsink_src='source', **properties):
        super(StreamFactory, self).__init__(**properties)
        self.frame_lock = threading.Lock()
        self.last_frame = None
        self.appsink_src = appsink_src
        self.color_buffer = deque(maxlen=10)  # Increased buffer size for more stability
    
    def configure(self, fps, width, height):
        self.number_frames = 0
        self.fps = fps
        self.duration = 1 / self.fps * Gst.SECOND
        self.width = width
        self.height = height
        
        # Simplified pipeline with lower bitrate for better compatibility
        self.launch_string = (
            f'appsrc name={self.appsink_src} is-live=true do_timestamp=true block=false format=GST_FORMAT_TIME ' 
            f'caps=video/x-raw,format=RGBA,width={width},height={height},framerate={fps}/1 ' 
            "! videoconvert ! video/x-raw,format=I420 "
            "! x264enc tune=zerolatency bitrate=500 speed-preset=superfast key-int-max=15 "
            '! rtph264pay config-interval=1 name=pay0 pt=96'
        )
        
        self.last_frame = np.zeros((self.height, self.width, 4), dtype=np.uint8).tobytes()
        logging.info(f"Configured stream with resolution {width}x{height} at {fps} fps")
        
    def add_to_buffer(self, frame):
        with self.frame_lock:
            self.color_buffer.append(frame)
            
    def get_from_buffer(self):
        with self.frame_lock:
            if len(self.color_buffer) == 0:
                raise IndexError("Buffer empty")
            return self.color_buffer.pop()

    def on_need_data(self, src, length):
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
        return Gst.parse_launch(self.launch_string)

    def do_configure(self, rtsp_media):
        self.number_frames = 0
        consuming_appsrc = rtsp_media.get_element().get_child_by_name(self.appsink_src)
        consuming_appsrc.connect('need-data', self.on_need_data)

class GstServer(GstRtspServer.RTSPServer):
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
        self.colorized_video = StreamFactory('depth_colorized')
        self.colorized_video.configure(fps, width, height)
        self.get_mount_points().add_factory(mount_point, self.colorized_video)            
        self.colorized_video.set_shared(True)
        return self.colorized_video
        
    def configure_video(self, fps, width, height, mount_point):
        self.normal_video = StreamFactory('normal_video')
        self.normal_video.configure(fps, width, height)
        self.get_mount_points().add_factory(mount_point, self.normal_video)            
        self.normal_video.set_shared(True)
        return self.normal_video

# ===================== MavlinkController Class (Simplified Integration) ======================
# We can integrate the necessary MAVLink functions directly into BackCameraStreamer
# or define helper functions if preferred, avoiding a separate class for simplicity here.
# ============================================================================================

class BackCameraStreamer:
    # Product IDs for D400 series
    DS5_product_ids = [
        "0AD1", "0AD2", "0AD3", "0AD4", "0AD5", "0AF6", "0AFE", 
        "0AFF", "0B00", "0B01", "0B03", "0B07", "0B3A", "0B5C"
    ]
    
    def __init__(self, serial_number="021222073747"):  # Default to the provided back camera serial
        self.serial_number = serial_number
        self.device = None
        self.device_id = None
        self.pipe = None
        self.profile = None # Store profile for intrinsics
        self.depth_width = 640
        self.depth_height = 480
        self.color_width = 640
        self.color_height = 480
        self.fps = 15
        self.use_preset = False
        self.preset_file = "./cfg/d4xx-default.json"
        
        # RTSP Configuration
        self.rtsp_port = "8554"  # Default port
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
        
        self.colorizer = rs.colorizer()
        self.colorizer.set_option(rs.option.color_scheme, 7)  # White close, black far
        self.colorizer.set_option(rs.option.min_distance, 1.0)
        self.colorizer.set_option(rs.option.max_distance, 2.5)
        
        self.depth_scale = 0
        self.time_to_exit = False
        self.camera_thread = None
        
        # Filters for depth processing
        self.filters = [
            [False, "Decimation Filter",    rs.decimation_filter()],
            [True,  "Threshold Filter",    rs.threshold_filter()],
            [True,  "Depth to Disparity",  rs.disparity_transform(True)],
            [True,  "Spatial Filter",      rs.spatial_filter()],
            [True,  "Temporal Filter",     rs.temporal_filter()],
            [False, "Hole Filling Filter", rs.hole_filling_filter()],
            [True,  "Disparity to Depth",  rs.disparity_transform(False)]
        ]
        
        # Configure threshold filter
        self.filters[1][2].set_option(rs.option.min_distance, 0.1)
        self.filters[1][2].set_option(rs.option.max_distance, 8.0)
        
        # Build list of filters to apply
        self.filter_to_apply = [f[2] for f in self.filters if f[0]]
        
        # ArUco configuration
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_4X4_250) # Changed to 4X4
        self.aruco_params = aruco.DetectorParameters()
        self.target_marker_id = 70
        self.marker_size_cm = 5.2
        self.marker_size_m = self.marker_size_cm / 100.0
        
        # Camera intrinsics (will be populated during connect)
        self.camera_matrix = None
        self.dist_coeffs = None
        
        # MAVLink Attributes
        self.connection = None
        self.mavlink_connect_str = "/dev/ttyUSB0" # Default connection string
        self.mavlink_baudrate = 230400 # Default baudrate

        # Control State
        self.control_lock = threading.Lock() # Lock for accessing shared control variables
        self.target_marker_detected = False
        self.estimated_distance_m = None
        self.control_thread = None
        self.last_command_time = 0

        # RC Command Placeholders
        self.neutral_cmd = None
        self.backward_cmd = None
        self.release_cmd = None
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.exit_handler)
        signal.signal(signal.SIGTERM, self.exit_handler)
        
        # Parse arguments
        self.parse_args()
        
    def parse_args(self):
        parser = argparse.ArgumentParser(description="Back Camera RTSP Streamer with ArUco Docking Control")
        parser.add_argument('--serial', type=str, default="021222073747", 
                          help="Serial number of the back camera (default: 021222073747)")
        parser.add_argument('--rtsp-port', type=str, default="8554", help="RTSP port")
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
        logging.info(f"Using ArUco dictionary: DICT_4X4_250, Target ID: {self.target_marker_id}")
        logging.info(f"MAVLink Connection: {self.mavlink_connect_str}, Baudrate: {self.mavlink_baudrate}")
    
    def find_device(self):
        """Find a RealSense device with the specified serial number or any compatible device"""
        max_retries = 5  # Increased retries
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
                            logging.info(f"Available device {i}: Name={name}, Product ID={product_id}, Serial={serial}")
                            
                            # If specific serial number is requested, check for match
                            if self.serial_number and serial == self.serial_number:
                                if product_id in self.DS5_product_ids:
                                    self.device = dev
                                    self.device_id = serial
                                    logging.info(f"Found device with serial {serial}")
                                    return True
                            # Otherwise, use the first compatible device
                            elif not self.serial_number and product_id in self.DS5_product_ids:
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
                logging.info(f"Retrying device search ({retry_count}/{max_retries})...")
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
                logging.info("Sleeping for 5 seconds...")
                time.sleep(5)
                # Need to find the device again
                if not self.find_device():
                    logging.error("Failed to reconnect to device")
                    return False
                advnc_mode = rs.rs400_advanced_mode(self.device)
                
            logging.info(f"Advanced mode is {'enabled' if advnc_mode.is_enabled() else 'disabled'}")
            
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
        """Connect to the camera and start streaming"""
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
                logging.info("Camera Matrix:\n" + str(self.camera_matrix))
                logging.info("Distortion Coefficients: " + str(self.dist_coeffs))
            
            return True
            
        except Exception as e:
            logging.error(f"Error connecting to camera: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def _filter_depth_frame(self, depth_frame):
        """Apply filters to depth frame"""
        filtered_frame = depth_frame
        for f in self.filter_to_apply:
            filtered_frame = f.process(filtered_frame)
        return filtered_frame
    
    def setup_rtsp(self):
        """Initialize RTSP streaming"""
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
                
            # Test VLC command
            vlc_cmd = f"vlc rtsp://{local_ip}:{self.rtsp_port}{self.video_mount_point}"
            ffplay_cmd = f"ffplay rtsp://{local_ip}:{self.rtsp_port}{self.video_mount_point}"
            logging.info(f"Play with VLC: {vlc_cmd}")
            logging.info(f"Play with FFplay: {ffplay_cmd}")
            
            # Create and start the GLib main loop
            self.glib_loop = GLib.MainLoop()
            self.video_thread = threading.Thread(target=self.glib_loop.run)
            self.video_thread.daemon = True  # Make thread a daemon so it exits when main thread exits
            self.video_thread.start()
            
            return True
        except Exception as e:
            logging.error(f"Error setting up RTSP: {e}")
            logging.error(traceback.format_exc())
            return False
    
    def get_local_ip(self):
        """Get local IP address for better URL display in logs"""
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
        self.camera_thread.daemon = True  # Make thread a daemon so it exits when main thread exits
        self.camera_thread.start()
        logging.info("Camera streaming started")

        # --- Check Vehicle State and Set Mode to MANUAL (moved from run) ---
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
                    # Potentially return False or raise an error
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
                            time.sleep(1) # Wait for mode change
                            msg_confirm = self.connection.recv_match(type='HEARTBEAT', blocking=True, timeout=2)
                            if msg_confirm:
                                new_mode_id = msg_confirm.custom_mode
                                new_mode_name = self.connection.mode_mapping().get(new_mode_id, f"UNKNOWN({new_mode_id})")
                                logging.info(f"Vehicle now in mode: {new_mode_name}")
                            else:
                                logging.warning("Did not receive confirmation heartbeat after mode change attempt.")
                        else:
                            logging.error(f"Mode {target_mode} is not supported by this firmware.")
                    else:
                        logging.info(f"Vehicle already in {target_mode} mode.")
        except Exception as mode_ex:
            logging.error(f"Error during initial state check or mode set: {mode_ex}")

        logging.warning("Ensure ARMING_CHECK is properly configured (recommended: 1).")

        # Start control loop thread
        self.control_thread = threading.Thread(target=self.control_loop)
        self.control_thread.daemon = True
        self.control_thread.start()
        logging.info("Control loop started")

        return True
    
    def camera_reader(self):
        """Main camera processing loop"""
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
                        # Apply filters
                        filtered_frame = self._filter_depth_frame(depth_frame)
                        # Colorize depth frame
                        depth_colormap = np.asanyarray(self.colorizer.colorize(filtered_frame).get_data())
                        # Convert to RGBA
                        colorized_frame = cv2.cvtColor(depth_colormap, cv2.COLOR_BGR2RGBA)
                        # Add to RTSP buffer
                        self.depth_stream.add_to_buffer(colorized_frame)
                
                # Process color frame if color streaming is enabled
                if self.enable_color and self.video_stream:
                    color_frame = frames.get_color_frame()
                    if color_frame:
                        # Get RGBA image (original format)
                        color_image_rgba = np.asanyarray(color_frame.get_data())
                        
                        # Convert to Grayscale for detection
                        gray_image = cv2.cvtColor(color_image_rgba, cv2.COLOR_RGBA2GRAY)
                        
                        # Detect markers
                        corners, ids, rejectedImgPoints = aruco.detectMarkers(
                            gray_image, self.aruco_dict, parameters=self.aruco_params
                        )
                        
                        # Draw rectangles around detected markers
                        if ids is not None:
                            logging.info(f"Detected marker IDs: {ids.flatten().tolist()}")
                            for i, marker_id in enumerate(ids):
                                marker_corners = corners[i].reshape((4, 2))
                                pts = np.array(marker_corners, np.int32).reshape((-1, 1, 2))
                                
                                if marker_id == self.target_marker_id:
                                    # Draw green rectangle for the target marker
                                    cv2.polylines(color_image_rgba, [pts], True, (0, 255, 0, 255), 2) # Green
                                    logging.debug(f"Detected target marker ID {self.target_marker_id}")
                                    # --- Optional: Estimate Pose --- 
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
                                        logging.debug(f"Target marker {marker_id} pose: Dist={distance_m:.3f} m") # Debug level for distance
                                        # Break if target found
                                        break
                                else:
                                    # Draw blue rectangle for other detected markers
                                    cv2.polylines(color_image_rgba, [pts], True, (255, 0, 0, 255), 1) # Blue
                            # If target wasn't found in the loop, update state
                            if not self.target_marker_detected:
                                with self.control_lock:
                                    self.estimated_distance_m = None # No valid distance if target not seen
                        else:
                            # No markers detected at all
                            with self.control_lock:
                                self.target_marker_detected = False
                                self.estimated_distance_m = None
                            logging.debug("No markers detected in this frame.")
                        
                        # Add the potentially modified RGBA frame to the RTSP buffer
                        self.video_stream.add_to_buffer(color_image_rgba)
                
                # Log frame rate periodically
                current_time = time.time()
                if current_time - last_log_time > 10:  # Log every 10 seconds
                    if current_time > last_log_time: # Avoid division by zero
                        fps = frames_processed / (current_time - last_log_time)
                        logging.info(f"Camera processing {fps:.2f} fps")
                    frames_processed = 0
                    last_log_time = current_time
                
            except rs.error as e:
                 # Handle potential Realsense errors (e.g., frame drops)
                 logging.warning(f"Realsense error: {e}")
                 time.sleep(0.01)
            except Exception as e:
                logging.error(f"Error while reading camera: {e}")
                logging.error(traceback.format_exc()) # Log full traceback
                # Reset detection state on error
                with self.control_lock:
                    self.target_marker_detected = False
                    self.estimated_distance_m = None
                time.sleep(0.1)
    
    def stop(self):
        """Stop all processing and clean up resources"""
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
                logging.info("Sending final neutral RC command and releasing override.")
                if self.neutral_cmd and self.release_cmd:
                    self.send_rc_override_command(self.neutral_cmd)
                    time.sleep(0.1)
                    self.send_rc_override_command(self.release_cmd)
                    time.sleep(0.1)
                else:
                    logging.warning("RC commands not prepared, cannot send final commands.")
            except Exception as final_e:
                logging.warning(f"Error sending final RC override commands: {final_e}")
            finally:
                logging.info("Closing MAVLink connection.")
                self.connection.close()
    
    def exit_handler(self, sig, frame):
        logging.info(f"Caught signal {sig}, shutting down...")
        self.stop()
        sys.exit(0)
    
    def run(self):
        """Main function to start the back camera streamer"""
        logging.info("Starting Back Camera RTSP Streamer with ArUco Detection")
        
        # Find device
        if not self.find_device():
            logging.error("Failed to find a compatible RealSense device. Exiting.")
            return False
        
        # Configure advanced settings if enabled
        if self.use_preset:
            if self.configure_advanced_settings():
                logging.info("Advanced settings applied")
        
        # Connect to MAVLink FIRST
        logging.info("Connecting to MAVLink...")
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
            logging.info(f"MAVLink connected to system {self.connection.target_system}")
        except Exception as mav_ex:
            logging.error(f"Failed to establish MAVLink connection: {mav_ex}")
            # No need to stop camera pipe yet as it hasn't started
            return False
        
        # Connect to camera
        if not self.connect():
            logging.error("Failed to connect to camera. Exiting.")
            if self.connection: self.connection.close() # Close MAVLink if camera fails
            return False
        
        # Setup RTSP streaming
        if not self.setup_rtsp():
            logging.error("Failed to setup RTSP streaming. Exiting.")
            if self.pipe: self.pipe.stop()
            if self.connection: self.connection.close()
            return False
        
        # Prepare RC Commands
        logging.info("Preparing RC commands...")
        self.neutral_cmd = [0] * NUM_CHANNELS
        self.neutral_cmd[THROTTLE_CHAN_IDX] = NEUTRAL_THROTTLE_PWM
        self.neutral_cmd[STEERING_CHAN_IDX] = STEERING_PWM
        self.backward_cmd = list(self.neutral_cmd)
        self.backward_cmd[THROTTLE_CHAN_IDX] = BACKWARD_PWM
        self.release_cmd = [0] * NUM_CHANNELS
        logging.info("RC commands prepared.")

        # Start streaming and control threads
        if not self.start_streaming_and_control():
            logging.error("Failed to start streaming. Exiting.")
            self.pipe.stop()
            if self.connection: self.connection.close()
            return False
        
        logging.info("Back camera streaming and control successfully started")
        return True

    # MAVLink Helper Function (integrated)
    def send_rc_override_command(self, channels):
        """Sends an RC_CHANNELS_OVERRIDE command."""
        if not self.connection:
            logging.warning("Cannot send RC override command, MAVLink not connected.")
            return

        rc_values = list(channels) + [0] * (NUM_CHANNELS - len(channels))
        try:
            self.connection.mav.rc_channels_override_send(
                self.connection.target_system,
                self.connection.target_component,
                *rc_values
            )
            # Log significant commands
            if channels[THROTTLE_CHAN_IDX] != NEUTRAL_THROTTLE_PWM:
                logging.debug(f"Sent RC Override: Thr={channels[THROTTLE_CHAN_IDX]}, Steer={channels[STEERING_CHAN_IDX]}")
            elif channels[THROTTLE_CHAN_IDX] == 0 and channels[STEERING_CHAN_IDX] == 0:
                logging.debug(f"Sent RC Override Release (all zeros)")

        except Exception as e:
            logging.error(f"Error sending rc_channels_override command: {e}")

    # Control Loop Implementation
    def control_loop(self):
        """Runs the docking control logic using continuous RC_CHANNELS_OVERRIDE."""
        log_msg = f"Continuous control loop starting. Target: {TARGET_DISTANCE_M:.2f}m, PWM: {BACKWARD_PWM}\n"
        logging.info(log_msg)
        is_moving = False # State variable
        last_command_resend_time = 0 # Track time for resending commands

        while not self.time_to_exit:
            try:
                # Read shared state under lock
                with self.control_lock:
                    target_detected = self.target_marker_detected
                    distance_m = self.estimated_distance_m

                # Control Logic
                if target_detected and distance_m is not None:
                    if distance_m > TARGET_DISTANCE_M:
                        if not is_moving:
                            logging.info(f"Target detected, moving backward (Dist: {distance_m:.3f}m > {TARGET_DISTANCE_M:.2f}m)")
                            self.send_rc_override_command(self.backward_cmd)
                            is_moving = True
                        else:
                            # Already moving, just log debug
                            logging.debug(f"Continuing backward movement (Dist: {distance_m:.3f}m)")
                            # Periodically resend backward command to maintain override
                            current_time = time.time()
                            if current_time - last_command_resend_time > COMMAND_RESEND_INTERVAL_S:
                                logging.debug("Resending backward command to maintain override.")
                                self.send_rc_override_command(self.backward_cmd)
                                last_command_resend_time = current_time

                    else:
                        # Target detected, distance reached or too close -> Stop
                        if is_moving:
                            logging.info(f"Target distance reached or passed (Dist: {distance_m:.3f}m). Stopping.")
                            self.send_rc_override_command(self.neutral_cmd)
                            is_moving = False
                        else:
                             # Already stopped, just log debug
                             logging.debug("Maintaining stop at target distance.")
                             # Periodically resend neutral command to maintain stop
                             current_time = time.time()
                             if current_time - last_command_resend_time > COMMAND_RESEND_INTERVAL_S:
                                 logging.debug("Resending neutral command to maintain stop.")
                                 self.send_rc_override_command(self.neutral_cmd)
                                 last_command_resend_time = current_time

                else:
                    # Target lost -> Stop
                    if is_moving:
                        logging.info(f"Target lost. Stopping.")
                        self.send_rc_override_command(self.neutral_cmd)
                        is_moving = False
                    else:
                        # Already stopped, just log debug
                        logging.debug("Maintaining stop due to lost target.")
                        # Periodically resend neutral command to maintain stop
                        current_time = time.time()
                        if current_time - last_command_resend_time > COMMAND_RESEND_INTERVAL_S:
                            logging.debug("Resending neutral command to maintain stop.")
                            self.send_rc_override_command(self.neutral_cmd)
                            last_command_resend_time = current_time

                # Control loop rate
                time.sleep(1.0 / CONTROL_LOOP_RATE_HZ)

            except Exception as e:
                logging.error(f"Error in control_loop: {e}")
                logging.error(traceback.format_exc())
                # Ensure stop command is sent on error
                try:
                    logging.info("Sending STOP command due to control loop error.")
                    # Set is_moving false on error to ensure stop logic triggers if loop continues
                    is_moving = False 
                    if self.connection and self.neutral_cmd:
                        self.send_rc_override_command(self.neutral_cmd)
                except Exception as stop_e:
                    logging.error(f"Failed to send stop command after error: {stop_e}")
                # Pause briefly after an error before retrying
                time.sleep(0.5)

        logging.info("Control loop finished.")

if __name__ == "__main__":
    print("=" * 80)
    print("Back Camera RTSP Streamer with ArUco Detection")
    print("=" * 80)
    # Create the streamer object first to parse args and access defaults
    streamer = BackCameraStreamer()
    print(f"Default camera serial: {streamer.serial_number}")
    print(f"MAVLink: {streamer.mavlink_connect_str} @ {streamer.mavlink_baudrate} baud")
    print("Using ArUco Dictionary: DICT_4X4_250")
    print(f"Target ArUco marker ID: {streamer.target_marker_id} (Green Rectangle)")
    print(f"Target Distance: {TARGET_DISTANCE_M:.2f} m")
    print(f"Backward PWM Step: {BACKWARD_PWM} (RC Override Value)")
    print("Detecting other ArUco markers (Blue Rectangle)")
    print("Run with --help for more options")
    print("=" * 80)
    
    if streamer.run():
        try:
            logging.info("Server running. Press Ctrl+C to exit.")
            # Keep main thread alive
            while not streamer.time_to_exit:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("KeyboardInterrupt received, shutting down...")
        finally:
            streamer.stop()
            logging.info("Back camera streamer stopped")
