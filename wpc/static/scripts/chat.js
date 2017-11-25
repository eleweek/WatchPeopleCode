(function($, window, undefined){
    
    var myUsername, streamer=$(".streamer-name").html();

    var chatAPI = {

        connect : function(done) {
        
            var that = this;

            this.socket = io.connect('/chat');
            this.socket.on('connect', done);

            this.socket.on('join', function(joined, my_username){
                console.log('join');
                if(that.onJoin){
                    that.onJoin(joined, my_username);
                }
            });

            this.socket.on('message', function(message){
                if(that.onMessage){
                    that.onMessage(message);
                }
            });

            this.socket.on('disconnect', function(){
                console.log('disconnect');
                if (that.onDisconnect) {
                    that.onDisconnect();
                }
                that.socket.emit('initialize');
                that.socket.emit('join', streamer);
            });

            this.socket.on('last_messages', function(messages, group){
                if (that.onLastMessages) {
                    that.onLastMessages(messages);
                }
            });

            this.socket.on('forbidden', function(){
                if (that.onForbidden) {
                    that.onForbidden();
                }
            });

            this.socket.on("clear", function(){
                if (that.onClear){
                    that.onClear();
                }
            });

            this.socket.emit('initialize');
            this.socket.emit('join', streamer);
        },

        sendMessage : function(message, onSent) {
            this.socket.emit('message', message, streamer, onSent);
        }

    };  

    var bindUI = function(){

        function pasteIntoInput(el, text) {
            el.focus();
            if (typeof el.selectionStart == "number" &&
                    typeof el.selectionEnd == "number") {
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
        var chat_msg_area = $(".compose-message-form").find("[name='message']");
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
            message.text = message.text.replace(/(\*\*|__)(.*?)\1/g, "<b>$2</b>"); //Markdown bold
            message.text = message.text.replace(/(\*|_)(.*?)\1/g, "<i>$2</i>"); //Markdown italic

            if (message.sender === myUsername) { 
                return '<b style="color: orangered">' + message.sender + '</b>: ' + message.text;
            } else {
                return '<b style="color: blue">' + message.sender + '</b>: ' + message.text;
            }
        };
        
        chatAPI.onJoin = function(joined, my_username) {
            if(joined){
                myUsername = my_username;
                $(".compose-message-form").show();
                $(".chat-loading").hide();
                $(".messages").append(
                    jQuery("<li>").html(
                        "<i>You've been connected.</i>"
                    )
                );
                $(".form-group").children().removeAttr("disabled");
            }else{
                myUsername = my_username;
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
                    "<i>You've been disconnected.</i>"
                )
            );
        };

        chatAPI.onLastMessages = function(messages){
            var msgs = $(".messages");
            msgs.empty();
            for (i = 0; i < messages.length; i++ ) {
                msgs.append(
                    jQuery("<li>").html(
                        format_message(messages[i])
                    )
                );
            }
            msgs.animate({ scrollTop: msgs[0].scrollHeight }, "fast");
        };

        chatAPI.onForbidden = function(){
            alert(
                "Sorry, this streamer disabled anonymous posting. " +
                "You can login with your reddit account if you have one."
            );
        };

        chatAPI.onClear = function(){
            $(".messages").html("<li><i>The chatroom has been cleared.</i></li>");
        };

    };

    var ready = function(){
        bindUI();
        chatAPI.connect(function(){});
    };


    $(function(){ ready(); });


}($, window));
