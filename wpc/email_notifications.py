from wpc import app

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


def generate_email_notifications(stream):
    text = render_template('mails/stream_notification.txt', stream=stream)
    html = render_template('mails/stream_notification.html', stream=stream)
    subscribers = stream.streamer.subscribers
    subject = 'Watchpeoplecode: {} just went live'.format(stream.streamer.reddit_username)
    return text, html, subscribers, subject


def send_email_notifications(text, html, subscribers, subject="WatchPeopleCode: weekly update"):
    num_subscribers = len(subscribers)
    batch_size = 1000  # mailgun limit
    num_batches = (num_subscribers + batch_size - 1) / batch_size
    for b in xrange(num_batches):
        recipient_vars = {subscriber.email: {}
                          for subscriber in subscribers[b * batch_size: (b + 1) * batch_size]}
        print b, send_message(recipient_vars, subject, text, html)
