#!/bin/sh
# Chroma probe: encode moving colour bars as H.265 4:4:4 on the GPU, one file per way of feeding
# the encoder and per picture size, into /tmp/chroma/NAME.h265, packed as /tmp/chroma.tar for
# chroma_check.py on the PC.
# Found with it (GStreamer 1.28.6, intel-media-driver 26.2.4): given vapostproc's surfaces,
# vah265lpenc smears the colour of the top rows from the first P frame on when the height is not
# a multiple of 16, and shears the whole picture when the width rounded up to 16 is not a
# multiple of 64. 4:2:0 from vapostproc keeps its colour but shears the same way. Frames converted
# on the CPU come out right at every size.
#   chroma_probe.sh [WIDTHxHEIGHT ...]
rm -rf /tmp/chroma
mkdir -p /tmp/chroma
encode="vah265lpenc rate-control=cbr bitrate=20000 b-frames=0 key-int-max=1024 target-usage=7"
parse="h265parse ! video/x-h265,stream-format=byte-stream"

# run NAME SIZE ELEMENTS...
run() {
    name=$1 size=$2
    shift 2
    timeout 20 gst-launch-1.0 -q videotestsrc pattern=smpte horizontal-speed=7 num-buffers=60 \
        ! video/x-raw,format=BGRx,width=${size%x*},height=${size#*x},framerate=60/1 \
        ! "$@" ! $encode ! $parse ! filesink location=/tmp/chroma/$name.h265 2>&1 | grep -v CRITICAL | head -2
}

for size in ${@:-1790x1378 1790x1376 1808x1392 1920x1080 1280x720}; do
    run cpu_$size $size videoconvert n-threads=2 ! video/x-raw,format=VUYA
    run gpu_$size $size vapostproc ! "video/x-raw(memory:VAMemory),format=VUYA"
    run gpu420_$size $size vapostproc ! "video/x-raw(memory:VAMemory),format=NV12"
done
cd /tmp/chroma && tar cf /tmp/chroma.tar ./*.h265
