from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
from flask_wtf import Form
from wtforms import StringField, SubmitField, validators
from wtforms.validators import ValidationError
from flask.ext.script import Manager
from flask.ext.migrate import Migrate, MigrateCommand

import os
import requests
import json
from datetime import datetime, timedelta
from utils import requests_get_with_retries
import humanize
import logging

from logentries import LogentriesHandler


def setup_logging(loggers_and_levels, logentries_id=None):
    log = logging.getLogger('logentries')
    log.setLevel(logging.INFO)
    if logentries_id:
        logentries_handler = LogentriesHandler(logentries_id)
        handler = logentries_handler
    else:
        handler = logging.StreamHandler()

    FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
    formatter = logging.Formatter(fmt=FORMAT)
    handler.setFormatter(formatter)

    log.addHandler(handler)
    for logger, level in loggers_and_levels:
        logger.setLevel(level)
        logger.addHandler(handler)


def create_app():
    app = Flask("WatchPeopleCode")
    app.secret_key = os.environ['SECRET_KEY']
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['MAILGUN_API_URL'] = os.environ['MAILGUN_API_URL']
    app.config['MAILGUN_API_KEY'] = os.environ['MAILGUN_API_KEY']
    app.config['MAILGUN_TEST_OPTION'] = True if os.environ['MAILGUN_TEST_OPTION'] == 'True' else False
    app.config['NOTIFICATION_EMAIL'] = os.environ['MAILGUN_SMTP_LOGIN']
    app.config['REDDIT_PASSWORD'] = os.environ['WPC_REDDIT_PASSWORD']
    app.config['REDDIT_USERNAME'] = os.environ['WPC_REDDIT_USERNAME']
    app.config['YOUTUBE_KEY'] = os.environ['WPC_YOUTUBE_KEY']
    app.config['GA_TRACKING_CODE'] = os.environ['GA_TRACKING_CODE']

    Bootstrap(app)
    loggers_and_levels = [(app.logger, logging.INFO),
                          (logging.getLogger('sqlalchemy'), logging.WARNING),
                          (logging.getLogger('apscheduler.scheduler'), logging.INFO)]
    setup_logging(loggers_and_levels, logentries_id=os.environ.get('LOGENTRIES_ID', None))

    app.logger.info("App created!")

    return app

app = create_app()

db = SQLAlchemy(app)
migrate = Migrate(app, db)
manager = Manager(app)
manager.add_command('db', MigrateCommand)


@app.before_request
def add_ga_tracking_code():
    g.ga_tracking_code = app.config['GA_TRACKING_CODE']


@manager.command
def run():
    app.run(debug=True)


def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_other_page'] = url_for_other_page


subscription = db.Table('subscription',
                        db.Column('stream_id', db.Integer(), db.ForeignKey('stream.id')),
                        db.Column('subscriber_id', db.Integer(), db.ForeignKey('subscriber.id')))


stream_sub = db.Table('stream_sub',
                      db.Column('stream_id', db.Integer(), db.ForeignKey('stream.id')),
                      db.Column('submission_id', db.String(6), db.ForeignKey('submission.submission_id')))


class Submission(db.Model):
    submission_id = db.Column(db.String(6), primary_key=True)

    def __repr__(self):
        return '<Submission %r>' % (self.submission_id)


class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50))
    scheduled_start_time = db.Column(db.DateTime())
    actual_start_time = db.Column(db.DateTime())
    status = db.Column(db.Enum('upcoming', 'live', 'completed', name='stream_status'))
    title = db.Column(db.String(200))
    subscribers = db.relationship('Subscriber', secondary=subscription, backref=db.backref('streams', lazy='dynamic'))
    submissions = db.relationship('Submission', secondary=stream_sub, backref=db.backref('streams', lazy='dynamic'))
    streamer_id = db.Column('streamer_id', db.Integer(), db.ForeignKey('streamer.id'))
    streamer = db.relationship('Streamer', backref=db.backref('streams', lazy='dynamic'))
    # reddit_thread = db.Column(db.String(255))

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'stream'
    }

    def format_start_time(self, countdown=True):
        if not self.scheduled_start_time:
            return None

        if countdown:
            return humanize.naturaltime(
                datetime.utcnow() - self.scheduled_start_time) + ", " + datetime.strftime(self.scheduled_start_time, "%Y-%m-%d %H:%M UTC")
        else:
            return datetime.strftime(self.scheduled_start_time, "%Y-%m-%d %H:%M UTC")

    def add_submission(self, submission):
        if submission not in self.submissions:
            self.submissions.append(submission)


class YoutubeStream(Stream):
    ytid = db.Column(db.String(11), unique=True)

    def __init__(self, id):
        self.ytid = id
        self.submissions = []

    def __eq__(self, other):
        return type(self) == type(other) and self.ytid == other.ytid

    def __hash__(self):
        return hash(self.ytid)

    def __repr__(self):
        return '<YoutubeStream %d %r>' % (self.id, self.ytid)

    def _update_status(self):
        app.logger.info("Updating status for {}".format(self))
        try:
            r = requests_get_with_retries(
                "https://www.googleapis.com/youtube/v3/videos?id={}&part=snippet,liveStreamingDetails&key={}".format(
                    self.ytid,
                    app.config['YOUTUBE_KEY'],
                    retries_num=15))

            r.raise_for_status()
        except Exception as e:
            app.logger.error("Error while updating {}".format(YoutubeStream))
            app.logger.exception(e)
            raise

        if not r.json()['items']:
            self.status = 'completed'
            return

        for item in r.json()['items']:
            self.title = item['snippet']['title']
            if 'liveStreamingDetails' in item:
                self.scheduled_start_time = item['liveStreamingDetails']['scheduledStartTime']
            if item['snippet']['liveBroadcastContent'] == 'live':
                self.status = 'live'
                self.actual_start_time = item['liveStreamingDetails']['actualStartTime']
            elif item['snippet']['liveBroadcastContent'] == 'upcoming':
                self.status = 'upcoming'
            else:
                self.status = 'completed'

            # add channel to streamer table if it's needed and fix if it's needed
            if self.streamer is not None:
                yc = item['snippet']['channelId']
                streamer = Streamer.query.filter_by(youtube_channel=yc).first()
                # if there is streamer with that channel
                if streamer:
                    self.streamer = streamer
                # there is no streamer with that channel
                else:
                    self.streamer.youtube_channel = yc
                    self.streamer.youtube_name = item['snippet']['channelTitle']

    def normal_url(self):
        return "http://www.youtube.com/watch?v={}".format(self.ytid)

    def html_code(self, autoplay=False):
        return """
                <iframe width="640" height="390"
                src="http://www.youtube.com/embed/{}?rel=0&autoplay={}">
                </iframe>
              """.format(self.ytid, int(autoplay))

    __mapper_args__ = {
        'polymorphic_identity': 'youtube_stream'
    }


class TwitchStream(Stream):
    channel = db.Column(db.String(25))
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
        try:
            r = requests_get_with_retries("https://api.twitch.tv/kraken/streams/{}".format(self.channel))
            r.raise_for_status()
        except Exception as e:
            app.logger.error("Error while updating {}".format(self))
            app.logger.exception(e)
            raise

        stream = r.json()['stream']
        if stream is not None:
            self.status = 'live'
            self.title = stream['channel']['status']
            self.last_time_live = datetime.utcnow()
            if self.actual_start_time is None:
                self.actual_start_time = self.last_time_live
        else:
            if self.status == 'live':
                # this is workaround for situations like stream going offline shortly
                if datetime.utcnow() - self.last_time_live > timedelta(minutes=12):
                    self.status = 'completed'

            if self.status == 'upcoming':
                self._update_title_from_channel()

        # add channel to streamer table if it's needed and fix if it's needed
        if self.streamer is not None:
            streamer = Streamer.query.filter_by(twitch_channel=self.channel).first()
            # if there is streamer with that channel
            if streamer:
                self.streamer = streamer
            # there is no streamer with that channel
            else:
                self.streamer.twitch_channel = self.channel

    def add_submission(self, submission):
        if submission not in self.submissions:
            self.status = 'upcoming'
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


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)

    def __repr__(self):
        return '<Subscriber %d %r>' % (self.id, self.email)


class Streamer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reddit_username = db.column_property(db.Column(db.String(20), unique=True), comparator_factory=CaseInsensitiveComparator)
    twitch_channel = db.column_property(db.Column(db.String(25), unique=True), comparator_factory=CaseInsensitiveComparator)
    youtube_channel = db.Column(db.String(24), unique=True)
    youtube_name = db.Column(db.String(30))

    def __init__(self, reddit_username):
        self.reddit_username = reddit_username

    def __repr__(self):
        return '<Streamer %d %r>' % (self.id, self.reddit_username)


def validate_email_unique(form, field):
    email = field.data
    if Subscriber.query.filter_by(email=email).first() is not None:
        raise ValidationError('This email is already in the database.')


class SubscribeForm(Form):
    email = StringField("Email address", [validators.DataRequired(), validators.Email(), validate_email_unique])
    submit_button = SubmitField('Subscribe')


@app.route('/', methods=['GET', 'POST'])
def index():
    live_streams = Stream.query.filter_by(status='live').order_by(Stream.actual_start_time.desc().nullslast(), Stream.id.desc()).all()

    form = SubscribeForm()
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        flash("you've subscribed successfully", "success")
        return redirect(url_for('.index'))

    random_stream = YoutubeStream.query.filter(YoutubeStream.status != 'upcoming').order_by(db.func.random()).first()
    upcoming_streams = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time.asc()).all()
    return render_template('index.html', form=form, live_streams=live_streams, random_stream=random_stream, upcoming_streams=upcoming_streams)


@app.route('/past_streams', defaults={'page': 1})
@app.route('/past_streams/page/<int:page>')
def past_streams(page):
    streams = YoutubeStream.query.filter_by(status='completed').order_by(YoutubeStream.scheduled_start_time.desc().nullslast()).paginate(page, per_page=5)
    return render_template('past_streams.html', streams=streams, page=page)


@app.route('/streamers/', defaults={'page': 1})
@app.route('/streamers/<int:page>')
def streamers_list(page):
    streamers = Streamer.query.order_by(Streamer.reddit_username).paginate(page, per_page=50)
    return render_template('streamers_list.html', streamers=streamers)


@app.route('/streamer/<streamer_name>', defaults={'page': 1})
@app.route('/streamer/<streamer_name>/<int:page>')
def streamer_page(streamer_name, page):
    streamer = Streamer.query.filter_by(reddit_username=streamer_name).first()
    streams = streamer.streams.order_by(Stream.scheduled_start_time.desc().nullslast()).paginate(page, per_page=5)
    return render_template('streamer.html', streamer=streamer, streams=streams)


@app.route('/json')
def stream_json():
    def make_dict(stream):
        return {'username': stream.streamer.reddit_username if stream.streamer else None,
                'title': stream.title, 'url': stream.normal_url()}
    try:
        return jsonify(live=[make_dict(st) for st in Stream.query.filter_by(status='live')],
                       upcoming=[make_dict(st) for st in Stream.query.filter_by(status='upcoming')],
                       completed=[make_dict(st) for st in YoutubeStream.query.filter_by(status='completed')])
    except Exception as e:
        app.logger.exception(e)
        return jsonify(error=True)


def send_message(recipient_vars, subject, text, html):
    return requests.post(
        app.config['MAILGUN_API_URL'],
        auth=("api", app.config['MAILGUN_API_KEY']),
        data={"from": "WatchPeopleCode <{}>".format(app.config['NOTIFICATION_EMAIL']),
              "to": recipient_vars.keys(),
              "subject": subject,
              "text": text,
              "html": html,
              "recipient-variables": (json.dumps(recipient_vars)),
              "o:testmode": app.config['MAILGUN_TEST_OPTION']
              })


def generate_email_notifications():
    # this is stub, fix before use
    live = Stream.query.filter_by(status='live').order_by(Stream.scheduled_start_time).all()
    upcoming = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time).all()
    text = render_template('mails/stream_notification.txt', live_streams=live, upcoming_streams=upcoming)
    html = render_template('mails/stream_notification.html', live_streams=live, upcoming_streams=upcoming)
    return text, html


def send_email_notifications(text, html, subject="WatchPeopleCode: weekly update"):
    # FIXME: mailgun batches are limited to 1000
    recipient_vars = {subscriber.email: {} for subscriber in Subscriber.query}
    print send_message(recipient_vars, subject, text, html)

if __name__ == '__main__':
    manager.run()
