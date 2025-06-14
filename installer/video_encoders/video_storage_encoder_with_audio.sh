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

log_message "Starting HLS recording with audio support and 60-minute playlist rotation"

# Check for audio encoder availability
check_audio_encoder
AUDIO_AVAILABLE=$?

# Main recording loop - runs indefinitely
while true; do
    # Generate timestamp for this hour's recording
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    
    log_message "Creating new playlist: ${TIMESTAMP}_playlist.m3u8"
    
    if [ $AUDIO_AVAILABLE -eq 0 ]; then
        log_message "Recording with audio from UDP stream (port 5011)"
        # Enhanced pipeline with audio support (video + UDP audio stream)
        # Try hardware encoding first, fallback to software if it fails
        timeout 3630 gst-launch-1.0 -e \
            mpegtsmux name=mux ! \
                hlssink playlist-root=file://$OUTPUT_DIR \
                         target-duration=60 playlist-length=60 max-files=0 \
                         playlist-location="$OUTPUT_DIR/${TIMESTAMP}_playlist.m3u8" \
                         location="$OUTPUT_DIR/${TIMESTAMP}_segment_%05d.ts" \
            rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
                rtph264depay ! h264parse ! \
                nvv4l2decoder enable-max-performance=1 disable-dpb=1 ! \
                nvvidconv ! \
                video/x-raw,format=I420 ! \
                videorate max-rate=25 ! \
                x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=15 bframes=0 ! \
                h264parse config-interval=1 ! \
                queue max-size-buffers=100 max-size-time=1000000000 ! \
                mux. \
            udpsrc port=5011 caps="application/x-rtp,media=audio,clock-rate=48000,encoding-name=OPUS,payload=111" ! \
                rtpopusdepay ! opusdec ! \
                audioconvert ! audioresample ! \
                audio/x-raw,rate=48000,channels=2 ! \
                queue max-size-buffers=200 max-size-time=2000000000 ! \
                avenc_aac bitrate=128000 ! aacparse ! mux.
    else
        log_message "Recording video only (no audio device available)"
        # Video-only pipeline using software encoding
        timeout 3630 gst-launch-1.0 -e \
            rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
            rtph264depay ! h264parse ! \
            nvv4l2decoder enable-max-performance=1 disable-dpb=1 ! \
            nvvidconv ! \
            video/x-raw,format=I420 ! \
            videorate max-rate=25 ! \
            x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=15 bframes=0 ! \
            h264parse config-interval=1 ! \
            queue max-size-buffers=100 max-size-time=1000000000 ! \
            mpegtsmux ! \
            hlssink playlist-root=file://$OUTPUT_DIR \
            target-duration=60 \
            playlist-length=60 \
            max-files=0 \
            playlist-location="$OUTPUT_DIR/${TIMESTAMP}_playlist.m3u8" \
            location="$OUTPUT_DIR/${TIMESTAMP}_segment_%05d.ts"
    fi
    
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
