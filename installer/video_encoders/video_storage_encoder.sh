#!/bin/bash

# Set output directory for video storage
OUTPUT_DIR="/home/skycore/videos"
# Create directory if it doesn't exist
mkdir -p $OUTPUT_DIR

# Log file for recording status
LOG_FILE="$OUTPUT_DIR/recording_log.txt"

# Function to log messages
log_message() {
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $1" >> "$LOG_FILE"
    echo "$1"
}

log_message "Starting HLS recording with 60-minute playlist rotation"

# Main recording loop - runs indefinitely
while true; do
    # Generate timestamp for this hour's recording
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    log_message "Creating new playlist: ${TIMESTAMP}_playlist.m3u8"
    
    # Run GStreamer for 60 minutes (3600 seconds)
    timeout 3600 gst-launch-1.0 -e \
        rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
        rtph264depay ! \
        h264parse ! \
        mpegtsmux ! \
        hlssink playlist-root=file://$OUTPUT_DIR \
        target-duration=60 \
        playlist-length=60 \
        max-files=0 \
        playlist-location="$OUTPUT_DIR/${TIMESTAMP}_playlist.m3u8" \
        location="$OUTPUT_DIR/${TIMESTAMP}_segment_%05d.ts"
    
    # Check if gst-launch exited due to an error
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 124 ]; then
        # Exit code 124 means timeout completed normally
        log_message "Error: gst-launch exited with code $EXIT_CODE. Waiting 10 seconds before retry."
        sleep 10
    else
        log_message "60-minute recording completed successfully"
        # Small pause between recordings
        sleep 2
    fi
done 