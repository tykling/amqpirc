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

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### class for amqpmsg-formatting table types
class StrFormatRules:
    def __init__(self):
        self.rkeylist  = list()
        self.formatstr = ""

class AMQPBotConfig:
    def __init__(self,options):
        self.options    = options
        self.userlist   = list()

        ### Check if password has been supplied on the command-line, prompt for one otherwise
        if not (options.password):
            options.password=getpass.getpass("Enter AMQP password: ")
        ### Check if options.ircchannel is prefixed with #, add it if not
        if not (options.ircchannel[:1]=="#"):
            options.ircchannel="#%s" % options.ircchannel

        ### Extract and parse routing keys from options input
        self.filter_rules_allow    = string.split(options.allow,",")
        if options.ignore:
            self.filter_rules_deny = string.split(options.ignore,",")
        else:
            self.filter_rules_deny = list() 
        for n in range(len(self.filter_rules_deny)):
            self.filter_rules_deny[n] = string.split(self.filter_rules_deny[n],".")
        for n in range(len(self.filter_rules_allow)):
            self.filter_rules_allow[n] = string.split(self.filter_rules_allow[n],".")

        self.filtertables      =  { 'allow' : self.filter_rules_allow,
                                    'deny'  : self.filter_rules_deny }
        self.formattingtables  = dict()
        self.defaultformatting = "Routingkey: %s "
        ### Extract config name and path from commandline input and parse config from file
        idx = options.config.rfind('/')
        if idx > -1:
            fname = options.config[idx+1:]
            path  = options.config[:idx]
        else:
            fname = options.config
            path  = "./"
        self.config_parser(fname,path)

    ### config that parses json config file
    def config_parser(self,fname,path):
        cfg_f      = open(os.path.join(path, fname), "r")
        ### Adjoin the lines and remove: linebreaks, comments 
        cfgstr = ""
        for line in cfg_f:
            n = line.find("%")
            if n==1:
                continue
            elif n==-1:
                line.replace("\n","")
                cfgstr = cfgstr + line
            else:
                line = line[:n] +"\n"
                line.replace("\n","")
                cfgstr = cfgstr + line
        jsonblob   = json.loads(cfgstr)
        if 'users' in jsonblob:
            self.userlist.extend(jsonblob['users'])
            self.usersexists = True
        else:
            self.usersexists = False
                
        ## adjoins the tables->routingkeys to the appropriate tables (i.e. might have values of commandline arguments)
        if 'tables' in jsonblob:
            for tentry in jsonblob['tables']:
                key = tentry['name']
                if key == "default":
                    self.defaultformatting = tentry['header'].replace("<RKEY>","%s") 
                    continue
                if key not in self.formattingtables and key not in self.filtertables:
                    x = StrFormatRules()
                    self.formattingtables.update( {key : x } ) 
                rkeys = tentry['rkeys'].split(",")
                for n in range(len(rkeys)):
                    rkeys[n] = rkeys[n].split(".")

                if key in self.filtertables:
                    self.filtertables[key].extend(rkeys)
                else:
                    self.formattingtables[key].rkeylist.extend(rkeys)
                    self.formattingtables[key].formatstr = tentry['header'].replace("<RKEY>","%s")

    def auth_user(self,sendernick,hostname):
        if self.usersexists:
            authed = False
            for user in self.userlist:
                if user['host'] == hostname and user['nick'] == sendernick:
                    return True
            return False
        else:
            return True

    # Checks each subkey to see if it matches the rule. If the entire rule matches (the relevant part of) the routing key the rule is validated 
    # otherwise it is not
    def validate_rules(self,filter_rules,routing_key):
        if len(filter_rules) > 0:
            rule_validated = False
            for rule in filter_rules: 
                min_len = min(len(rule),len(routing_key))
                for n in range(min_len):
                    ### Check if sub-key match or wildcard is used
                    if rule[n] == "#":
                        rule_validated = True
                        break
                    elif not rule[n] == routing_key[n]:
                        break
                    ### Check if we're done checking (and there is an exact match)
                    if n + 1 == len(rule) and n + 1 == len(routing_key):
                        rule_validated = True
                        break

                ### If the rule validated the message, stop looking thorugh filter_rules_allow
                if rule_validated:
                    break
            return rule_validated
        else:
            return False

    ### Function to format the message, if it is found in some of the formatting-tables
    def string_formatting(self,routingkey):
        routingkeylisted = routingkey.split(".")
        for key in self.formattingtables:
            #this validates to false
            if self.validate_rules(self.formattingtables[key].rkeylist,routingkeylisted):
                return (self.formattingtables[key].formatstr % routingkey).decode('string-escape')
        return (self.defaultformatting % routingkey).decode('string-escape') 

    ### Function to determine whether a routing-key match the deny/allow filtering rules:
    ### First it determines if the message is in the allow-list, if it is, it checks whether it is in the deny list
    ### Returns True if the message is relevant and False if it should be discarded 
    def routing_key_filter(self,routing_key):
        ### If the the routingkey is in filter_rules_allow see if it is in the ignore list. If so, return false otherwise return true
        if not self.validate_rules(self.filter_rules_allow,routing_key):
            return False
        else:
            #first check if there are any rules in the deny table
            if len(self.filter_rules_deny) == 0: 
                return True 
            #if there is, check them to see if there is a match or not
            elif self.validate_rules(self.filter_rules_deny,routing_key):
                return False
            else:
                return True

    ### Find proper rule table, return False otherwise
    def find_table_type(self,ruletype):
        ### determine which of the rules to delete entry from
        if ruletype in self.filtertables:
            return self.filtertables[ruletype]
        elif ruletype in self.formattingtables:
            return self.formattingtables[ruletype].rkeylist
        else:
            consoleoutput("Error! Rule table type %s does not exist" % ruletype)
            return False

class AMQPChannel:
    def __init(self):
        self.result = None
        self.queue_name = None
        self.channel    = None

### AMQP-receiving class 
class AMQPhandler:
    def create_connection(self,n):
        try:
            ### Connect to ampq and open channel
            if (self.password == 'nopass'):
                self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost))
            else:
                self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost,credentials=pika.PlainCredentials(self.user, self.password)))
        except:
            consoleoutput("Unable to connect to AMQP, error: %s" % sys.exc_info()[0])
            sys.exit(1)

    def create_channel(self,n):
        try:
            self.chanlist.append(AMQPChannel())
            self.chanlist[-1].channel = self.conn.channel()
        except:
            consoleoutput("Unable to open channel, error: %s" % sys.exc_info()[0])
            sys.exit(1)

    def declare_exchange(self,n):
        ### Declare exchange
        self.chanlist[n].channel.exchange_declare(exchange=self.exchange,type='topic')#, durable=True, auto_delete=False)#passive=True

    def declare_queueANDbind(self,n):
        ### Declare queue and get unique queuename
        self.chanlist[n].result     = self.chanlist[n].channel.queue_declare(exclusive=True)
        self.chanlist[n].queue_name = self.chanlist[n].result.method.queue
        self.chanlist[n].channel.queue_bind(exchange=self.exchange,queue=self.chanlist[n].queue_name,routing_key=self.routingkey)
                       
    def changeroutingkey(self,n,rkey):
        self.chanlist[n].queue_unbind(exchange=self.exchange,routing_key=self.routingkey,queue=self.chanlist[n].queue_name)
        self.chanlist[n].queue_bind(exchange=self.exchange,queue=self.chanlist[n].queue_name,routing_key=rkey)
        self.routingkey = rkey

    def amqpsend(self,amqpbody,routingkey):
        self.conn[0].channel.basic_publish(exchange=self.exchange,routing_key=self.routingkey,body=amqpbody,properties=self.properties)

    def __init__(self,options):
        self.amqphost      = options.amqpserver
        self.user          = options.user
        self.password      = options.password
        self.exchange      = options.exchange
        self.routingkey    = options.routingkey
        self.conn          = None
        self.chanlist      = list();
        self.properties    = pika.BasicProperties(delivery_mode=2)
        ### List of messages that havne't been printed to IRC
        self.amqpq         = deque()

        ### create sending connection w. channel and exchange
        self.create_connection(0)
        self.create_channel(0)
        self.declare_exchange(0)

        ### create receiving connection w. channel, exchange and queue
        self.create_channel(1)
        self.declare_exchange(1)
        self.declare_queueANDbind(1)

    def check_incoming(self):
        if self.chanlist[1].channel.is_open:
            while True:
                method, header, body = self.chanlist[1].channel.basic_get(queue=self.chanlist[1].queue_name,no_ack=True)
                if header:
                    self.amqpq.append([method.routing_key,body])
                else:
                    break

### Define exception to use for socket read errors
class ReadError(Exception):
    pass

### IRC-object: Connects to irc and reads IRC-feed from socket
class IRCClient:
    ### Connect to IRC
    def __init__(self,options,cfg,amqphandler):
        self.amqphandler = amqphandler
        self.cfg         = cfg
        self.irchost     = options.irchost
        self.ircport     = options.ircport
        self.ircssl      = options.ircusessl
        self.ircchannel  = options.ircchannel
        self.botnick     = options.nick
        self.debug       = options.debug
        self.ircq        = deque()
        self.sendernick  = ""
        self.readbuffer  = ""
        self.irclinelist = list()
        self.joined      = False
        self.nickcount   = 0
        self.commandict  = {'listrules'     : self.listrules,
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
            consoleoutput("Connecting to IRC server %s port %s ..." % (self.irchost,self.ircport))
            self.s.connect((self.irchost, int(self.ircport)))
        except:
            consoleoutput("Unable to connect to IRC, error: %s" % sys.exc_info()[0])
            sys.exit(1)

        ### Enable SSL if requested
        if(self.ircssl):
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
        while True:
            try:
                ### Handle commmands, if any
                self.handlecmds()
                ### check if on IRC, haven't been kicked/banned, having nick etc. If so, pass messages from spool to irc channel
                if self.sanitycheck():
                    ### check if there are any messages in queue and if so, send them
                    self.ircsend_receivedmsg()
                #### otherwise try to join the channel
                else:
                    self.joinchannel()

                ### Try reading data from the IRC socket, timeout is 1 second, 
                ### If there is no data to read, an exception is raised and the loop continues
                self.irclinelist = ""
                self.readirc()

            ### Allow control-c to exit the script
            except (KeyboardInterrupt):
                self.ircprivmsg("I'm afraid. I'm afraid, Dave. Dave, my mind is going. I can feel it.")
                self.queuesend()
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
                    self.queuesend()
                    continue
                else:
                    ### raise any other exception
                    raise

            ### Continue the loop after socket timeout error (happens if we didn't receive any data before timeout)
            except socket.timeout as e:
                ### Send a line to IRC if any are waiting in the queue to be sent...
                self.queuesend()
                continue

            ### Catch sys.exit from earlier in the script
            except SystemExit:
                os._exit(0)

    ############## Command functions for IRC #################
    ### List selected rules
    def ping(self,line,target):
        ### send PONG to IRC
        self.ircprivmsg("%s: pong" % self.sendernick,target)

    ###### Table management functions
    ### List rules on irc. Returns True if success, False if failing
    def listrules(self,line,target):
        if len(line) < 6:
            self.ircprivmsg("What ruletype do you want me to list?",target)
        else:
            ruletype = line[5]
            rules    = self.cfg.find_table_type(ruletype)
            if not rules:
                self.ircprivmsg("Could not list rules, sure you gave a valid table type?",target)
                return

            self.ircprivmsg("Listing rules from %s-table:" % ruletype,target)
            if len(rules) == 0:
                self.ircprivmsg("No rules in table.",target)
            else:
                for n in range(len(rules)):
                    rulestr = ""
                    for subkey in rules[n]:
                        rulestr = rulestr + "." + subkey
                    self.ircprivmsg("Rule %s: %s" % (n,rulestr[1:]),target)

    ### Append rule to specified rule list, other return false
    def addrule(self,line,target):
        ruletype = line[5]
        rule     = line[6]
        rules    = self.cfg.find_table_type(ruletype)
        if not rules:
            self.ircprivmsg("Could not add rule, sure you gave a valid table type?",target)
            return
        ### append rule
        rule = string.split(rule,".")
        rules.append(rule)
        self.ircprivmsg("Rule succesfully added!",target)


    ### Delete rule from one of the rule tables. Return True on success, False othwise
    def delrule(self,line,target):
        ruletype = line[6]
        rule_no  = line[5]
        success  = None

        rules = self.cfg.find_table_type(ruletype)
        if not rules:
            success = False
        
        if ruletype == "allow" and rule_no == "0" and len(rules) == 1:
            self.ircprivmsg("Can't remove the last rule in the allow table. Use '#' wildcard in deny table for complete blocking")
            success = False

        ### Delete rule if there is a match, otherwise return false
        try:
            if ruletype == "deny" and rule_no == "0" and len(rules) == 1:
                rules[int(rule_no)] = ""
            else:
                rules.remove(rules[int(rule_no)])
            success = True
        except:
            consoleoutput("Error! Unable to delete rule no. %s" % str(rule_no))
            success = False

        if not success:
            self.ircprivmsg("Rule succesfully deleted!",target)
        else:
            self.ircprivmsg("Could not list rule, sure you gave a valid table type and rule number?",target)

    ####### AMQP management functions ########
    def amqpsend(self,line,target):
        ### send message from IRC to AMQP
        routingkey=line[5]
        amqpbody    = ' '.join(line[6:])
        self.amqphandler.amqpsend(amqpbody,routingkey) 

    def amqpclose(self,line,target):
        self.ircprivmsg("Closing AMQP receiver channel.",target)
        self.amqphandler.chanlist[1].channel.close()
        time.sleep(1)

    def amqpdisconnect(self,line,target):
        self.ircprivmsg("Closing AMQP connection.",target)
        self.amqphandler.conn.close()
        time.sleep(1)

    def amqpopen(self,line,target):
        self.amqphandler.chanlist[1].channel.open()
        self.ircprivmsg("Receiving AMQP channel is now open.",target)

    def amqpstatus(self,line,target):
        if self.amqphandler.chanlist[1].channel.is_closed:
            self.ircprivmsg("AMQP receiver is closed.",target)
        elif self.amqphandler.chanlist[1].channel.is_closing:
            self.ircprivmsg("The AMQP receiver is closing",target)
        else:
            self.ircprivmsg("AMQP receiver is open.",target)
    
    def amqppurgeopen(self,line,target):
        if self.amqphandler.chanlist[1].channel.is_closed or self.amqphandler.chanlist[1].channel.is_closing:
            self.amqphandler.chanlist[1].channel.open()
            self.amqphandler.chanlist[1].channel.queue_purge(queue=self.amqphandler.chanlist[1].queue_name)#,nowait=True
            self.ircprivmsg("Channel opened and queue purged.",target)
        else:
            self.ircprivmsg("Channel must be closed before you can open (and purge).",target)

    def amqpchangekey(self,line,target):
        self.amqphandler.changeroutingkey(1,line[5])
        self.ircprivmsg("Routingkey changed. ",target)

    ### sends received AMQP messages
    def ircsend_receivedmsg(self):
        self.amqphandler.check_incoming()
        if self.amqphandler.amqpq:
            while len(self.amqphandler.amqpq)>0:
                msg = self.amqphandler.amqpq.popleft()
                if self.cfg.routing_key_filter(msg[0]):
                    # format routingkey irc line
                    msg_status = " (%s messages in bot queue)" % len(self.amqphandler.amqpq)
                    msg[0]     = self.cfg.string_formatting(msg[0]) + msg_status
                    if self.debug:
                        self.ircprivmsg("Routing key allowed")
                    self.ircprivmsg(msg[0])
                    self.ircprivmsg("%s" % msg[1])
                elif(self.debug):
                    self.ircprivmsg("Routing key denied")

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
            if(self.debug):
                consoleoutput("<IRC: %s" % self.irclinelist[n])
            self.irclinelist[n] = string.split(string.rstrip(self.irclinelist[n]))
        self.irclinelist

    ### Function to send PRIVMSG message to IRC
    def ircprivmsg(self,message,target=False):
        if not target:
            target=self.ircchannel
        self.ircsend("PRIVMSG %s :%s" % (target,message))

    ### Function to send message on the IRC socket (adds \r\n to the message)
    def ircsend(self,message):
        if(self.debug):
            consoleoutput(">IRC: %s" % message)
        if(message[-2:]=='\r\n'):
            self.ircq.append("%s" % message)
        else:
            self.ircq.append("%s\r\n" % message)

    def queuesend(self):
        if(len(self.ircq)>0):
            try:
                self.s.send(self.ircq.popleft())
            except Exception as e:
                consoleoutput("Socket exception sending to IRC, type: %s exception message: %s" % (str(type(e)),e.strerror))
                sys.exit(1)

    def joinchannel(self,channel=None):
        if not channel:
            channel = self.ircchannel
        consoleoutput("Joining channel %s" % channel)
        self.ircsend("JOIN %s" % channel)

    def setnick(self,nick=None):
        if not nick:
            nick = self.botnick
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
                consoleoutput("Nickname %s is in use, trying another..." % self.botnick)
                self.setnick(nick="%s%s" % (self.botnick,nickcount))
                self.nickcount += 1
                continue

            ### Handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                self.joined=True
                consoleoutput("Joined channel %s" % self.ircchannel)
                continue

            ### Handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==self.ircchannel and line[3]==self.botnick):
                self.joined=False
                consoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                continue

            ### Handle raw 474 (raw 474 is sent when the bot tries to join the channel and is banned)
            if(line[1]=="474"):
                ### try joining again until successful, sleep 1 sec first to avoid flooding the server
                time.sleep(1)
                consoleoutput("Banned from channel %s - attempting rejoin..." % self.ircchannel)
                continue
        return self.joined

    ### Handle commands for the bot
    def handlecmds(self):
        for line in self.irclinelist: 
            target = True
            if(line[1]=="PRIVMSG"):
                if (line[2]==self.ircchannel and line[3]==":%s:" % self.botnick):
                    target = False
                elif (line[2]==self.botnick):
                    line.insert(3,None)
                    line[4] = line[4][1:]
                else:
                    continue

                fullcommand=" ".join(line[4:])
                self.sendernick=line[0][1:].partition("!")[0]
                if target:
                    target = self.sendernick
                consoleoutput("IRC command from %s received: %s" % (self.sendernick,fullcommand))
                hostname = line[0].partition("@")[2]
                if self.cfg.auth_user(self.sendernick,hostname):
                    if line[4] in self.commandict:
                        self.commandict[line[4]](line,target)
                    else:
                        self.ircprivmsg("%s: unrecognized command: %s" % (self.sendernick,line[4]),target)
                else:
                    self.ircprivmsg("%s: Sorry, could not find you in the user list." % self.sendernick)

###############################################################################

### get commandline options
options, args = parser.parse_args()

### Create configuration object
cfgobj      = AMQPBotConfig(options)

### Spawn AMQP object
amqphandler = AMQPhandler(options) 

### Spawn IRC object
ircclient   = IRCClient(options,cfgobj,amqphandler)
