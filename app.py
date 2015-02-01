from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
from flask_wtf import Form
from wtforms import StringField, SubmitField, validators
from wtforms.validators import ValidationError
from flask.ext.script import Manager
from flask.ext.migrate import Migrate, MigrateCommand

import praw
import os
from utils import youtube_video_id, is_live_yt_stream, twitch_channel, is_live_twitch_stream
from bs4 import BeautifulSoup

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
Bootstrap(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
manager = Manager(app)
manager.add_command('db', MigrateCommand)


@manager.command
def run():
    app.run(debug=True)


reddit_user_agent = "/r/WatchPeopleCode app"
youtube_api_key = os.environ['ytokkey']


class Stream(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50))
    scheduled_start_time = db.Column(db.DateTime())
    is_live = db.Column(db.Boolean())
    is_completed = db.Column(db.Boolean())

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'stream'
    }


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

    def normal_url(self):
        return "http://www.youtube.com/watch?v={}".format(self.ytid)

    def html_code(self):
        return """
                <iframe width="640" height="390"
                src="http://www.youtube.com/embed/{}">
                </iframe>
              """.format(self.ytid)

    __mapper_args__ = {
        'polymorphic_identity': 'youtube_stream'
    }


class TwitchStream(Stream):
    channel = db.Column(db.String(25))

    def __init__(self, channel):
        self.channel = channel

    def __eq__(self, other):
        return type(self) == type(other) and self.channel == other.channel

    def __hash__(self):
        return hash(self.channel)

    def __repr__(self):
        return '<TwitchStream %d %r>' % (self.id, self.channel)

    def normal_url(self):
        return "http://www.twitch.tv/" + self.channel

    def html_code(self):
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
                         value="hostname=www.twitch.tv&channel={}&auto_play=false" />
               </object>
               """.format(self.channel, self.channel)

    __mapper_args__ = {
        'polymorphic_identity': 'twitch_stream'
    }


def get_or_create_stream_from_url(url):
    ytid = youtube_video_id(url)
    if ytid is not None:
        ys = YoutubeStream.query.filter_by(ytid=ytid).first()
        if not ys:
            ys = YoutubeStream(ytid)
            db.session.add(ys)

        return ys if is_live_yt_stream(ytid, youtube_api_key) else None

    tc = twitch_channel(url)
    if tc is not None:
        ts = TwitchStream.query.filter_by(channel=tc).first()
        if not ts:
            ts = TwitchStream(tc)
            db.session.add(ts)

        return ts if is_live_twitch_stream(tc) else None

    return None


def extract_links_from_selftexts(selftext_html):
    soup = BeautifulSoup(selftext_html)
    return [a['href'] for a in soup.findAll('a')]


def get_current_live_streams():
    r = praw.Reddit(user_agent=reddit_user_agent)
    r.config.decode_html_entities = True

    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=50)
    new_live_streams = set()
    # TODO : don't forget about http vs https
    # TODO better way of caching api requests
    checked_stream_urls = set()
    for s in submissions:
        selfposts_urls = extract_links_from_selftexts(s.selftext_html) if s.selftext_html else []
        for url in selfposts_urls + [s.url]:
            if url not in checked_stream_urls:
                # FIXME super ugly workaround :(
                for i in xrange(10):
                    try:
                        stream = get_or_create_stream_from_url(url)
                        break
                    except:
                        if i == 9:
                            raise

                checked_stream_urls.add(url)
                if stream:
                    new_live_streams.add(stream)

    db.session.commit()
    return new_live_streams


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)

    def __repr__(self):
        return '<Subscriber %d %r>' % (self.id, self.email)


def validate_email_unique(form, field):
    email = field.data
    if Subscriber.query.filter_by(email=email).first() is not None:
        raise ValidationError('This email is already in the database.')


class SubscribeForm(Form):
    email = StringField("Email address", [validators.DataRequired(), validators.Email(), validate_email_unique])
    submit_button = SubmitField('Subscribe')


@app.route('/', methods=['GET', 'POST'])
def index():
    try:
        live_streams = Stream.query.filter_by(is_live=True).all()
    except Exception as e:
        live_streams = None
        flash("Error while getting list of streams. Please try refreshing the page", "error")
        app.logger.exception(e)

    form = SubscribeForm()
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        flash("you've subscribed successfully", "success")
        return redirect(url_for('.index'))

    random_stream = YoutubeStream.query.order_by(db.func.random()).first()
    return render_template('index.html', form=form, live_streams=live_streams, random_stream=random_stream)


@app.route('/json')
def json():
    try:
        return jsonify(stream_urls=[s.normal_url() for s in CurrentLiveStreams.get_streams()])
    except Exception as e:
        app.logger.exception(e)
        return jsonify(error=True)

if __name__ == '__main__':
    manager.run()
