# -*- coding: utf-8 -*-

from RP_Lock import *

host, port = '192.168.0.57', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'monitor')
Lock.setup_server(loop=False)
Lock.start_server()