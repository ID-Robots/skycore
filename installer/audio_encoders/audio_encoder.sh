#!/bin/bash

# Function to find ReSpeaker audio device
find_respeaker_device() {
    CARD_NUMBER=$(arecord -l | grep -i respeaker | head -1 | sed 's/card \([0-9]\).*/\1/')
    if [ -z "$CARD_NUMBER" ]; then
        echo "Warning: No ReSpeaker device found. Audio will be disabled." >&2
        return 1
    else
        echo "Found ReSpeaker at card $CARD_NUMBER" >&2
        echo $CARD_NUMBER
        return 0
    fi
}

# Check for ReSpeaker device
RESPEAKER_CARD=$(find_respeaker_device | tail -n 1)
AUDIO_AVAILABLE=$?

# Audio pipeline (if ReSpeaker available)
if [ $AUDIO_AVAILABLE -eq 0 ]; then
    echo "Adding audio stream from ReSpeaker (card $RESPEAKER_CARD) on port 5011"
    gst-launch-1.0 -e \
        alsasrc device=hw:$RESPEAKER_CARD,0 do-timestamp=true ! \
        audio/x-raw,format=S16LE,rate=16000,channels=6 ! \
        audioconvert ! audioresample ! \
        audio/x-raw,rate=48000,channels=2 ! \
        opusenc bitrate=128000 ! \
        rtpopuspay pt=111 ! \
        udpsink host=127.0.0.1 port=5011 sync=false &
else
    echo "No audio device found - audio encoder disabled"
fi

# Wait for all background processes
wait
