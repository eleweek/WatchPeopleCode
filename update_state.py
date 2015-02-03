from apscheduler.schedulers.blocking import BlockingScheduler
from app import db, Stream, get_new_streams
from sqlalchemy import or_

sched = BlockingScheduler()


@sched.scheduled_job('interval', seconds=20)
def update_state():
    for ls in Stream.query.filter(or_(Stream.status != 'completed', Stream.status == None)):
        try:
            ls._get_api_status()
        except Exception as e:
            db.session.rollback()
            print e
            raise

    try:
        get_new_streams()
    except Exception as e:
        db.session.rollback()
        print e
        raise

    db.session.commit()

sched.start()
