$(document).ready(function() {
    var RequestConstructor = function(streamer_id, email, action) {
        this.url = '/_subscriptions';
        this.data = { "email": email,
                "streamer_id" : streamer_id
              };
        if (action === "subscribe") {
            this.method = "PUT";
            this.error = function() {
                console.log("Failed to subscribe to streamer with id " + streamer_id);
                bootbox.alert("Failed to subscribe to the streamer :(");
            };
            this.success = function() {
                console.log("Successfully subscribed to streamer with id " + streamer_id);
                subscribers_count = $(".streamer-subscribers-count-" + streamer_id);
                subscribers_count.html(+subscribers_count.html() + 1);
                $(".subscribe-button-" + streamer_id).not('.regular-streamer-subscribe-button').html("Unsubscribe").toggleClass("btn-success btn-danger");
            };
        } else if (action === "unsubscribe") {
            this.method = "DELETE";
            this.error = function() {
                console.log("Failed to unsubscribe from streamer with id " + streamer_id);
                bootbox.alert("Failed to unsubscribe from the streamer :(");
            };
            this.success = function() {
                console.log("Successfully unsubscribed from streamer with id " + streamer_id);
                subscribers_count = $(".streamer-subscribers-count-" + streamer_id);
                subscribers_count.html(+subscribers_count.html() - 1);
                $(".subscribe-button-" + streamer_id).not('.regular-streamer-subscribe-button').html("Subscribe").toggleClass("btn-success btn-danger");
            };
        }
    };

    var modifySubscriptions = function(streamer_id, email, action) {
        $.ajax(new RequestConstructor(streamer_id, email, action));
    };

    $(".subscribe-button").click(function(){
        var that = this;
        var action = $(that).html().toLowerCase();
        var streamer_id_class = $(that).attr("class").split(' ').filter(
                function(cn){
                    return cn.indexOf("subscribe-button-") === 0;
                }
            )[0];
        var streamer_id = +streamer_id_class.split('-')[2];
        var email = $.cookie('email');
        var only_id = $.cookie('subscribe_send_only_id') == "true";
        console.log("Cookie email " + email);
        console.log("Cookie only_id " + only_id);
        if (only_id) {
            modifySubscriptions(streamer_id, email, action);
            return;
        }
        if (action === "subscribe") {
            bootbox.prompt({
                title: "What is your email?",
                value: email,
                callback: function(result) {
                    if (result !== null) {
                        modifySubscriptions(streamer_id, result, action);
                    }
                }
            });
        }
    });

});
