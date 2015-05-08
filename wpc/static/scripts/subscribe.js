var do_subscribe = function(streamer_id, email) {
    $.ajax({
        method: "POST",
        url: '/_subscribe_to_streamer',
        data: { "email": email,
                "streamer_id" : streamer_id
              },
        error: function() {
            console.log("Failed to subscribe to streamer with id " + streamer_id);
            bootbox.alert("Failed to subscribe to the streamer :(");
        },
        success: function() {
            console.log("Successfully subscribed to streamer with id " + streamer_id);
            $(".subscribe-button-" + streamer_id).hide();
        }
    });
};

$(document).ready(function() {
    $(".subscribe-button").click(function(){
        var that = this;
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
            do_subscribe(streamer_id, email);
            return;
        }
        bootbox.prompt({
            title: "What is your email?",
            value: email,
            callback: function(result) {
                if (result !== null) {
                    do_subscribe(streamer_id, result);
                }
            }
        });
    });
});
