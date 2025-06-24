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

# Function to check if audio encoder is running and providing audio stream
check_audio_encoder() {
    # Check if audio_encoder.sh is running
    if pgrep -f "audio_encoder.sh" > /dev/null; then
        log_message "Audio encoder is running - will use UDP audio stream on port 5011"
        return 0
    else
        log_message "Warning: Audio encoder is not running. Audio will be disabled."
        return 1
    fi
}

# Function to run GStreamer with logging
run_gstreamer_with_logging() {
    local timestamp=$1
    local audio_available=$2
    
    if [ $audio_available -eq 0 ]; then
        log_message "Recording with audio from UDP stream (port 5011)"
        # Enhanced pipeline with audio support (video + UDP audio stream)
        timeout 3630 gst-launch-1.0 -e \
            mpegtsmux name=mux ! \
                hlssink playlist-root=file://$OUTPUT_DIR \
                         target-duration=60 playlist-length=60 max-files=0 \
                         playlist-location="$OUTPUT_DIR/${timestamp}_playlist.m3u8" \
                         location="$OUTPUT_DIR/${timestamp}_segment_%05d.ts" \
            rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
                rtph264depay ! h264parse ! \
                avdec_h264 ! videoconvert ! \
                x264enc speed-preset=veryfast bitrate=12000 key-int-max=50 bframes=0 ! \
                h264parse config-interval=1 ! \
                queue max-size-buffers=100 max-size-time=1000000000 ! \
                mux. \
            udpsrc port=5011 caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=111" ! \
                rtpopusdepay ! opusdec ! \
                audioconvert ! audioresample ! \
                audio/x-raw,rate=48000,channels=2 ! \
                queue max-size-buffers=200 max-size-time=2000000000 ! \
                avenc_aac bitrate=128000 ! aacparse ! mux. &
    else
        log_message "Recording video only (no audio device available)"
        # Video-only pipeline using software encoding
        timeout 3630 gst-launch-1.0 -e \
            rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
            rtph264depay ! h264parse ! \
            avdec_h264 ! videoconvert ! \
            x264enc speed-preset=veryfast bitrate=12000 key-int-max=50 bframes=0 ! \
            h264parse config-interval=1 ! \
            queue max-size-buffers=100 max-size-time=1000000000 ! \
            mpegtsmux ! \
            hlssink playlist-root=file://$OUTPUT_DIR \
            target-duration=60 \
            playlist-length=60 \
            max-files=0 \
            playlist-location="$OUTPUT_DIR/${timestamp}_playlist.m3u8" \
            location="$OUTPUT_DIR/${timestamp}_segment_%05d.ts" &
    fi
    
    local gst_pid=$!
    
    # Keep track of logged files to avoid duplicates
    local logged_files_list="/tmp/logged_segments_${timestamp}.txt"
    touch "$logged_files_list"
    
    # Monitor for new .ts files while GStreamer is running
    while kill -0 $gst_pid 2>/dev/null; do
        # Find all current .ts files for this timestamp
        for ts_file in "$OUTPUT_DIR"/${timestamp}_segment_*.ts; do
            if [ -f "$ts_file" ]; then
                local filename=$(basename "$ts_file")
                # Check if we've already logged this file
                if ! grep -q "^$filename$" "$logged_files_list" 2>/dev/null; then
                    log_message "Created segment file: $filename"
                    echo "$filename" >> "$logged_files_list"
                fi
            fi
        done
        sleep 2
    done
    
    # Clean up the temporary file
    rm -f "$logged_files_list"
    
    wait $gst_pid
    return $?
}

log_message "Starting HLS recording with audio support and 60-minute playlist rotation"

# Check for audio encoder availability
check_audio_encoder
AUDIO_AVAILABLE=$?

# Main recording loop - runs indefinitely
while true; do
    # Generate timestamp for this hour's recording
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    log_message "Creating new playlist: ${TIMESTAMP}_playlist.m3u8"
    
    # Run GStreamer with logging
    run_gstreamer_with_logging "$TIMESTAMP" $AUDIO_AVAILABLE
    
    # Check if gst-launch exited due to an error
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 124 ]; then
        # Exit code 124 means timeout completed normally
        log_message "Error: gst-launch exited with code $EXIT_CODE. Waiting 10 seconds before retry."
        sleep 10
    else
        if [ $AUDIO_AVAILABLE -eq 0 ]; then
            log_message "60-minute recording with UDP audio completed successfully"
        else
            log_message "60-minute recording (video only) completed successfully"
        fi
        # Small pause between recordings
        sleep 2
    fi
done
