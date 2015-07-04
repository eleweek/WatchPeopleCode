from wpc import db, app, login_manager
from wpc.utils import requests_get_with_retries
from wpc.flask_utils import get_or_create

from flask.ext.login import UserMixin, AnonymousUserMixin, current_user
from sqlalchemy.orm.properties import ColumnProperty
from flask import url_for, request, render_template

import humanize
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


@login_manager.user_loader
def load_user(reddit_username):
    return Streamer.query.filter_by(reddit_username=reddit_username).first()


class Anon(AnonymousUserMixin):
    def already_subscribed(self, streamer):
        email = request.cookies.get("email")
        return email and streamer and get_or_create(Subscriber, email=email) in streamer.subscribers

login_manager.anonymous_user = Anon

stream_sub = db.Table('stream_sub',
                      db.Column('stream_id', db.Integer(), db.ForeignKey('stream.id')),
                      db.Column('submission_id', db.String(6), db.ForeignKey('submission.submission_id')))

streamer_subscriptions = db.Table('streamer_subscriptions',
                                  db.Column('streamer_id', db.Integer(), db.ForeignKey('streamer.id')),
                                  db.Column('subscriber_id', db.Integer(), db.ForeignKey('subscriber.id')))


class Submission(db.Model):
    submission_id = db.Column(db.String(6), primary_key=True)
    recording_available = db.Column(db.Boolean())

    def __repr__(self):
        return '<Submission {}>'.format(self.submission_id)


class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50))
    scheduled_start_time = db.Column(db.DateTime())
    actual_start_time = db.Column(db.DateTime())
    status = db.Column(db.Enum('upcoming', 'live', 'completed', name='stream_status'))
    title = db.Column(db.String(200))
    submissions = db.relationship('Submission', secondary=stream_sub, backref=db.backref('streams', lazy='dynamic'))
    streamer_id = db.Column('streamer_id', db.Integer(), db.ForeignKey('streamer.id'))
    streamer = db.relationship('Streamer', backref=db.backref('streams', lazy='dynamic'))
    current_viewers = db.Column(db.Integer)
    confstream = db.Column(db.Boolean(), default=False)
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'stream'
    }

    def format_start_time(self, countdown=True, start_time=True):
        if not self.scheduled_start_time or (not countdown and not start_time):
            return None

        if countdown:
            return humanize.naturaltime(datetime.utcnow() - self.scheduled_start_time) +\
                ((", " + datetime.strftime(self.scheduled_start_time, "%Y-%m-%d %H:%M UTC")) if start_time else "")
        else:
            return datetime.strftime(self.scheduled_start_time, "%Y-%m-%d %H:%M UTC")

    def add_submission(self, submission):
        if submission not in self.submissions:
            self.submissions.append(submission)

    def _go_live(self):
        if self.status != 'live' and self.streamer and\
            self.streamer.checked and\
            (self.streamer.last_time_notified is None or
                (datetime.utcnow() - self.streamer.last_time_notified) > timedelta(hours=1)):
            self.streamer.need_to_notify_subscribers = True
        self.status = 'live'


class WPCStream(Stream):
    channel_name = db.Column(db.String(30), unique=True)
    chat_anon_forbidden = db.Column(db.Boolean, default=False)

    def __init__(self, channel_name):
        self.status = 'upcoming'
        self.channel_name = channel_name
        self.submissions = []

    def __eq__(self, other):
        return type(self) == type(other) and self.channel_name == other.channel_name

    def __hash__(self):
        return hash(self.channel_name)

    def __repr__(self):
        return '<WPC Stream {} {}>'.format(self.id, self.channel_name)

    def _update_status(self):
        app.logger.info("Updating status for {}".format(self))
        r = requests_get_with_retries(
            "http://{}:{}@{}/stat".format(
                app.config['RTMP_LOGIN'], app.config['RTMP_PASSWORD'], app.config['RTMP_SERVER']))
        r.raise_for_status()

        soup = BeautifulSoup(r.content, 'xml')
        for stream in soup.find_all('stream'):
            if stream.find('name').string == self.channel_name:
                client_num = int(stream.find('nclients').string)
                is_live = stream.find('codec')
                if is_live:
                    self.status = 'live'
                    self.current_viewers = client_num - 1
                    if self.actual_start_time is None:
                        self.actual_start_time = datetime.utcnow()
                # workaround for situations when update_state changes status before streamer get authorization
                elif self.status == 'live' and (self.actual_start_time is None or datetime.utcnow() - self.actual_start_time > timedelta(seconds=30)):
                    self.status = 'completed'
                    self.actual_start_time = None
                    self.current_viewers = None
                break
        # same workaround
        else:
            if self.status == 'live' and (self.actual_start_time is None or datetime.utcnow() - self.actual_start_time > timedelta(seconds=30)):
                self.status = 'completed'
                self.actual_start_time = None
                self.current_viewers = None

    def normal_url(self):
        return url_for('streamer_page', streamer_name=self.streamer.reddit_username, _external=True)

    def html_code(self, autoplay=False):
        return render_template("jwplayer.html",
                               channel_name=self.channel_name,
                               autostart=("true" if autoplay else "false"),
                               offline_image_url=url_for("static", filename="dragon_is_offline.png"),
                               rtmp_server=app.config['RTMP_SERVER'])

    def _get_flair(self):
        fst = self.format_start_time(start_time=False)
        status_to_flair = {"live": (u"Live", u"one"),
                           "completed": (u"Finished", u"three"),
                           "upcoming": (fst if fst else u"Upcoming", u"two"),
                           None: (None, None)}

        return status_to_flair[self.status]

    def add_submission(self, submission):
        if submission not in self.submissions:
            self.status = 'upcoming'
            self.scheduled_start_time = None
            self.actual_start_time = None

        Stream.add_submission(self, submission)

    __mapper_args__ = {
        'polymorphic_identity': 'wpc_stream'
    }


class YoutubeStream(Stream):
    ytid = db.Column(db.String(11), unique=True)
    vod_views = db.Column(db.Integer)

    def __init__(self, id):
        self.ytid = id
        self.submissions = []

    def __eq__(self, other):
        return type(self) == type(other) and self.ytid == other.ytid

    def __hash__(self):
        return hash(self.ytid)

    def __repr__(self):
        return '<YoutubeStream {} {}>'.format(self.id, self.ytid)

    def _update_vod_views(self):
        app.logger.info("Updating view count for {}".format(self))
        r = requests_get_with_retries(
            "https://www.googleapis.com/youtube/v3/videos?id={}&part=statistics&key={}".format(
                self.ytid, app.config['YOUTUBE_KEY']), retries_num=15)

        r.raise_for_status()
        for item in r.json()['items']:
            self.vod_views = item['statistics']['viewCount']

    def _update_status(self):
        app.logger.info("Updating status for {}".format(self))
        r = requests_get_with_retries(
            "https://www.googleapis.com/youtube/v3/videos?id={}&part=snippet,liveStreamingDetails&key={}".format(
                self.ytid, app.config['YOUTUBE_KEY']), retries_num=15)

        r.raise_for_status()
        if not r.json()['items']:
            self.status = 'completed'
            self.current_viewers = None
            return

        for item in r.json()['items']:

            # add channel to streamer table if it's needed and fix if it's needed
            if self.streamer is not None:
                yc = item['snippet']['channelId']
                streamer = Streamer.query.filter_by(youtube_channel=yc).first()
                # if there is streamer with this channel
                if streamer:
                    self.streamer = streamer
                # if streamer has no yc and didn't ever checked profile
                elif self.streamer.youtube_channel is None and\
                        not self.streamer.checked:
                    self.streamer.youtube_channel = yc
                    self.streamer.youtube_name = item['snippet']['channelTitle']
                # otherwise
                else:
                    self.streamer = None

            self.title = item['snippet']['title']
            if 'liveStreamingDetails' in item:
                self.scheduled_start_time = item['liveStreamingDetails']['scheduledStartTime']
                if 'concurrentViewers' in item['liveStreamingDetails']:
                    self.current_viewers = item['liveStreamingDetails']['concurrentViewers']

            if item['snippet']['liveBroadcastContent'] == "none" and not self.actual_start_time:
                # TODO: it is probably better to have a separate column for vids
                self.actual_start_time = item['snippet'].get('publishedAt')

            if item['snippet']['liveBroadcastContent'] == 'live':
                self._go_live()
                if 'actualStartTime' in item['liveStreamingDetails']:
                    self.actual_start_time = item['liveStreamingDetails']['actualStartTime']
                else:  # Youtube is weird, and sometimes this happens. If there is no actual start time, then we fall back to scheduledStartTime
                    self.actual_start_time = item['liveStreamingDetails']['scheduledStartTime']
            elif item['snippet']['liveBroadcastContent'] == 'upcoming':
                self.status = 'upcoming'
            else:
                self.status = 'completed'
                self.current_viewers = None

    def _get_flair(self):
        fst = self.format_start_time(start_time=False)
        status_to_flair = {"live": (u"Live", u"one"),
                           "completed": (u"Recording Available", u"four"),
                           "upcoming": (fst if fst else u"Upcoming", u"two"),
                           None: (None, None)}

        return status_to_flair[self.status]

    def normal_url(self):
        return "http://www.youtube.com/watch?v={}".format(self.ytid)

    def html_code(self, autoplay=False):
        return """
                <iframe width="640" height="390" allowfullscreen
                src="http://www.youtube.com/embed/{}?rel=0&autoplay={}">
                </iframe>
              """.format(self.ytid, int(autoplay))

    __mapper_args__ = {
        'polymorphic_identity': 'youtube_stream'
    }


class TwitchStream(Stream):
    channel = db.Column(db.String(25), unique=True)
    last_time_live = db.Column(db.DateTime())

    def __init__(self, channel):
        self.channel = channel
        self.status = 'upcoming'
        self.submissions = []

    def __eq__(self, other):
        return type(self) == type(other) and self.channel == other.channel

    def __hash__(self):
        return hash(self.channel)

    def __repr__(self):
        return '<TwitchStream {} {}>'.format(self.id, self.channel)

    def _update_title_from_channel(self):
        r = requests_get_with_retries("https://api.twitch.tv/kraken/channels/{}".format(self.channel))
        r.raise_for_status()
        stream = r.json()
        if stream is not None:
            if stream['status'] is not None:
                self.title = stream['status']

    def _update_status(self):
        app.logger.info("Updating status for {}".format(self))

        # add channel to streamer table if it's needed and fix if it's needed
        if self.streamer is not None:
            streamer = Streamer.query.filter_by(twitch_channel=self.channel).first()
            # if there is streamer with this channel
            if streamer:
                self.streamer = streamer
            # if streamer has no tc and didn't ever checked profile
            elif self.streamer.twitch_channel is None and\
                    not self.streamer.checked:
                self.streamer.twitch_channel = self.channel
            else:
                self.streamer = None

        r = requests_get_with_retries("https://api.twitch.tv/kraken/streams/{}".format(self.channel))
        r.raise_for_status()

        stream = r.json()['stream']
        if stream is not None:
            self._go_live()
            if 'status' in stream['channel']:
                self.title = stream['channel']['status']
            self.current_viewers = stream['viewers']
            self.last_time_live = datetime.utcnow()
            if self.actual_start_time is None:
                self.actual_start_time = self.last_time_live
        else:
            if self.status == 'live':
                # this is workaround for situations like stream going offline shortly
                if datetime.utcnow() - self.last_time_live > timedelta(minutes=12):
                    self.status = 'completed'
                    self.current_viewers = None

            if self.status == 'upcoming':
                self._update_title_from_channel()

    def _get_flair(self):
        fst = self.format_start_time(start_time=False)
        status_to_flair = {"live": (u"Live", u"one"),
                           "completed": (u"Finished", u"three"),
                           "upcoming": (fst if fst else u"Upcoming", u"two"),
                           None: (None, None)}

        return status_to_flair[self.status]

    def add_submission(self, submission):
        if submission not in self.submissions:
            self.status = 'upcoming'
            self.scheduled_start_time = None
            self.actual_start_time = None

        Stream.add_submission(self, submission)

    def normal_url(self):
        return "http://www.twitch.tv/" + self.channel

    def html_code(self, autoplay=False):
        return """
               <object type="application/x-shockwave-flash"
                       height="390"
                       width="640"
                       id="live_embed_player_flash"
                       data="http://www.twitch.tv/widgets/live_embed_player.swf?channel={}"
                       bgcolor="#000000">
                 <param  name="wmode"
                         value="opaque" />
                 <param  name="allowFullScreen"
                         value="true" />
                 <param  name="allowScriptAccess"
                         value="always" />
                 <param  name="allowNetworking"
                         value="all" />
                 <param  name="movie"
                         value="http://www.twitch.tv/widgets/live_embed_player.swf" />
                 <param  name="flashvars"
                         value="hostname=www.twitch.tv&channel={}&auto_play={}" />
               </object>
               """.format(self.channel, self.channel, "true" if autoplay else "false")

    __mapper_args__ = {
        'polymorphic_identity': 'twitch_stream'
    }


class MozillaStreamHack(object):
    def html_code(self, autoplay=None):
        return '''<iframe src="https://air.mozilla.org/the-joy-of-coding-mconley-livehacks-on-firefox-episode-18/video/" width="640" height="380" frameborder="0" allowfullscreen></iframe>'''  # NOQA

    def normal_url(self):
        return "https://air.mozilla.org/the-joy-of-coding-mconley-livehacks-on-firefox-episode-18/"

    def __init__(self):
        self.id = 0
        self.current_viewers = None
        self.streamer = Streamer.query.filter_by(reddit_username='good_grief').one()


class GitHubStreamHack(object):
    def html_code(self, autoplay=None):
        return '''<iframe width="640" height="392" src="http://www.ustream.tv/embed/18841580?v=3&amp;wmode=direct" scrolling="no" frameborder="0" style="border: 0px none transparent;">    </iframe>'''  # NOQA

    def normal_url(self):
        return "https://live-stream.github.com/"

    def __init__(self):
        self.id = -1
        self.current_viewers = None
        self.streamer = None
        self.title = "GitHub CodeConf"


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)

    def __repr__(self):
        return '<Subscriber {} {}>'.format(self.id, self.email)

    def already_subscribed(self, streamer):
        return streamer and (self in streamer.subscribers or self == streamer.as_subscriber)


class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    description = db.Column(db.Text(), nullable=False)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sent_on = db.Column(db.DateTime, default=db.func.now())
    streamer = db.relationship('Streamer', backref=db.backref('chat_messages', lazy='dynamic'))
    streamer_id = db.Column('streamer_id', db.Integer(), db.ForeignKey('streamer.id'))
    sender = db.Column(db.String())
    text = db.Column(db.String())


class Streamer(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    reddit_username = db.column_property(db.Column(db.String(20), unique=True), comparator_factory=CaseInsensitiveComparator)
    twitch_channel = db.column_property(db.Column(db.String(25), unique=True), comparator_factory=CaseInsensitiveComparator)
    youtube_channel = db.Column(db.String(24), unique=True)
    youtube_name = db.Column(db.String(30))
    info = db.Column(db.Text())
    checked = db.Column(db.Boolean(), default=False)
    rtmp_secret = db.Column(db.String(50))
    test = db.Column(db.Boolean(), default=False)
    as_subscriber_id = db.Column('as_subscriber_id', db.Integer(), db.ForeignKey('subscriber.id'))
    as_subscriber = db.relationship('Subscriber', backref=db.backref('as_streamer'))
    subscribers = db.relationship('Subscriber', secondary=streamer_subscriptions, lazy='dynamic', backref=db.backref('subscribed_to', lazy='dynamic'))
    need_to_notify_subscribers = db.Column(db.Boolean, default=False)
    last_time_notified = db.Column(db.DateTime())
    banned = db.Column(db.Boolean(), default=False)

    # XXX: this is kinda ugly, but simple
    # nginx-rtmp supports only fixed number of redirects
    # TODO: This should be fixed later
    rtmp_redirect_1 = db.Column(db.String())
    rtmp_redirect_2 = db.Column(db.String())
    rtmp_redirect_3 = db.Column(db.String())

    def __init__(self, reddit_username, checked=False):
        self.reddit_username = reddit_username
        self.checked = checked

    def __repr__(self):
        return '<Streamer {} {}>'.format(self.id, self.reddit_username)

    def get_id(self):
        return self.reddit_username

    def already_subscribed(self, another_streamer):
        return another_streamer and (another_streamer == self or (self.as_subscriber and self.as_subscriber.already_subscribed(another_streamer)))

    def streaming_key(self):
        return self.reddit_username + '?pass=' + self.rtmp_secret

    def populate(self, form):
        self.info = form.info.data
        tc = form.twitch_channel_extract()

        # delete inapropriate tstream
        if tc != self.twitch_channel:
            ts = self.streams.filter_by(type='twitch_stream').first()
            if ts:
                ts.streamer = None

        # rebind tstream
        streamer = Streamer.query.filter_by(twitch_channel=tc).first()
        if streamer and streamer != current_user:
            streamer.twitch_channel = None
            for ts in streamer.streams.filter_by(type='twitch_stream'):
                ts.streamer = self

        self.twitch_channel = tc if tc else None

        yc = form.youtube_channel_extract()

        # delete inapropriate ystreams
        if yc != self.youtube_channel:
            for ys in self.streams.filter_by(type='youtube_stream'):
                ys.streamer = None

        # rebind ystreams
        streamer = Streamer.query.filter_by(youtube_channel=yc).first()
        if streamer and streamer != current_user:
            # to not make api-requests
            yn = streamer.youtube_name
            if yn is not None:
                self.youtube_name = yn
                self.youtube_channel = streamer.youtube_channel
                streamer.youtube_name = None

            streamer.youtube_channel = None
            for ys in streamer.streams.filter_by(type='youtube_stream'):
                ys.streamer = self

        # get yc name
        if yc and (yc != self.youtube_channel or self.youtube_name is None):
            r = requests_get_with_retries(
                "https://www.googleapis.com/youtube/v3/channels?id={}&part=snippet&key={}".format(
                    yc, app.config['YOUTUBE_KEY']), retries_num=15)

            r.raise_for_status()

            for item in r.json()['items']:
                self.youtube_name = item['snippet']['title']

        self.youtube_channel = yc if yc else None
