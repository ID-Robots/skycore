import sys

# First import the direct compiled library
import pyrealsense2 as rs
import numpy as np
import math as m
import signal
import sys
import time
import threading
import os
import traceback

os.environ["MAVLINK20"] = "1"
from pymavlink import mavutil

# Placeholder for Camera IDs and MAVLink Frames
FRONT_CAM_SENSOR_TYPE = 0  # MAV_DISTANCE_SENSOR_LASER
BACK_CAM_SENSOR_TYPE = 1   # Using a different ID for the back camera
# Define MAVLink frames (assuming standard orientation)
# Forward camera aligned with vehicle front
FRONT_CAM_FRAME = mavutil.mavlink.MAV_FRAME_BODY_FRD
# Backward camera also aligned with vehicle frame, but facing rear.
# MAV_FRAME_BODY_FRD still seems appropriate, the angle_offset handles direction.
BACK_CAM_FRAME = mavutil.mavlink.MAV_FRAME_BODY_FRD

import cv2

import logging
from collections import deque
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib
import argparse

logging.basicConfig(level=logging.INFO)

class ManagedCamera:
    """
    Encapsulates a single RealSense camera with all its configuration and processing
    """
    def __init__(self, 
                 camera_name,
                 serial_number=None, 
                 depth_width=640, 
                 depth_height=480,
                 color_width=640,
                 color_height=480,
                 depth_fps=15,
                 color_fps=15,
                 depth_range_m=(0.1, 8.0),
                 use_preset=True,
                 preset_file="./cfg/d4xx-default.json",
                 camera_facing_angle_degree=0,
                 sensor_type=FRONT_CAM_SENSOR_TYPE,
                 frame_type=FRONT_CAM_FRAME,
                 obstacle_line_height_ratio=0.18,
                 obstacle_line_thickness_pixel=10):
        """
        Initialize a managed camera instance
        
        Args:
            camera_name: Name to identify this camera (e.g., 'front', 'back')
            serial_number: Serial number of the camera to connect to
            depth_width: Width of depth stream
            depth_height: Height of depth stream
            color_width: Width of color stream
            color_height: Height of color stream
            depth_fps: Framerate of depth stream
            color_fps: Framerate of color stream
            depth_range_m: Tuple of (min_depth_m, max_depth_m)
            use_preset: Whether to use a preset config file
            preset_file: Path to the preset config file
            camera_facing_angle_degree: Camera orientation relative to vehicle (0=front, 180=back)
            sensor_type: MAVLink sensor type ID for this camera
            frame_type: MAVLink frame type for obstacle messages
            obstacle_line_height_ratio: [0-1]: Vertical position of the scan line
            obstacle_line_thickness_pixel: Pixel thickness of the scan line
        """
        self.camera_name = camera_name
        self.serial_number = serial_number
        self.device_id = None  # Will be set when camera is found
        
        # Stream configuration
        self.STREAM_TYPE = [rs.stream.depth, rs.stream.color]
        self.FORMAT = [rs.format.z16, rs.format.rgba8]
        self.DEPTH_WIDTH = depth_width
        self.DEPTH_HEIGHT = depth_height
        self.COLOR_WIDTH = color_width
        self.COLOR_HEIGHT = color_height
        self.DEPTH_FPS = depth_fps
        self.COLOR_FPS = color_fps
        self.DEPTH_RANGE_M = depth_range_m
        
        # Preset configuration
        self.USE_PRESET_FILE = use_preset
        self.PRESET_FILE = preset_file
        
        # Camera orientation (important for obstacle avoidance)
        self.camera_facing_angle_degree = camera_facing_angle_degree
        self.sensor_type = sensor_type
        self.frame_type = frame_type
        
        # Obstacle detection configuration
        self.obstacle_line_height_ratio = obstacle_line_height_ratio
        self.obstacle_line_thickness_pixel = obstacle_line_thickness_pixel
        
        # Depth processing
        self.threshold_min_m = self.DEPTH_RANGE_M[0]
        self.threshold_max_m = self.DEPTH_RANGE_M[1]
        
        # Runtime objects
        self.ctx = None
        self.device = None
        self.pipe = None
        self.depth_scale = 0
        self.depth_hfov_deg = None
        self.depth_vfov_deg = None
        self.colorizer = rs.colorizer()
        self.filters = [
            [False, "Decimation Filter",    rs.decimation_filter()],
            [True,  "Threshold Filter",    rs.threshold_filter()],
            [True,  "Depth to Disparity",  rs.disparity_transform(True)],
            [True,  "Spatial Filter",      rs.spatial_filter()],
            [True,  "Temporal Filter",     rs.temporal_filter()],
            [False, "Hole Filling Filter", rs.hole_filling_filter()],
            [True,  "Disparity to Depth",  rs.disparity_transform(False)]
        ]
        
        # Colorizer configuration
        self.colorizer.set_option(rs.option.color_scheme, 7)  # 7 is white close black far
        self.colorizer.set_option(rs.option.min_distance, 1.0)
        self.colorizer.set_option(rs.option.max_distance, 2.5)
        
        # Configure threshold filter if enabled
        if self.filters[1][0] is True:
            self.filters[1][2].set_option(rs.option.min_distance, self.threshold_min_m)
            self.filters[1][2].set_option(rs.option.max_distance, self.threshold_max_m)
        
        # Build list of filters to apply
        self.filter_to_apply = [f[2] for f in self.filters if f[0]]
        
        # Camera thread
        self.camera_thread = None
        self.time_to_exit = False
        
        # Mavlink integration references (set from outside)
        self.mavlink_integration = None
        
        # RTSP streaming references (set from outside)
        self.gst_server = None
        self.colorized_stream = None
        self.video_stream = None
        
        # Obstacle detection parameters
        self.distances_array_length = 72
        self.distances = np.ones((self.distances_array_length,), dtype=np.uint16) * (int(self.DEPTH_RANGE_M[1] * 100) + 1)
        self.min_depth_cm = int(self.DEPTH_RANGE_M[0] * 100)
        self.max_depth_cm = int(self.DEPTH_RANGE_M[1] * 100)
        self.angle_offset = None  # Set after camera intrinsics are obtained
        self.increment_f = None   # Set after camera intrinsics are obtained
        
        # Will be set during configuration
        self.obstacle_line_height = None
        self.center_pixel = None
        self.upper_pixel = None
        self.lower_pixel = None
        self.step = None

    def find_device(self):
        """
        Find the RealSense device with the specified serial number.
        If no serial number is specified, find any compatible device.
        
        Returns:
            True if a device was found, False otherwise
        """
        self.ctx = rs.context()
        devices = self.ctx.query_devices()
        logging.info(f"[{self.camera_name}] Searching for device among {len(devices)} found...")
        
        # If a serial number was provided, search for that specific device
        if self.serial_number:
            for dev in devices:
                if dev.supports(rs.camera_info.serial_number) and dev.get_info(rs.camera_info.serial_number) == self.serial_number:
                    product_id = str(dev.get_info(rs.camera_info.product_id))
                    if dev.supports(rs.camera_info.product_id) and product_id in RealsenseService.DS5_product_ids:
                        self.device = dev
                        self.device_id = self.serial_number
                        logging.info(f"[{self.camera_name}] Found device with serial {self.serial_number}")
                        return True
                    else:
                        logging.warning(f"[{self.camera_name}] Found device with serial {self.serial_number}, but it doesn't support advanced mode or isn't a D4xx series.")
                        return False
            logging.error(f"[{self.camera_name}] Could not find device with serial {self.serial_number}")
            return False
        
        # If no serial number was provided, find any compatible device not already in use
        # We determine this by checking all in-use devices (needs to be tracked somewhere)
        for i, dev in enumerate(devices):
            try:
                product_id = str(dev.get_info(rs.camera_info.product_id))
                name = dev.get_info(rs.camera_info.name)
                serial = dev.get_info(rs.camera_info.serial_number)
                
                # Skip devices that are already in use (this needs coordination)
                # if serial in RealsenseService.active_camera_serials:
                #     continue
                
                logging.info(f"[{self.camera_name}] Checking Device {i}: Name={name}, Product ID={product_id}, Serial={serial}")
                if dev.supports(rs.camera_info.product_id) and product_id in RealsenseService.DS5_product_ids:
                    self.device = dev
                    self.device_id = serial
                    self.serial_number = serial  # Save for future reference
                    logging.info(f"[{self.camera_name}] Using device {i}: Serial={serial}")
                    return True
            except Exception as e:
                logging.error(f"[{self.camera_name}] Error querying info for device {i}: {e}")
                
        logging.error(f"[{self.camera_name}] No compatible device found")
        return False

    def configure_advanced_settings(self):
        """
        Apply advanced settings to camera from preset file if enabled.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.USE_PRESET_FILE or not self.device:
            return False
            
        try:
            # Apply advanced mode settings if preset file specified
            if not os.path.isfile(self.PRESET_FILE):
                logging.warning(f"[{self.camera_name}] Cannot find preset file {self.PRESET_FILE}")
                return False
                
            # Enable advanced mode if supported
            if not self.device.supports(rs.camera_info.product_id):
                logging.warning(f"[{self.camera_name}] Device does not support product_id info, can't verify advanced mode support")
                return False
                
            # Use advanced mode interface to configure
            advnc_mode = rs.rs400_advanced_mode(self.device)
            if not advnc_mode.is_enabled():
                logging.info(f"[{self.camera_name}] Enabling advanced mode...")
                advnc_mode.toggle_advanced_mode(True)
                # At this point the device will disconnect and re-connect
                logging.info(f"[{self.camera_name}] Sleeping for 5 seconds...")
                time.sleep(5)
                # Need to find the device again
                if not self.find_device():
                    logging.error(f"[{self.camera_name}] Failed to reconnect to device after enabling advanced mode")
                    return False
                advnc_mode = rs.rs400_advanced_mode(self.device)
                
            logging.info(f"[{self.camera_name}] Advanced mode is {'enabled' if advnc_mode.is_enabled() else 'disabled'}")
            
            if not advnc_mode.is_enabled():
                logging.warning(f"[{self.camera_name}] Advanced mode not enabled, skipping preset loading")
                return False
                
            # Load the JSON preset file
            with open(self.PRESET_FILE, 'r') as file:
                json_text = file.read().strip()
                
            advnc_mode.load_json(json_text)
            logging.info(f"[{self.camera_name}] Applied preset from {self.PRESET_FILE}")
            return True
            
        except Exception as e:
            logging.error(f"[{self.camera_name}] Error configuring advanced settings: {e}")
            logging.error(traceback.format_exc())
            return False

    def connect(self, enable_color=True):
        """
        Connect to the camera and start streaming
        
        Args:
            enable_color: Whether to enable color stream (for RTSP)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Create pipeline
            self.pipe = rs.pipeline()
            
            # Configure streams
            config = rs.config()
            if self.device_id:
                # Connect to specific device
                config.enable_device(self.device_id)
                
            # Always enable depth stream
            config.enable_stream(
                self.STREAM_TYPE[0], self.DEPTH_WIDTH, self.DEPTH_HEIGHT, 
                self.FORMAT[0], self.DEPTH_FPS
            )
            
            # Optionally enable color stream for RTSP
            if enable_color:
                config.enable_stream(
                    self.STREAM_TYPE[1], self.COLOR_WIDTH, self.COLOR_HEIGHT, 
                    self.FORMAT[1], self.COLOR_FPS
                )
                
            # Start streaming with requested config
            profile = self.pipe.start(config)
            
            # Get depth scale from the device
            depth_sensor = profile.get_device().first_depth_sensor()
            self.depth_scale = depth_sensor.get_depth_scale()
            logging.info(f"[{self.camera_name}] Depth scale is: {self.depth_scale}")
            
            # Calculate obstacle detection parameters
            self.calculate_obstacle_params(profile)
            
            return True
            
        except Exception as e:
            logging.error(f"[{self.camera_name}] Error connecting to camera: {e}")
            logging.error(traceback.format_exc())
            return False
            
    def calculate_obstacle_params(self, profile):
        """
        Calculate parameters for obstacle detection based on camera intrinsics
        
        Args:
            profile: The active stream profile
        """
        try:
            # Obtain the intrinsics from the camera itself
            depth_intrinsics = profile.get_stream(self.STREAM_TYPE[0]).as_video_stream_profile().intrinsics
            logging.info(f"[{self.camera_name}] Depth camera intrinsics: {depth_intrinsics}")
            
            # Calculate field of view
            self.depth_hfov_deg = m.degrees(2 * m.atan(self.DEPTH_WIDTH / (2 * depth_intrinsics.fx)))
            self.depth_vfov_deg = m.degrees(2 * m.atan(self.DEPTH_HEIGHT / (2 * depth_intrinsics.fy)))
            logging.info(f"[{self.camera_name}] Depth camera HFOV: {self.depth_hfov_deg:.2f} degrees")
            logging.info(f"[{self.camera_name}] Depth camera VFOV: {self.depth_vfov_deg:.2f} degrees")
            
            # Calculate MAVLink OBSTACLE_DISTANCE parameters
            self.angle_offset = self.camera_facing_angle_degree - (self.depth_hfov_deg / 2)
            self.increment_f = self.depth_hfov_deg / self.distances_array_length
            logging.info(f"[{self.camera_name}] OBSTACLE_DISTANCE angle_offset: {self.angle_offset:.3f}")
            logging.info(f"[{self.camera_name}] OBSTACLE_DISTANCE increment_f: {self.increment_f:.3f}")
            logging.info(f"[{self.camera_name}] OBSTACLE_DISTANCE coverage: from {self.angle_offset:.3f} to " +
                         f"{self.angle_offset + self.increment_f * self.distances_array_length:.3f} degrees")
            
            # Calculate obstacle line parameters
            self.find_obstacle_line_height()
            self.configure_depth_shape()
            
        except Exception as e:
            logging.error(f"[{self.camera_name}] Error calculating obstacle parameters: {e}")
            logging.error(traceback.format_exc())

    def find_obstacle_line_height(self, vehicle_pitch_rad=0):
        """
        Determine the height of the obstacle detection line, accounting for vehicle pitch
        
        Args:
            vehicle_pitch_rad: Current vehicle pitch in radians
        """
        # Basic position
        obstacle_line_height = self.DEPTH_HEIGHT * self.obstacle_line_height_ratio

        # Compensate for the vehicle's pitch angle if data is available
        if vehicle_pitch_rad is not None and self.depth_vfov_deg is not None:
            delta_height = m.sin(vehicle_pitch_rad / 2) / m.sin(m.radians(self.depth_vfov_deg) / 2) * self.DEPTH_HEIGHT
            obstacle_line_height += delta_height

        # Sanity check
        if obstacle_line_height < 0:
            obstacle_line_height = 0
        elif obstacle_line_height > self.DEPTH_HEIGHT:
            obstacle_line_height = self.DEPTH_HEIGHT
        
        self.obstacle_line_height = obstacle_line_height
        return obstacle_line_height
        
    def configure_depth_shape(self):
        """
        Configure depth processing parameters for obstacle detection
        """
        # Parameters for obstacle distance message
        self.step = int(self.DEPTH_WIDTH / self.distances_array_length)
        
        self.center_pixel = self.obstacle_line_height
        self.upper_pixel = self.center_pixel + self.obstacle_line_thickness_pixel / 2
        self.lower_pixel = self.center_pixel - self.obstacle_line_thickness_pixel / 2

        # Each range (left to right) is found from a set of rows within a column
        #  [ ] -> ignored
        #  [x] -> center + obstacle_line_thickness_pixel / 2
        #  [x] -> center = obstacle_line_height (moving up and down according to the vehicle's pitch angle)
        #  [x] -> center - obstacle_line_thickness_pixel / 2
        #  [ ] -> ignored
        #   ^ One of [distances_array_length] number of columns, from left to right in the image
        if self.upper_pixel > self.DEPTH_HEIGHT:
            self.upper_pixel = self.DEPTH_HEIGHT
        elif self.upper_pixel < 1:
            self.upper_pixel = 1
        if self.lower_pixel > self.DEPTH_HEIGHT:
            self.lower_pixel = self.DEPTH_HEIGHT - 1
        elif self.lower_pixel < 0:
            self.lower_pixel = 0
            
        # cast all pixels to int
        self.center_pixel = int(self.center_pixel)
        self.upper_pixel = int(self.upper_pixel)
        self.lower_pixel = int(self.lower_pixel)
        
    def _filter_depth_frame(self, depth_frame):
        """
        Apply filters to depth frame
        
        Args:
            depth_frame: The raw depth frame
            
        Returns:
            Filtered depth frame
        """
        filtered_frame = depth_frame
        for f in self.filter_to_apply:
            filtered_frame = f.process(filtered_frame)
            
        return filtered_frame

    def distances_from_depth_image(self, depth_mat, distances=None, min_depth_m=None, max_depth_m=None):
        """
        Calculate obstacle distances from depth image
        
        Args:
            depth_mat: Depth image matrix
            distances: Array to store distances (will create if None)
            min_depth_m: Minimum depth in meters (uses instance default if None)
            max_depth_m: Maximum depth in meters (uses instance default if None)
            
        Returns:
            Array of distances in centimeters
        """
        if distances is None:
            distances = np.ones((self.distances_array_length,), dtype=np.uint16) * 65535
            
        if min_depth_m is None:
            min_depth_m = self.DEPTH_RANGE_M[0]
            
        if max_depth_m is None:
            max_depth_m = self.DEPTH_RANGE_M[1]

        # Calculate distances for each column
        for i in range(self.distances_array_length):
            min_point_in_scan = np.min(depth_mat[int(self.lower_pixel):int(self.upper_pixel), int(i * self.step)])
            dist_m = min_point_in_scan * self.depth_scale

            distances[i] = 65535  # Default: no obstacle

            # Note that dist_m is in meter, while distances[] is in cm.
            if dist_m > min_depth_m and dist_m < max_depth_m:
                distances[i] = dist_m * 100
        
        return distances

    def start_processing(self, mavlink_integration, rtsp_enabled=False, video_enabled=False, colorization_enabled=False):
        """
        Start camera processing thread
        
        Args:
            mavlink_integration: MavlinkIntegration instance to send data to
            rtsp_enabled: Whether RTSP streaming is enabled
            video_enabled: Whether to stream color video
            colorization_enabled: Whether to stream colorized depth
            
        Returns:
            True if successful, False otherwise
        """
        if self.pipe is None:
            logging.error(f"[{self.camera_name}] Cannot start processing: camera not connected")
            return False
            
        self.mavlink_integration = mavlink_integration
        
        # Configure MAVLink obstacle parameters
        self.mavlink_integration.configure_sensor(
            self.sensor_type, 
            self.min_depth_cm, 
            self.max_depth_cm,
            self.angle_offset,
            self.increment_f,
            self.frame_type
        )
        
        # Start camera thread
        self.time_to_exit = False
        self.camera_thread = threading.Thread(
            target=self.camera_reader,
            args=(rtsp_enabled, video_enabled, colorization_enabled)
        )
        self.camera_thread.start()
        
        return True
        
    def stop_processing(self):
        """
        Stop camera processing
        """
        self.time_to_exit = True
        if self.camera_thread:
            self.camera_thread.join()
            
        if self.pipe:
            self.pipe.stop()

    def camera_reader(self, rtsp_enabled=False, video_enabled=False, colorization_enabled=False):
        """
        Main camera processing loop
        
        Args:
            rtsp_enabled: Whether RTSP streaming is enabled
            video_enabled: Whether to stream color video
            colorization_enabled: Whether to stream colorized depth
        """
        while not self.time_to_exit:
            try:
                # This call waits until a new coherent set of frames is available on a device
                frames = self.pipe.wait_for_frames()
                
                depth_frame = frames.get_depth_frame()
                sensing_time = int(round(depth_frame.timestamp * 1000))
                
                if depth_frame:
                    self._process_depth_frame(depth_frame, sensing_time)
                
                if rtsp_enabled and video_enabled and self.gst_server is not None and self.video_stream is not None:
                    color_frame = frames.get_color_frame()
                    if color_frame:               
                        self._process_color_frame(color_frame)
                
            except Exception as e:
                logging.error(f"[{self.camera_name}] Error while reading camera: {e}")
                time.sleep(0.1)
                
    def _process_depth_frame(self, depth_frame, sensing_time):
        """
        Process a depth frame: filter, calculate distances, send to MAVLink, handle RTSP
        
        Args:
            depth_frame: Raw depth frame
            sensing_time: Frame timestamp in milliseconds
        """
        try:
            # Apply the filters
            filtered_frame = self._filter_depth_frame(depth_frame)

            # Extract depth in matrix form
            depth_data = filtered_frame.as_frame().get_data()
            depth_mat = np.asanyarray(depth_data)
            
            # Create obstacle distance data from depth image
            distances = self.distances_from_depth_image(
                depth_mat, 
                self.distances, 
                self.DEPTH_RANGE_M[0], 
                self.DEPTH_RANGE_M[1]
            )
            
            # Send to MAVLink
            if self.mavlink_integration:
                self.mavlink_integration.obstacle_queue.append(
                    (distances.copy(), sensing_time, self.sensor_type)
                )

            # Handle RTSP streaming of colorized depth
            if self.gst_server is not None and self.colorized_stream is not None:
                # Use CPU-based processing
                depth_colormap = np.asanyarray(self.colorizer.colorize(filtered_frame).get_data())
                
                # Convert to RGBA
                colorized_frame = cv2.cvtColor(depth_colormap, cv2.COLOR_BGR2RGBA)
                
                self.colorized_stream.add_to_buffer(colorized_frame)
                
        except Exception as e:
            logging.error(f"[{self.camera_name}] Error processing depth frame: {e}")
            logging.error(traceback.format_exc())

    def _process_color_frame(self, color_frame):
        """
        Process a color frame for RTSP streaming
        
        Args:
            color_frame: Raw color frame
        """
        try:
            if self.gst_server is not None and self.video_stream is not None:
                color_image = np.asanyarray(color_frame.get_data())
                self.video_stream.add_to_buffer(color_image)
        except Exception as e:
            logging.error(f"[{self.camera_name}] Error processing color frame: {e}")
            logging.error(traceback.format_exc())

class Settings:
    
    def __init__(self):
        args = self.parse_args()
        self.mavlink_device = args.connect
        self.baudrate = args.baudrate
        self.rtsp_enable = args.rtsp_enable
        self.video_enable = args.video_enable
        self.colorization_enable = args.colorization_enable
        self.use_preset = args.use_preset
        self.front_serial = args.front_serial
        self.back_serial = args.back_serial
        self.num_cameras = sum(1 for s in [self.front_serial, self.back_serial] if s)
        
        logging.info(f"Connection string: {self.mavlink_device}")
        logging.info(f"RTSP enabled: {self.rtsp_enable}")
        if self.front_serial:
            logging.info(f"Front camera serial: {self.front_serial}")
        if self.back_serial:
            logging.info(f"Back camera serial: {self.back_serial}")
        if self.num_cameras == 0:
            logging.warning("No camera serial numbers provided. Attempting to find any compatible device.")
    
    def parse_args(self):
        parser = argparse.ArgumentParser(description="Realsense Service")
        parser.add_argument('--connect', type=str, default="/dev/ttyTHS1", help="Mavlink device connection string")
        parser.add_argument('--baudrate', type=int, default=230400, help="Baudrate for mavlink device")
        parser.add_argument('--rtsp_enable', type=bool, default=True, help="Enable RTSP streaming")
        parser.add_argument('--video_enable', type=bool, default=False, help="Enable video streaming")
        parser.add_argument('--colorization_enable', type=bool, default=True, help="Enable colorization streaming")
        parser.add_argument('--use_preset', type=bool, default=True, help="Use preset configuration file")
        parser.add_argument('--front-serial', type=str, default=None, help="Serial number of the front-facing RealSense camera")
        parser.add_argument('--back-serial', type=str, default=None, help="Serial number of the back-facing RealSense camera")
        return parser.parse_args()

            

class StreamFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, appsink_src='source', **properties):
        super(StreamFactory, self).__init__(**properties)
        self.frame_lock = threading.Lock()
        self.last_frame = None
        self.appsink_src = appsink_src
        self.color_buffer = deque(maxlen=5)
    
    # TODO:FIXME: sometimes old buffers are shown from a a couple of frames back
    def configure(self, fps, color_width, color_height):
        self.number_frames = 0
        self.fps = fps
        
        self.duration = 1 / self.fps * Gst.SECOND
        self.width = color_width
        self.height = color_height
        self.launch_string = (
            f'appsrc name={self.appsink_src} is-live=true do_timestamp=true block=false format=GST_FORMAT_TIME ' 
            f'caps=video/x-raw,format=RGBA,width={color_width},height={color_height},framerate={fps}/1 ' 
            "! identity sync=true "
            "! nvvidconv ! nvv4l2h264enc " 
                "profile=0 " 
                "bitrate=1000000 " 
                # "EnableTwopassCBR=true "\
                # "num-Ref-Frames=2 "\
                "insert-sps-pps=true "\
                "maxperf-enable=true "\
                "poc-type=2 "\
                "insert-aud=true "\
                "insert-vui=true "\
                "iframeinterval=3 "\
                "idrinterval=1 "\
            '! rtph264pay config-interval=-1 name=pay0 pt=96'
            
        )
        
        self.last_frame = np.zeros((self.height, self.width, 3), dtype=np.uint8).tobytes()
        
        
    def add_to_buffer(self, frame):
        with self.frame_lock:
            self.color_buffer.append(frame)
            
    def get_from_buffer(self):
        with self.frame_lock:
            return self.color_buffer.pop()

    def on_need_data(self, src, length):
        
        frame = None
        
        try:
            frame = self.get_from_buffer()
        except IndexError as e:
            logging.error(f"{self.appsink_src} frame not ready!") 
            frame = None
        
        if frame is None:
            data = self.last_frame
        if frame is not None:
            data = frame.tobytes()
            self.last_frame = data
            
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)
        
        buf.duration = self.duration
        timestamp = self.number_frames * self.duration
        buf.pts = buf.dts = int(timestamp)
        buf.offset = timestamp
        self.number_frames += 1
        
        retval = src.emit('push-buffer', buf)
        if retval != Gst.FlowReturn.OK:
            logging.warning(retval)
        
        return retval

    def do_create_element(self, url):
        return Gst.parse_launch(self.launch_string)

    def do_configure(self, rtsp_media):
        self.number_frames = 0
        consuming_appsrc = rtsp_media.get_element().get_child_by_name(self.appsink_src)
        consuming_appsrc.connect('need-data', self.on_need_data)

class GstServer(GstRtspServer.RTSPServer):
    def __init__(self, RTSP_PORT='8555', **properties):
        super(GstServer, self).__init__(**properties)
        self.RTSP_PORT = RTSP_PORT
        self.set_service(self.RTSP_PORT)
        self.attach(None)
        self.colorized_video = None
        self.normal_video = None
            
    def configure_depth(self, fps, color_width, color_height, mount_point):
        self.colorized_video = StreamFactory('depth_colorized')
        self.colorized_video.configure(fps, color_width=color_width, color_height=color_height)
        self.get_mount_points().add_factory(mount_point, self.colorized_video)            
        self.colorized_video.set_shared(True)
        
    def configure_video(self, fps, color_width, color_height, mount_point):
        self.normal_video = StreamFactory('normal_video')
        self.normal_video.configure(fps, color_width=color_width, color_height=color_height)
        self.get_mount_points().add_factory(mount_point, self.normal_video)            
        self.normal_video.set_shared(True)

class MavlinkIntegration:
    
    def __init__(self, connection_string, connection_baudrate=None):
        
        extra_kwargs = {}
        
        if 'udp' in connection_string:
            extra_kwargs = {
                **extra_kwargs,
                'udp_timeout': 1,
                'use_native': True,
                'autoreconnect': True
            }
        elif 'tty' in connection_string:
            extra_kwargs = {
                **extra_kwargs,
                'baud': connection_baudrate or 230400,
                # 'use_native': True
            }
        
        logging.info(f"Connecting to {connection_string}...")
        self.conn = mavutil.mavlink_connection(
            device=connection_string,
            source_system = 1,
            source_component = 93,
            force_connected=True,
            **extra_kwargs
        )
        
        self.time_to_exit = False
        self.debug_enable = False
        self.vehicle_pitch_rad = 0
        self.connected = False
        
        self.heartbeat_thread = threading.Thread(target=self.send_heartbeat)
        self.receive_thread = threading.Thread(target=self.receive_data)
        self.obstacle_thread = threading.Thread(target=self.send_obstacles)
        self.obstacle_queue = deque(maxlen=10) # Increased size slightly for two cameras
        
        # Store parameters per sensor_type
        self.camera_params = {} # {sensor_type: {'min_depth_cm': ..., 'max_depth_cm': ..., 'angle_offset': ..., 'increment_f': ..., 'frame': ...}}
        self.last_obstacle_distance_sent_ms = {} # {sensor_type: timestamp}
        
    def wait_for_heartbeat(self, timeout=10):
        """
        Wait for ArduPilot heartbeat to verify connection
        Returns True if heartbeat received within timeout, False otherwise
        """
        logging.info(f"Waiting for ArduPilot heartbeat (timeout: {timeout}s)...")
        try:
            heartbeat = self.conn.wait_heartbeat(timeout=timeout)
            if heartbeat:
                # For UDP connections, these attributes might not be available immediately
                try:
                    system_type = self.conn.mav_type
                    autopilot_type = self.conn.mav_autopilot
                    system_id = self.conn.target_system
                    component_id = self.conn.target_component
                    
                    type_map = {
                        mavutil.mavlink.MAV_TYPE_QUADROTOR: "Quadcopter",
                        mavutil.mavlink.MAV_TYPE_HEXAROTOR: "Hexacopter",
                        mavutil.mavlink.MAV_TYPE_OCTOROTOR: "Octocopter",
                        mavutil.mavlink.MAV_TYPE_TRICOPTER: "Tricopter",
                        mavutil.mavlink.MAV_TYPE_HELICOPTER: "Helicopter",
                        mavutil.mavlink.MAV_TYPE_FIXED_WING: "Fixed Wing",
                        mavutil.mavlink.MAV_TYPE_GROUND_ROVER: "Ground Rover",
                        mavutil.mavlink.MAV_TYPE_SUBMARINE: "Submarine",
                        mavutil.mavlink.MAV_TYPE_BOAT: "Boat"
                    }
                    
                    autopilot_map = {
                        mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA: "ArduPilot",
                        mavutil.mavlink.MAV_AUTOPILOT_PX4: "PX4"
                    }
                    
                    vehicle_type = type_map.get(system_type, f"Unknown ({system_type})")
                    autopilot = autopilot_map.get(autopilot_type, f"Unknown ({autopilot_type})")
                    
                    logging.info(f"Connected to {autopilot} {vehicle_type} (system: {system_id}, component: {component_id})")
                except AttributeError:
                    # UDP connections might not have these attributes until we receive more messages
                    logging.info("Connected to vehicle (limited information available)")
                
                self.connected = True
                return True
            else:
                logging.error("Failed to receive heartbeat from ArduPilot!")
                return False
        except Exception as e:
            logging.error(f"Exception in wait_for_heartbeat: {e}")
            return False
        
    def start(self):
        if not self.wait_for_heartbeat():
            logging.warning("Starting anyway without ArduPilot connection confirmation")
        
        self.heartbeat_thread.start()
        self.receive_thread.start()
        self.obstacle_thread.start()
        
    def stop(self):
        self.time_to_exit = True
        self.heartbeat_thread.join()
        self.receive_thread.join()
        self.obstacle_thread.join()
        self.conn.close()
        
    def receive_data(self):
        while not self.time_to_exit:
            try:
                message = self.conn.recv_match(type='ATTITUDE', timeout=0.5, blocking=True)
                if message:
                    self.vehicle_pitch_rad = message.pitch
                    if self.debug_enable == 1:
                        logging.info("INFO: Received ATTITUDE msg, current pitch is %.2f degrees" % (m.degrees(self.vehicle_pitch_rad),))
                    if not self.connected:
                        logging.info("Connection to ArduPilot confirmed (received ATTITUDE message)")
                        self.connected = True
            except Exception as e:
                logging.error("Error while receiving data: %s" % e)
                time.sleep(0.01)
       
    def send_heartbeat(self):
        while not self.time_to_exit:
            try:
                self.conn.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE
                )
            except Exception as e:
                logging.error("Error while sending heartbeat: %s" % e)
            
            time.sleep(1)
            
    def send_obstacles(self):
        while not self.time_to_exit:
            try:
                # Expecting (distances, sensing_time, sensor_type)
                distances, sensing_time, sensor_type = self.obstacle_queue.popleft() # Use popleft for FIFO
                self.send_obstacle_distance_message(sensing_time, distances, sensor_type)
            except IndexError as e:
                # Queue is empty, wait a bit
                time.sleep(0.005) # Shorter sleep as queue might fill faster
            except Exception as e:
                logging.error(f"Error in send_obstacles loop: {e}")
                time.sleep(0.01) # Prevent fast error loops
            
    def send_obstacle_distance_message(self, sensing_time, distances, sensor_type):
        if sensor_type not in self.camera_params:
            logging.warning(f"Received data for unconfigured sensor_type {sensor_type}. Ignoring.")
            return
        
        params = self.camera_params[sensor_type]
        last_sent_time = self.last_obstacle_distance_sent_ms.get(sensor_type, 0)

        if sensing_time == last_sent_time:
            # no new frame for this specific sensor
            return
        
        self.last_obstacle_distance_sent_ms[sensor_type] = sensing_time

        try:
            self.conn.mav.obstacle_distance_send(
                sensing_time,           # us Timestamp (UNIX time or time since system boot)
                sensor_type,            # sensor_type, defined here: https://mavlink.io/en/messages/common.html#MAV_DISTANCE_SENSOR
                distances,              # distances,    uint16_t[72],   cm
                0,                      # increment,    uint8_t,        deg - Standard says 0 if increment_f is used.
                params['min_depth_cm'], # min_distance, uint16_t,       cm
                params['max_depth_cm'], # max_distance, uint16_t,       cm
                params['increment_f'],  # increment_f,  float,          deg
                params['angle_offset'], # angle_offset, float,          deg
                params['frame']         # MAV_FRAME, see https://mavlink.io/en/messages/common.html#MAV_FRAME_BODY_FRD
            )
        except Exception as e:
            logging.error(f"Failed to send obstacle distance message for sensor {sensor_type}: {e}")
        
    def configure_sensor(self, sensor_type, min_depth_cm, max_depth_cm, angle_offset, increment_f, frame):
        """Configure parameters for a specific sensor_type."""
        self.camera_params[sensor_type] = {
            'min_depth_cm': min_depth_cm,
            'max_depth_cm': max_depth_cm,
            'angle_offset': angle_offset,
            'increment_f': increment_f,
            'frame': frame
        }
        self.last_obstacle_distance_sent_ms[sensor_type] = 0 # Reset last sent time on config
        logging.info(f"Configured Mavlink parameters for sensor_type {sensor_type}:")
        logging.info(f"  min_depth_cm: {min_depth_cm}, max_depth_cm: {max_depth_cm}")
        logging.info(f"  angle_offset: {angle_offset:.3f}, increment_f: {increment_f:.3f}, frame: {frame}")
        
class RealsenseService:
    
    # Class attribute for camera discovery
    DS5_product_ids = [
        "0AD1", "0AD2", "0AD3", "0AD4", "0AD5", "0AF6", "0AFE", 
        "0AFF", "0B00", "0B01", "0B03", "0B07", "0B3A", "0B5C"
    ]
    
    # Track active cameras to avoid using the same device twice
    active_camera_serials = set()
    
    def __init__(self):
        try:
            self.settings = Settings()    
        
            # RTSP streaming configuration
            self.RTSP_STREAMING_ENABLE = self.settings.rtsp_enable
            self.COLORIZATION_ENABLE = self.settings.colorization_enable
            self.VIDEO_ENABLE = self.settings.video_enable
            self.RTSP_PORT = "3355"
            # Define mount points for front and back cameras
            self.FRONT_VIDEO_MOUNT_POINT = "/front/video"
            self.FRONT_DEPTH_MOUNT_POINT = "/front/depth"
            self.BACK_VIDEO_MOUNT_POINT = "/back/video"
            self.BACK_DEPTH_MOUNT_POINT = "/back/depth"
            
            signal.signal(signal.SIGINT, self.exit_int)
            signal.signal(signal.SIGTERM, self.exit_term)
            
            # Common configuration parameters - can be moved to settings
            self.depth_width = 640
            self.depth_height = 480
            self.color_width = 640
            self.color_height = 480
            self.depth_fps = 15
            self.color_fps = 15
            self.depth_range_m = (0.1, 8.0)
            self.use_preset = self.settings.use_preset
            self.preset_file = "./cfg/d4xx-default.json"
            self.obstacle_line_height_ratio = 0.18
            self.obstacle_line_thickness_pixel = 10

            # Create camera instances
            # Front camera (0 degrees - facing forward)
            self.front_camera = ManagedCamera(
                camera_name="front",
                serial_number=self.settings.front_serial,
                depth_width=self.depth_width,
                depth_height=self.depth_height,
                color_width=self.color_width,
                color_height=self.color_height,
                depth_fps=self.depth_fps,
                color_fps=self.color_fps,
                depth_range_m=self.depth_range_m,
                use_preset=self.use_preset,
                preset_file=self.preset_file,
                camera_facing_angle_degree=0,  # Front-facing
                sensor_type=FRONT_CAM_SENSOR_TYPE,
                frame_type=FRONT_CAM_FRAME,
                obstacle_line_height_ratio=self.obstacle_line_height_ratio,
                obstacle_line_thickness_pixel=self.obstacle_line_thickness_pixel
            )
            
            # Back camera (180 degrees - facing backward)
            self.back_camera = ManagedCamera(
                camera_name="back",
                serial_number=self.settings.back_serial,
                depth_width=self.depth_width,
                depth_height=self.depth_height,
                color_width=self.color_width,
                color_height=self.color_height,
                depth_fps=self.depth_fps,
                color_fps=self.color_fps,
                depth_range_m=self.depth_range_m,
                use_preset=self.use_preset,
                preset_file=self.preset_file,
                camera_facing_angle_degree=180,  # Rear-facing
                sensor_type=BACK_CAM_SENSOR_TYPE,
                frame_type=BACK_CAM_FRAME,
                obstacle_line_height_ratio=self.obstacle_line_height_ratio,
                obstacle_line_thickness_pixel=self.obstacle_line_thickness_pixel
            )

            # Store cameras in a list for easier iteration
            self.cameras = []
            if self.settings.front_serial:
                self.cameras.append(self.front_camera)
            if self.settings.back_serial:
                self.cameras.append(self.back_camera)

            # System state
            self.time_to_exit = False
            self.device_id = None
            self.camera_name = None
            self.pipe = None
            self.depth_scale = 0
            self.depth_hfov_deg = None
            self.depth_vfov_deg = None
            self.colorizer = rs.colorizer()
            
            # 7 is white close black far
            self.colorizer.set_option(rs.option.color_scheme, 7)
            self.colorizer.set_option(rs.option.min_distance, 1.0)
            self.colorizer.set_option(rs.option.max_distance, 2.5)
            
            self.min_depth_cm = int(self.depth_range_m[0] * 100)  # In cm
            self.max_depth_cm = int(self.depth_range_m[1] * 100)  # In cm, should be a little conservative
            self.distances_array_length = 72
            self.angle_offset = None
            self.increment_f  = None
            self.distances = np.ones((self.distances_array_length,), dtype=np.uint16) * (self.max_depth_cm + 1)
            
            self.debug_enable = False
            self.display_name  = 'Input/output depth'
            self.last_time = time.time()
            
            self.video_thread = None
            
            self.glib_loop = None
            self.gst_server = None
            
            if self.RTSP_STREAMING_ENABLE:
                logging.info("Initializing RTSP streaming...")
                Gst.init(None)
                self.gst_server = GstServer(self.RTSP_PORT)
                self.glib_loop = GLib.MainLoop()
                self.video_thread = threading.Thread(target=self.glib_loop.run, args=())
            else:
                logging.info("RTSP streaming disabled.")
            
            self.mavlink = MavlinkIntegration(
                self.settings.mavlink_device, self.settings.baudrate
            )
            
            self.camera_thread = threading.Thread(target=self.camera_reader)
        except Exception as e:
            logging.error(f"Error during initialization: {e}")
            logging.error(traceback.format_exc())
            raise

    def start(self):
        try:
            # Start mavlink first
            self.mavlink.start()

            # Initialize cameras if available
            if not self.cameras:
                logging.warning("No cameras were configured! Check serial numbers.")
                return

            # Find devices for each camera
            active_cameras = []
            for camera in self.cameras:
                if camera.find_device():
                    if camera.configure_advanced_settings():
                        logging.info(f"Advanced settings applied for {camera.camera_name} camera")
                    if camera.connect(enable_color=self.RTSP_STREAMING_ENABLE and self.VIDEO_ENABLE):
                        active_cameras.append(camera)
                        # Track active serials to avoid using the same device twice
                        RealsenseService.active_camera_serials.add(camera.serial_number)
                    else:
                        logging.error(f"Failed to connect to {camera.camera_name} camera")
                else:
                    logging.error(f"Failed to find {camera.camera_name} camera")

            # Update camera list to only include active cameras
            self.cameras = active_cameras
            if not self.cameras:
                logging.error("No cameras were successfully initialized!")
                return

            # Configure RTSP streaming for each camera if enabled
            if self.RTSP_STREAMING_ENABLE and self.gst_server is not None:
                for camera in self.cameras:
                    # Set up mount points based on camera name
                    if camera.camera_name == "front":
                        video_mount = self.FRONT_VIDEO_MOUNT_POINT
                        depth_mount = self.FRONT_DEPTH_MOUNT_POINT
                    elif camera.camera_name == "back":
                        video_mount = self.BACK_VIDEO_MOUNT_POINT
                        depth_mount = self.BACK_DEPTH_MOUNT_POINT
                    else:
                        # Default fallback for any other camera names
                        video_mount = f"/{camera.camera_name}/video"
                        depth_mount = f"/{camera.camera_name}/depth"

                    # Configure color video stream if enabled
                    if self.VIDEO_ENABLE:
                        self.gst_server.configure_video(
                            camera.COLOR_FPS, camera.COLOR_WIDTH, camera.COLOR_HEIGHT, 
                            video_mount
                        )
                        camera.video_stream = self.gst_server.normal_video
                        logging.info(f"RTSP stream for {camera.camera_name} video: rtsp://0.0.0.0:{self.RTSP_PORT}{video_mount}")

                    # Configure colorized depth stream if enabled
                    if self.COLORIZATION_ENABLE:
                        self.gst_server.configure_depth(
                            camera.DEPTH_FPS, camera.DEPTH_WIDTH, camera.DEPTH_HEIGHT, 
                            depth_mount
                        )
                        camera.colorized_stream = self.gst_server.colorized_video
                        logging.info(f"RTSP stream for {camera.camera_name} depth: rtsp://0.0.0.0:{self.RTSP_PORT}{depth_mount}")

                    # Store GST server reference in camera
                    camera.gst_server = self.gst_server

                # Start RTSP server thread
                self.video_thread.start()

            # Start camera processing threads
            for camera in self.cameras:
                camera.start_processing(
                    self.mavlink,
                    rtsp_enabled=self.RTSP_STREAMING_ENABLE,
                    video_enabled=self.VIDEO_ENABLE,
                    colorization_enabled=self.COLORIZATION_ENABLE
                )
                
        except Exception as e:
            logging.error(f"Error during startup: {e}")
            logging.error(traceback.format_exc())
            self.stop()
            raise
            
    def stop(self):
        self.time_to_exit = True

        # Stop all cameras
        for camera in self.cameras:
            camera.stop_processing()

        # Stop Mavlink
        self.mavlink.stop()

        # Stop RTSP server
        if self.glib_loop:
            self.glib_loop.quit()
            if self.video_thread and self.video_thread.is_alive():
                self.video_thread.join()

    def exit_int(self, sig, frame):
        logging.info("Caught SIGINT, shutting down...")
        self.stop()
        sys.exit(0)
        
    def exit_term(self, sig, frame):
        logging.info("Caught SIGTERM, shutting down...")
        self.stop()
        sys.exit(0)

    def camera_reader(self):
        """
        Main camera processing loop for the service
        """
        while not self.time_to_exit:
            try:
                time.sleep(0.1)  # Sleep to prevent busy waiting
            except Exception as e:
                logging.error(f"Error in camera reader: {e}")
                time.sleep(0.1)

if __name__ == "__main__":
    service = RealsenseService()
    service.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
        logging.info("Exiting...")