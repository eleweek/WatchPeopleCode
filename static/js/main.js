var app = angular.module('WPC', ['ngRoute']);

app.config(['$routeProvider', 
	function($routeProvider) {
		$routeProvider.
			when('/live', {
				templateUrl: "/templates/stream.html",
				controller: "LiveCtrl"
			}).
			when('/upcoming', {
				templateUrl: "/templates/stream.html"
			}).
			when('/completed', {
				templateUrl: "/templates/stream.html",
				controller: "CompletedCtrl"
			}).
			otherwise({
				redirectTo: '/live'
			});
	}]);

app.controller('LiveCtrl', function($scope, $http, $sce) {
	// $http.get('http://www.watchpeoplecode.com/json').success(function(data) {
	// 	$scope.streams = process(data, "live")

	// 	console.log($scope.streams)
	// });

	$scope.streams = process({"live": [{
	      "title": "Streaming some AngularJS!", 
	      "url": "http://twitch.tv/paked", 
	      "user": "paked",
	      "username": "hcwool"
	    }, 		{
	      "title": "Streaming some AngularJS!", 
	      "url": "http://twitch.tv/tyrantwarship",
	      "user": "paked", 
	      "username": "hcwool"
	    }, 		
	    {
	      "title": "Streaming some AngularJS!", 
	      "url": "http://twitch.tv/swagcs",
	      "user": "swagcs", 
	      "username": "hcwool"
	    }]}, 'live', $sce)


});

app.controller('CompletedCtrl', function($scope, $http, $sce) {
	console.log("Hello")
	// $http.get('http://www.watchpeoplecode.com/json').success(function(data) {
	// 	$scope.streams = process(data, "completed")

	// 	console.log($scope.streams)
	// });

	$scope.streams = process({"completed": [
    {
      "title": "Instruction Set Development - Part 5", 
      "url": "http://www.youtube.com/watch?v=MCFA-6JPvPQ", 
      "username": "ConformingCivilian"
    }, 
    {
      "title": "Beginner Java: Lesson 2", 
      "url": "http://www.youtube.com/watch?v=IT8snRacAcw", 
      "username": "add7"
    }, 
    {
      "title": "Building a Search Engine -- Season 2 episode 1", 
      "url": "http://www.youtube.com/watch?v=L2DJhwANoUQ", 
      "username": "godlikesme"
    }, 
    {
      "title": "Cutting CODE! Ep 3 - Building a SASS to CSS compiler! (well, almost)", 
      "url": "http://www.youtube.com/watch?v=stF4J3GI_-0", 
      "username": "davidwhitney"
    }]}, 'completed', $sce)

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
