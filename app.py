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


app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.config['MAILGUN_API_URL'] = os.environ['MAILGUN_API_URL']
app.config['MAILGUN_API_KEY'] = os.environ['MAILGUN_API_KEY']
app.config['MAILGUN_TEST_OPTION'] = True if os.environ['MAILGUN_TEST_OPTION'] == 'True' else False
app.config['NOTIFICATION_EMAIL'] = os.environ['MAILGUN_SMTP_LOGIN']
app.config['REDDIT_PASSWORD'] = os.environ['REDDIT_PASSWORD']
app.config['REDDIT_USERNAME'] = os.environ['REDDIT_USERNAME']
Bootstrap(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
manager = Manager(app)
manager.add_command('db', MigrateCommand)


@app.before_request
def add_ga_tracking_code():
    g.ga_tracking_code = os.environ['GA_TRACKING_CODE']


@manager.command
def run():
    app.run(debug=True)


youtube_api_key = os.environ['ytokkey']


subscription = db.Table('subscription',
                        db.Column('stream_id', db.Integer(), db.ForeignKey('stream.id')),
                        db.Column('subscriber_id', db.Integer(), db.ForeignKey('subscriber.id')))


class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50))
    scheduled_start_time = db.Column(db.DateTime())
    status = db.Column(db.Enum('upcoming', 'live', 'completed', name='stream_status'))
    title = db.Column(db.String(200))
    subscribers = db.relationship('Subscriber', secondary=subscription, backref=db.backref('streams', lazy='dynamic'))
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


class YoutubeStream(Stream):
    ytid = db.Column(db.String(11), unique=True)

    def __init__(self, id):
        self.ytid = id

    def __eq__(self, other):
        return type(self) == type(other) and self.ytid == other.ytid

    def __hash__(self):
        return hash(self.ytid)

    def __repr__(self):
        return '<YoutubeStream %d %r>' % (self.id, self.ytid)

    def _update_status(self):
        r = requests_get_with_retries(
            "https://www.googleapis.com/youtube/v3/videos?id={}&part=snippet,liveStreamingDetails&key={}".format(self.ytid, youtube_api_key), retries_num=15)
        r.raise_for_status()

        if not r.json()['items']:
            self.status = 'completed'
            return

        for item in r.json()['items']:
            self.title = item['snippet']['title']
            if 'liveStreamingDetails' in item:
                self.scheduled_start_time = item['liveStreamingDetails']['scheduledStartTime']
            if item['snippet']['liveBroadcastContent'] == 'live':
                self.status = 'live'
            elif item['snippet']['liveBroadcastContent'] == 'upcoming':
                self.status = 'upcoming'
            else:
                self.status = 'completed'

            # add channel to streamer table if it's needed
            if self.streamer.youtube_channel is None:
                self.streamer.youtube_channel = item['snippet']['channelId']

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
    submission_id = db.Column(db.String())

    def __init__(self, channel, submission_id):
        self.channel = channel
        self.submission_id = submission_id
        self.status = 'upcoming'

    def __eq__(self, other):
        return type(self) == type(other) and self.channel == other.channel and self.submission_id == other.submission_id

    def __hash__(self):
        return hash(self.channel)

    def __repr__(self):
        return '<TwitchStream {} {} {}>'.format(self.id, self.channel, self.submission_id)

    def _update_status(self):
        r = requests_get_with_retries("https://api.twitch.tv/kraken/streams/{}".format(self.channel))
        r.raise_for_status()
        stream = r.json()['stream']
        if stream is not None:
            self.status = 'live'
            self.title = stream['channel']['status']
            self.last_time_live = datetime.utcnow()
        else:
            if self.status == 'live':
                if datetime.utcnow() - self.last_time_live > timedelta(minutes=12):
                    self.status = 'completed'
            # if stream is upcoming we should go to api for the title
            else:
                r = requests_get_with_retries("https://api.twitch.tv/kraken/channels/{}".format(self.channel))
                r.raise_for_status()
                stream = r.json()
                if stream is not None:
                    if stream['status'] is not None:
                        self.title = stream['status']

        # add channel to streamer table if it's needed
        if self.streamer.twitch_channel is None:
            self.streamer.twitch_channel = self.channel

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
    youtube_channel = db.column_property(db.Column(db.String(24), unique=True), comparator_factory=CaseInsensitiveComparator)

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
    live_streams = Stream.query.filter_by(status='live').order_by(Stream.scheduled_start_time.desc().nullslast(), Stream.id.desc()).all()

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


@app.route('/json')
def stream_json():
    try:
        return jsonify(stream_urls=[st.normal_url() for st in Stream.query.filter_by(status='live')])
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


def notify():
    # this is stub, fix before use
    live = Stream.query.filter_by(status='live').order_by(Stream.scheduled_start_time).all()
    upcoming = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time).all()
    subject = "WatchPeopleCode: today's streams"
    text = render_template('mails/stream_notification.txt', live_streams=live, upcoming_streams=upcoming)
    html = render_template('mails/stream_notification.html', live_streams=live, upcoming_streams=upcoming)
    recipient_vars = {subscriber.email: {} for subscriber in Subscriber.query}
    send_message(recipient_vars, subject, text, html)


if __name__ == '__main__':
    manager.run()
