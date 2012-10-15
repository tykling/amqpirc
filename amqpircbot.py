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

### load libraries
import os
import sys
import socket
import string
import time
from optparse import OptionParser

### define and handle command line options
use = "Usage: %prog [-H irchost -P ircport -n ircnick -r ircname -i ircident -c ircchannel -s spoolpath -S]"
parser = OptionParser(usage = use)
parser.add_option("-H", "--irchost", dest="host", metavar="host", default="irc.efnet.org", help="The IRC server hostname or IP")
parser.add_option("-P", "--ircport", dest="port", metavar="port", default=6667, help="The IRC server port")
parser.add_option("-n", "--ircnick", dest="nick", metavar="nick", default="amqpirc", help="The bots IRC nickname")
parser.add_option("-r", "--ircname", dest="realname", metavar="realname", default="amqpirc bot", help="The bots IRC realname")
parser.add_option("-i", "--ircident", dest="ident", metavar="ident", default="amqpirc", help="The bots IRC ident")
parser.add_option("-c", "--ircchannel", dest="ircchannel", metavar="ircchannel", default="#amqpirc", help="The IRC channel the bot should join")
parser.add_option("-s", "--spoolpath", dest="path", metavar="path", default="/var/spool/amqpirc/", help="The path of the spool folder")
parser.add_option("-S", "--ssl", action="store_true", dest="usessl", default=False)
options, args = parser.parse_args()

### initialize variables
readbuffer=""
joined=False

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Check access to spool path options.path
if not os.access(options.path, os.R_OK) or not os.access(options.path, os.W_OK):
    consoleoutput("Spool path %s is not readable or writable, bailing out" % options.path)
    sys.exit(1)

### IRC connect
s=socket.socket( )
s.settimeout(1)
consoleoutput("Connecting to IRC server %s port %s ..." % (options.host,options.port))
s.connect((options.host, int(options.port)))

### enable SSL if requested
if(options.usessl):
    s = ssl.wrap_socket(s)

### nick and USER
s.send("nick %s\r\n" % options.nick)
s.send("USER %s %s bla :%s\r\n" % (options.ident, options.host, options.realname))

### JOIN channel
consoleoutput("Joining channel %s" % options.ircchannel)
s.send("JOIN %s\r\n" % options.ircchannel)

while 1:
    ### Check if we already joined the channel
    if(joined):
        ### loop through all message file in the spool folder options.path
        dirList=os.listdir(options.path)
        for fname in dirList:
            f = open(os.path.join(options.path, fname), "r")
            linenumber=0
            ### loop through lines of the found message
            for line in f:
                linenumber += 1
                ### first line is the routingkey
                if(linenumber==1):
                    s.send("PRIVMSG %s :Routingkey: %s\r\n" % (options.ircchannel,line))
                else:
                    s.send("PRIVMSG %s :%s\r\n" % (options.ircchannel,line))
            f.close
            ### delete the spool file
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

            ### handle PING
            if(line[0]=="PING"):
                s.send("PONG %s\r\n" % line[1])
                continue

            ### handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                joined=True
                consoleoutput("Joined channel, waiting for messages ...")
                continue

            ### handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==options.ircchannel and line[3]==options.nick):
                joined=False
                consoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                s.send("JOIN %s\r\n" % options.ircchannel)
                continue
                
    ### allow exceptions to exit the script
    except (KeyboardInterrupt, SystemExit):
        raise
    
    ### continue the loop after a socket timeout and other exceptions
    except:
        continue
