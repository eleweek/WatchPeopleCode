from apscheduler.schedulers.blocking import BlockingScheduler
from app import get_current_live_streams, db, Stream

sched = BlockingScheduler()


@sched.scheduled_job('interval', seconds=20)
def update_state():
    print "updating_state"
    for ls in Stream.query:
        if ls.status == 'live':
            ls.status = 'completed'

    try:
        live_streams = get_current_live_streams()
    except Exception as e:
        db.session.rollback()
        print e
        raise

    print live_streams
    for ls in live_streams:
        ls.status = 'live'

    db.session.commit()

sched.start()
