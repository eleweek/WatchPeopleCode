#!/bin/bash
name=$1
id=$2
rtmp_url=`curl http://www.watchpeoplecode.com/admin/streamer/$name/rtmp_redirect/$id`
/usr/bin/avconv -analyzeduration 1000000 -i rtmp://localhost/live/$1 -c:v copy -c:a copy -f flv $rtmp_url
