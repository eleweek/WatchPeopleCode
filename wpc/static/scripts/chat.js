(function($, window, undefined){
    
    var myUsername;

    var chatAPI = {

        connect : function(done) {
        
            var that = this;

            this.socket = io.connect('/chat');
            this.socket.on('connect', done);

            this.socket.on('join', function(joined, my_username){
                if(that.onJoin){
                    that.onJoin(joined, my_username);
                }
            });

            this.socket.on('message', function(message){
                console.log(message);
                if(that.onMessage){
                    that.onMessage(message);
                }
            });

            this.socket.on('disconnect', function(){
                if (that.onDisconnect) {
                    that.onDisconnect();
                }
            });

        },

        sendMessage : function(message, onSent) {
            this.socket.emit('message', message, onSent);
        }

    };  

    var bindUI = function(){

        function pasteIntoInput(el, text) {
            el.focus();
            if (typeof el.selectionStart == "number"
                    && typeof el.selectionEnd == "number") {
                var val = el.value;
                var selStart = el.selectionStart;
                el.value = val.slice(0, selStart) + text + val.slice(el.selectionEnd);
                el.selectionEnd = el.selectionStart = selStart + text.length;
            } else if (typeof document.selection != "undefined") {
                var textRange = document.selection.createRange();
                textRange.text = text;
                textRange.collapse(false);
                textRange.select();
            }
        }
        var chat_msg_area = $(".compose-message-form").find("[name='message']")
        chat_msg_area.on("keypress", function(e){
            e = e || event;
            if (e.keyCode === 13) {
                if (!e.ctrlKey) {
                    if (chat_msg_area.val() !== "") {
                        $(".compose-message-form").submit();
                    } else {
                        return false;
                    }
                } else {
                    pasteIntoInput(this, "\n");
                }
            }
        });
    
        $(".compose-message-form").validate({
            submitHandler: function(form) {
                var form_group = $(form).find(".form-group");
                var chat_msg_area = form_group.find("textarea");
                if (chat_msg_area.val() !== "") {
                    form_group.children().attr("disabled", "disabled");
                    chatAPI.sendMessage(chat_msg_area.val(), function(sent){
                        if(sent){
                            form_group.children().removeAttr("disabled");
                            chat_msg_area.val("");
                            chat_msg_area.focus();
                        }
                    });
                }
            }
        });
        
        var format_message = function(message) {
            return "<b>" + message.sender + "</b>: " + message.text;
        }
        
        chatAPI.onJoin = function(joined, my_username) {
            if(joined){
                myUsername = my_username;
                $(".compose-message-form").show();
                $(".messages").append(
                    jQuery("<li>").html(
                        "<b><i>You've been connected. Send some messages! </i></b>"
                    )
                );
                $(".form-group").children().removeAttr("disabled");
            }
        };

        chatAPI.onMessage = function(message){
            var msgs = $(".messages");
            msgs.append(
                jQuery("<li>").html(
                    format_message(message)
                )
            ).animate({ scrollTop: msgs[0].scrollHeight }, "fast");
        };

        chatAPI.onDisconnect = function(){
            $(".messages").append(
                jQuery("<li>").html(
                    "<b><i>You've been disconnected.</i></b>"
                )
            );
        };
        
    };

    var ready = function(){
        bindUI();
        chatAPI.connect(function(){});
    };


    $(function(){ ready(); });


}($, window));
