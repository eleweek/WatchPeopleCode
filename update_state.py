from apscheduler.schedulers.blocking import BlockingScheduler
import praw
from bs4 import BeautifulSoup
from sqlalchemy import or_

from app import db, Stream, YoutubeStream, TwitchStream, app
from utils import youtube_video_id, twitch_channel
import traceback
import datetime


reddit_user_agent = "/r/WatchPeopleCode app"
r = praw.Reddit(user_agent=reddit_user_agent)
r.config.decode_html_entities = True
r.login(app.config['REDDIT_USERNAME'], app.config['REDDIT_PASSWORD'])


def get_stream_from_url(url, submission_id, only_new=False):
    db_stream = None

    ytid = youtube_video_id(url)
    if ytid is not None:
        db_stream = YoutubeStream.query.filter_by(ytid=ytid).first()
        if db_stream is None:
            return YoutubeStream(ytid)

    tc = twitch_channel(url)
    if tc is not None:
        db_stream = TwitchStream.query.filter_by(channel=tc, submission_id=submission_id).first()
        if db_stream is None:
            return TwitchStream(tc, submission_id)

    return None if only_new else db_stream


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


def get_submission_urls(submission):
    return [submission.url] + extract_links_from_selftexts(submission.selftext_html) if submission.selftext_html else []


def get_new_streams():
    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
    new_streams = set()
    # TODO : don't forget about http vs https
    # TODO better way of caching api requests
    for s in submissions:
        for url in get_submission_urls(s):
            stream = get_stream_from_url(url, s.id, only_new=True)

            if stream:
                stream._update_status()
                db.session.add(stream)
                new_streams.add(stream)

    db.session.commit()


sched = BlockingScheduler()


@sched.scheduled_job('interval', seconds=50)
def update_flairs():
    try:
        submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
        for s in submissions:
            if s.id == '2v1bnt':
                continue
            for url in get_submission_urls(s):
                stream = get_stream_from_url(url, s.id)
                if stream:
                    flair_choices = s.get_flair_choices()['choices']
                    current_flair_text = s.get_flair_choices()[u'current'][u'flair_text']
                    status_to_flair_text = {"live": u"Live",
                                            "completed": u"Recording Available",  # TODO, careful, only for youtube
                                            "upcoming": u"Upcoming",
                                            None: None}

                    flair_text = status_to_flair_text[stream.status]
                    is_twitch_stream = ('channel' in dir(stream))  # TODO: better way
                    if is_twitch_stream:
                        created_dt = datetime.datetime.utcfromtimestamp(s.created_utc)
                        now = datetime.datetime.utcnow()
                        if now - created_dt > datetime.timedelta(hours=12):
                            flair_text = current_flair_text if current_flair_text == "Finished" else None

                    if flair_text is not None:
                        for fc in flair_choices:
                            if fc[u"flair_text"] == flair_text:
                                s.set_flair(fc[u"flair_text"], fc[u'flair_css_class'])
                    else:
                        s.set_flair('')
    except:
        traceback.print_exc()


@sched.scheduled_job('interval', seconds=20)
def update_state():
    for ls in Stream.query.filter(or_(Stream.status != 'completed', Stream.status == None)):
        try:
            ls._update_status()
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

if __name__ == '__main__':
    sched.start()
