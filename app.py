from flask import Flask, render_template, request, redirect, url_for, flash
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
from flask_wtf import Form
from wtforms import StringField, SubmitField, validators
from wtforms.validators import ValidationError

import praw
import os
from utils import youtube_video_id, is_live_yt_stream, twitch_channel, is_live_twitch_stream
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
Bootstrap(app)
db = SQLAlchemy(app)

reddit_user_agent = "/r/WatchPeopleCode app"
youtube_api_key = os.environ['ytokkey']


class YoutubeStream(object):
    def __init__(self, id):
        self.id = id

    def __eq__(self, other):
        return type(self) == type(other) and self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def html_code(self):
        return """
              <iframe id="ytplayer" type="text/html" width="640" height="390
                                                                 src="http://www.youtube.com/embed/{}?autoplay=0"
               frameborder="0"/>
              </iframe>
              """.format(self.id)


class TwitchStream(object):
    def __init__(self, channel):
        self.channel = channel

    def __eq__(self, other):
        return type(self) == type(other) and self.channel == other.channel

    def __hash__(self):
        return hash(self.channel)

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


def create_stream_from_url(url):
    ytid = youtube_video_id(url)
    if ytid is not None:
        return YoutubeStream(ytid) if is_live_yt_stream(ytid, youtube_api_key) else None

    tc = twitch_channel(url)
    if tc is not None:
        return TwitchStream(tc) if is_live_twitch_stream(tc) else None

    return None


class CurrentLiveStreams:
    _streams = None
    _last_time_checked = None

    @classmethod
    def get_streams(self):
        if self._last_time_checked is None or datetime.now() - self._last_time_checked > timedelta(seconds=59):
            self._last_time_checked = datetime.now()
            self._streams = self._get_current_live_streams()

        return self._streams

    @classmethod
    def _extract_links_from_selftexts(self, selftext_html):
        soup = BeautifulSoup(selftext_html)
        return [a['href'] for a in soup.findAll('a')]

    @classmethod
    def _get_current_live_streams(self):
        r = praw.Reddit(user_agent=reddit_user_agent)
        r.config.decode_html_entities = True

        submissions = r.get_subreddit('watchpeoplecode').get_new(limit=20)
        live_streams = set()
        for s in submissions:
            selfposts_urls = sum([self._extract_links_from_selftexts(s.selftext_html) for s in submissions if s.selftext_html], [])
            for url in selfposts_urls + [s.url]:
                stream = create_stream_from_url(url)
                if stream:
                    live_streams.add(stream)

        return live_streams


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)


def validate_email_unique(form, field):
    email = field.data
    if Subscriber.query.filter_by(email=email).first() is not None:
        raise ValidationError('This email is already in the database.')


class SubscribeForm(Form):
    email = StringField("Email address", [validators.DataRequired(), validators.Email(), validate_email_unique])
    submit_button = SubmitField('Subscribe')


@app.route('/', methods=['GET', 'POST'])
def index():
    live_streams = CurrentLiveStreams.get_streams()

    form = SubscribeForm()
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        flash("you've subscribed successfully", "success")
        return redirect(url_for('.index'))

    return render_template('index.html', form=form, live_streams=live_streams)


if __name__ == '__main__':
    app.run(debug=True)
