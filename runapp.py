from gevent import monkey
monkey.patch_all()

from wpc import app, db, socketio
from wpc.views import add_force_test_login

from flask.ext.migrate import Migrate, MigrateCommand
from flask.ext.script import Manager


migrate = Migrate(app, db)
manager = Manager(app)
manager.add_command('db', MigrateCommand)


@manager.command
def run():
    app.debug = True
    add_force_test_login(app)
    socketio.run(app)

if __name__ == '__main__':
    manager.run()
