#!/bin/bash

# Script to kill all GStreamer processes
# This will stop all video encoders and audio encoders

echo "Stopping all GStreamer processes..."

# Function to log messages
log_message() {
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $1"
}

# Kill all gst-launch processes
log_message "Killing gst-launch-1.0 processes..."
pkill -f "gst-launch-1.0"

# Kill any remaining gstreamer processes
log_message "Killing any remaining GStreamer processes..."
pkill -f "gstreamer"
pkill -f "gst-"

# Kill specific encoder scripts if they're running
log_message "Killing encoder scripts..."
pkill -f "video_storage_encoder_with_audio.sh"
pkill -f "video_software_encoder.sh"
pkill -f "video_combined_storage_and_stream.sh"
pkill -f "audio_encoder.sh"

# Wait a moment for processes to terminate
sleep 2

# Check if any GStreamer processes are still running
REMAINING_GST=$(pgrep -f "gst-launch-1.0" | wc -l)
REMAINING_SCRIPTS=$(pgrep -f "encoder.sh" | wc -l)

if [ $REMAINING_GST -eq 0 ] && [ $REMAINING_SCRIPTS -eq 0 ]; then
    log_message "All GStreamer processes stopped successfully."
else
    log_message "Warning: Some processes may still be running. Attempting force kill..."
    
    # Force kill any remaining processes
    pkill -9 -f "gst-launch-1.0"
    pkill -9 -f "gstreamer"
    pkill -9 -f "encoder.sh"
    
    sleep 1
    
    # Final check
    FINAL_GST=$(pgrep -f "gst-launch-1.0" | wc -l)
    FINAL_SCRIPTS=$(pgrep -f "encoder.sh" | wc -l)
    
    if [ $FINAL_GST -eq 0 ] && [ $FINAL_SCRIPTS -eq 0 ]; then
        log_message "All processes forcefully terminated."
    else
        log_message "Error: Some processes could not be terminated. Manual intervention may be required."
        log_message "Remaining GStreamer processes:"
        pgrep -f "gst-launch-1.0" -l
        log_message "Remaining encoder scripts:"
        pgrep -f "encoder.sh" -l
    fi
fi

log_message "GStreamer cleanup completed."
