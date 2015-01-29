from urlparse import urlparse, parse_qs
import requests


# this functions is originally FROM: http://stackoverflow.com/questions/4356538/how-can-i-extract-video-id-from-youtubes-link-in-python
def youtube_video_id(url):
    """
    Examples:
    - http://youtu.be/SA2iWivDJiE
    - http://www.youtube.com/watch?v=_oPAwA_Udwc&feature=feedu
    - http://www.youtube.com/embed/SA2iWivDJiE
    - http://www.youtube.com/v/SA2iWivDJiE?version=3&amp;hl=en_US
    """
    query = urlparse(url)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ('www.youtube.com', 'youtube.com'):
        if query.path == '/watch':
            p = parse_qs(query.query)
            return p['v'][0]
        if query.path[:7] == '/embed/':
            return query.path.split('/')[2]
        if query.path[:3] == '/v/':
            return query.path.split('/')[2]
    # fail?
    return None


def twitch_channel(url):
    query = urlparse(url)
    channel = query.path.strip('/').split('/')[0] if query.hostname == 'twitch.tv' or query.hostname == 'www.twitch.tv' else None
    return channel if channel else None


def is_live_yt_stream(yt_video_id, yt_key):
    r = requests.get("https://www.googleapis.com/youtube/v3/videos?id={}&part=snippet&key={}".format(yt_video_id, yt_key))
    r.raise_for_status()
    for item in r.json()['items']:
        if item['snippet']['liveBroadcastContent'] == 'live':
            return True

    return False


def is_live_twitch_stream(twitch_channel):
    r = requests.get("https://api.twitch.tv/kraken/streams/{}".format(twitch_channel))
    r.raise_for_status()
    return r.json()['stream'] is not None
