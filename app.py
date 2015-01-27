from flask import Flask, render_template
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
import os


app = Flask(__name__)
Bootstrap(app)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
db = SQLAlchemy(app)


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)


@app.route('/')
def index():
    return render_template('index.html')


if __name__ == '__main__':
    app.run()
