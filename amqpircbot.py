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
import subprocess
import getpass
import pika
from optparse import OptionParser

### Define and handle command line options
use = "Usage: %prog [options]"
parser = OptionParser(usage = use)

### IRC specific options
parser.add_option("-H", "--irchost", dest="irchost", metavar="irchost", default="irc.efnet.org", help="The IRC server hostname or IP (default: 'irc.efnet.org')")
parser.add_option("-P", "--ircport", dest="ircport", metavar="ircport", default=6667, help="The IRC server port (default: 6667)")
parser.add_option("-n", "--ircnick", dest="nick", metavar="nick", default="amqpirc", help="The bots IRC nickname (default: 'amqpirc')")
parser.add_option("-R", "--ircname", dest="realname", metavar="realname", default="amqpirc bot", help="The bots IRC realname (default: 'amqpirc')")
parser.add_option("-i", "--ircident", dest="ident", metavar="ident", default="amqpirc", help="The bots IRC ident (default: 'amqpirc')")
parser.add_option("-c", "--ircchannel", dest="ircchannel", metavar="ircchannel", default="#amqpirc", help="The IRC channel the bot should join (default: '#amqpirc')")
parser.add_option("-S", "--ssl", action="store_true", dest="ircusessl", default=False, help="Set to enable SSL connection to IRC")

### AMQP specific options
parser.add_option("-a", "--amqphost", dest="amqpserver", metavar="amqpserver", default="localhost", help="The AMQP/RabbitMQ server hostname or IP (default: 'localhost')")
parser.add_option("-u", "--amqpuser", dest="user", metavar="user", help="The AMQP username")
parser.add_option("-p", "--amqppass", dest="password", metavar="password", help="The AMQP password (omit for password prompt)")
parser.add_option("-e", "--amqpexchange", dest="exchange", metavar="exchange", default="myexchange", help="The AMQP exchange name (default 'myexchange')")
parser.add_option("-r", "--routingkey", dest="routingkey", metavar="routingkey", default="#", help="The AMQP routingkey to listen for (default '#')")
parser.add_option("-s", "--amqpspoolpath", dest="amqpspoolpath", metavar="amqpspoolpath", default="/var/spool/amqpirc/", help="The path of the spool folder (default: '/var/spool/amqpirc/')")

### get options
options, args = parser.parse_args()

### Check if password has been supplied on the command-line, prompt for one otherwise
if not (options.password):
    options.password=getpass.getpass("Enter AMQP password: ")

### Initialize variables
readbuffer=""
joined=False
spoolproc=None
spoolcommand = "/usr/home/tykling/amqpircspool.py -a %s -u %s -p %s -e %s" % (options.amqpserver,options.user,options.password,options.exchange)
spoolcommandlist = spoolcommand.split()

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Check access to spool path options.amqpspoolpath
if not os.access(options.amqpspoolpath, os.R_OK) or not os.access(options.amqpspoolpath, os.W_OK):
    consoleoutput("AMQP spool path %s is not readable or writable, bailing out" % options.amqpspoolpath)
    sys.exit(1)

### Check if options.ircchannel is prefixed with #, add it if not
if not (options.ircchannel[:1]=="#"):
    options.ircchannel="#%s" % options.ircchannel

### Function to send message to IRC
def ircoutput(message,target=options.ircchannel):
    s.send("PRIVMSG %s :%s\r\n" % (target,message))

### Connect to ampq and open channel
try:
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.amqpserver,credentials=pika.PlainCredentials(options.user, options.password)))
    channel = connection.channel()
except:
    consoleoutput("Unable to connect to AMQP and open channel, error: %s" % sys.exc_info()[0])
    sys.exit(1)

### Declare exchange
channel.exchange_declare(exchange=options.exchange,type='topic',passive=True, durable=True, auto_delete=False)

### IRC connect
s=socket.socket( )
s.settimeout(1)
consoleoutput("Connecting to IRC server %s port %s ..." % (options.irchost,options.ircport))
s.connect((options.irchost, int(options.ircport)))

### Enable SSL if requested
if(options.ircusessl):
    consoleoutput("Enabling SSL for this connection...")
    import ssl
    s = ssl.wrap_socket(s)
else:
    consoleoutput("Not enabling SSL for this connection...")

### NICK and USER
s.send("nick %s\r\n" % options.nick)
s.send("USER %s %s bla :%s\r\n" % (options.ident, options.irchost, options.realname))

### JOIN irc channel
consoleoutput("Joining channel %s" % options.ircchannel)
s.send("JOIN %s\r\n" % options.ircchannel)

while 1:
    ### Check if we already joined the channel
    if(joined):
        ### Find all message file in the spool folder options.amqpspoolpath
        dirList=os.listdir(options.amqpspoolpath)

        ### sort filelist
        if(len(dirList)<0):
            dirList=dirList.sort()

        ### Loop through found files in chronological order, first message first
        for fname in dirList:
            f = open(os.path.join(options.amqpspoolpath, fname), "r")
            linenumber=0
            ### Loop through lines of the found message
            for line in f:
                linenumber += 1
                ### First line is the routingkey
                if(linenumber==1):
                    ircoutput("Routingkey: %s" % line)
                else:
                    ircoutput(line)
            f.close
            ### Delete the spool file
            os.remove(os.path.join(options.amqpspoolpath, fname))
            consoleoutput("AMQP message sent to IRC and deleted from spool file %s" % os.path.join(options.amqpspoolpath, fname))

        ### Check if AMQP process is running
        if(spoolproc==None or spoolproc.poll()!=None):
            ### Start AMQP spool process
            consoleoutput("Launching AMQP spool process...")
            ircoutput("Launching AMQP spool process...")
            consoleoutput(spoolcommand)
            try:
                spoolproc = subprocess.Popen(spoolcommandlist)
                consoleoutput("Successfully launched AMQP spool process...")
            except:
                consoleoutput("Unable to start AMQP spooler :(")

    else:
        ### Try joining the Channel
        s.send("JOIN %s\r\n" % options.ircchannel)

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
                consoleoutput("Joined channel %s" % options.ircchannel)
                continue

            ### Handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==options.ircchannel and line[3]==options.nick):
                joined=False
                consoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                continue

            ### Handle raw 474 (raw 474 is sent when the bot tries to join the channel and is banned)
            if(line[1]=="474"):
                ### try joining again until successful, sleep 1 sec first to avoid flooding the server
                time.sleep(1)
                consoleoutput("Banned from channel %s - attempting rejoin..." % options.ircchannel)
                continue
 
            ### Handle commands for the bot
            if(line[1]=="PRIVMSG" and line[2]==options.ircchannel and line[3]==":%s:" % options.nick):
                fullcommand=" ".join(line[4:])
                sendernick=line[0][1:].partition("!")[0]
                consoleoutput("IRC command from %s received: %s" % (sendernick,fullcommand))
                if(line[4]=="amqpsend"):
                    ### send message from IRC to AMQP
                    routingkey=line[5]
                    amqpbody=' '.join(line[6:])
                    properties=pika.BasicProperties(delivery_mode=2)
                    channel.basic_publish(exchange=options.exchange,routing_key=routingkey,body=amqpbody,properties=properties)
                elif(line[4]=="ping"):
                    ### send PONG to IRC
                    ircoutput("%s: pong" % sendernick)
                else:
                    ircoutput("%s: unrecognized command: %s" % (sendernick,line[4]))
                    
    ### Allow exceptions to exit the script
    except (KeyboardInterrupt, SystemExit):
        raise                                      

    ### Continue the loop after a socket timeout and other exceptions
    except:
        continue