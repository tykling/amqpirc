#!/usr/local/bin/python

### Load libraries
import os
import pika
import sys
import time
import tempfile
from optparse import OptionParser

### define and handle command line options
use = "Usage: %prog [-s amqpserver -u amqpuser -p amqppass -e amqpexchange]"
parser = OptionParser(usage = use)
parser.add_option("-s", "--amqpserver", dest="SERVER", metavar="SERVER", default="localhost", help="The AMQP/RabbitMQ server hostname or IP")
parser.add_option("-u", "--amqpuser", dest="USER", metavar="USER", help="The AMQP username")
parser.add_option("-p", "--amqppass", dest="PASS", metavar="PASS", help="The AMQP password")
parser.add_option("-e", "--amqpexchange", dest="EXCHANGE", metavar="EXCHANGE", default="myexchange", help="The AMQP exchange name")
options, args = parser.parse_args()

### Connect to ampq and open channel
connection = pika.BlockingConnection(pika.ConnectionParameters(host=options.SERVER,credentials=pika.PlainCredentials(options.USER, options.PASS)))
channel = connection.channel()

### Declare exchange
channel.exchange_declare(exchange=options.EXCHANGE,type='topic',passive=True, durable=True, auto_delete=False)

### Declare queue and get unique queuename
result = channel.queue_declare(exclusive=True)
queue_name = result.method.queue

### Bind queue to exchange with the wildcard routing key #
channel.queue_bind(exchange='bbdev',queue=queue_name,routing_key='#')
print ' [%s] Waiting for messages matching routingkey #. To exit press CTRL+C' % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))

### This function is called whenever a message is received
def process_message(ch, method, properties, body):
    fd, filename = tempfile.mkstemp(dir="/var/spool/amqpirc/")
    f = os.fdopen(fd, 'wt')
    f.write(method.routing_key+'\n')
    f.write(body)
    f.close
    print " [%s] Message written to spool file %s with routingkey %s:" % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),filename,method.routing_key)
    print body

### Register callback function process_message to be called when a message is received
channel.basic_consume(process_message,queue=queue_name,no_ack=True)

### Loop waiting for messages
channel.start_consuming()
