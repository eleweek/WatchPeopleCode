from wpc import db, app
from wpc.models import Stream, YoutubeStream, TwitchStream, WPCStream, Streamer, Submission, get_or_create
from wpc.utils import youtube_video_id, twitch_channel, wpc_channel, requests_get_with_retries
from wpc.email_notifications import generate_email_notifications, send_email_notifications


from apscheduler.schedulers.blocking import BlockingScheduler
import praw
from bs4 import BeautifulSoup
from sqlalchemy import or_
import datetime
import re


r = praw.Reddit(user_agent=app.config['REDDIT_BOT_USER_AGENT'])
r.config.decode_html_entities = True
if app.config['REDDIT_PASSWORD']:
    r.login(app.config['REDDIT_USERNAME'], app.config['REDDIT_PASSWORD'])


def get_stream_from_url(url, submission_id=None, only_new=False):
    assert bool(submission_id) == bool(only_new)
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
        if submission_id and submission_id not in [s.submission_id for s in db_stream.submissions]:
            return db_stream

    wc = wpc_channel(url)
    if wc is not None:
        db_stream = WPCStream.query.filter_by(channel_name=wc).first()
        if db_stream and submission_id and\
                submission_id not in [s.submission_id for s in db_stream.submissions]:
            return db_stream

    return None if only_new else db_stream


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


def get_submission_urls(submission):
    return [submission.url] + (extract_links_from_selftexts(submission.selftext_html) if submission.selftext_html else [])


def get_reddit_username(submission, url):
    if submission.author.name != 'godlikesme' or not submission.selftext_html or submission.selftext_html.find('<table>') == -1:
        return submission.author.name
    else:
        trs = BeautifulSoup(submission.selftext_html).table.find_all('tr')
        for tr in trs:
            if tr.find(href=url) is not None:
                streamer_link = tr.find(href=re.compile('/u/'))
                return streamer_link.get_text()[3:]
        return None


def get_new_streams():
    if app.config['REDDIT_PASSWORD']:
        moditem = list(r.get_subreddit('watchpeoplecode').get_mod_queue(limit=1))
        if moditem and datetime.datetime.now() - datetime.datetime.utcfromtimestamp(moditem[0].created_utc) < datetime.timedelta(hours=2):
            if Streamer.query.filter_by(reddit_username=moditem[0].author.name).first() is not None:
                moditem[0].approve()
    db.session.close()

    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
    # TODO : don't forget about http vs https
    # TODO better way of caching api requests
    for s in submissions:
        for url in get_submission_urls(s):
            try:
                stream = get_stream_from_url(url, s.id, only_new=True)
                if stream:
                    submission = get_or_create(Submission, submission_id=s.id)
                    stream.add_submission(submission)
                    reddit_username = get_reddit_username(s, url)
                    if reddit_username is not None and stream.streamer is None:
                        stream.streamer = get_or_create(Streamer, reddit_username=reddit_username)

                    stream._update_status()

                    db.session.add(stream)
                    db.session.commit()
                db.session.close()
            except Exception as e:
                app.logger.exception(e)
                db.session.rollback()


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

            db_s = Submission.query.filter_by(submission_id=s.id).first()

            if db_s is None:
                db.session.close()
                continue

            if not db_s.recording_available:
                s.replace_more_comments()
                for author, text in map(lambda c: (c.author, c.body), s.comments) + [(s.author, s.selftext)]:
                    if author is None:
                        continue
                    if author.name == s.author.name and re.search("recording\s+(is)?\s*(now)?\s*available", text, flags=re.IGNORECASE):
                        db_s.recording_available = True
                        db.session.commit()
                new_flair_text = None
                new_flair_css = None
            else:
                new_flair_text = u"Recording Available"
                new_flair_css = u"four"

            db.session.close()

            for url in get_submission_urls(s):
                stream = get_stream_from_url(url, None)
                if stream:
                    # set user flair
                    if not wpc_sub.get_flair(s.author)['flair_text']:
                        wpc_sub.set_flair(s.author, flair_text='Streamer', flair_css_class='text-white background-blue')

                    # set link flairs

                    allow_flair_change = True

                    isnt_youtube_stream = (stream.type != 'youtube')
                    if isnt_youtube_stream:
                        created_dt = datetime.datetime.utcfromtimestamp(s.created_utc)
                        now = datetime.datetime.utcnow()
                        if now - created_dt > datetime.timedelta(hours=24):
                            allow_flair_change = False

                    if allow_flair_change:
                        flair_text, flair_css = stream._get_flair()
                        # Somewhat complex logic for multi-stream submissions
                        # Live > Recording Available > everything else
                        if not new_flair_text or flair_text == "Live" or\
                                (new_flair_text != "Live" and flair_text == "Recording Available") or\
                                (new_flair_text != "Live" and stream.status == "upcoming"):
                            new_flair_text, new_flair_css = flair_text, flair_css

                    if stream.type == 'youtube':
                        db_s.recording_available = True

                db.session.close()

            if new_flair_text and new_flair_css:
                s.set_flair(new_flair_text, new_flair_css)

    except Exception as e:
        db.session.rollback()
        app.logger.exception(e)


def get_bonus_twitch_stream():
    app.logger.info("Getting bonus twitch stream")
    r = requests_get_with_retries("https://api.twitch.tv/kraken/streams?game=Programming")
    streams = sorted([s for s in r.json()['streams']], key=lambda s: s['viewers'], reverse=True)
    print streams
    if streams:
        ts = get_or_create(TwitchStream, channel=streams[0]['channel']['name'])
        ts._update_status()
        db.session.add(ts)
        db.session.commit()


@sched.scheduled_job('interval', seconds=30)
def update_state():
    app.logger.info("Updating old streams")
    for ls in Stream.query.filter(or_(Stream.status != 'completed', Stream.status == None)):  # NOQA
        try:
            ls._update_status()
            app.logger.info("Status of {} is {}".format(ls, ls.status))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            app.logger.exception(e)
    db.session.close()

    app.logger.info("Updating new streams")
    get_new_streams()

    if not db.session.query(Stream.query.filter_by(status='live').exists()).scalar():
        get_bonus_twitch_stream()
    db.session.close()


@sched.scheduled_job('interval', seconds=100)
def send_notifications():
    app.logger.info("Send email notifications")
    with app.app_context():
        for streamer in Streamer.query.filter_by(need_to_notify_subscribers=True):
            try:
                streamer.need_to_notify_subscribers = False
                streamer.last_time_notified = datetime.datetime.utcnow()
                db.session.commit()
                if streamer.streams.filter_by(status='live').count() > 0:
                    try:
                        send_email_notifications(*generate_email_notifications(streamer))
                    except Exception as e:
                        app.logger.exception(e)
            except Exception as e:
                db.session.rollback()
                app.logger.exception(e)

        db.session.close()


if __name__ == '__main__':
    sched.start()
