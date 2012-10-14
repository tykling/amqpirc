#!/usr/local/bin/python

### load libraries
import os
import sys
import socket
import string
import time
from optparse import OptionParser

### define and handle command line options
use = "Usage: %prog [-H irchost -P ircport -n ircnick -r ircname -i ircident -c ircchannel -s spoolpath]"
parser = OptionParser(usage = use)
parser.add_option("-H", "--irchost", dest="HOST", metavar="HOST", default="irc.efnet.org", help="The IRC server hostname or IP")
parser.add_option("-P", "--ircport", dest="PORT", metavar="PORT", default=6667, help="The IRC server port")
parser.add_option("-n", "--ircnick", dest="NICK", metavar="NICK", default="amqpirc", help="The bots IRC nickname")
parser.add_option("-r", "--ircname", dest="REALNAME", metavar="REALNAME", default="amqpirc bot", help="The bots IRC realname")
parser.add_option("-i", "--ircident", dest="IDENT", metavar="IDENT", default="amqpirc", help="The bots IRC ident")
parser.add_option("-c", "--ircchannel", dest="IRCCHANNEL", metavar="IRCCHANNEL", default="#amqpirc", help="The IRC channel the bot should join")
parser.add_option("-s", "--spoolpath", dest="path", metavar="path", default="/var/spool/amqpirc/", help="The path of the spool folder")
options, args = parser.parse_args()

### initialize variables
readbuffer=""
joined=False

### IRC connect
s=socket.socket( )
s.settimeout(1)
print " [%s] Connecting to IRC server %s port %s ..." % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),options.HOST,options.PORT)
s.connect((options.HOST, int(options.PORT)))
s.send("NICK %s\r\n" % options.NICK)
s.send("USER %s %s bla :%s\r\n" % (options.IDENT, options.HOST, options.REALNAME))
print " [%s] Joining channel %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),options.IRCCHANNEL)
s.send("JOIN %s\r\n" % options.IRCCHANNEL)

while 1:
    if(joined):
        dirList=os.listdir(options.path)
        for fname in dirList:
            f = open(os.path.join(options.path, fname), "r")
            linenumber=0
            for line in f:
                linenumber += 1
                if(linenumber==1):
                    s.send("PRIVMSG %s :Routingkey: %s\r\n" % (options.IRCCHANNEL,line))
                else:
                    s.send("PRIVMSG %s :%s\r\n" % (options.IRCCHANNEL,line))
            f.close
            os.remove(os.path.join(options.path, fname))
            print " [%s] AMQP message sent to IRC and deleted from spool file %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),os.path.join(options.path, fname))

    try:
        readbuffer=readbuffer+s.recv(1024)
        temp=string.split(readbuffer, "\n")
        readbuffer=temp.pop( )
        for line in temp:
            line=string.rstrip(line)
            line=string.split(line)

            if(line[0]=="PING"):
                s.send("PONG %s\r\n" % line[1])

            if(line[1]=="353"):
                joined=True
                print " [%s] Joined channel, waiting for messages ..." % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    except (KeyboardInterrupt, SystemExit):
        raise

    except:
        continue
