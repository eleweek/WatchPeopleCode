$(document).ready(function() {
    var update_viewers = function(stream_id) {
        $.ajax("/api/v1/streams/" + stream_id).done(function(data){
            count = data.data.viewers;
            cls_selector = ".viewers-count-stream-" + stream_id;
            if (count !== undefined) {
                $(cls_selector).html(count.toString() + " " + (count === 1 ? "viewer" : "viewers"));
            }
        });
    };

    $('.viewers-count-stream').each(function(){
        var that = this;
        var stream_id_class = $(that).attr("class").split(' ').filter(
                function(c) {
                    return c.indexOf("viewers-count-stream-") === 0;
                }
            )[0];
        var stream_id = +stream_id_class.split('-')[3];
        setInterval(function() { update_viewers(stream_id); }, 20000);
    });
});
