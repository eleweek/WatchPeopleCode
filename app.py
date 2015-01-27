from flask import Flask, render_template
from flask_bootstrap import Bootstrap
import praw
import os
from utils import youtube_video_id, is_live_stream
from bs4 import BeautifulSoup

app = Flask(__name__)
Bootstrap(app)

reddit_user_agent = "/r/WatchPeopleCode app"
youtube_api_key = os.environ['ytokkey']


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


def get_current_live_streams_ids():
    r = praw.Reddit(user_agent=reddit_user_agent)
    r.config.decode_html_entities = True

    submissions = list(r.get_subreddit('watchpeoplecode').get_new(limit=10))
    submission_urls = [s.url for s in submissions]
    selfposts_urls = sum([extract_links_from_selftexts(s.selftext_html) for s in submissions if s.selftext_html], [])
    youtube_ids = set(filter(None, [youtube_video_id(s) for s in selfposts_urls + submission_urls]))
    live_stream_ids = [yt_id for yt_id in youtube_ids if is_live_stream(yt_id, youtube_api_key)]

    return live_stream_ids


@app.route('/')
def index():
    live_stream_ids = get_current_live_streams_ids()
    print live_stream_ids
    return render_template('index.html', live_stream_ids=live_stream_ids*2)


if __name__ == '__main__':
    app.run(debug=True)
