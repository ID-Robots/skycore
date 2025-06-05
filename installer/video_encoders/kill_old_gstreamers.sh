#!/bin/bash

# Kill Old GStreamer Processes Script
# This script cleans up any running gst-launch processes that might be blocking audio/video devices

echo "🧹 GStreamer Process Cleanup Script"
echo "===================================="

# Function to cleanup old GStreamer processes
cleanup_old_processes() {
    echo "🔍 Searching for running GStreamer processes..."
    
    # Find and display all gst-launch processes
    PROCESS_LIST=$(ps aux | grep gst-launch | grep -v grep)
    
    if [ ! -z "$PROCESS_LIST" ]; then
        echo "📋 Found running GStreamer processes:"
        echo "$PROCESS_LIST"
        echo ""
        
        # Extract PIDs
        OLD_PIDS=$(echo "$PROCESS_LIST" | awk '{print $2}')
        
        echo "🔫 Terminating processes (SIGTERM): $OLD_PIDS"
        echo $OLD_PIDS | xargs kill 2>/dev/null
        sleep 3
        
        # Check if any processes are still running
        REMAINING_LIST=$(ps aux | grep gst-launch | grep -v grep)
        if [ ! -z "$REMAINING_LIST" ]; then
            REMAINING_PIDS=$(echo "$REMAINING_LIST" | awk '{print $2}')
            echo "💀 Force killing remaining processes (SIGKILL): $REMAINING_PIDS"
            echo $REMAINING_PIDS | xargs kill -9 2>/dev/null
            sleep 1
            
            # Final check
            FINAL_CHECK=$(ps aux | grep gst-launch | grep -v grep)
            if [ ! -z "$FINAL_CHECK" ]; then
                echo "❌ Warning: Some processes may still be running:"
                echo "$FINAL_CHECK"
            else
                echo "✅ All GStreamer processes successfully terminated"
            fi
        else
            echo "✅ All GStreamer processes successfully terminated"
        fi
    else
        echo "✅ No running GStreamer processes found"
    fi
    
    echo ""
    echo "🎤 Audio devices should now be available"
    echo "📹 Video pipeline resources freed"
}

# Run the cleanup
cleanup_old_processes

# Optional: Show available audio devices
if command -v arecord &> /dev/null; then
    echo ""
    echo "🎵 Available audio capture devices:"
    arecord -l | grep "card" | head -5
fi

echo ""
echo "Done! 🎬"
