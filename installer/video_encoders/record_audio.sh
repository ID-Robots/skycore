#!/bin/bash

# Simple audio recording script for testing ReSpeaker microphone
# Usage: ./record_audio.sh [duration_in_seconds] [output_filename]

# Default values
DURATION=${1:-10}  # Default 10 seconds
OUTPUT_FILE=${2:-"audio_test_$(date +%Y%m%d_%H%M%S).wav"}
DEVICE="respeaker"

echo "🎤 Audio Recording Test Script"
echo "==============================="
echo "Device: $DEVICE"
echo "Duration: $DURATION seconds"
echo "Output file: $OUTPUT_FILE"
echo ""

# Check if arecord is available
if ! command -v arecord &> /dev/null; then
    echo "❌ Error: arecord not found. Please install alsa-utils:"
    echo "   sudo apt-get install alsa-utils"
    exit 1
fi

# List available audio devices
echo "📋 Available audio devices:"
arecord -l
echo ""

# Try to find ReSpeaker device
echo "🔍 Looking for ReSpeaker device..."
CARD_NUMBER=$(arecord -l | grep -i respeaker | head -1 | sed 's/card \([0-9]\).*/\1/')

if [ -z "$CARD_NUMBER" ]; then
    echo "⚠️  Warning: No ReSpeaker device found in device list."
    echo "   Available devices:"
    arecord -l | grep "card"
    echo ""
    echo "   Please specify the correct card number manually or check device connection."
    echo "   You can also try running with a specific device:"
    echo "   arecord -D hw:CARD_NUMBER,0 -f S16_LE -r 16000 -c 6 -d $DURATION $OUTPUT_FILE"
    exit 1
else
    echo "✅ Found ReSpeaker at card $CARD_NUMBER"
fi

# Record audio
echo ""
echo "🔴 Starting recording in 3 seconds..."
echo "   Speak into your microphone to test it!"
sleep 1
echo "   3..."
sleep 1
echo "   2..."
sleep 1
echo "   1..."
sleep 1
echo "   🎙️  RECORDING NOW! (${DURATION}s)"

# Record with specific parameters for ReSpeaker
arecord -D hw:$CARD_NUMBER,0 \
        -f S16_LE \
        -r 16000 \
        -c 6 \
        -d $DURATION \
        "$OUTPUT_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Recording completed successfully!"
    echo "   File: $OUTPUT_FILE"
    echo "   Size: $(ls -lh "$OUTPUT_FILE" | awk '{print $5}')"
    echo ""
    echo "🔊 To play back the recording:"
    echo "   aplay $OUTPUT_FILE"
    echo ""
    echo "   Or with volume control:"
    echo "   aplay $OUTPUT_FILE || paplay $OUTPUT_FILE"
else
    echo ""
    echo "❌ Recording failed. Please check:"
    echo "   1. ReSpeaker device is connected"
    echo "   2. Device permissions (try with sudo if needed)"
    echo "   3. Audio drivers are installed"
fi
