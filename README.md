# Amqpircbot
__NB! This readme is obsolete. The commands should work, but a lot of new features have been added.__
__The readme will be updated when all the planned new features have been added.__

Python scripts that form an AMQP/RabbitMQ<>IRC proxy. AMQP messages can be output to IRC, 
and you can send AMQP messages from IRC by sending commands to the bot.

Amqpirc was written by Thomas Steen Rasmussen <thomas@gibfest.dk>, the latest version
can always be found on Github: https://github.com/tykling/amqpirc - pull requests are welcome.

## List of features
- Relay AMQP messages to IRC
- Send messages from IRC to AMQP
- Manage lists of routingkeys to allow/deny relaying of messages
- Control which users have access to the bot commands

# Usage
The ircbot is started by executing amqpircbot.py (see usage below) which then connects to irc and
spawns a process listening for amqp-messages. Recieved messages are written to, and subsequently 
read + deleted from, a supplied path (amqpspoolpath).
Access control to the bot can be supplied by providing a config with user credentials. If no config
is supplied, everybody can use the bot. 

## Allow/deny routingkeys
Two tables of routingkeys control which messages are ignored/relayed to irc: A table containing allowed
routingkeys and a table containing routingkeys to deny. The allow table is checked first and if it is
allowed, the deny table is checked to see if there is a more specific rule denying the messages. The 
wildcard '#' can be used to allow/deny ranges of routingkeys. E.g. the tables

    Allowed routingkeys:
        this.is
        this.is.a.#
    Denied routingkeys:
        this.is.a.routingkey

would allow routingkey `this.is` and all routingkeys starting with `this.is.a` except for the routingkey
 `this.is.a.routingkey`. Default configuration is `#` in the allow table and nothing in deny table, i.e.
all routingkeys are relayed.

## Command line usage example 
For a list of command line options (and their defaults):

    $ ./amqpircbot.py -h
    Usage: amqpircbot.py [options]
    
    Options:
    -h, --help            show this help message and exit
    -d, --debug           Set to enable debugging, output received IRC messages to console and more.
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
    -C config, --config=config 
                        The path of the config file (default:'./amqpircbot_config')
    -a amqpserver, --amqphost=amqpserver
                            The AMQP/RabbitMQ server hostname or IP (default: 'localhost')
    -u user, --amqpuser=user
                            The AMQP username
    -p password, --amqppass=password
                            The AMQP password (omit for password prompt). Set to 'nopass' if user/pass should not be used
    -e exchange, --amqpexchange=exchange
                            The AMQP exchange name (default 'myexchange')
    -r routingkey, --routingkey=routingkey
                            Comma seperated list of routingkeys to listen for. (default: '#')
    -s amqpspoolpath, --amqpspoolpath=amqpspoolpath
                            The path of the spool folder (default: '/var/spool/amqpirc/')
    -I ignore, --ignore=ignore
                            Comma seperated list of routing keys to ignore (default: None)

## IRC commands
The following commands exist for amqpircbot:
- `ping` See if the bot is alive.
- `amqpsend <routingkey> <message body>` Sends a amqp message.
- `listrules <table>` List routingkey rules for one of the tables. `<table>` can be "allow" or "deny". 
- `delrule <table> <entry no.>` Delete routingkey number `<entry no.>` from `<table>`
- `addrule <table> <routingkey>` Add the key `<routingkey>` to table `<table>`

The general format for speaking to the bot is `<botnick>: <command>`.

### IRC command examples

    22:41 <@Tykling> amqpirc: ping
    22:41 < amqpirc> Tykling: pong
    22:41 <@Tykling> amqpirc: amqpsend test.routingkey.lol message body goes here
    22:41 < amqpirc> Routingkey: test.routingkey.lol
    22:41 < amqpirc> message body goes here

## Example config

    users = { 
              # User entry example
              {
              nick = "tykling"              # irc nick of the user
              host = "this.is.a.host.org"   # hostname of the user
              usertype = "admin"            # usertype, have not been implemented yet
              }                                             
    
              # Compact example
              { nick="borgtu" host="127.0.0.1" usertype="admin" }
            } 

