amqpirc
=======
Python scripts that form an AMQP/RabbitMQ<>IRC proxy. AMQP messages can be output to IRC, 
and you can send AMQP messages from IRC by sending commands to the bot.

amqpirc was written by Thomas Steen Rasmussen <thomas@gibfest.dk>, the latest version
can always be found on Github: https://github.com/tykling/amqpirc - pull requests are welcome.


List of features
================
- Relay AMQP messages to IRC
- Send messages from IRC to AMQP


Background
==========
amqpircbot.py is the main script, the IRC bot which connects to the specified IRC server as 
well as the specified AMQP server. The bot will launch the amqpircspool.py and listen for messages 
as soon as it has joined the IRC channel. You should not need to launch amqpircspool.py manually.

The IRC bot logs messages to the console when something happens.


Example usage:
==============
    $ ./amqpircbot.py -h
    Usage: amqpircbot.py [options]

    Options:
      -h, --help            show this help message and exit
      -H irchost, --irchost=irchost
                            The IRC server hostname or IP (default: 'irc.efnet.org')
      -P ircport, --ircport=ircport
                            The IRC server port (default: 6667)
      -n nick, --ircnick=nick
                            The bots IRC nickname (default: 'amqpirc')
      -R realname, --ircname=realname
                            The bots IRC realname (default: 'amqpirc')
      -i ident, --ircident=ident
                            The bots IRC ident (default: 'amqpirc')
      -c ircchannel, --ircchannel=ircchannel
                            The IRC channel the bot should join (default: '#amqpirc')
      -S, --ssl             Set to enable SSL connection to IRC
      -a amqpserver, --amqphost=amqpserver
                            The AMQP/RabbitMQ server hostname or IP (default: 'localhost')
      -u user, --amqpuser=user
                            The AMQP username
      -p password, --amqppass=password
                            The AMQP password (omit for password prompt)
      -e exchange, --amqpexchange=exchange
                            The AMQP exchange name (default 'myexchange')
      -r routingkey, --routingkey=routingkey
                            The AMQP routingkey to listen for (default '#')
      -s amqpspoolpath, --amqpspoolpath=amqpspoolpath
                            The path of the spool folder (default: '/var/spool/amqpirc/')


Example IRC command
===================
22:41 <@Tykling> amqpirc: ping
22:41 < amqpirc> Tykling: pong
22:41 <@Tykling> amqpirc: amqpsend test.routingkey.lol message body goes here
22:41 < amqpirc> Routingkey: test.routingkey.lol
22:41 < amqpirc> message body goes here

Todo
====
- ACL support for IRC so not everyone can send commands to the bot
- Possibly flood control support for IRC
- Dynamically change (with IRC commands) which routingkey the bot using to listen for AMQP messages
- IRC socket timeout/disconnect handling
- Hide password somehow when launching the spool listener
- Look into merging the two scripts to one
- Check spool status through IRC commands
- Stop/start spooler through IRC commands
