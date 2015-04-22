from wpc import app
from wpc.models import Stream, Streamer, ChatMessage
from flask import abort, jsonify

from wpc.flask_utils import crossdomain


def transform_stream(stream):
    return {
        'id': stream.id,
        'title': stream.title,
        'user': stream.streamer.reddit_username if stream.streamer else None,
        'site': stream.type,
        'url': stream.normal_url(),
        'viewers': stream.current_viewers,
        'scheduled_start_time': stream.scheduled_start_time,
        'actual_start_time': stream.actual_start_time
    }


def transform_streamer(streamer):
    return {
        'name': streamer.reddit_username,
        'twitch': streamer.twitch_channel,
        'youtube': streamer.youtube_channel
    }


def transform_chat_message(message):
    return {
        'id': message.id,
        'sent_on': message.sent_on,
        'sender': message.sender,
        'text': message.text,
    }


@app.route('/api/v1/streams/live')
@crossdomain(origin='*', max_age=15)
def api_streams_live():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='live')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streams/upcoming')
@crossdomain(origin='*', max_age=15)
def api_streams_upcoming():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='upcoming')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streams/completed')
@crossdomain(origin='*', max_age=15)
def api_streams_past():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='completed')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streams/<int:stream_id>')
@crossdomain(origin='*', max_age=15)
def api_streams_view(stream_id):
    try:
        st = Stream.query.get_or_404(stream_id)
        return jsonify(data=transform_stream(st),
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers')
@crossdomain(origin='*', max_age=15)
def api_streamers():
    try:
        return jsonify(data=[transform_streamer(st) for st in Streamer.query.all()],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers/<name>')
@crossdomain(origin='*', max_age=15)
def api_streamers_view(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        return jsonify(data=transform_streamer(streamer),
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers/<name>/last_chat_messages/<msg_count>')
@crossdomain(origin='*', max_age=15)
def api_streamers_last_chat_messages(name, msg_count):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        return jsonify(data=[transform_chat_message(cm) for cm in streamer.chat_messages.order_by(ChatMessage.id.desc()).limit(msg_count)],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers/<name>/upcoming')
@crossdomain(origin='*', max_age=15)
def api_streamers_upcoming(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        streams = streamer.streams.filter_by(status='upcoming')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers/<name>/live')
@crossdomain(origin='*', max_age=15)
def api_streamers_live(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        streams = streamer.streams.filter_by(status='live')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/v1/streamers/<name>/completed')
@crossdomain(origin='*', max_age=15)
def api_streamers_past(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        streams = streamer.streams.filter_by(status='completed')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)
