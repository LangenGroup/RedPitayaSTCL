# -*- coding: utf-8 -*-

from RP_Lock import *

host, port = '172.16.111.55', 5000
Lock = RP_Server(host, port, 5065, RP_mode = 'scan')
Lock.setup_server(loop=False)
Lock.start_server()