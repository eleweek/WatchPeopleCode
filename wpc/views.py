from wpc import db, app, socketio
from wpc.models import MozillaStreamHack  # NOQA
from wpc.models import YoutubeStream, WPCStream, Stream, Streamer, Subscriber, Idea, ChatMessage, get_or_create
from wpc.forms import SubscribeForm, EditStreamerInfoForm, EditStreamTitleForm, SearchForm, IdeaForm

from flask import render_template, request, redirect, url_for, flash, jsonify, g, Response, session, abort
from flask.ext.login import login_user, logout_user, login_required, current_user
from jinja2 import escape, evalcontextfilter, Markup
from flask.ext.socketio import emit, join_room

from uuid import uuid4
import praw
from crossdomain import crossdomain
import random
from feedgen.feed import FeedGenerator
from datetime import datetime
import pytz


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


def process_idea_form(idea_form):
    if idea_form.submit_button.data and idea_form.validate_on_submit():
        idea = Idea()
        idea_form.populate_obj(idea)
        db.session.add(idea)
        db.session.commit()
        flash("Your idea was added successfully", "success")
        return redirect(url_for("idea_list"))


@app.route('/', methods=['GET', 'POST'])
def index():
    live_streams = Stream.query.filter_by(status='live').order_by(Stream.actual_start_time.desc().nullslast(), Stream.id.desc()).all()
    # Uncomment this when mozilla guys start livestreaming
    # live_streams.insert(0, MozillaStreamHack())
    idea_form = IdeaForm(prefix='idea')
    redir = process_idea_form(idea_form)
    if redir:
        return redir

    subscribe_form = SubscribeForm(prefix='subscribe')
    if subscribe_form.submit_button.data and subscribe_form.validate_on_submit():
        subscriber = Subscriber()
        subscribe_form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        flash("you've subscribed successfully", "success")
        return redirect(url_for('.index'))

    random_stream = YoutubeStream.query.filter(YoutubeStream.status != 'upcoming').order_by(db.func.random()).first()
    upcoming_streams = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time.asc()).all()
    return render_template('index.html', subscribe_form=subscribe_form, idea_form=idea_form, live_streams=live_streams,
                           random_stream=random_stream,
                           upcoming_streams=upcoming_streams)


@app.route('/idea_list', methods=['GET', 'POST'])
def idea_list():
    ideas = Idea.query.order_by(Idea.id.desc()).all()

    idea_form = IdeaForm(prefix='idea')
    redir = process_idea_form(idea_form)
    if redir:
        return redir

    return render_template("idea_list.html", ideas=ideas, idea_form=idea_form)


# TODO it is copypasted from index(), but whatever, this is one time change
@app.route('/onlineconf', methods=['GET', 'POST'])
def onlineconf():
    streams = YoutubeStream.query.filter_by(confstream=True).filter(
        Stream.status == 'completed').order_by(
        Stream.actual_start_time.desc().nullsfirst(),
        Stream.id.desc()).all()

    form = SubscribeForm()
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()
        flash("you've subscribed successfully", "success")
        return redirect(url_for('.index'))

    return render_template('onlineconf.html', form=form, streams=streams)


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


def nl2br_py(value):
    result = (u'%s' % escape(value)).replace('\n', '<br>')
    return result


@app.route('/streamer/<streamer_name>/popout_chat', methods=["GET", "POST"])
def streamer_popout_chat(streamer_name):
    streamer = Streamer.query.filter_by(reddit_username=streamer_name).first_or_404()
    return render_template("streamer_popout_chat.html", streamer=streamer)


@app.route('/streamer/<streamer_name>', defaults={'page': 1}, methods=["GET", "POST"])
@app.route('/streamer/<streamer_name>/<int:page>', methods=["GET", "POST"])
def streamer_page(streamer_name, page):
    streamer = Streamer.query.filter_by(reddit_username=streamer_name).first_or_404()
    wpc_stream = streamer.streams.filter_by(type='wpc_stream').first()
    streams = streamer.streams
    if wpc_stream:
        streams = streams.filter(Stream.id != wpc_stream.id)
    streams = streams.order_by(Stream.actual_start_time.desc().nullslast()).paginate(page, per_page=5)
    info_form = EditStreamerInfoForm(prefix='info')
    title_form = EditStreamTitleForm(prefix='title')

    if current_user.is_authenticated() and current_user == streamer:
        if request.method == 'POST':
            if info_form.submit_button.data:
                if info_form.validate_on_submit():
                    current_user.populate(info_form)
                    db.session.commit()
                    flash("Updated successfully", category='success')
                    return redirect(url_for('.streamer_page', streamer_name=streamer_name, page=page))
                else:
                    return render_template('streamer.html', streamer=streamer,
                                           streams=streams, info_form=info_form,
                                           title_form=title_form, edit_info=True,
                                           edit_title=False, wpc_stream=wpc_stream)

            elif title_form.submit_button.data:
                if title_form.validate_on_submit():
                    wpc_stream.title = title_form.title.data
                    db.session.commit()
                    return jsonify(newTitle=Markup.escape(title_form.title.data))

                else:
                    return render_template('streamer.html', streamer=streamer,
                                           streams=streams, info_form=info_form,
                                           title_form=title_form, edit_info=False,
                                           edit_title=True, wpc_stream=wpc_stream)
        else:
            info_form.youtube_channel.data = current_user.youtube_channel
            info_form.twitch_channel.data = current_user.twitch_channel
            info_form.info.data = current_user.info
            if wpc_stream:
                title_form.title.data = wpc_stream.title

    return render_template('streamer.html', streamer=streamer,
                           streams=streams, info_form=info_form,
                           title_form=title_form, edit_info=False,
                           edit_title=False, wpc_stream=wpc_stream)


@app.route('/json')
@crossdomain(origin='*', max_age=15)
def stream_json():
    def make_dict(stream):
        return {'username': stream.streamer.reddit_username if stream.streamer else None,
                'title': stream.title, 'url': stream.normal_url(), 'viewers': stream.current_viewers,
                'scheduled_start_time': stream.scheduled_start_time, 'actual_start_time': stream.actual_start_time}
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
    if True:  # str(session['unique_key']) == request.args.get('state', ''):
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


def authenticate_streamer():
    streamer_username = request.values.get('name', '')
    rtmp_secret = request.values.get('pass', '')
    streamer = Streamer.query.filter_by(reddit_username=streamer_username).first()
    if not streamer or not streamer.rtmp_secret or streamer.rtmp_secret != rtmp_secret:
        app.logger.info("Fail to check credentials for streamer {}", streamer_username)
        return None, None
    return get_or_create(WPCStream, channel_name=streamer_username), streamer


@app.route('/rtmp_auth', methods=['POST'])
def rtmp_auth():
    stream, streamer = authenticate_streamer()
    if stream is None:
        abort(403)

    stream.streamer = streamer

    # test stream
    if streamer.test:
        db.session.commit()
        return "OK"

    stream.status = 'live'
    stream.actual_start_time = datetime.utcnow()
    db.session.commit()
    return "OK"


@app.route('/rtmp_done', methods=['POST'])
def rtmp_done():
    stream, streamer = authenticate_streamer()
    if stream is not None:
        stream.status = 'completed'
        stream.actual_start_time = None
        stream.current_viewers = None
        db.session.commit()
    return "OK"


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully", 'info')
    return redirect(url_for(".index"))


@app.route("/podcast_feed.xml")
def podcast_feed():
    logo_url = url_for("static", filename="wpclogo_big.png", _external=True)

    fg = FeedGenerator()
    fg.load_extension('podcast')
    fg.podcast.itunes_category('Technology', 'Podcasting')
    fg.podcast.itunes_image(logo_url)
    fg.author({'name': 'Nathan Kellert', 'email': 'nathankellert@gmail.com'})
    fg.link(href='http://watchpeoplecode.com/podcast_feed.xml', rel='self')
    fg.title('WPC Coders Podcast')
    fg.description('WPC Coders Podcast is a weekly peek into the lives of developers and the WatchPeopleCode community. Our goal is to keep our listeners entertained by giving them new and interesting insights into our industry as well as awesome things happening within our own community. Here, you can expect hear about some of the latest news, tools, and opportunities for developers in nearly every aread of our industry. Most importantly, we hope to have some fun and a few laughs in ways only other nerds know how.')  # NOQA

    episodes = [('ep1.mp3', 'Episode 1', datetime(2015, 02, 21, 23), 'Learn all about the WPC hosts, and where we came from in Episode 1!'),
                ('ep2.mp3', 'Episode 2', datetime(2015, 02, 28, 23), 'This week we cover your news, topics and questions in episode 2!'),
                ('ep3.mp3', 'Episode 3', datetime(2015, 03, 07, 23), "On todays podcast we talk to WatchPeopleCode's founder Alex Putilin. Hear about how the reddit search engine thousands watched him write. Also, hear the inside scoop of how WatchPeopleCode got started!"),  # NOQA
                ('ep4.mp3', 'Episode 4', datetime(2015, 03, 14, 23), "This week we talk to FreeCodeCamps Quincy Larson(http://www.freecodecamp.com) about their project that combines teaching new developers how to code and completing projects for non-profits! Lets find out how this group of streamers code with a cause!")]  # NOQA

    for epfile, eptitle, epdate, epdescription in episodes[::-1]:
        epurl = "https://s3.amazonaws.com/wpcpodcast/{}".format(epfile)
        fe = fg.add_entry()
        fe.id(epurl)
        fe.title(eptitle)
        fe.description(epdescription)
        fe.podcast.itunes_image(logo_url)
        fe.pubdate(epdate.replace(tzinfo=pytz.UTC))
        fe.enclosure(epurl, 0, 'audio/mpeg')

    return Response(response=fg.rss_str(pretty=True),
                    status=200,
                    mimetype='application/rss+xml')


chat_users = list()


@socketio.on('connect', namespace='/chat')
def chat_connect():
    print('New connection')
    return True


@socketio.on('initialize', namespace='/chat')
def chat_initialize():
    first_words = ['True', 'False', 'For', 'While', 'If', 'Else', 'Elif', 'Undefined', 'Do',
                   'Exit', 'Continue', 'Super', 'Break', 'Try', 'Catch', 'Class', 'Object',
                   'Def', 'Var', 'Pass', 'Return', 'Static', 'Const', 'Template', 'Delete', 'Int',
                   'Float', 'Struct', 'Void', 'Self', 'This']
    second_words = ['C', 'C++', 'Lisp', 'Python', 'Java', 'JavaScript', 'Pascal', 'Objective-C',
                    'C#', 'Perl', 'Ruby', 'Ada', 'Haskell', 'Octave', 'Basic', 'Fortran', 'PHP', 'R',
                    'Assembly', 'COBOL', 'Rust', 'Swift', 'Bash']

    if current_user.is_authenticated():
        session['username'] = current_user.reddit_username
    elif 'username' not in session or session['username'] in chat_users:
        while True:
            session['username'] = random.choice(first_words) + ' ' + random.choice(second_words)
            if session['username'] not in chat_users:
                break
    chat_users.append(session['username'])


def check_chat_access_and_get_streamer(streamer_username=None):
    if 'username' not in session:
        abort(403)
    if streamer_username is not None:
        streamer = Streamer.query.filter_by(reddit_username=streamer_username.strip()).first_or_404()
        return streamer


@socketio.on('join', namespace='/chat')
def join(streamer_username):
    streamer = check_chat_access_and_get_streamer(streamer_username)
    join_room(streamer.reddit_username)
    emit('last_messages',
         [{"sender": msg.sender,
           "text": nl2br_py(msg.text)}
          for msg in reversed(ChatMessage.query.filter_by(streamer=streamer).order_by(ChatMessage.id.desc()).limit(20).all())])
    emit('join', True, session['username'])


@socketio.on('disconnect', namespace='/chat')
def chat_disconnect():
    if 'username' not in session:
        abort(403)
    chat_users.remove(session['username'])


@socketio.on('message', namespace='/chat')
def chat_message(message_text, streamer_username):
    streamer = check_chat_access_and_get_streamer(streamer_username)
    cm = ChatMessage(streamer=streamer, text=message_text, sender=session['username'])
    db.session.add(cm)
    db.session.commit()

    message = {"sender": session['username'],
               "text": nl2br_py(message_text)}
    emit("message", message, room=streamer.reddit_username)
    return True


@socketio.on_error_default
def default_error_handler(e):
    app.logger.error(e)
