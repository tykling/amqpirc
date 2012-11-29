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
import multiprocessing
import getpass
import pika
import ssl
import tempfile
from collections import deque
from optparse import OptionParser
### Define and handle command line options
use = "Usage: %prog [options]"
parser = OptionParser(usage = use)

### Debug option
parser.add_option("-d", "--debug", action="store_true", dest="debug", default=False, help="Set to enable debugging, output received IRC messages to console...")

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
parser.add_option("-p", "--amqppass", dest="password", metavar="password", help="The AMQP password (omit for password prompt). Set to 'nopass' if user/pass should not be used")
parser.add_option("-e", "--amqpexchange", dest="exchange", metavar="exchange", default="myexchange", help="The AMQP exchange name (default 'myexchange')")
parser.add_option("-r", "--routingkey", dest="routingkey", metavar="routingkey", default="#", help="The AMQP routingkey to listen for (default '#')")
parser.add_option("-s", "--amqpspoolpath", dest="amqpspoolpath", metavar="amqpspoolpath", default="/var/spool/amqpirc/", help="The path of the spool folder (default: '/var/spool/amqpirc/')")

### get options
options, args = parser.parse_args()

### Check if password has been supplied on the command-line, prompt for one otherwise
if not (options.password):
    options.password=getpass.getpass("Enter AMQP password: ")

### Check if options.ircchannel is prefixed with #, add it if not
if not (options.ircchannel[:1]=="#"):
    options.ircchannel="#%s" % options.ircchannel

###############################################################################

### Initialize variables
joined=False
scriptdir=os.path.dirname(os.path.realpath(__file__))
ircq = deque()
joinsent=False
nickcount=0

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Function to send PRIVMSG message to IRC
def ircprivmsg(message,target=options.ircchannel):
    ircsend("PRIVMSG %s :%s" % (target,message))

### Function to send message on the IRC socket (adds \r\n to the message)
def ircsend(message):
    if(options.debug):
        consoleoutput(">IRC: %s" % message)
    if(message[-2:]=='\r\n'):
        ircq.append("%s" % message)
    else:
        ircq.append("%s\r\n" % message)

def queuesend():
    if(len(ircq)>0):
        try:
            ircinst.s.send(ircq.popleft())
        except Exception as e:
            consoleoutput("Socket exception sending to IRC, type: %s exception message: %s" % (str(type(e)),e.strerror))
            sys.exit(1)

def joinchannel(channel=options.ircchannel):
    if not joinsent:
        consoleoutput("Joining channel %s" % options.ircchannel)
        global joinsent
        ircsend("JOIN %s" % channel)
        joinsent=True

def setnick(nick=options.nick):
    consoleoutput("Setting IRC nickname %s" % nick)
    ircsend("NICK %s" % nick)

### Define exception to use for socket read errors
class ReadError(Exception):
    pass

### Check access to spool path options.amqpspoolpath
if not os.access(options.amqpspoolpath, os.R_OK) or not os.access(options.amqpspoolpath, os.W_OK):
    consoleoutput("AMQP spool path %s is not readable or writable, bailing out" % options.amqpspoolpath)
    sys.exit(1)

###############################################################################

### Connect to ampq
if not (options.password == 'nopass'):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.amqpserver,credentials=pika.PlainCredentials(options.user, options.password)))
    except:
        consoleoutput("Unable to connect to AMQP, error: %s" % sys.exc_info()[0])
        sys.exit(1)
else:
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.amqpserver))
    except:
        consoleoutput("Unable to connect to AMQP, error: %s" % sys.exc_info()[0])
        sys.exit(1)

### Open AMQP channel
try:
    channel = connection.channel()
except:
    consoleoutput("Unable to open AMQP channel, error: %s" % sys.exc_info()[0])
    sys.exit(1)

### Declare exchange
try:
    channel.exchange_declare(exchange=options.exchange,type='topic',passive=True, durable=True, auto_delete=False)
except:
    consoleoutput("Unable to declare AMQP exchange, error: %s" % sys.exc_info()[0])
    sys.exit(1)

### IRC-object: Connects to irc and reads IRC-feed from socket
class IRCClient:
    ### Connect to IRC
    def __init__(self,irchost,ircport,ircssl):
        self.readbuffer = ""#DET HER SKAL NOK LAVES OM. MAA FAA MRE STYR PAA KLASSER
        try:
            self.s=socket.socket( )
            self.s.settimeout(1)
            consoleoutput("Connecting to IRC server %s port %s ..." % (options.irchost,options.ircport))
            self.s.connect((irchost, int(ircport)))
        except:
            consoleoutput("Unable to connect to IRC, error: %s" % sys.exc_info()[0])
            sys.exit(1)

        ### Enable SSL if requested
        if(ircssl):
            consoleoutput("Enabling SSL for this IRC connection...")
            try:
                self.s = ssl.wrap_socket(s)
            except:
                consoleoutput("Unable to enable SSL for this connection, error: %s" % sys.exc_info()[0])
                sys.exit(1)
        else:
            consoleoutput("Not enabling SSL for this IRC connection...")

        ### NICK and USER
        setnick()
        ircsend("USER %s %s bla :%s" % (options.ident,options.irchost,options.realname))

        ### JOIN irc channel
        joinchannel()

        ### Read from the socket and prepare data for parsing 
    def readirc(self):
        buf = self.s.recv(1024)
        if not buf:
            raise ReadError("Socket disconnected ?")
        self.readbuffer=self.readbuffer+buf
        linelist=string.split(self.readbuffer, "\n")
        self.readbuffer=linelist.pop( )
        return linelist


### AMQP-receiving object
class Spoold(multiprocessing.Process):
    def __init__(self,amqpspoolpath,amqphost,user,password,exch,rkey):
        multiprocessing.Process.__init__(self)
        self.amqpspoolpath = amqpspoolpath
        self.amqphost      = amqphost
        self.user          = user
        self.password      = password
        self.exch          = exch
        self.rkey          = rkey

    def run(self):
        ### Check access to spool path options.amqpspoolpath
        if not os.access(self.amqpspoolpath, os.R_OK) or not os.access(self.amqpspoolpath, os.W_OK):
            consoleoutput("Spool path %s is not readable or writable, bailing out" % amqpspoolpath)
            sys.exit(1)

        ### Connect to ampq and open channel
        if not (self.password == 'nopass'):
            try:
                self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost,credentials=pika.PlainCredentials(self.user, self.password)))
                self.channel = connection.channel()
            except:
                consoleoutput("Unable to connect to AMQP and open channel, error: %s" % sys.exc_info()[0])
                sys.exit(1)
        else:
            try:
                consoleoutput("POOLP %s HOST %s USER %s PASS %s EXCH %s" % (self.amqpspoolpath,self.amqphost,self.user,self.password,self.exch))
                self.connection = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost))
                self.channel = connection.channel()
            except:
                consoleoutput("Unable to connect to AMQP and open channel, error: %s" % sys.exc_info()[0])
                sys.exit(1)

        ### Declare exchange
        self.channel.exchange_declare(exchange=self.exch,type='topic',passive=True, durable=True, auto_delete=False)

        ### Declare queue and get unique queuename
        self.result = channel.queue_declare(exclusive=True)
        self.queue_name = self.result.method.queue

        ### Bind queue to exchange with the wildcard routing key #
        self.channel.queue_bind(exchange=self.exch,queue=self.queue_name,routing_key=self.rkey)
        consoleoutput("Waiting for messages matching routingkey %s. To exit press CTRL+C" % self.rkey)

        ### Register callback function process_message to be called when a message is received
        self.channel.basic_consume(self.process_message,queue=self.queue_name,no_ack=True)

        ### Loop waiting for messages
        self.channel.start_consuming()

    ### This function is called whenever a message is received
    def process_message(self,ch, method, properties, body):
        tid="%f-" % time.time()
        fd, filename = tempfile.mkstemp(dir=self.amqpspoolpath,prefix=tid)
        f = os.fdopen(fd, 'wt')
        f.write(method.routing_key+'\n')
        f.write(body)
        f.close
        consoleoutput("AMQP message received and written to spool file %s with routingkey %s:" % (filename,method.routing_key))
        print body
    
### Spawn AMQP-receiving process
spoolinst = Spoold(options.amqpspoolpath,options.amqpserver,options.user,options.password,options.exchange,options.routingkey) 
spoolinst.start()

### Connect to IRC
ircinst = IRCClient(options.irchost,options.ircport,options.ircusessl)

###############################################################################
while 1:
    joinchannel()
    ### Check if we already joined the channel
    if(joined):
        ### Find all message file in the spool folder options.amqpspoolpath
        dirList=os.listdir(options.amqpspoolpath)

        ### Loop through found files in chronological order, first message first
        for fname in sorted(dirList):
            f = open(os.path.join(options.amqpspoolpath, fname), "r")
            linenumber=0
            ### Loop through lines of the found message
            for line in f:
                linenumber += 1
                ### First line is the routingkey
                if(linenumber==1):
                    ircprivmsg("Routingkey: %s (%s messages in bot queue)" % (line,len(dirList)-1))
                else:
                    ircprivmsg(line)
            f.close
            ### Delete the spool file
            os.remove(os.path.join(options.amqpspoolpath, fname))
            consoleoutput("AMQP message sent to IRC queue and deleted from spool file %s" % os.path.join(options.amqpspoolpath, fname))
            break
    else:
        joinchannel()

    ### Try reading data from the IRC socket, timeout is 1 second, 
    ### check for disconnected socket and raise exception
    try:
        temp = ircinst.readirc()
                
        ### Loop through the lines received from the IRC server
        for line in temp:
            if(options.debug):
                consoleoutput("<IRC: %s" % line)
            line=string.split(string.rstrip(line))

            ### Handle PING
            if(line[0]=="PING"):
                ircsend("PONG %s" % line[1])
                continue

            ### Handle raw 433 (raw 433 is sent when the chosen nickname is in use)
            if(line[1]=="433"):
                consoleoutput("Nickname %s is in use, trying another..." % options.nick)
                setnick(nick="%s%s" % (options.nick,nickcount))
                nickcount += 1
                
                joinsent=False
                joinchannel()
                continue

            ### Handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                joined=True
                consoleoutput("Joined channel %s" % options.ircchannel)
                joinsent=False
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
                    ircprivmsg("%s: pong" % sendernick)
                else:
                    ircprivmsg("%s: unrecognized command: %s" % (sendernick,line[4]))

    ### Allow control-c to exit the script
    except (KeyboardInterrupt):
        consoleoutput("control-c received, exiting")
        spoolinst.terminate()
        sys.exit(0)
    
    ### socket read error exception (disconnected from IRC)
    except (ReadError):
        consoleoutput("socket disconnected/error, bailing out")
        sys.exit(1)

    ### Continue the loop after SSL socket timeout error (happens if we didn't receive any data before timeout)
    except ssl.SSLError as e:
        if(e.message=="The read operation timed out"):
            ### Send a line to IRC if any are waiting in the queue to be sent...
            queuesend()
            continue
        else:
            ### raise any other exception
            raise

    ### Continue the loop after socket timeout error (happens if we didn't receive any data before timeout)
    except socket.timeout as e:
        ### Send a line to IRC if any are waiting in the queue to be sent...
        queuesend()
        continue

    ### Catch sys.exit from earlier in the script
    except SystemExit:
        os._exit(0)

    ### Catch other exceptions
    except Exception as e:
        consoleoutput("uncaught exception type: %s exception message: %s" % (str(type(e)),e.message))
        sys.exit(1)
