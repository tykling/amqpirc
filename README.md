amqpirc
=======

Python scripts to listen to an AMQP/RabbitMQ exchange and output messages to IRC.

- amqpircbot.py is the IRC bot which connects to the specified IRC server and outputs messages from the specified spool path.
- amqpircspool.py is the AMQP client which connects to AMQP/RabbitMQ and listens to the specified exchange, writing messages to the specified spool path.

Example usage:
