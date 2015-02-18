var app = angular.module('WPC', ['ngRoute']);

app.config(['$routeProvider', 
	function($routeProvider) {
		$routeProvider.
			when('/live', {
				template: "<p>Hey guys</p>"
			}).
			when('upcoming', {
				template: "<p>I'm upcmomnign</p>"
			}).
			when('completed', {
				template: "<p>I'm completed</p>"
			}).
			otherwise({
				redirectTo: '/live'
			});
	}])

app.controller('MainCtrl', function($scope) {
	$scope.streams = [
		{
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
	    }
	]
});
