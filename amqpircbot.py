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
import getpass
import pika
import json
import ssl
import tempfile
import logging
logging.basicConfig()
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
parser.add_option("-C", "--config", dest="config", metavar="config", default="./amqpircbot_config", help="The path of the config file (default: './amqpircbot_config')")

### AMQP specific options
parser.add_option("-a", "--amqphost", dest="amqpserver", metavar="amqpserver", default="localhost", help="The AMQP/RabbitMQ server hostname or IP (default: 'localhost')")
parser.add_option("-u", "--amqpuser", dest="user", metavar="user", help="The AMQP username")
parser.add_option("-p", "--amqppass", dest="password", metavar="password", help="The AMQP password (omit for password prompt). Set to 'nopass' if user/pass should not be used")
parser.add_option("-e", "--amqpexchange", dest="exchange", metavar="exchange", default="myexchange", help="The AMQP exchange name (default 'myexchange')")
parser.add_option("-A", "--allow", dest="allow", metavar="allow", default="#", help="The AMQP routingkeys to allow to be sent to IRC, in a comma seperated list. (default: '#')")
parser.add_option("-I", "--ignore", dest="ignore", metavar="ignore", default=None, help="Ignore messages where the routingkey begins with one of the keys in this comma seperated list (default: None)")

parser.add_option("-r", "--routingkey", dest="routingkey", metavar="routingkey", default="#", help="The AMQP routingkey that the bot will receive messages from. (default: '#')")

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
scriptdir=os.path.dirname(os.path.realpath(__file__))
ircq = deque()

### Extract routing keys from options input
filter_rules_allow = string.split(options.allow,",")
if options.ignore:
    filter_rules_deny = string.split(options.ignore,",")
else:
    filter_rules_deny = list() 

### Create rule tables for routing_key_filter()
for n in range(len(filter_rules_deny)):
    filter_rules_deny[n] = string.split(filter_rules_deny[n],".")
for n in range(len(filter_rules_allow)):
    filter_rules_allow[n] = string.split(filter_rules_allow[n],".")

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Functions that extracts user-information from config file
idx = options.config.rfind('/')
if idx > -1:
    fname = options.config[idx+1:]
    path  = options.config[:idx]
else:
    fname = options.config
    path  = "./"

def config_parser(fname,path):
    cfg_f    = open(os.path.join(path, fname), "r")
    jsonblob = json.load(cfg_f)
    userlist = jsonblob['users']
    return userlist        

def auth_user(sendernick,hostname):
    authed = False
    for user in userlist:
        if user['host'] == hostname and user['nick'] == sendernick:
            return True

    ircclient.ircprivmsg("%s: Sorry, could not find you in the user list." % sendernick)
    return False

### Function to determine whether a routing-key match the deny/allow filtering rules:
### First it determines if the message is in the allow-list, if it is, it checks whether it is in the deny list
### Returns True if the message is relevant and False if it should be discarded 
def routing_key_filter(routing_key):
    # Checks each subkey to see if it matches the rule. If the entire rule matches (the relevant part of) the routing key the rule is validated 
    # otherwise it is not
    def validate_rules(filter_rules):
        if len(filter_rules) > 0:
            rule_validated = False
            for rule in filter_rules: 
                min_len = min(len(rule),len(subkeys))
                for n in range(min_len):
                    ### Check if sub-key match or wildcard is used
                    if rule[n] == "#":
                        rule_validated = True
                        break
                    elif not rule[n] == subkeys[n]:
                        break

                    ### Check if we're done checking (and there is an exact match)
                    if n + 1 == len(rule) and n + 1 == len(subkeys):
                        rule_validated = True
                        break

                ### If the rule validated the message, stop looking thorugh filter_rules_allow
                if rule_validated:
                    break
            return rule_validated
        else:
            return False

    ### split message routing key into sub-keys 
    subkeys = string.split(routing_key,".")

    ### If the the routingkey is in filter_rules_allow see if it is in the ignore list. If so, return false otherwise return true
    if not validate_rules(filter_rules_allow):
        return False
    else:
        #first check if there are any rules in the deny table
        if len(filter_rules_deny) == 0: 
            return True 
        #if there is, check them to see if there is a match or not
        elif validate_rules(filter_rules_deny):
            return False
        else:
            return True

### Find proper rule table, return False otherwise
def find_table_type(ruletype):
    ### determine which of the rules to delete entry from
    if ruletype=="allow":
        global filter_rules_allow
        rules = filter_rules_allow
    elif ruletype=="deny":
        global filter_rules_deny
        rules = filter_rules_deny
    else:
        consoleoutput("Error! Rule table type %s does not exist" % ruletype)
        return False
    return rules

### List rules on irc. Returns True if success, False if failing
def list_rules(ruletype):
    rules = find_table_type(ruletype)
    if not rules:
        return False

    ircclient.ircprivmsg("Listing rules from %s-table:" % ruletype)
    if len(rules) == 0:
        ircclient.ircprivmsg("No rules in table.")
    else:
        for n in range(len(rules)):
            rulestr = ""
            for subkey in rules[n]:
                rulestr = rulestr + "." + subkey
            ircclient.ircprivmsg("Rule %s: %s" % (n,rulestr[1:]))
    return True

### Delete rule from one of the rule tables. Return True on success, False othwise
def del_rule(ruletype,rule_no):
    rules = find_table_type(ruletype)
    if not rules:
        return False
    
    if ruletype == "allow" and rule_no == "0" and len(rules) == 1:
        ircclient.ircprivmsg("Can't remove the last rule in the allow table. Use '#' wildcard in deny table for complete blocking")
        return False

    ### Delete rule if there is a match, otherwise return false
    try:
        if ruletype == "deny" and rule_no == "0" and len(rules) == 1:
            rules[int(rule_no)] = ""
        else:
            rules.remove(rules[int(rule_no)])
        return True
    except:
        consoleoutput("Error! Unable to delete rule no. %s" % str(rule_no))
        return False

### Append rule to specified rule list, other return false
def append_rule(ruletype,rule):
    rules = find_table_type(ruletype)
    if not rules:
        return False

    ### append rule
    rule = string.split(rule,".")
    rules.append(rule)
    return True

### Define exception to use for socket read errors
class ReadError(Exception):
    pass

###############################################################################

### IRC-object: Connects to irc and reads IRC-feed from socket
class IRCClient:
    ### Connect to IRC
    def __init__(self,irchost,ircport,ircssl):
        self.sendernick = ""
        self.readbuffer = ""
        self.irclinelist = list()
        self.joined = False
        self.nickcount=0
        self.commandict = {'listrules'      : self.listrules,
                           'amqpsend'       : self.amqpsend,
                           'ping'           : self.ping, 
                           'addrule'        : self.addrule,
                           'delrule'        : self.delrule,
                           'amqpclose'      : self.amqpclose,
                           'amqppurgeopen'  : self.amqppurgeopen,
                           'amqpdisconnect' : self.amqpdisconnect,
                           'amqpopen'       : self.amqpopen,
                           'amqpchangekey'  : self.amqpchangekey,
                           'amqpstatus'     : self.amqpstatus}

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
                self.s = ssl.wrap_socket(self.s)
            except:
                consoleoutput("Unable to enable SSL for this connection, error: %s" % sys.exc_info()[0])
                sys.exit(1)
        else:
            consoleoutput("Not enabling SSL for this IRC connection...")

        ### NICK and USER
        self.setnick()
        self.ircsend("USER %s %s bla :%s" % (options.ident,options.irchost,options.realname))

        ### JOIN irc channel This can probably be removed
        self.joinchannel()

    ############## Command functions for IRC #################
    ### List selected rules
    def listrules(self,line):
        if len(line) < 6:
            self.ircprivmsg("What ruletype do you want me to list?")
        else:
            if not list_rules(line[5]):
                self.ircprivmsg("Could not list rules, sure you gave a valid table type?")

    def amqpsend(self,line):
        ### send message from IRC to AMQP
        routingkey=line[5]
        amqpbody    = ' '.join(line[6:])
        amqphandler.amqpsend(amqpbody,routingkey) 

    def ping(self,line):
        ### send PONG to IRC
        self.ircprivmsg("%s: pong" % self.sendernick)

    def addrule(self,line):
        if not append_rule(line[5],line[6]):
            self.ircprivmsg("Could not add rule, sure you gave a valid table type?")
        else:
            self.ircprivmsg("Rule succesfully added!")

    def delrule(self,line):
        if not del_rule(line[5],line[6]):
            self.ircprivmsg("Could not list rule, sure you gave a valid table type and rule number?")
        else:
            self.ircprivmsg("Rule succesfully deleted!")

    def amqpclose(self,line):
        self.ircprivmsg("Closing AMQP receiver channel.")
        amqphandler.conns[1]['channel'].close()
        time.sleep(1)

    def amqpdisconnect(self,line):
        self.ircprivmsg("Closing AMQP receiver connection.")
        amqphandler.conns[1]['connection'].close()
        time.sleep(1)

    def amqpopen(self,line):
        amqphandler.conns[1]['channel'].open()
        self.ircprivmsg("Receiving AMQP connection is now open.")

    def amqpstatus(self,line):
        if amqphandler.conns[1]['channel'].is_closed:
            self.ircprivmsg("AMQP receiver is closed.")
        elif amqphandler.conns[1]['channel'].is_closing:
            self.ircprivmsg("The AMQP receiver is closing")
        else:
            self.ircprivmsg("AMQP receiver is open.")
    
    def amqppurgeopen(self,line):
        amqphandler.conns[1]['channel'].open()
        amqphandler.conns[1]['channel'].queue_purge(queue=amqphandler.conns[1]['queue_name'])#,nowait=True
        self.ircprivmsg("Channel opened and queue purged.")

    def amqpchangekey(self,line):
        amqphandler.changeroutingkey(1,line[5])
        self.ircprivmsg("Routingkey changed. ")

    ########### Misc commands for IRChandling ###################
    ### Read from the socket and prepare data for parsing 
    def readirc(self):
        buf = self.s.recv(1024)
        if not buf:
            raise ReadError("Socket disconnected ?")
        self.readbuffer  = self.readbuffer+buf
        self.irclinelist = string.split(self.readbuffer, "\n")
        self.readbuffer  = self.irclinelist.pop()

        ### Loop through the lines received from the IRC server and make list of sentences with lists of  words
        for n in range(len(self.irclinelist)):
            if(options.debug):
                consoleoutput("<IRC: %s" % self.irclinelist[n])
            self.irclinelist[n] = string.split(string.rstrip(self.irclinelist[n]))
        self.irclinelist

    ### Function to send PRIVMSG message to IRC
    def ircprivmsg(self,message,target=options.ircchannel):
        self.ircsend("PRIVMSG %s :%s" % (target,message))

    ### Function to send message on the IRC socket (adds \r\n to the message)
    def ircsend(self,message):
        if(options.debug):
            consoleoutput(">IRC: %s" % message)
        if(message[-2:]=='\r\n'):
            ircq.append("%s" % message)
        else:
            ircq.append("%s\r\n" % message)

    def queuesend(self):
        if(len(ircq)>0):
            try:
                ircclient.s.send(ircq.popleft())
            except Exception as e:
                consoleoutput("Socket exception sending to IRC, type: %s exception message: %s" % (str(type(e)),e.strerror))
                sys.exit(1)

    def joinchannel(self,channel=options.ircchannel):
        consoleoutput("Joining channel %s" % options.ircchannel)
        self.ircsend("JOIN %s" % channel)

    def setnick(self,nick=options.nick):
        consoleoutput("Setting IRC nickname %s" % nick)
        self.ircsend("NICK %s" % nick)

    def sanitycheck(self):
        for line in self.irclinelist:
            ### Handle PING
            if(line[0]=="PING"):
                self.ircsend("PONG %s" % line[1])
                continue

            ### Handle raw 433 (raw 433 is sent when the chosen nickname is in use)
            if(line[1]=="433"):
                consoleoutput("Nickname %s is in use, trying another..." % options.nick)
                self.setnick(nick="%s%s" % (options.nick,nickcount))
                self.nickcount += 1
                continue

            ### Handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                self.joined=True
                consoleoutput("Joined channel %s" % options.ircchannel)
                continue

            ### Handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==options.ircchannel and line[3]==options.nick):
                self.joined=False
                consoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                continue

            ### Handle raw 474 (raw 474 is sent when the bot tries to join the channel and is banned)
            if(line[1]=="474"):
                ### try joining again until successful, sleep 1 sec first to avoid flooding the server
                time.sleep(1)
                consoleoutput("Banned from channel %s - attempting rejoin..." % options.ircchannel)
                continue
        return self.joined

    ### Handle commands for the bot
    def handlecmds(self):
        for line in self.irclinelist: 
            if(line[1]=="PRIVMSG" and line[2]==options.ircchannel and line[3]==":%s:" % options.nick):
                fullcommand=" ".join(line[4:])
                self.sendernick=line[0][1:].partition("!")[0]
                consoleoutput("IRC command from %s received: %s" % (self.sendernick,fullcommand))
                hostname = line[0].partition("@")[2]
                consoleoutput(hostname)
                if auth_user(self.sendernick,hostname):
                    if line[4] in self.commandict:
                        self.commandict[line[4]](line)
                    else:
                        self.ircprivmsg("%s: unrecognized command: %s" % (self.sendernick,line[4]))

    ######### Misc commands for AMQPhandling ###################
    def ircsend_receivedmsg(self):
        amqphandler.check_incoming()
        if amqphandler.msg_queue:
            while len(amqphandler.msg_queue)>0:
                msg = amqphandler.msg_queue.pop(0)
                if routing_key_filter(msg[0]):
                    if options.debug:
                        self.ircprivmsg("Routing key allowed")
                    self.ircprivmsg("Routingkey: %s (%s messages in bot queue)" % (msg[0],len(amqphandler.msg_queue)))
                    self.ircprivmsg("%s" % msg[1])
                elif(options.debug):
                    self.ircprivmsg("Routing key denied")

### AMQP-receiving class 
class AMQPhandler:
    def create_connection(self,n):
        try:
            ### Connect to ampq and open channel
            if (self.password == 'nopass'):
                self.conns[n]['connection'] = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost))
            else:
                self.conns[n]['connection'] = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost,credentials=pika.PlainCredentials(self.user, self.password)))
        except:
            consoleoutput("Unable to connect to AMQP, error: %s" % sys.exc_info()[0])
            sys.exit(1)

    def create_channel(self,n):
        try:
            self.conns[n]['channel'] = self.conns[n]['connection'].channel()
        except:
            consoleoutput("Unable to open channel, error: %s" % sys.exc_info()[0])
            sys.exit(1)

    def declare_exchange(self,n):
        ### Declare exchange
        self.conns[n]['channel'].exchange_declare(exchange=self.exch,type='topic')#, durable=True, auto_delete=False)#passive=True

    def declare_queueANDbind(self,n):
        ### Declare queue and get unique queuename
        self.conns[n]['result']     = self.conns[n]['channel'].queue_declare(exclusive=True)
        self.conns[n]['queue_name'] = self.conns[n]['result'].method.queue
        self.conns[n]['channel'].queue_bind(exchange=self.exch,queue=self.conns[n]['queue_name'],routing_key=self.routingkey)
                       
    def changeroutingkey(self,n,rkey):
        self.conns[n]['channel'].queue_unbind(exchange=options.exchange,routing_key=self.routingkey,queue=self.conns[n]['queue_name'])
        self.conns[n]['channel'].queue_bind(exchange=self.exch,queue=self.conns[n]['queue_name'],routing_key=rkey)
        self.routingkey = rkey

    def amqpsend(self,amqpbody,routingkey):
        self.conns[0]['channel'].basic_publish(exchange=options.exchange,routing_key=self.routingkey,body=amqpbody,properties=self.properties)

    def __init__(self,amqphost,user,password,exch,routingkey):
        self.amqphost      = amqphost
        self.user          = user
        self.password      = password
        self.exch          = exch
        self.routingkey    = routingkey
        self.conns         = [dict(),dict()]
        self.properties    = pika.BasicProperties(delivery_mode=2)
        ### List of messages that havne't been printed to IRC
        self.msg_queue     = list()

        ### create sending connection w. channel and exchange
        self.create_connection(0)
        self.create_channel(0)
        self.declare_exchange(0)

        ### create receiving connection w. channel, exchange and queue
        self.create_connection(1)
        self.create_channel(1)
        self.declare_exchange(1)
        self.declare_queueANDbind(1)


    def check_incoming(self):
        if self.conns[1]['channel'].is_open:
            print "Checking for new messages...."
            while True:
                method, header, body = self.conns[1]['channel'].basic_get(queue=self.conns[1]['queue_name'],no_ack=True)
                if header:
                    self.msg_queue.append([method.routing_key,body])
                else:
                    break

###############################################################################

### Fetch userlist from config
userlist    = config_parser(fname,path)

### Spawn AMQP object
amqphandler = AMQPhandler(options.amqpserver,options.user,options.password,options.exchange,options.routingkey) 

### Spawn IRC object
ircclient   = IRCClient(options.irchost,options.ircport,options.ircusessl)

while True:
    try:
        ### Handle commmands, if any
        ircclient.handlecmds()
        ### check if on IRC, haven't been kicked/banned, having nick etc. If so, pass messages from spool to irc channel
        if ircclient.sanitycheck():
            ### check if there are any messages in queue and if so, send them
            ircclient.ircsend_receivedmsg()
        #### otherwise try to join the channel
        else:
            ircclient.joinchannel()

        ### Try reading data from the IRC socket, timeout is 1 second, 
        ### If there is no data to read, an exception is raised and the loop continues
        ircclient.irclinelist = ""
        ircclient.readirc()

    ### Allow control-c to exit the script
    except (KeyboardInterrupt):
        ircclient.ircprivmsg("I'm afraid. I'm afraid, Dave. Dave, my mind is going. I can feel it.")
        ircclient.queuesend()
        consoleoutput("control-c received, exiting")
        sys.exit(0)
    
    ### socket read error exception (disconnected from IRC)
    except (ReadError):
        consoleoutput("socket disconnected/error, bailing out")
        sys.exit(1)

    ### Continue the loop after SSL socket timeout error (happens if we didn't receive any data before timeout)
    except ssl.SSLError as e:
        if(e.message=="The read operation timed out"):
            ### Send a line to IRC if any are waiting in the queue to be sent...
            ircclient.queuesend()
            continue
        else:
            ### raise any other exception
            raise

    ### Continue the loop after socket timeout error (happens if we didn't receive any data before timeout)
    except socket.timeout as e:
        ### Send a line to IRC if any are waiting in the queue to be sent...
        ircclient.queuesend()
        continue

    ### Catch sys.exit from earlier in the script
    except SystemExit:
        os._exit(0)

    ### Catch other exceptions
    except Exception as e:
        consoleoutput("uncaught exception type: %s exception message: %s" % (str(type(e)),e.message))
        sys.exit(1)
