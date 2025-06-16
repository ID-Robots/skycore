#!/bin/bash
gst-launch-1.0 -e \
    rtspsrc location=rtsp://192.168.144.25:8554/main.264 latency=50 drop-on-latency=true ! \
    rtph264depay ! h264parse ! \
    avdec_h264 ! \
    videoconvert ! \
    video/x-raw,format=I420 ! \
    videorate max-rate=25 ! \
    x264enc tune=zerolatency speed-preset=ultrafast bitrate=2500 key-int-max=15 bframes=0 ! \
    h264parse config-interval=1 ! \
    video/x-h264,stream-format=byte-stream,alignment=au ! \
    udpsink host=127.0.0.1 port=5010 sync=false
