from apscheduler.schedulers.blocking import BlockingScheduler
import praw
from bs4 import BeautifulSoup
from sqlalchemy import or_

from app import db, Stream, YoutubeStream, TwitchStream
from utils import youtube_video_id, twitch_channel


def get_new_stream_from_url(url):
    ytid = youtube_video_id(url)
    if ytid is not None:
        if YoutubeStream.query.filter_by(ytid=ytid).first() is None:
            return YoutubeStream(ytid)
        else:
            return None

    tc = twitch_channel(url)
    if tc is not None:
        if TwitchStream.query.filter_by(channel=tc).first() is None:
            return TwitchStream(tc)
        else:
            return None

    return None


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


reddit_user_agent = "/r/WatchPeopleCode app"


def get_new_streams():
    r = praw.Reddit(user_agent=reddit_user_agent)
    r.config.decode_html_entities = True

    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
    new_streams = set()
    # TODO : don't forget about http vs https
    # TODO better way of caching api requests
    for s in submissions:
        selfposts_urls = extract_links_from_selftexts(s.selftext_html) if s.selftext_html else []
        for url in selfposts_urls + [s.url]:
            # FIXME super ugly workaround :(
            for i in xrange(10):
                try:
                    stream = get_new_stream_from_url(url)
                    break
                except:
                    if i == 9:
                        raise

            if stream:
                stream._get_api_status()
                db.session.add(stream)
                new_streams.add(stream)

    db.session.commit()


sched = BlockingScheduler()


@sched.scheduled_job('interval', seconds=20)
def update_state():
    for ls in Stream.query.filter(or_(Stream.status != 'completed', Stream.status == None)):
        try:
            ls._get_api_status()
        except Exception as e:
            db.session.rollback()
            print e
            raise

    try:
        get_new_streams()
    except Exception as e:
        db.session.rollback()
        print e
        raise

    db.session.commit()

sched.start()
