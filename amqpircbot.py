#!/usr/local/bin/python
#####################################################################
###
### AMQPBot an IRC bot that relays/sends AMQP messages to/from IRC.
###
### README and the latest version of the script can be found on Github:
### https://github.com/tykling/amqpirc
#####################################################################

### Load libraries
import os
import sys
import socket
import string
import time
import thread
import pika
import json
import ssl
import logging
logging.basicConfig()
from collections import deque

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message.decode('utf-8'))

### class for amqpmsg-formatting table types
class StrFormatRules:
    def __init__(self):
        self.rkeylist  = list()
        self.formatstr = ""

class AMQPBotConfig:
    def __init__(self,config):
        #self.options     = options
        self.userlist    = list()
        self.amqpoptions = { 'server'       : 'localhost',
                             'user'         : 'guest',  
                             'password'     : 'guest',  
                             'exchange'     : 'myexchange', 
                             'maxfetch'     : 20,
                             'vhost'        : '/',
                             'routingkey'   : '#' ,
                             'exc_passive'  : False,
                             'exc_durable'  : False,
                             'exc_autodel'  : False,
                             'exc_internal' : False,                             
                             'exc_nowait'   : False,                             
                             'exc_args'     : None,                             
                             'exc_type'     : 'topic',                             
                             'queue'        : '',
                             'que_passive'  : False,
                             'que_durable'  : False,
                             'que_exclusive': False,
                             'que_autodel'  : False,
                             'que_nowait'   : False,                             
                             'que_args'     : None}                             

        self.ircoptions = { 'host'        : 'irc.efnet.org',
                            'port'        : 6667,
                            'serverpass'  : False,
                            'channelpass' : False,
                            'nick'        : 'amqpbot',
                            'realname'    : 'amqpirc bot',
                            'ident'       : 'amqpirc',
                            'channel'     : '#amqpirc',
                            'ssl_enabled' : False,
                            'compact'     : False}


        self.filtertables      =  { 'allow' : list(),
                                    'deny'  : list() }
        self.formattingtables  = dict()
        self.defaultformatting = "Routingkey: %s "
        self.notables          = True

        ### Extract config name and path from commandline input and parse config from file
        idx = config.rfind('/')
        if idx > -1:
            fname = config[idx+1:]
            path  = config[:idx]
        else:
            fname = config
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
                line   = line[:n] +"\n"
                line.replace("\n","")
                cfgstr = cfgstr + line
        jsonblob = json.loads(cfgstr)
        if 'users' in jsonblob:
            self.userlist.extend(jsonblob['users'])
            self.usersexists = True
        else:
            self.usersexists = False
                
        ## handle AMQPOptions here
        if 'amqp_options' in jsonblob:
            amqpo = jsonblob['amqp_options']
            for key in amqpo:
                if amqpo[key] == "":
                    continue
                else:
                    self.amqpoptions[key] = amqpo[key]
        else:
            consoleoutput("Did not find any 'amqp_options' entry in config, was that on purpose?")

        ## handle IRCOptions here
        if 'irc_options' in jsonblob:
            irco = jsonblob['irc_options']
            for key in self.ircoptions:
                if key not in irco:
                    continue
                elif irco[key] == "":
                    continue
                self.ircoptions[key] = irco[key]
        else:
            consoleoutput("Did not find any 'irc_options' entry in config, was that on purpose?")

        if self.ircoptions['channel'][0] != '#':
            self.ircoptions['channel'] = '#' + self.ircoptions['channel']

        ## adjoins the tables->routingkeys to the appropriate tables (i.e. might have values of commandline arguments)
        if 'tables' in jsonblob:
            self.notables = False
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
        else:
            return True
        return False

    # Checks each subkey to see if it matches the rule. If the entire rule matches (the relevant part of) the routing key the rule is validated 
    # otherwise it is not
    def validate_rules(self,filter_rules,routing_key):
        if self.notables:
            return True
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

                ### If the rule validated the message, stop looking thorugh rules allow
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
        ### If the the routingkey is in filter allow see if it is in the ignore list. If so, return false otherwise return true
        if not self.validate_rules(self.filtertables['allow'],routing_key):
            return False
        else:
            #first check if there are any rules in the deny table
            if len(self.filtertables['deny']) == 0: 
                return True 
            #if there is, check them to see if there is a match or not
            elif self.validate_rules(self.filtertables['deny'],routing_key):
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
    def create_connection(self):
        try:
            ### Connect to ampq 
            self.conn = pika.BlockingConnection(pika.ConnectionParameters(host=self.amqphost,virtual_host=self.vhost,credentials=pika.PlainCredentials(self.user, self.password)))
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
        self.chanlist[n].channel.exchange_declare(exchange=self.exchange,exchange_type=self.exc_type, passive=self.exc_passive, durable=self.exc_durable,
                                                  auto_delete=self.exc_autodel, internal=self.exc_internal, nowait=self.exc_nowait, arguments=self.exc_args)

    def declare_queueANDbind(self,n):
        ### Declare queue and get unique queuename
        self.chanlist[n].result = self.chanlist[n].channel.queue_declare(queue=self.queue, passive=self.que_passive, durable=self.que_durable, nowait=self.que_nowait, 
                                                                         exclusive=self.que_exclusive, auto_delete=self.que_autodel, arguments=self.que_args)
        self.chanlist[n].queue_name = self.chanlist[n].result.method.queue
        self.chanlist[n].channel.queue_bind(exchange=self.exchange,queue=self.chanlist[n].queue_name,routing_key=self.routingkey)
                       
    def changeroutingkey(self,n,rkey):
        self.chanlist[n].queue_unbind(exchange=self.exchange,routing_key=self.routingkey,queue=self.chanlist[n].queue_name)
        self.chanlist[n].queue_bind(exchange=self.exchange,queue=self.chanlist[n].queue_name,routing_key=rkey)
        self.routingkey = rkey

    def amqpsend(self,amqpbody,routingkey):
        self.chanlist[0].channel.basic_publish(exchange=self.exchange,routing_key=routingkey,body=amqpbody,properties=self.properties)

    def __init__(self,options):
        self.amqphost      = options['server']
        self.user          = options['user']
        self.password      = options['password']
        self.exchange      = options['exchange']
        self.routingkey    = options['routingkey']
        self.maxfetch      = options['maxfetch']
        self.vhost         = options['vhost']
        self.exc_passive   = options['exc_passive']
        self.exc_durable   = options['exc_durable']
        self.exc_autodel   = options['exc_autodel']
        self.exc_internal  = options['exc_internal']
        self.exc_nowait    = options['exc_nowait']
        self.exc_args      = options['exc_args']
        self.exc_type      = options['exc_type']
        self.queue         = options['queue']
        self.que_passive   = options['que_passive']
        self.que_durable   = options['que_durable']
        self.que_exclusive = options['que_exclusive']
        self.que_autodel   = options['que_autodel']
        self.que_nowait    = options['que_nowait']
        self.que_args      = options['que_args']

        self.conn          = None
        self.chanlist      = list();
        self.properties    = pika.BasicProperties(delivery_mode=2)
        ### List of messages that havne't been printed to IRC
        self.amqpq         = deque()

        ### create connection to rabbitmq
        self.create_connection()

        ### create sending channel and exchange
        self.create_channel(0)
        self.declare_exchange(0)

        ### create receiving connection w. channel, exchange and queue
        self.create_channel(1)
        self.declare_exchange(1)
        self.declare_queueANDbind(1)

    def check_incoming(self):
        count = 0
        if self.chanlist[1].channel.is_open:
            while True and self.maxfetch > count:
                method, header, body = self.chanlist[1].channel.basic_get(queue=self.chanlist[1].queue_name,no_ack=True)
                if header:
                    self.amqpq.append([method.routing_key,body])
                else:
                    break
                count += 1

### Define exception to use for socket read errors
class ReadError(Exception):
    pass

### IRC-object: Connects to irc and reads IRC-feed from socket
class IRCClient:
    ### Connect to IRC
    def __init__(self,options,cfg,amqphandler):
        self.amqphandler = amqphandler
        self.cfg         = cfg
        self.host        = options['host']
        self.port        = options['port']
        self.ircssl      = options['ssl_enabled']
        self.ircchannel  = options['channel']
        self.botnick     = options['nick']
        self.ident       = options['ident']
        self.realname    = options['realname']
        self.serverpass  = options['serverpass']
        self.channelpass = options['channelpass']
        self.compact = options['compact']
        self.debug       = debug 
        self.ircq        = deque()
        self.sendernick  = ""
        self.readbuffer  = ""
        self.irclinelist = list()
        self.joined      = False
        self.nickcount   = 0
        self.commandict  = {'help'          : self.printircmds,
                            'listrules'     : self.listrules,
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

        self.helpdict    = {'help'          : '"help <string>" lists all commands containing <string>. If <string> is empty, all commands are listed.',
                           'listrules'      : '"listrules <table>" lists the routingkeys in <table>',
                           'amqpsend'       : '"amqpsend <rkey> <body>" sends a amqp message with routing key <rkey> and message <body>.',
                           'ping'           : '"ping" makes the bot respond with a "pong" message (to check if it is alve).', 
                           'addrule'        : '"addrule <table> <rkey>" adds <rkey>-rule to <table>',
                           'delrule'        : '"delrule <table> <entry no.>" removes the routing key rule no. <entry no.> from <table>',
                           'amqpclose'      : 'closes the receiving amqp channel',
                           'amqppurgeopen'  : 'opens the receiving amqp channel and purges the queue immediately after opening',
                           'amqpdisconnect' : 'dicsonnects from amqp! (Should not be used for other than debugging)',
                           'amqpopen'       : 'opens the receiving amqp channel',
                           'amqpchangekey'  : 'change the routingkey the receiving channel is listening to',
                           'amqpstatus'     : 'reports the status of the receiving channel: Is it closed/closing or open. Atm it seems like it says "closing" when it is closed'}

        try:
            self.s=socket.socket( )
            self.s.settimeout(1)
            self.ircconsoleoutput("Connecting to IRC server %s port %s ..." % (self.host,self.port))
            self.s.connect((self.host, int(self.port)))
        except:
            self.ircconsoleoutput("Unable to connect to IRC, error: %s" % sys.exc_info()[0])
            sys.exit(1)

        ### Enable SSL if requested
        if(self.ircssl):
            self.ircconsoleoutput("Enabling SSL for this IRC connection...")
            try:
                self.s = ssl.wrap_socket(self.s)
            except:
                self.ircconsoleoutput("Unable to enable SSL for this connection, error: %s" % sys.exc_info()[0])
                sys.exit(1)
        else:
            self.ircconsoleoutput("Not enabling SSL for this IRC connection...")

        if self.serverpass:
            self.ircsend("PASS %s" % self.serverpass)
        

        ### NICK and USER
        self.setnick()
        self.ircsend("USER %s %s bla :%s" % (self.ident,self.host,self.realname))

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
                self.ircconsoleoutput("control-c received, exiting")
                sys.exit(0)
            
            ### socket read error exception (disconnected from IRC)
            except (ReadError):
                self.ircconsoleoutput("socket disconnected/error, bailing out")
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
    ## line[4] contains the command.
    ### List selected rules
    def ping(self,line,target):
        ### send PONG to IRC
        self.ircprivmsg("pong",target)

    ### prints help function
    def printircmds(self,line,target):
        if len(line)<6:
            searchstr = ""
            self.ircprivmsg("Commands for the AMQP bot:",target)
        else:
            searchstr = line[5]
            self.ircprivmsg("Commands for the AMQP bot matching search-string '%s'" % searchstr,target)
        
        for cmd in self.helpdict:
            if searchstr in cmd:
                self.ircprivmsg("%s: %s" % (cmd,self.helpdict[cmd]),target)                
        self.ircprivmsg("That's it! Remember to put '<botnick>:' in front of the commands.",target)

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
            self.ircconsoleoutput("Error! Unable to delete rule no. %s" % str(rule_no))
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
                    if self.compact:
                        self.ircprivmsg("%s: %s" % (msg[0],msg[1]))
                    else:
                        msg_status = " (%s messages in bot queue)" % len(self.amqphandler.amqpq)
                        msg[0]     = self.cfg.string_formatting(msg[0]) + msg_status
                        if self.debug:
                            self.ircprivmsg("Routing key allowed")
                        self.ircprivmsg(msg[0])
                        self.ircprivmsg("%s" % msg[1])
                elif(self.debug):
                    self.ircprivmsg("Routing key denied")

    ########### Misc commands for IRChandling ###################
    ### Append botnick to console output
    def ircconsoleoutput(self,message):
        consoleoutput("%s: %s" % (self.botnick, message.decode('utf-8')))   

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
                self.ircconsoleoutput("<IRC: %s" % self.irclinelist[n])
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
            self.ircconsoleoutput(">IRC: %s" % message)
        if(message[-2:]=='\r\n'):
            self.ircq.append("%s" % message)
        else:
            self.ircq.append("%s\r\n" % message)

    def queuesend(self):
        if(len(self.ircq)>0):
            try:
                self.s.send(self.ircq.popleft().decode('utf-8'))
            except Exception as e:
                self.ircconsoleoutput("Socket exception sending to IRC, type: %s exception message: %s" % (str(type(e)),e))
                sys.exit(1)

    def joinchannel(self,channel=None):
        if not channel:
            channel = self.ircchannel
        self.ircconsoleoutput("Joining channel %s" % channel)
        if self.channelpass:
            self.ircsend("JOIN %s %s" % (channel,self.channelpass))
        else:
            self.ircsend("JOIN %s" % channel)

    def setnick(self,nick=None):
        if not nick:
            nick = self.botnick
        self.ircconsoleoutput("Setting IRC nickname %s" % nick)
        self.ircsend("NICK %s" % nick)

    def sanitycheck(self):
        for line in self.irclinelist:
            ### Handle PING
            if(line[0]=="PING"):
                self.ircsend("PONG %s" % line[1])
                continue

            ### Handle raw 433 (raw 433 is sent when the chosen nickname is in use)
            if(line[1]=="433"):
                self.ircconsoleoutput("Nickname %s is in use, trying another..." % self.botnick)
                self.setnick(nick="%s%s" % (self.botnick,self.nickcount))
                self.botnick = self.botnick + str(self.nickcount)
                self.nickcount += 1
                continue

            ### Handle raw 353 (raw 353 is sent after channel JOIN completes)
            if(line[1]=="353"):
                self.joined=True
                self.ircconsoleoutput("Joined channel %s" % self.ircchannel)
                continue

            ### Handle KICK (attempt rejoin)
            if(line[1]=="KICK" and line[2]==self.ircchannel and line[3]==self.botnick):
                self.joined=False
                self.ircconsoleoutput("Kicked from channel by %s - attempting rejoin..." % line[0])
                continue

            ### Handle raw 474 (raw 474 is sent when the bot tries to join the channel and is banned)
            if(line[1]=="474"):
                ### try joining again until successful, sleep 1 sec first to avoid flooding the server
                time.sleep(1)
                self.ircconsoleoutput("Banned from channel %s - attempting rejoin..." % self.ircchannel)
                continue
        return self.joined

    ### Handle commands for the bot
    def handlecmds(self):
        for line in self.irclinelist: 
            target = True
            if(line[1]=="PRIVMSG"):
                if (line[2]==self.ircchannel and line[3]==u':%s:' % self.botnick):
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
                self.ircconsoleoutput("IRC command from %s received: %s" % (self.sendernick,fullcommand))
                hostname = line[0].partition("@")[2]
                if self.cfg.auth_user(self.sendernick,hostname):
                    if line[4] in self.commandict:
                        self.commandict[line[4]](line,target)
                    else:
                        self.ircprivmsg("%s: unrecognized command: %s" % (self.sendernick,line[4]),target)
                else:
                    self.ircprivmsg("%s: Sorry, could not find you in the user list." % self.sendernick)

###############################################################################

## function to use in thread-spawning
def init_threadbot(cfg):
    cfgobj = AMQPBotConfig(cfg)
    amqph  = AMQPhandler(cfgobj.amqpoptions)
    ircclient = IRCClient(cfgobj.ircoptions,cfgobj,amqph)

## non-threaded spawning
def init_bot(cfgstr):
    ### Create configuration object
    cfgobj      = AMQPBotConfig(cfgstr)
    ### Spawn AMQP object
    amqphandler = AMQPhandler(cfgobj.amqpoptions) 
    ### Spawn IRC object
    ircclient   = IRCClient(cfgobj.ircoptions,cfgobj,amqphandler)

## fetch command line arguments
debug = False
if len(sys.argv)>2:
    if sys.argv[2] == 'debug':
        debug = True
cfgstr = sys.argv[1]

## If there is only one bot to start then do not use threads
cfglist = cfgstr.split(',') 
for n in range(1,len(cfglist)):
    thread.start_new_thread(init_threadbot,(cfglist[n],))
init_bot(cfglist[0])
