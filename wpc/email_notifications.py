from wpc import app
from wpc.models import Stream, Subscriber

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


def generate_email_notifications():
    # fix before use
    live = Stream.query.filter_by(status='live').order_by(Stream.scheduled_start_time).all()
    upcoming = Stream.query.filter_by(status='upcoming').order_by(Stream.scheduled_start_time).all()
    text = render_template('mails/stream_notification.txt', live_streams=live, upcoming_streams=upcoming)
    html = render_template('mails/stream_notification.html', live_streams=live, upcoming_streams=upcoming)
    return text, html


def send_email_notifications(text, html, subject="WatchPeopleCode: weekly update"):
    num_subscribers = Subscriber.query.count()
    batch_size = 1000  # mailgun limit
    num_batches = (num_subscribers + batch_size - 1) / batch_size
    for b in xrange(num_batches):
        recipient_vars = {subscriber.email: {} for subscriber in Subscriber.query.order_by(Subscriber.id).offset(b * batch_size).limit(batch_size)}
        print b, send_message(recipient_vars, subject, text, html)
