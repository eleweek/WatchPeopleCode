var app = angular.module('WPC', []);

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
