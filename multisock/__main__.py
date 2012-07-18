# Copyright (c) 2012, Michal Zielinski <michal@zielinscy.org.pl>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
# 
#     * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
# 
#     * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

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

start = time.time()
times = 10000
for i in xrange(times):
    channel.send_async('aa')
    channel.recv()
length = time.time() - start

print 'latency %.2f ms' % (length / times * 1000)

#t.thread.join()
