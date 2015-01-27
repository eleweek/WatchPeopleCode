from flask import Flask, render_template, request
from flask_bootstrap import Bootstrap
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.properties import ColumnProperty
import os
from flask_wtf import Form
from wtforms import TextField, SubmitField, validators
from wtforms.validators import ValidationError


app = Flask(__name__)
app.secret_key = os.environ['SECRET_KEY'] 
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
Bootstrap(app)
db = SQLAlchemy(app)


class CaseInsensitiveComparator(ColumnProperty.Comparator):
    def __eq__(self, other):
        return db.func.lower(self.__clause_element__()) == db.func.lower(other)


class Subscriber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.column_property(db.Column(db.String(256), unique=True, nullable=False), comparator_factory=CaseInsensitiveComparator)


def validate_email_unique(form, field):
    email = field.data
    if Subscriber.query.filter_by(email=email).first() is not None:
        raise ValidationError('This email is already in base.')


class SubscribeForm(Form):
    email = TextField("Email address", [validators.Required(), validators.Email(), validate_email_unique])
    submit_button = SubmitField('Subscribe')


@app.route('/', methods = ['GET', 'POST'])
def index():
    form = SubscribeForm()
    if request.method == "POST" and form.validate_on_submit():
        subscriber = Subscriber()
        form.populate_obj(subscriber)
        db.session.add(subscriber)
        db.session.commit()

    return render_template('index.html', form=form)


if __name__ == '__main__':
    app.run()
