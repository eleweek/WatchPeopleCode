from apscheduler.schedulers.blocking import BlockingScheduler
import praw
from bs4 import BeautifulSoup
from sqlalchemy import or_
import traceback
import datetime

from app import db, Stream, YoutubeStream, TwitchStream, Streamer, Submission, app
from utils import youtube_video_id, twitch_channel, requests_get_with_retries


reddit_user_agent = "/r/WatchPeopleCode app"
r = praw.Reddit(user_agent=reddit_user_agent)
r.config.decode_html_entities = True
if app.config['REDDIT_PASSWORD']:
    r.login(app.config['REDDIT_USERNAME'], app.config['REDDIT_PASSWORD'])


def get_stream_from_url(url, submission=None, only_new=False):
    assert bool(submission) == bool(only_new)
    db_stream = None

    ytid = youtube_video_id(url)
    if ytid is not None:
        db_stream = YoutubeStream.query.filter_by(ytid=ytid).first()
        if db_stream is None:
            r = requests_get_with_retries(
                "https://www.googleapis.com/youtube/v3/videos?id={}&part=liveStreamingDetails&key={}".format(ytid, app.config['YOUTUBE_KEY']), retries_num=15)
            item = r.json()['items']
            if item:
                if 'liveStreamingDetails' in item[0]:
                    return YoutubeStream(ytid)

    tc = twitch_channel(url)
    if tc is not None:
        db_stream = TwitchStream.query.filter_by(channel=tc).first()
        if db_stream is None:
            return TwitchStream(tc)
        if submission and submission not in db_stream.submissions:
            return db_stream

    return None if only_new else db_stream


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


def get_submission_urls(submission):
    return [submission.url] + (extract_links_from_selftexts(submission.selftext_html) if submission.selftext_html else [])


def get_reddit_username(submission, url):
    if submission.author.name != 'godlikesme' or submission.selftext.find('description') == -1:
        return submission.author.name
    else:
        after_url = submission.selftext[submission.selftext.find(url) + len(url):]
        start = after_url.find('/u/') + 3
        finish = start + after_url[start:].find(' ')
        return after_url[start:finish]


def get_or_create(model, **kwargs):
    instance = model.query.filter_by(**kwargs).first()
    if instance is None:
        instance = model(**kwargs)
        db.session.add(instance)
    return instance


def get_new_streams():
    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
    new_streams = set()
    # TODO : don't forget about http vs https
    # TODO better way of caching api requests
    for s in submissions:
        for url in get_submission_urls(s):
            submission = get_or_create(Submission, submission_id=s.id)
            stream = get_stream_from_url(url, submission, only_new=True)
            if stream:
                stream.add_submission(submission)
                reddit_username = get_reddit_username(s, url)
                if reddit_username is not None:
                    stream.streamer = get_or_create(Streamer, reddit_username=reddit_username)

                stream._update_status()

                db.session.add(stream)
                new_streams.add(stream)

    db.session.commit()


sched = BlockingScheduler()


@sched.scheduled_job('interval', seconds=60)
def update_flairs():
    if not app.config['REDDIT_PASSWORD']:
        return

    try:
        wpc_sub = r.get_subreddit('watchpeoplecode')
        submissions = wpc_sub.get_new(limit=25)
        for s in submissions:
            if s.id == '2v1bnt' or s.id == '2v70uo':  # ignore LCS threads TODO
                continue
            for url in get_submission_urls(s):
                stream = get_stream_from_url(url, None)
                if stream:
                    # set user flair
                    if not wpc_sub.get_flair(s.author)['flair_text']:
                        print "Setting flair to ", s.author
                        wpc_sub.set_flair(s.author, flair_text='Streamer', flair_css_class='text-white background-blue')

                    # set link flairs
                    flair_choices = s.get_flair_choices()['choices']
                    current_flair_text = s.get_flair_choices()[u'current'][u'flair_text']
                    status_to_flair_text = {"live": u"Live",
                                            "completed": u"Recording Available",  # TODO, careful, only for youtube
                                            "upcoming": u"Upcoming",
                                            None: None}

                    flair_text = status_to_flair_text[stream.status]
                    flair_css_text = status_to_flair_text[stream.status]
                    is_twitch_stream = ('channel' in dir(stream))  # TODO: better way
                    if is_twitch_stream:
                        created_dt = datetime.datetime.utcfromtimestamp(s.created_utc)
                        now = datetime.datetime.utcnow()
                        if stream.status == 'completed':
                            flair_text = u'Finished'
                            flair_css_text = u'Finished'
                        if now - created_dt > datetime.timedelta(hours=12):
                            flair_text = current_flair_text if current_flair_text == u"Finished" else None

                    if flair_text is not None:
                        for fc in flair_choices:
                            if fc[u"flair_text"] == flair_css_text:
                                s.set_flair(flair_text, fc[u'flair_css_class'])
                    else:
                        s.set_flair('')
    except:
        traceback.print_exc()


@sched.scheduled_job('interval', seconds=10)
def update_state():
    for ls in Stream.query.filter(or_(Stream.status != 'completed', Stream.status == None)):
        try:
            ls._update_status()
        except Exception as e:
            db.session.rollback()
            traceback.print_exc()
            raise

    try:
        get_new_streams()
    except Exception as e:
        db.session.rollback()
        traceback.print_exc(e)
        raise

    db.session.commit()

if __name__ == '__main__':
    sched.start()
