var app = angular.module('WPC', ['ngRoute', 'ngResource']);

app.config(['$routeProvider', 
	function($routeProvider) {
		$routeProvider.
			when('/live', {
				templateUrl: "/static/templates/stream.html",
				controller: "LiveCtrl"
			}).
			when('/upcoming', {
				templateUrl: "/static/templates/stream.html"
			}).
			when('/completed', {
				templateUrl: "/static/templates/stream.html",
				controller: "CompletedCtrl"
			}).
			otherwise({
				redirectTo: '/live'
			});
	}]);

app.controller('LiveCtrl', function($scope, $http, $sce) {
	$scope.isActive = function(str) {
		return str == 'live'
	}

	$http.get('http://www.watchpeoplecode.com/json').
		success(function(data) {
			console.log(data)
			$scope.streams = process(data, 'live', $sce)
		}).
		error(function() {
			console.log("ERROR")
			/* Act on the event */
		});
    $http.defaults.useXDomain = true;
});

app.controller('CompletedCtrl', function($scope, $http, $sce) {
	$scope.isActive = function(str) {
		return str == 'completed'
	}
	$http.get('http://www.watchpeoplecode.com/json').
		success(function(data) {
			console.log(data)
			$scope.streams = process(data, 'completed', $sce, max)
		}).
		error(function() {
			console.log("ERROR")
			/* Act on the event */
		});
});


function process(data, mode, $sce) {
	streams = data[mode]
	out = []
	for (var i = 0; i < streams.length; i++) {
		stream = streams[i]
		l = getLocation(stream.url)
		stream.youtube = true

		if (l.hostname == "twitch.tv") {
			stream.youtube = false
			url = stream.url.split("/")
			stream.user = url[url.length - 1]
		}else {
			url = stream.url.split("=")
			stream.id = url[url.length - 1]
			stream.embed = $sce.trustAsResourceUrl("http://www.youtube.com/embed/" + stream.id + "?rel=0&autoplay=0");
		}

		console.log(stream)
		out.push(stream)
	}

	return out
}

var getLocation = function(href) {
    var l = document.createElement("a");
    l.href = href;
    return l;
};
