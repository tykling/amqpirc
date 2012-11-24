#!/usr/local/bin/python
#####################################################################
# amqpircspool.py is a part of amqpirc which is an AMQP to IRC proxy.
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
import pika
import sys
import time
import tempfile
from optparse import OptionParser

### define and handle command line options
use = "Usage: %prog [-s amqpserver -u amqpuser -p amqppass -e amqpexchange -r routingkey]"
parser = OptionParser(usage = use)
parser.add_option("-a", "--amqphost", dest="amqpserver", metavar="amqpserver", default="localhost", help="The AMQP/RabbitMQ server hostname or IP (default: 'localhost')")
parser.add_option("-u", "--amqpuser", dest="user", metavar="user", help="The AMQP username")
parser.add_option("-p", "--amqppass", dest="password", metavar="password", help="The AMQP password (omit for password prompt). Set to 'nopass' if user/pass should not be used")
parser.add_option("-e", "--amqpexchange", dest="exchange", metavar="exchange", default="myexchange", help="The AMQP exchange name (default 'myexchange')")
parser.add_option("-r", "--routingkey", dest="routingkey", metavar="routingkey", default="#", help="The AMQP routingkey to listen for (default '#')")
parser.add_option("-s", "--amqpspoolpath", dest="amqpspoolpath", metavar="amqpspoolpath", default="/var/spool/amqpirc/", help="The path of the spool folder (default: '/var/spool/amqpirc/')")
options, args = parser.parse_args()

### Function to output to the console with a timestamp
def consoleoutput(message):
    print " [%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),message)

### Check access to spool path options.amqpspoolpath
if not os.access(options.amqpspoolpath, os.R_OK) or not os.access(options.amqpspoolpath, os.W_OK):
    consoleoutput("Spool path %s is not readable or writable, bailing out" % options.amqpspoolpath)
    sys.exit(1)

### Connect to ampq and open channel
if not (options.password == 'nopass'):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.amqpserver,credentials=pika.PlainCredentials(options.user, options.password)))
        channel = connection.channel()
    except:
        consoleoutput("Unable to connect to AMQP and open channel, error: %s" % sys.exc_info()[0])
        sys.exit(1)
else:
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.amqpserver))
        channel = connection.channel()
    except:
        consoleoutput("Unable to connect to AMQP and open channel, error: %s" % sys.exc_info()[0])
        sys.exit(1)

### Declare exchange
channel.exchange_declare(exchange=options.exchange,type='topic',passive=True, durable=True, auto_delete=False)

### Declare queue and get unique queuename
result = channel.queue_declare(exclusive=True)
queue_name = result.method.queue

### Bind queue to exchange with the wildcard routing key #
channel.queue_bind(exchange=options.exchange,queue=queue_name,routing_key='#')
consoleoutput("Waiting for messages matching routingkey %s. To exit press CTRL+C" % options.routingkey)

### This function is called whenever a message is received
def process_message(ch, method, properties, body):
    tid="%f-" % time.time()
    fd, filename = tempfile.mkstemp(dir=options.amqpspoolpath,prefix=tid)
    f = os.fdopen(fd, 'wt')
    f.write(method.routing_key+'\n')
    f.write(body)
    f.close
    consoleoutput("AMQP message received and written to spool file %s with routingkey %s:" % (filename,method.routing_key))
    print body

### Register callback function process_message to be called when a message is received
channel.basic_consume(process_message,queue=queue_name,no_ack=True)

### Loop waiting for messages
channel.start_consuming()
