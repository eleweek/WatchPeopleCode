from wpc import app
from wpc.models import Subscriber, Stream

from flask import render_template

import requests
import json


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


def generate_email_notifications(streamer):
    streams = streamer.streams.filter_by(status='live').all()
    text = render_template('mails/stream_notification.txt',
                           streamer=streamer, streams=streams)
    html = render_template('mails/stream_notification.html',
                           streamer=streamer, streams=streams)
    subscribers = streamer.subscribers.all()
    subject = 'Watchpeoplecode: {} just went live'.format(streamer.reddit_username)
    return text, html, subscribers, subject


def send_email_notifications(text, html, subscribers, subject="WatchPeopleCode: weekly update"):
    num_subscribers = len(subscribers)
    batch_size = 1000  # mailgun limit
    num_batches = (num_subscribers + batch_size - 1) / batch_size
    for b in xrange(num_batches):
        recipient_vars = {subscriber.email: {}
                          for subscriber in subscribers[b * batch_size: (b + 1) * batch_size]}
        print b, send_message(recipient_vars, subject, text, html)


def generate_stream_list():
    # fix before use
    live = Stream.query.filter_by(status='live').order_by(Stream.scheduled_start_time).all()
    upcoming = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time).all()
    text = render_template('mails/stream_list.txt', live_streams=live, upcoming_streams=upcoming)
    html = render_template('mails/stream_list.html', live_streams=live, upcoming_streams=upcoming)
    subscribers = Subscriber.query.all()
    subject = 'WatchPeopleCode: newsletter'
    return text, html, subscribers, subject
