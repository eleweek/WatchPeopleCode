from wpc import db, app
from wpc.models import YoutubeStream, Stream, Streamer, Subscriber, get_or_create
from wpc.forms import SubscribeForm, EditStreamerInfoForm, SearchForm

from flask import render_template, request, redirect, url_for, flash, jsonify, g, send_from_directory, session
from flask.ext.login import login_user, logout_user, login_required, current_user
from jinja2 import escape, evalcontextfilter, Markup

from uuid import uuid4
import praw
from crossdomain import crossdomain
import os


@app.before_request
def add_ga_tracking_code():
    g.ga_tracking_code = app.config['GA_TRACKING_CODE']


@app.before_request
def create_search_form():
    g.search_form = SearchForm()


def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)

app.jinja_env.globals['url_for_other_page'] = url_for_other_page


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
