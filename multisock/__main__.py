import multisock
import threading
import time
import functools

t = multisock.SocketThread()

t.start()

server = t.listen('tcp:localhost:7890')

def echo_server_accept(sock):
    channel = sock.get_main_channel()
    channel.recv.bind(functools.partial(echo_server_request, channel))

def echo_server_request(channel, data):
    channel.send_async(data)

server.bind(echo_server_accept)

client = t.connect('tcp:localhost:7890')
channel = client.get_main_channel()
channel.send_async('hello world!')
assert channel.recv() == 'hello world!'

channel.send_async('123!')
print channel.recv()
