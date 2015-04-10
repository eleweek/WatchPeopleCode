from wpc import app
from wpc.models import Stream, Streamer
from flask import abort, jsonify

from crossdomain import crossdomain

def transform_stream(stream):
    return {
        'id': stream.id,
        'title': stream.title,
        'user': stream.streamer.reddit_username,
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


@app.route('/api/streams/live')
@crossdomain(origin='*', max_age=15)
def api_streams_live():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='live')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streams/upcoming')
@crossdomain(origin='*', max_age=15)
def api_streams_upcoming():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='upcoming')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streams/completed')
@crossdomain(origin='*', max_age=15)
def api_streams_past():
    try:
        return jsonify(data=[transform_stream(st) for st in Stream.query.filter_by(status='completed')],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streams/<stream_id>')
@crossdomain(origin='*', max_age=15)
def api_streams_view(stream_id):
    try:
        st = Stream.query.get(stream_id)
        if st is None:
            abort(404)
        return jsonify(data=transform_stream(st),
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)


@app.route('/api/streamers')
@crossdomain(origin='*', max_age=15)
def api_streamers():
    try:
        return jsonify(data=[transform_streamer(st) for st in Streamer.query.all()],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streamers/<name>')
@crossdomain(origin='*', max_age=15)
def api_streamers_view(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        if streamer is None:
            abort(404)
        return jsonify(data=transform_streamer(streamer),
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streamers/<name>/upcoming')
@crossdomain(origin='*', max_age=15)
def api_streamers_upcoming(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        if streamer is None:
            abort(404)
        streams = streamer.streams.filter(Stream.status == 'upcoming')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streamers/<name>/live')
@crossdomain(origin='*', max_age=15)
def api_streamers_live(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        if streamer is None:
            abort(404)
        streams = streamer.streams.filter(Stream.status == 'live')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)

@app.route('/api/streamers/<name>/completed')
@crossdomain(origin='*', max_age=15)
def api_streamers_past(name):
    try:
        streamer = Streamer.query.filter_by(reddit_username=name).first_or_404()
        if streamer is None:
            abort(404)
        streams = streamer.streams.filter(Stream.status == 'completed')
        return jsonify(data=[transform_stream(st) for st in streams],
                       info={'status': 200})
    except Exception as e:
        app.logger.exception(e)
        abort(500)
