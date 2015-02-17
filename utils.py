from urlparse import urlparse, parse_qs
import requests
import re


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
    path_elements = query.path.strip('/').split('/')
    if len(path_elements) == 1:
        channel = path_elements[0] if re.match(r'([\w-]+\.)?twitch\.tv', query.hostname) else None
        return channel if channel else None
    else:
        return None


def requests_get_with_retries(url, retries_num=5):
    # Use a `Session` instance to customize how `requests` handles making HTTP requests.
    session = requests.Session()

    # `mount` a custom adapter that retries failed connections for HTTP and HTTPS requests.
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=retries_num))
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries_num))

    # Rejoice with new fault tolerant behaviour!
    return session.get(url=url)
