# WatchPeopleCode
Helper app for /r/WatchPeopleCode subreddit

Currently available at: http://watchpeoplecode.com

# The following information is obsolete, install anything however you want. Modify templates to work on frontend in templates/
## Working on the frontend
If you are interested in working on the frontend, we recently moved to a bower dependency model. To start hacking install bower, and an optional static server through NPM (and if you don't have npm, consult your package manager or http://nodejs.org).

```npm install -g bower http-server``` (Depending on your OS you will have to run this as root, try without root first)

Now, navigitate to the root directory of your WatchPeopleCode fork and execute ```bower install``` this downloads all of the needed dependencies and places them in static/lib.

If you need to install a new dependency please install it through bower with ```bower install angular``` where angular is the framework/library you want to install.
