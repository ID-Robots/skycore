#!/bin/bash
gst-launch-1.0 \
    rtspsrc latency=10 drop-on-latency=true location=rtsp://192.168.144.25:8554/main.264 ! \
        rtph264depay ! \
        h264parse config-interval=-1 ! \
        nvv4l2decoder \
            disable-dpb=true \
            enable-max-performance=true ! \
        videorate max-rate=25 ! \
        nvv4l2h264enc \
            profile=0 \
            bitrate=5000000 \
            iframeinterval=15 \
            idrinterval=1 \
            maxperf-enable=true \
            poc-type=2 \
            insert-sps-pps=true ! \
        "video/x-h264, stream-format=(string)byte-stream, alignment=(string)au" ! \
        udpsink host=127.0.0.1 port=5010 sync=false