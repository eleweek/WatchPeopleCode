#!/bin/bash
name=$1
id=$2
rtmp_url=`curl http://www.watchpeoplecode.com/admin/streamer/$name/rtmp_redirect/$id`
echo $name, $id, $rtmp_url
if [ ! -z "$rtmp_url" ]; then 
    # /usr/bin/avconv -analyzeduration 1000000 -i rtmp://localhost/live/$1 -c:v copy -c:a copy -f flv $rtmp_url
    ffmpeg -i rtmp://localhost/live/$1 -vcodec copy -acodec copy -f flv $rtmp_url
fi
