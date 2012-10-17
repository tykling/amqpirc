#!/usr/local/bin/python
#####################################################################
# amqpircbot.py is a part of amqpirc which is an AMQP to IRC proxy.
#
# amqpircbot.py is the IRC bot which connects to the specified IRC
# server and outputs messages from the specified spool path.
# 
# amqpircspool.py is the AMQP client which connects to AMQP/RabbitMQ
# and listens to the specified exchange, writing messages to the
# specified spool path.
#
# README and the latest version of the script can be found on Github:
# https://github.com/tykling/amqpirc
#####################################################################

### Load libraries
import os
import sys
import socket
import string
import time
from optparse import OptionParser

### Define and handle command line options
use = "Usage: %prog [-H irchost -P ircport -n ircnick -r ircname -i ircident -c ircchannel -s spoolpath -S]"
parser = OptionParser(usage = use)
parser.add_option("-H", "--irchost", dest="host", metavar="host", default="irc.efnet.org", help="The IRC server hostname or IP (default: 'irc.efnet.org')")
parser.add_option("-P", "--ircport", dest="port", metavar="port", default=6667, help="The IRC server port (default: 6667)")
parser.add_option("-n", "--ircnick", dest="nick", metavar="nick", default="amqpirc", help="The bots IRC nickname (default: 'amqpirc')")
parser.add_option("-r", "--ircname", dest="realname", metavar="realname", default="amqpirc bot", help="The bots IRC realname (default: 'amqpirc')")
parser.add_option("-i", "--ircident", dest="ident", metavar="ident", default="amqpirc", help="The bots IRC ident (default: 'amqpirc')")
parser.add_option("-c", "--ircchannel", dest="ircchannel", metavar="ircchannel", default="#amqpirc", help="The IRC channel the bot should join (default: '#amqpirc')")
parser.add_option("-s", "--spoolpath", dest="path", metavar="path", default="/var/spool/amqpirc/", help="The path of the spool folder (default: '/var/spool/amqpirc/')")
parser.add_option("-S", "--ssl", action="store_true", dest="usessl", default=False, help="Set to enable SSL connection to IRC")
options, args = parser.parse_args()

### Initialize variables
readbuffer=""
joined=False

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Check access to spool path options.path
if not os.access(options.path, os.R_OK) or not os.access(options.path, os.W_OK):
    consoleoutput("Spool path %s is not readable or writable, bailing out" % options.path)
    sys.exit(1)

### Check if options.ircchannel is prefixed with #, add it if not
if not (options.ircchannel[:1]=="#"):
    options.ircchannel="#%s" % options.ircchannel

### IRC connect
s=socket.socket( )
s.settimeout(1)
consoleoutput("Connecting to IRC server %s port %s ..." % (options.host,options.port))
s.connect((options.host, int(options.port)))

### Enable SSL if requested
if(options.usessl):
    consoleoutput("Enabling SSL for this connection...")
    import ssl
    s = ssl.wrap_socket(s)
else:
    consoleoutput("Not enabling SSL for this connection...")

### NICK and USER
s.send("nick %s\r\n" % options.nick)
s.send("USER %s %s bla :%s\r\n" % (options.ident, options.host, options.realname))

### JOIN irc channel
consoleoutput("Joining channel %s" % options.ircchannel)
s.send("JOIN %s\r\n" % options.ircchannel)

while 1:
    ### Check if we already joined the channel
    if(joined):
        ### Loop through all message file in the spool folder options.path
        dirList=os.listdir(options.path)
        for fname in dirList:
            f = open(os.path.join(options.path, fname), "r")
            linenumber=0
            ### Loop through lines of the found message
            for line in f:
                linenumber += 1
                ### First line is the routingkey
                if(linenumber==1):
                    s.send("PRIVMSG %s :Routingkey: %s\r\n" % (options.ircchannel,line))
                else:
                    s.send("PRIVMSG %s :%s\r\n" % (options.ircchannel,line))
            f.close
            ### Delete the spool file
            os.remove(os.path.join(options.path, fname))
            consoleoutput("AMQP message sent to IRC and deleted from spool file %s" % os.path.join(options.path, fname))

    ### Try reading data from the IRC socket, timeout is 1 second
    try:
        readbuffer=readbuffer+s.recv(1024)
        temp=string.split(readbuffer, "\n")
        readbuffer=temp.pop( )
        
        ### Loop through the lines received from the IRC server
        for line in temp:
            line=string.split(string.rstrip(line))

            ### Handle PING
            if(line[0]=="PING"):
                s.send("PONG %s\r\n" % line[1])
                continue

            ### Handle raw 433 (raw 433 is sent when the chosen nickname is in use)
            if(line[1]=="433"):
                consoleoutput("Nickname %s is in use, please try another" % options.nick)
                sys.exit(1)

            ### Handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                joined=True
                consoleoutput("Joined channel %s, waiting for messages to appear in spooldir %s" % (options.ircchannel,options.path))
                continue

            ### Handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==options.ircchannel and line[3]==options.nick):
                joined=False
                consoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                s.send("JOIN %s\r\n" % options.ircchannel)
                continue

            ### Handle raw 474 (raw 474 is sent when the bot tries to join the channel and is banned)
            if(line[1]=="474"):
                ### try joining again until successful, sleep 1 sec first to avoid flooding the server
                time.sleep(1)
                consoleoutput("Banned from channel %s - attempting rejoin..." % options.ircchannel)
                s.send("JOIN %s\r\n" % options.ircchannel)
                continue

    ### Allow exceptions to exit the script
    except (KeyboardInterrupt, SystemExit):
        raise

    ### Continue the loop after a socket timeout and other exceptions
    except:
        continue