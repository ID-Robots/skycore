import pyrealsense2 as rs
import logging

logging.basicConfig(level=logging.INFO)

def list_cameras():
    ctx = rs.context()
    devices = ctx.query_devices()
    
    if len(devices) == 0:
        logging.warning("No RealSense devices found!")
        return
        
    logging.info(f"Found {len(devices)} RealSense device(s):")
    
    for i, dev in enumerate(devices):
        try:
            name = dev.get_info(rs.camera_info.name)
            serial = dev.get_info(rs.camera_info.serial_number)
            product_id = dev.get_info(rs.camera_info.product_id)
            firmware = dev.get_info(rs.camera_info.firmware_version)
            
            logging.info(f"Device {i}:")
            logging.info(f"  Name: {name}")
            logging.info(f"  Serial Number: {serial}")
            logging.info(f"  Product ID: {product_id}")
            logging.info(f"  Firmware Version: {firmware}")
            logging.info("")
            
        except Exception as e:
            logging.error(f"Error getting info for device {i}: {e}")

if __name__ == "__main__":
    list_cameras() 