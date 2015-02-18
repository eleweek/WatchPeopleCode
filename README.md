# WatchPeopleCode
Helper app for /r/WatchPeopleCode subreddit

Currently available at: http://watchpeoplecode.com

To run, create .env file with these contents

```
SECRET_KEY=secret
DATABASE_URL=<your_url>
MAILGUN_API_URL=
MAILGUN_API_KEY=
MAILGUN_TEST_OPTION=true
MAILGUN_SMTP_LOGIN=
WPC_REDDIT_PASSWORD=
WPC_REDDIT_USERNAME=
WPC_YOUTUBE_KEY=
GA_TRACKING_CODE=
```

Then try `foreman run python app.py run`

## Working on the frontend
If you are interested in working on the frontend, we recently moved to a bower dependency model. To start hacking install bower, and an optional static server through NPM (and if you don't have npm, consult your package manager or http://nodejs.org).

```npm install -g bower http-server``` (Depending on your OS you will have to run this as root, try without root first)

Now, navigitate to the root directory of your WatchPeopleCode fork and execute ```bower install``` this downloads all of the needed dependencies and places them in static/lib.

If you need to install a new dependency please install it through bower with ```bower install angular``` where angular is the framework/library you want to install.
