# Amqpircbot
Python scripts that form an AMQP/RabbitMQ<>IRC proxy. AMQP messages can be output to IRC, 
and you can send AMQP messages from IRC by sending commands to the bot.

Amqpirc was initially written by Thomas Steen Rasmussen <thomas@gibfest.dk>,  
with a modified/enhanced version developed by Lasse Grinderslev Andersen <borgtu@etableret.dk>.
Latest version can be found on Github: https://github.com/tykling/amqpirc or 
https://github.com/borgtu/amqpirc - pull requests are welcome.
 
### List of features
- Relay AMQP messages to IRC and send messages from IRC to AMQP
- Spawn multiple bots at once
- Manage lists of routingkeys to allow/deny relaying of messages
- Create your own tables for special message formatting
- Basic AMQP connection and table control through IRC
- Control which users have access to the bot commands

# Usage
The ircbot is started by executing amqpircbot.py and parsing a comma-seperated list of config files to it (see example config file below).
Each config give rise to a AMQPBot instance created by the credentials supplied in the config. 
If a name with no path is supplied, the path defaults to path of amqpircbot.py. Optionally 'debug' can be
parsed as a second argument which gives additional output to the prompt. 

    $ ./amqpircbot.py /path/to/config1,config2,/another/path/to/conf3 debug 

or with less outputi to e.g. the terminal:

    $ ./amqpircbot.py /path/to/config1,config2,/another/path/to/conf3

### Allow/deny routingkeys
Two tables of routingkeys control which messages are ignored and relayed to irc: A table containing allowed
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
all routingkeys are relayed. These tables can be specified in the config and modified via IRC commands.
Note that this has nothing to do with what routing key the bot is listening to: this filtering is done 
after the messages have been fetched from the AMQP queue.

### Message formatting tables
Besides the tables mentioned above, it is possible to create your own tables with routing keys and templates
to use when relaying a AMQP message to IRC (that matches one of the routing keys in the table). This can be useful
to highlight e.g. important AMQP messages with coloring and so on. It works almost like above: You create tables with
routing keys and a templates. If a message matches none of the routing keys from the user-defined tables it will use a default
formatting template which can configured as well. The following codes can be used to modify text on IRC:

    Bold            = \\x02     
    Color           = \\x03 
    Italic          = \\x09     
    StrikeThrough   = \\x13     
    Reset           = \\x0f     
    Underline       = \\x15     
    Underline2      = \\x1f     
    Reverse         = \\x16      

If the color code is used it should be adjoined with one or two comma seperated numbers for text or text,background colors.
The different colors and corresponding codes are: 

    White       =   0
    Black       =   1
    DarkBlue    =   2
    DarkGreen   =   3
    Red         =   4
    DarkRed     =   5
    DarkViolet  =   6
    Orange      =   7
    Yellow      =   8
    LightGreen  =   9
    Cyan        =  10
    LightCyan   =  11
    Blue        =  12
    Violet      =  13
    DarkGray    =  14
    LightGray   =  15

I.e. "\\x034,8 text \\x034,8" will produce 'text' in red letters on yellow background.
See the commented example config file for details of this works. 

## Configuration and config example 
Configuration of the bots is done by supplying json-encoded config files at startup. The config files contains information about
AMQP settings, IRC server settings etc. In addition it is possible to specify different table types as described above. The '%' symbol
is used for making comments in the configuration files. If an entry is omitted or set to nothing (i.e. "value" : "") default values is
used. A commented example is shown below, which also explains the details of the tables'
specification and meaning:

    % Commented example (json) config for the AMQPBot
    % Use '%' for comments...
    % This is the options for the AMQP and IRC clients, they should be pretty explanatory.
    {
    "amqp_options" : {
            "server"     : "127.0.0.1",  % The AMQP/RabbitMQ server hostname or IP (default: 'localhost')
            "user"       : "guest",      % The AMQP username (default: 'guest')
            "password"   : "guest",      % The AMQP password (default: 'guest') 
            "exchange"   : "myexchange", % The AMQP exchange name (default 'myexchange')
            "routingkey" : "#",          % Routingkey to listen for. (default: '#')
            "maxfetch"   : "20",         % Maxminum number of fetches per fetch-session (default: '20').
            "vhost"      : "/"           % The AMQP vhost (default: '/')
        },
    "irc_options" : {
            "host" : "irc.freenode.net", % The IRC server hostname or IP (default: 'irc.efnet.org')
            "port" : "6697",             % The IRC server port (default: 6667)
            "nick" : "amqpbot",          % The bots IRC nickname (default: 'amqpirc')
            "realname" : "",             % The bots IRC realname (default: 'amqpirc')
            "ident" : "",                % The bots IRC ident (default: 'amqpirc')
            "channel" : "amqpbotchan",   % The IRC channel the bot should join (default: '#amqpirc')
            "ssl_enabled" : "yes"        % Whether or not SSL should be enabled for the IRC connection (default: no)
        }        
    % This is the users that can access the bots commands.
    % If no users is supplied in the config (i.e. by ommitting the "users" entry), everyone is allowed.
    "users" : [
          {
              "nick"     : "Tykling", 
              "host"     : "gibfest.dk"
          },
          {
              "nick"     : "borgtu",
              "host"     : "ildipiben.dk"
          }
              ], 

    % This section defines the tables and their rules. There exists three special tables which is known to the AMQPBot beforehand:
    % 'allow', 'deny' and 'default'. Their meaning is special and have been described in the README.md. The 'default' table contains  
    % the standard template if the routing key of a message does not match any of the routing keys from the user-defined tables.
    % The '<RKEY>' keyword is substituted for the routing key when the AMQPBot is using the template for relaying a message. 
    % The '\\x038' is a colorcode for use in IRC (yellow). All the standard IRC color and control codes are in the 'README.md' file.
    % Atm there is no way to make templates for the body of a message. Only the way to display the routing key can be modified by the user.
    "tables" : [
        {
            "name"  : "allow", 
            "rkeys" : "#"
        }, 
        {
            "name"  : "deny",
            "rkeys" : "a.routingkey,and.another.key"
        },
        {
            "name"  : "deny",
            "rkeys" : "yet.another.key"
        },
        %table that produces yellow coloring of the routing key
        {
            "name"  : "warning",
            "rkeys" : "warning.key",
            "header": "\\x038 Routingkey: <RKEY>\\x03"
        },
        {
            "name"  : "default",
            "header": "Routingkey: <RKEY>"
        }
               ],
    }

### IRC commands
The following commands exist for amqpircbot:

    help:            "help <string>" lists all commands containing <string>. If <string> is empty, all commands are listed.
    amqppurgeopen:   opens the receiving amqp channel and purges the queue immediately after opening
    delrule:         "delrule <table> <entry no.>" removes the routing key rule no. <entry no.> from <table>
    listrules:       "listrules <table>" lists the routingkeys in <table>
    amqpdisconnect:  dicsonnects from amqp! (Should not be used for other than debugging)
    amqpsend:        "amqpsend <rkey> <body>" sends a amqp message with routing key <rkey> and message <body>.
    amqpchangekey:   change the routingkey the receiving channel is listening to
    addrule:         "addrule <table> <rkey>" adds <rkey>-rule to <table>
    ping:            "ping" makes the bot respond with a "pong" message (to check if it is alve).
    amqpopen:        opens the receiving amqp channel
    amqpclose:       closes the receiving amqp channel
    amqpstatus:      reports the status of the receiving channel: Is it closed/closing or open. Atm it seems like it says "closing" when it is closed

The general format for speaking to the bot is `<botnick>: <command>`.

### IRC command examples

    22:41 <@Tykling> amqpirc: ping
    22:41 < amqpirc> Tykling: pong
    22:41 <@Tykling> amqpirc: amqpsend test.routingkey.lol message body goes here
    22:41 < amqpirc> Routingkey: test.routingkey.lol
    22:41 < amqpirc> message body goes here
