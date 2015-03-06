from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g, send_from_directory, session
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
from flask_wtf import Form
from wtforms import StringField, SubmitField, validators, TextAreaField
from wtforms.validators import ValidationError
from flask.ext.script import Manager
from flask.ext.migrate import Migrate, MigrateCommand
from flask.ext.login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

import os
import requests
import json
from datetime import datetime, timedelta
from utils import requests_get_with_retries
import humanize
import logging
import praw
import re
from jinja2 import escape, evalcontextfilter, Markup
from urlparse import urlparse
from uuid import uuid4

from logentries import LogentriesHandler
from crossdomain import crossdomain


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
    app.config['REDDIT_API_ID'] = os.environ['WPC_APP_ID']
    app.config['REDDIT_API_SECRET'] = os.environ['WPC_APP_SECRET']
    app.config['REDDIT_WEB_APP_USER_AGENT'] = "/r/WatchPeopleCode web app(main contact: /u/godlikesme)"

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
login_manager = LoginManager(app)


@login_manager.user_loader
def load_user(reddit_username):
        return Streamer.query.filter_by(reddit_username=reddit_username).first()


@app.before_request
def add_ga_tracking_code():
    g.ga_tracking_code = app.config['GA_TRACKING_CODE']


@app.before_request
def create_search_form():
    g.search_form = SearchForm()


@manager.command
def run():
    app.run(debug=True)


def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_other_page'] = url_for_other_page


def get_or_create(model, **kwargs):
    instance = model.query.filter_by(**kwargs).first()
    if instance is None:
        instance = model(**kwargs)
        db.session.add(instance)
    return instance


stream_tag = db.Table('stream_tag',
                      db.Column('stream_id', db.Integer(), db.ForeignKey('stream.id')),
                      db.Column('tag_name', db.String(256), db.ForeignKey('tag.name')))


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
    submissions = db.relationship('Submission', secondary=stream_sub, backref=db.backref('streams', lazy='dynamic'))
    streamer_id = db.Column('streamer_id', db.Integer(), db.ForeignKey('streamer.id'))
    streamer = db.relationship('Streamer', backref=db.backref('streams', lazy='dynamic'))
    tags = db.relationship('Tag', secondary=stream_tag, backref=db.backref('streams', lazy='dynamic'))

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
                elif not self.streamer.checked:
                    self.streamer.youtube_channel = yc
                    self.streamer.youtube_name = item['snippet']['channelTitle']

    def normal_url(self):
        return "http://www.youtube.com/watch?v={}".format(self.ytid)

    def html_code(self, autoplay=False):
        return """
            <div class="embed-responsive embed-responsive-16by9">
                <iframe width="640" height="390"
                src="http://www.youtube.com/embed/{}?rel=0&autoplay={}">
                </iframe>
                </div>
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
            elif not self.streamer.checked:
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
            <div class="embed-responsive embed-responsive-16by9">
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
               </div>
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


class Streamer(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    reddit_username = db.column_property(db.Column(db.String(20), unique=True), comparator_factory=CaseInsensitiveComparator)
    twitch_channel = db.column_property(db.Column(db.String(25), unique=True), comparator_factory=CaseInsensitiveComparator)
    youtube_channel = db.Column(db.String(24), unique=True)
    youtube_name = db.Column(db.String(30))
    info = db.Column(db.Text())
    checked = db.Column(db.Boolean(), default=False)

    def __init__(self, reddit_username, checked=False):
        self.reddit_username = reddit_username
        self.checked = checked

    def __repr__(self):
        return '<Streamer %d %r>' % (self.id, self.reddit_username)

    def get_id(self):
        return self.reddit_username

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
            try:
                r = requests_get_with_retries(
                    "https://www.googleapis.com/youtube/v3/channels?id={}&part=snippet&key={}".format(
                        yc,
                        app.config['YOUTUBE_KEY'],
                        retries_num=15))

                r.raise_for_status()
            except Exception as e:
                app.logger.error("Error while updating {}".format(Streamer))
                app.logger.exception(e)
                raise

            for item in r.json()['items']:
                self.youtube_name = item['snippet']['title']

        self.youtube_channel = yc if yc else None


class Tag(db.Model):
    __tablename__ = 'tag'
    name = db.column_property(db.Column(db.String(256), primary_key=True), comparator_factory=CaseInsensitiveComparator)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<Tag {}>'.format(self.name)


def validate_email_unique(form, field):
    email = field.data
    if Subscriber.query.filter_by(email=email).first() is not None:
        raise ValidationError('This email is already in the database.')


class SubscribeForm(Form):
    email = StringField("Email address", [validators.DataRequired(), validators.Email(), validate_email_unique])
    submit_button = SubmitField('Subscribe')


class EditStreamerInfoForm(Form):
    youtube_channel = StringField("Youtube channel", [validators.Length(max=100)])
    twitch_channel = StringField("Twitch channel", [validators.Length(max=100)])
    info = TextAreaField("Info", [validators.Length(max=5000)])
    submit_button = SubmitField('Submit')

    def twitch_channel_extract(self):
        """
        Examples:
        - channel_name
        - https://www.twitch.tv.channel_name
        - something_wrong?!twitch.tv/channel_name
        """
        string = self.twitch_channel.data.strip()
        position = string.find('twitch.tv')
        if position != -1:
            path = urlparse(string[position:]).path.split('/')
            if len(path) < 2:
                return None
            string = path[1]

        return string if len(string) <= 25 and re.match(r'\w*$', string) else None

    def youtube_channel_extract(self):
        """
        Examples:
        - UCJAVLOqT6Mgn_YD5lAxxkUA
        - https://www.youtube.com/channel/UCJAVLOqT6Mgn_YD5lAxxkUA
        - something_wrong}[youtube.com/channel/UCJAVLOqT6Mgn_YD5lAxxkUA
        """
        string = self.youtube_channel.data.strip()
        position = string.find('youtube.com')
        if position != -1:
            path = urlparse(string[position:]).path.split('/')
            if len(path) < 3 or path[1] != "channel":
                return None
            else:
                string = path[2]

        return string if len(string) == 24 and re.match(r'[\w-]*$', string) or string == '' else None

    def validate_youtube_channel(form, field):
        yc = form.youtube_channel_extract()
        if yc is None:
            # FIXME: add explanation here or hint to page
            raise ValidationError("This field should contain valid youtube channel.")

        streamer = Streamer.query.filter_by(youtube_channel=yc).first()
        if streamer and streamer.checked and streamer != current_user:
            raise ValidationError("There is another user with this channel. If it is your channel, please message about that to r/WatchPeoplecode moderators.")

    def validate_twith_channel(form, field):
        tc = form.twitch_channel_extract()
        if tc is None:
            raise ValidationError('This field should be valid twitch channel.')

        streamer = Streamer.query.filter_by(twitch_channel=tc).first()
        if streamer and streamer.checked and streamer != current_user:
            raise ValidationError("There is another user with this channel. If it is your channel, please message about that to r/WatchPeoplecode moderators.")


class SearchForm(Form):
    query = StringField("Query")
    search_button = SubmitField('Search past streams')


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


@app.route('/search', methods=['GET', 'POST'])
def search():
    if g.search_form.validate_on_submit():
        return redirect(url_for("past_streams", query=g.search_form.query.data))
    else:
        # Should never happen, unless user requested /search manually
        return redirect(url_for("past_streams"))


@app.route('/past_streams', defaults={'page': 1, 'query': None}, methods=["GET", "POST"])
@app.route('/past_streams/query/<query>', defaults={'page': 1}, methods=["GET", "POST"])
@app.route('/past_streams/page/<int:page>', defaults={'query': None}, methods=["GET", "POST"])
@app.route('/past_streams/query/<query>/page/<int:page>', methods=["GET", "POST"])
def past_streams(query, page):
    streams = YoutubeStream.query.filter_by(status='completed')

    if query:
        terms = [t.strip() for t in query.split(" ")]
        streams = streams.filter(YoutubeStream.title.match(" & ".join(terms)))

    streams = streams.order_by(YoutubeStream.scheduled_start_time.desc().nullslast()).paginate(page, per_page=5)
    return render_template('past_streams.html', streams=streams, page=page, query=query)


@app.route('/streamers/', defaults={'page': 1})
@app.route('/streamers/<int:page>')
def streamers_list(page):
    streamers = Streamer.query.filter(Streamer.streams.any()).order_by(Streamer.reddit_username).paginate(page, per_page=50)
    return render_template('streamers_list.html', streamers=streamers)


@app.template_filter()
@evalcontextfilter
def nl2br(eval_ctx, value):
    result = (u'%s' % escape(value)).replace('\n', '<br>')
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


@app.route('/streamer/<streamer_name>', defaults={'page': 1}, methods=["GET", "POST"])
@app.route('/streamer/<streamer_name>/<int:page>', methods=["GET", "POST"])
def streamer_page(streamer_name, page):
    streamer = Streamer.query.filter_by(reddit_username=streamer_name).first()
    streams = streamer.streams.order_by(Stream.scheduled_start_time.desc().nullslast()).paginate(page, per_page=5)
    form = EditStreamerInfoForm()

    if current_user.is_authenticated() and current_user == streamer:
        if request.method == 'POST':
            if form.validate_on_submit():
                current_user.populate(form)
                db.session.commit()
                flash("Updated successfully", category='success')
                return redirect(url_for('.streamer_page', streamer_name=streamer_name))
            else:
                return render_template('streamer.html', streamer=streamer, streams=streams, form=form, edit=True)
        else:
            form.youtube_channel.data = current_user.youtube_channel
            form.twitch_channel.data = current_user.twitch_channel
            form.info.data = current_user.info

    return render_template('streamer.html', streamer=streamer, streams=streams, form=form, edit=False)


@app.route('/json')
@crossdomain(origin='*', max_age=15)
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


@app.route('/reddit_authorize_callback')
def reddit_authorize_callback():
    r = praw.Reddit(user_agent=app.config["REDDIT_WEB_APP_USER_AGENT"])
    r.set_oauth_app_info(app.config['REDDIT_API_ID'], app.config['REDDIT_API_SECRET'], url_for('.reddit_authorize_callback', _external=True))
    if str(session['unique_key']) == request.args.get('state', ''):
        code = request.args.get('code', '')
        if code:
            r.get_access_information(code)
            name = r.get_me().name
            if name:
                user = get_or_create(Streamer, reddit_username=name)
                user.checked = True
                db.session.commit()
                login_user(user)
                flash("Logged in successfully", 'success')
                return redirect(url_for(".streamer_page", streamer_name=name))

    flash("Error while trying to log in", 'error')
    return redirect(url_for(".index"))


@app.route('/auth')
def authorize():
    r = praw.Reddit(user_agent=app.config["REDDIT_WEB_APP_USER_AGENT"])
    r.set_oauth_app_info(app.config['REDDIT_API_ID'], app.config['REDDIT_API_SECRET'], url_for('.reddit_authorize_callback', _external=True))
    session['unique_key'] = uuid4()
    url = r.get_authorize_url(session['unique_key'], 'identity')
    return redirect(url)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully", 'info')
    return redirect(url_for(".index"))


@app.route("/podcast_feed.xml")
def podcast_feed():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'podcast_feed.xml', mimetype='application/rss+xml')


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
    # fix before use
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
