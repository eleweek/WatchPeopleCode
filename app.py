from flask import Flask, render_template, request, redirect, url_for
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
from flask_wtf import Form
from wtforms import StringField, SubmitField, validators
from wtforms.validators import ValidationError

import praw
import os
from utils import youtube_video_id, is_live_stream
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
Bootstrap(app)
db = SQLAlchemy(app)

reddit_user_agent = "/r/WatchPeopleCode app"
youtube_api_key = os.environ['ytokkey']


class CurrentLiveStreams:
    ids = None
    _last_time_checked = None

    @classmethod
    def get_ids(self):
        if self._last_time_checked is None or datetime.now() - self._last_time_checked > timedelta(seconds=59):
            print "GETTING IDS"
            self._last_time_checked = datetime.now()
            self.ids = self._get_current_live_streams_ids()
        else:
            print "CACHED"

        return self.ids

    @classmethod
    def _extract_links_from_selftexts(self, selftext_html):
        soup = BeautifulSoup(selftext_html)
        return [a['href'] for a in soup.findAll('a')]

    @classmethod
    def _get_current_live_streams_ids(self):
        r = praw.Reddit(user_agent=reddit_user_agent)
        r.config.decode_html_entities = True

        submissions = list(r.get_subreddit('watchpeoplecode').get_new(limit=20))
        submission_urls = [s.url for s in submissions]
        selfposts_urls = sum([self._extract_links_from_selftexts(s.selftext_html) for s in submissions if s.selftext_html], [])
        youtube_ids = set(filter(None, [youtube_video_id(s) for s in selfposts_urls + submission_urls]))
        live_stream_ids = [yt_id for yt_id in youtube_ids if is_live_stream(yt_id, youtube_api_key)]

        return live_stream_ids


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
    live_stream_ids = CurrentLiveStreams.get_ids()

    form = SubscribeForm()
    added_successfully = False
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        added_successfully = True
        return redirect(url_for('.index'))

    return render_template('index.html', form=form, live_stream_ids=live_stream_ids, added_successfully=added_successfully)


if __name__ == '__main__':
    app.run(debug=True)
