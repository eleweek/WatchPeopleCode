from update_state import r, get_submission_urls, get_stream_from_url, get_reddit_username
from app import Streamer, Submission, TwitchStream, db, get_or_create


def add_streamers():
    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=None)
    for s in submissions:
        for url in get_submission_urls(s):
            stream = get_stream_from_url(url, s.id)
            if stream and stream.streamer is None:
                reddit_username = get_reddit_username(s, url)
                if reddit_username:
                    stream.streamer = get_or_create(Streamer, reddit_username=reddit_username)
                    stream._update_status()

                db.session.add(stream)
    db.session.commit()


def add_submissions():
    submissions = r.get_subreddit('watchpeoplecode').get_new(limit=None)
    for s in submissions:
        for url in get_submission_urls(s):
            stream = get_stream_from_url(url, s.id)
            if stream:
                submission = get_or_create(Submission, submission_id=s.id)
                if submission not in stream.submissions:
                    stream.submissions.append(submission)
    db.session.commit()


# move submission_id to submissions if needed
def move_submissions():
    q = TwitchStream.query
    for stream in q:
        if stream.submission_id:
            submission = get_or_create(Submission, submission_id=stream.submission_id)
            if submission not in stream.submissions:
                stream.submissions.append(submission)
    db.session.commit()


# delete twitch stream's copies
def delete_copies():
    q = TwitchStream.query.order_by(TwitchStream.last_time_live.desc().nullslast(), TwitchStream.id)
    for stream in q.all():
        copies = q.filter_by(channel=stream.channel).all()
        if len(copies) > 1:
            for copy in copies[1:]:
                stream.submissions = list(set(stream.submissions + copy.submissions))
                db.session.delete(copy)

    db.session.commit()
