amqpirc
=======

Python scripts to listen to an AMQP/RabbitMQ exchange and output messages to IRC.

- amqpircbot.py is the IRC bot which connects to the specified IRC server and outputs messages from the specified spool path.
- amqpircspool.py is the AMQP client which connects to AMQP/RabbitMQ and listens to the specified exchange, writing messages to the specified spool path.

Example usage:
==============
    $ ./amqpircbot.py -h
    Usage: amqpircbot.py [-H irchost -P ircport -n ircnick -r ircname -i ircident -c ircchannel -s spoolpath -S]

    Options:
      -h, --help            show this help message and exit
      -H host, --irchost=host
                            The IRC server hostname or IP (default: 'irc.efnet.org')
      -P port, --ircport=port
                            The IRC server port (default: 6667)
      -n nick, --ircnick=nick
                            The bots IRC nickname (default: 'amqpirc')
      -r realname, --ircname=realname
                            The bots IRC realname (default: 'amqpirc')
      -i ident, --ircident=ident
                            The bots IRC ident (default: 'amqpirc')
      -c ircchannel, --ircchannel=ircchannel
                            The IRC channel the bot should join (default: '#amqpirc')
      -s path, --spoolpath=path
                            The path of the spool folder (default: '/var/spool/amqpirc/')
      -S, --ssl             Set to enable SSL connection to IRC

    $ ./amqpircspool.py -h
    Usage: amqpircspool.py [-s amqpserver -u amqpuser -p amqppass -e amqpexchange -r routingkey]

    Options:
      -h, --help            show this help message and exit
      -H server, --amqphost=server
                            The AMQP/RabbitMQ server hostname or IP (default: 'localhost')
      -u user, --amqpuser=user
                            The AMQP username
      -p password, --amqppass=password
                            The AMQP password
      -e exchange, --amqpexchange=exchange
                            The AMQP exchange name (default 'myexchange')
      -r routingkey, --routingkey=routingkey
                            The AMQP routingkey (default '#')
      -s path, --spoolpath=path
                            The spool path (default '/var/spool/amqpirc')
