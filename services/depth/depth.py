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

# Debug print added
print(f"DEBUG: Imported pyrealsense2 as rs: {rs}, File: {getattr(rs, '__file__', 'N/A')}, Has stream: {hasattr(rs, 'stream')}")

os.environ["MAVLINK20"] = "1"
from pymavlink import mavutil
import cv2

import logging
from collections import deque
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib
import argparse

logging.basicConfig(level=logging.INFO)


class Settings:
    
    def __init__(self):
        args = self.parse_args()
        self.mavlink_device = args.connect
        self.baudrate = args.baudrate
        self.rtsp_enable = args.rtsp_enable
        self.video_enable = args.video_enable
        self.colorization_enable = args.colorization_enable
        self.use_preset = args.use_preset
        
        logging.info(f"Connection string: {self.mavlink_device}")
        logging.info(f"RTSP enabled: {self.rtsp_enable}")
    
    def parse_args(self):
        parser = argparse.ArgumentParser(description="Realsense Service")
        parser.add_argument('--connect', type=str, default="/dev/ttyTHS1", help="Mavlink device connection string")
        parser.add_argument('--baudrate', type=int, default=230400, help="Baudrate for mavlink device")
        parser.add_argument('--rtsp_enable', type=bool, default=True, help="Enable RTSP streaming")
        parser.add_argument('--video_enable', type=bool, default=False, help="Enable video streaming")
        parser.add_argument('--colorization_enable', type=bool, default=True, help="Enable colorization streaming")
        parser.add_argument('--use_preset', type=bool, default=True, help="Use preset configuration file")
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
        self.obstacle_queue = deque(maxlen=5)
        
        self.min_depth_cm = 0
        self.max_depth_cm = 0
        self.distances_array_length = 0
        self.angle_offset = 0
        self.increment_f = 0
        self.last_obstacle_distance_sent_ms = 0
        
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
                distances, current_time_us = self.obstacle_queue.pop()
                self.send_obstacle_distance_message(current_time_us, distances)
            except IndexError as e:
                # logging.warning("Could not pop obstacle from obstacle_queue")
                time.sleep(0.01)
            
    def send_obstacle_distance_message(self, sensing_time, distances):
        if sensing_time == self.last_obstacle_distance_sent_ms:
            # no new frame
            return
        
        self.last_obstacle_distance_sent_ms = sensing_time
        if self.angle_offset is None or self.increment_f is None:
            logging.warning("Please call set_obstacle_distance_params before continue")
        else:
            #TODO:FIXME: configure these
            try:
                self.conn.mav.obstacle_distance_send(
                    sensing_time,    # us Timestamp (UNIX time or time since system boot)
                    0,                  # sensor_type, defined here: https://mavlink.io/en/messages/common.html#MAV_DISTANCE_SENSOR
                    distances,          # distances,    uint16_t[72],   cm
                    0,                  # increment,    uint8_t,        deg
                    self.min_depth_cm,	    # min_distance, uint16_t,       cm
                    self.max_depth_cm,       # max_distance, uint16_t,       cm
                    self.increment_f,	    # increment_f,  float,          deg
                    self.angle_offset,       # angle_offset, float,          deg
                    12                  # MAV_FRAME, vehicle-front aligned: https://mavlink.io/en/messages/common.html#MAV_FRAME_BODY_FRD    
                )
                logging.debug(f"Sent obstacle data at {sensing_time}")
            except Exception as e:
                logging.error(f"Failed to send obstacle distance message: {e}")
        
    def configure(self, min_depth_cm, max_depth_cm, distances_array_length, angle_offset, increment_f):
        self.min_depth_cm = min_depth_cm
        self.max_depth_cm = max_depth_cm
        self.distances_array_length = distances_array_length
        self.angle_offset = angle_offset
        self.increment_f = increment_f
        
class RealsenseService:
    
    def __init__(self):
        try:
            self.settings = Settings()    
        
            self.STREAM_TYPE  = [rs.stream.depth, rs.stream.color]  # rs2_stream is a types of data provided by RealSense device
            self.FORMAT       = [rs.format.z16, rs.format.rgba8]     # rs2_format is identifies how binary data is encoded within a frame
            self.DEPTH_WIDTH  = 640               # Defines the number of columns for each frame or zero for auto resolve
            self.DEPTH_HEIGHT = 480               # Defines the number of lines for each frame or zero for auto resolve
            self.COLOR_WIDTH  = 640
            self.COLOR_HEIGHT = 480
            self.DEPTH_FPS          = 15
            self.COLOR_FPS          = 15
            self.DEPTH_RANGE_M = [0.1, 8.0]  
            self.USE_PRESET_FILE = self.settings.use_preset
            self.PRESET_FILE  = "./cfg/d4xx-default.json"
            self.RTSP_STREAMING_ENABLE = self.settings.rtsp_enable
            self.COLORIZATION_ENABLE = self.settings.colorization_enable
            self.VIDEO_ENABLE = self.settings.video_enable
            self.RTSP_PORT = "3355"
            self.VIDEO_MOUNT_POINT = "/video"
            self.COLORIZATION_MOUNT_POINT = "/depth"
            self.camera_facing_angle_degree = 0
            
            self.threshold_min_m = self.DEPTH_RANGE_M[0]
            self.threshold_max_m = self.DEPTH_RANGE_M[1]
            
            signal.signal(signal.SIGINT, self.exit_int)
            signal.signal(signal.SIGTERM, self.exit_term)
            
            self.filters = [
                [False,  "Decimation Filter",   rs.decimation_filter()],
                [True,  "Threshold Filter",    rs.threshold_filter()],
                [True,  "Depth to Disparity",  rs.disparity_transform(True)],
                [True,  "Spatial Filter",      rs.spatial_filter()],
                [True,  "Temporal Filter",     rs.temporal_filter()],
                [False, "Hole Filling Filter", rs.hole_filling_filter()],
                [True,  "Disparity to Depth",  rs.disparity_transform(False)]
            ]
            
            if self.filters[1][0] is True:
                self.filters[1][2].set_option(rs.option.min_distance, self.threshold_min_m)
                self.filters[1][2].set_option(rs.option.max_distance, self.threshold_max_m)
            
            self.filter_to_apply = [
                f[2] for f in self.filters if f[0]
            ]
            
                
            self.obstacle_line_height_ratio = 0.18  # [0-1]: 0-Top, 1-Bottom. The height of the horizontal line to find distance to obstacle.
            self.obstacle_line_thickness_pixel = 10 # [1-DEPTH_HEIGHT]: Number of pixel rows to use to generate the obstacle distance message. For each column, the scan will return the minimum value for those pixels centered vertically in the image.

            self.DS5_product_ids = [
                "0AD1", "0AD2", "0AD3", "0AD4", "0AD5", "0AF6", "0AFE", 
                "0AFF", "0B00", "0B01", "0B03", "0B07", "0B3A", "0B5C"
            ]
            
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
            
            self.min_depth_cm = int(self.DEPTH_RANGE_M[0] * 100)  # In cm
            self.max_depth_cm = int(self.DEPTH_RANGE_M[1] * 100)  # In cm, should be a little conservative
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
            
            self.camera_thread = threading.Thread(target=self.camer_reader)
        except Exception as e:
            logging.error(f"Error during initialization: {e}")
            logging.error(traceback.format_exc())
            raise

    def start(self):
        try:
            if self.USE_PRESET_FILE:
                try:
                    self.realsense_configure_setting(self.PRESET_FILE)
                except Exception as e:
                    logging.warning(f"Failed to configure advanced settings: {e}")
                    logging.warning("Continuing without preset configuration")
            self.realsense_connect()
            self.set_obstacle_distance_params()
            self.find_obstacle_line_height()
            self.configure_depth_shape()
            self.camera_thread.start()
            
            self.mavlink.configure(
                self.min_depth_cm, self.max_depth_cm, 
                self.distances_array_length, 
                self.angle_offset, self.increment_f
            )
            self.mavlink.start()
            
            if self.RTSP_STREAMING_ENABLE and self.gst_server is not None:
                
                if self.VIDEO_ENABLE:
                    self.gst_server.configure_video(
                        self.COLOR_FPS, self.COLOR_WIDTH, self.COLOR_HEIGHT, 
                        self.VIDEO_MOUNT_POINT
                    )
                    logging.info(f"rtsp://0.0.0.0:{self.RTSP_PORT}{self.VIDEO_MOUNT_POINT}")
                
                if self.COLORIZATION_ENABLE:
                    self.gst_server.configure_depth(
                        self.DEPTH_FPS, self.DEPTH_WIDTH, self.DEPTH_HEIGHT, 
                        self.COLORIZATION_MOUNT_POINT
                    )
                    logging.info(f"rtsp://0.0.0.0:{self.RTSP_PORT}{self.COLORIZATION_MOUNT_POINT}")
                
                self.video_thread.start()
        except Exception as e:
            logging.error(f"Error during startup: {e}")
            logging.error(traceback.format_exc())
            self.stop()
            raise
            
    def stop(self):
        self.time_to_exit = True
        self.pipe.stop()
        self.camera_thread.join()
        self.mavlink.stop()
        if self.glib_loop:
            self.glib_loop.quit()
        
        self.video_thread.join()
        
    def find_device_that_supports_advanced_mode(self) :
        ctx = rs.context()
        devices = ctx.query_devices()
        logging.info(f"Found {len(devices)} RealSense devices:")
        for i, dev in enumerate(devices):
            try:
                product_id = str(dev.get_info(rs.camera_info.product_id))
                name = dev.get_info(rs.camera_info.name)
                logging.info(f"  Device {i}: Name={name}, Product ID={product_id}")
                if dev.supports(rs.camera_info.product_id) and product_id in self.DS5_product_ids:
                    logging.info(f"  Device {i} MATCHES. Supports Advanced Mode.")
                    self.device_id = dev.get_info(rs.camera_info.serial_number)
                    return dev
            except Exception as e:
                 logging.error(f"  Error querying info for device {i}: {e}")

        raise Exception("No device that supports advanced mode was found in the enumerated devices.")

    # Loop until we successfully enable advanced mode
    def realsense_enable_advanced_mode(self, advnc_mode):
        while not advnc_mode.is_enabled():
            logging.info("Trying to enable advanced mode...")
            advnc_mode.toggle_advanced_mode(True)
            # At this point the device will disconnect and re-connect.
            logging.info("Sleeping for 5 seconds...")
            time.sleep(5)
            # The 'dev' object will become invalid and we need to initialize it again
            dev = self.find_device_that_supports_advanced_mode()
            advnc_mode = rs.rs400_advanced_mode(dev)
            logging.info("Advanced mode is %s" "enabled" if advnc_mode.is_enabled() else "disabled")

    # Load the settings stored in the JSON file
    def realsense_load_settings_file(self, advnc_mode, setting_file):
        # Sanity checks
        if os.path.isfile(setting_file):
            logging.info("Setting file found %s" % setting_file)
        else:
            logging.info("Cannot find setting file %s" % setting_file)
            exit()

        if advnc_mode.is_enabled():
            logging.info("Advanced mode is enabled")
        else:
            logging.info("Device does not support advanced mode")
            exit()
        
        # Input for load_json() is the content of the json file, not the file path
        with open(setting_file, 'r') as file:
            json_text = file.read().strip()

        advnc_mode.load_json(json_text)

    # Establish connection to the Realsense camera
    def realsense_connect(self):
        # Declare RealSense pipe, encapsulating the actual device and sensors
        self.pipe = rs.pipeline()

        # Configure image stream(s)
        config = rs.config()
        if self.device_id: 
            # connect to a specific device ID
            config.enable_device(self.device_id)
            
            
        config.enable_stream(
            self.STREAM_TYPE[0], self.DEPTH_WIDTH, self.DEPTH_HEIGHT, self.FORMAT[0], self.DEPTH_FPS)
        if self.RTSP_STREAMING_ENABLE is True:
            config.enable_stream(
                self.STREAM_TYPE[1], self.COLOR_WIDTH, self.COLOR_HEIGHT, self.FORMAT[1], self.COLOR_FPS
            )

        # Start streaming with requested config
        profile = self.pipe.start(config)

        # Getting the depth sensor's depth scale (see rs-align example for explanation)
        depth_sensor = profile.get_device().first_depth_sensor()
        self.depth_scale = depth_sensor.get_depth_scale()
        logging.info("Depth scale is: %s" % self.depth_scale)

    def realsense_configure_setting(self, setting_file):
        device = self.find_device_that_supports_advanced_mode()
        advnc_mode = rs.rs400_advanced_mode(device)
        self.realsense_enable_advanced_mode(advnc_mode)
        self.realsense_load_settings_file(advnc_mode, setting_file)

    # Setting parameters for the OBSTACLE_DISTANCE message based on actual camera's intrinsics and user-defined params
    def set_obstacle_distance_params(self):
        
        # Obtain the intrinsics from the camera itself
        profiles = self.pipe.get_active_profile()
        depth_intrinsics = profiles.get_stream(self.STREAM_TYPE[0]).as_video_stream_profile().intrinsics
        logging.info("Depth camera intrinsics: %s" % depth_intrinsics)
        
        # For forward facing camera with a horizontal wide view:
        #   HFOV=2*atan[w/(2.fx)],
        #   VFOV=2*atan[h/(2.fy)],
        #   DFOV=2*atan(Diag/2*f),
        #   Diag=sqrt(w^2 + h^2)
        self.depth_hfov_deg = m.degrees(2 * m.atan(self.DEPTH_WIDTH / (2 * depth_intrinsics.fx)))
        self.depth_vfov_deg = m.degrees(2 * m.atan(self.DEPTH_HEIGHT / (2 * depth_intrinsics.fy)))
        logging.info("Depth camera HFOV: %0.2f degrees" % self.depth_hfov_deg)
        logging.info("Depth camera VFOV: %0.2f degrees" % self.depth_vfov_deg)

        self.angle_offset = self.camera_facing_angle_degree - (self.depth_hfov_deg / 2)
        self.increment_f = self.depth_hfov_deg / self.distances_array_length
        logging.info("OBSTACLE_DISTANCE angle_offset: %0.3f" % self.angle_offset)
        logging.info("OBSTACLE_DISTANCE increment_f: %0.3f" % self.increment_f)
        logging.info("OBSTACLE_DISTANCE coverage: from %0.3f to %0.3f degrees" %
            (self.angle_offset, self.angle_offset + self.increment_f * self.distances_array_length))

        # Sanity check for depth configuration
        if self.obstacle_line_height_ratio < 0 or self.obstacle_line_height_ratio > 1:
            logging.error("Please make sure the horizontal position is within [0-1]: %s"  % self.obstacle_line_height_ratio)
            sys.exit()

        if self.obstacle_line_thickness_pixel < 1 or self.obstacle_line_thickness_pixel > self.DEPTH_HEIGHT:
            logging.error("Please make sure the thickness is within [0-DEPTH_HEIGHT]: %s" % self.obstacle_line_thickness_pixel)
            sys.exit()
            
    def find_obstacle_line_height(self):

        # Basic position
        obstacle_line_height = self.DEPTH_HEIGHT * self.obstacle_line_height_ratio

        # Compensate for the vehicle's pitch angle if data is available
        if self.mavlink.vehicle_pitch_rad is not None and self.depth_vfov_deg is not None:
            delta_height = m.sin(self.mavlink.vehicle_pitch_rad / 2) / m.sin(m.radians(self.depth_vfov_deg) / 2) * self.DEPTH_HEIGHT
            obstacle_line_height += delta_height

        # Sanity check
        if obstacle_line_height < 0:
            obstacle_line_height = 0
        elif obstacle_line_height > self.DEPTH_HEIGHT:
            obstacle_line_height = self.DEPTH_HEIGHT
        
        self.obstacle_line_height = obstacle_line_height
        return obstacle_line_height
    
    def configure_depth_shape(self):
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

    
    def distances_from_depth_image(self, depth_mat, distances, min_depth_m, max_depth_m):
        # TODO: make fast via numpy

        for i in range(self.distances_array_length):
            

            min_point_in_scan = np.min(depth_mat[int(self.lower_pixel):int(self.upper_pixel), int(i * self.step)])
            dist_m = min_point_in_scan * self.depth_scale

            distances[i] = 65535

            # Note that dist_m is in meter, while distances[] is in cm.
            if dist_m > min_depth_m and dist_m < max_depth_m:
                distances[i] = dist_m * 100
        
        return distances
    
    # TODO:FIXME: make it work fast via numpy
    # def distances_from_depth_image_fast(self, depth_mat, distances, min_depth_m, max_depth_m):
    #     # Parameters for depth image
        
    #     # Extract the relevant part of the depth matrix
    #     depth_slice = depth_mat[self.lower_pixel:self.upper_pixel, ::self.step]
        
    #     # Find the minimum depth value in each column
    #     min_points_in_scan = np.min(depth_slice, axis=0)
        
    #     # Convert depth values to meters
    #     dist_m = min_points_in_scan * self.depth_scale
        
    #     # Initialize distances array to 65535
    #     distances.fill(65535)
        
    #     # Apply the depth range filter and convert to centimeters
    #     valid_mask = (dist_m > min_depth_m) & (dist_m < max_depth_m)
    #     distances[valid_mask] = dist_m[valid_mask] * 100
        
    #     return distances
    
    def _filter_dept_frame(self, depth_frame):
        filtered_frame = depth_frame
        for f in self.filter_to_apply:
            filtered_frame = f.process(filtered_frame)
            
        return filtered_frame
        
    
    def _process_depth_frame(self, depth_frame, sensing_time):
        try:
            # Apply the filters
            filtered_frame = self._filter_dept_frame(depth_frame)

            # Extract depth in matrix form
            depth_data = filtered_frame.as_frame().get_data()
            depth_mat = np.asanyarray(depth_data)
            
            # Create obstacle distance data from depth image
            distances = self.distances_from_depth_image(
                depth_mat, 
                self.distances, self.DEPTH_RANGE_M[0], 
                self.DEPTH_RANGE_M[1]
            )
            
            self.mavlink.obstacle_queue.append((distances, sensing_time,))

            if self.RTSP_STREAMING_ENABLE and self.COLORIZATION_ENABLE and self.gst_server is not None and self.gst_server.colorized_video is not None:
                # Use CPU-based processing instead of CUDA
                depth_colormap = np.asanyarray(self.colorizer.colorize(filtered_frame).get_data())
                
                # Convert to RGBA without using CUDA
                colorized_frame = cv2.cvtColor(depth_colormap, cv2.COLOR_BGR2RGBA)
                
                self.gst_server.colorized_video.add_to_buffer(colorized_frame)
        except Exception as e:
            logging.error(f"Error processing depth frame: {e}")

    def _process_color_frame(self, color_frame):
        try:
            if self.gst_server is not None and self.gst_server.normal_video is not None:
                color_image = np.asanyarray(color_frame.get_data())
                self.gst_server.normal_video.add_to_buffer(color_image)
        except Exception as e:
            logging.error(f"Error processing color frame: {e}")
    
    def camer_reader(self):
        while not self.time_to_exit:
            try:
                # This call waits until a new coherent set of frames is available on a device
                # Calls to get_frame_data(...) and get_frame_timestamp(...) on a device will return stable values until wait_for_frames(...) is called
                frames = self.pipe.wait_for_frames()
                
                depth_frame = frames.get_depth_frame()
                # sensing_time = int(round(time.time() * 1000000))
                sensing_time = int(round(depth_frame.timestamp * 1000))
                
                if depth_frame:
                    self._process_depth_frame(depth_frame, sensing_time)
                
                if self.RTSP_STREAMING_ENABLE and self.VIDEO_ENABLE and self.gst_server is not None:
                    color_frame = frames.get_color_frame()
                    if color_frame:               
                        self._process_color_frame(color_frame)
                
            except Exception as e:
                logging.error(f"Error while reading camera: {e}")
                time.sleep(0.1)

    def exit_int(self, sig, frame):
        logging.info("Caught SIGINT, shutting down...")
        self.stop()
        sys.exit(0)
        
    def exit_term(self, sig, frame):
        logging.info("Caught SIGTERM, shutting down...")
        self.stop()
        sys.exit(0)

if __name__ == "__main__":
    service = RealsenseService()
    service.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
        logging.info("Exiting...")