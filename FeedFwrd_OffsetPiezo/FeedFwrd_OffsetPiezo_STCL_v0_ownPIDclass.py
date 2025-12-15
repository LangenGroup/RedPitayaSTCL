# -*- coding: utf-8 -*-
"""
Created on Wed Jul 19 14:51:42 2023

@author: ColdMolBaFExp
"""

from ColdMolpy.labdevices import RP, PID
import numpy as np
import time
import matplotlib.pyplot as plt
from serial import Serial

rp_s = RP(host='192.168.0.14',bits=14)
rp_s.tx_txt('ACQ:RST')
rp_s.tx_txt('ACQ:DEC 64')

rp_s.tx_txt('ACQ:TRIG:LEVEL 500')
# rp_s.tx_txt('ACQ:TRIG:DLY 6000')
rp_s.tx_txt('ACQ:SOUR1:GAIN HV')
rp_s.tx_txt('ACQ:SOUR2:GAIN HV')

def wait_for_Trig_Ch(rp_):
    rp_.tx_txt('ACQ:START')
    rp_.tx_txt('ACQ:TRIG CH2_PE')
    while 1:
        rp_.tx_txt('ACQ:TRIG:STAT?')
        if rp_.rx_txt() == 'TD':
            break

def get_scanpiezo_offset(wdh=10):
    
    chData_arr  = np.zeros([wdh, 2**rp_s.bits])
    
    for i in range(wdh):
        wait_for_Trig_Ch(rp_s)
        chData_arr[i,:] = rp_s.get_data(Ch=1)
        
        time.sleep(0.1)
    
    value = chData_arr[:,4000:7000].mean()
    return value

def query(conn,s):
    time.sleep(0.05)
    conn.write(str.encode(s+'\n'))
    time.sleep(0.05)
    return conn.readline().decode().split('\r\n')[0]

def OWON_getV(port):
    with Serial(port=port,timeout=0.5,baudrate=115200) as conn:
        value = query(conn,'VOLT?')
        conn.close()
    return float(value)

def OWON_setV(port,value):
    with Serial(port=port,timeout=0.5,baudrate=115200) as conn:
        conn.write(str.encode('VOLTAGE {} \n'.format(value)))
        conn.write(str.encode('OUTPut 1 \n'))
        conn.close()


#%% initialize PID
pid = PID(P=0.1,I=0,limit=[-0.15,0.15])
#%%
V_set = -4
piezo_limits = [8,50]

MV_arr = [] # correction voltage for offset piezo
V_new_arr = [] # set voltages of the offset piezo
V_scanpiezo_arr = [] # read DC voltages of the scan piezo ramp

while True:
    V_scanpiezo = get_scanpiezo_offset()
    V_scanpiezo_arr.append(V_scanpiezo)
    print('Scan piezo: {:+8.4f} V'.format(V_scanpiezo),end=', ')
    
    pid.update(e=V_scanpiezo-V_set, t=time.perf_counter())
    print('MV: {:+8.4f} V'.format(pid.MV),end=', ')
    V_old = OWON_getV('COM17')
    V_new = V_old - pid.MV
    MV_arr.append(pid.MV)
    V_new_arr.append(V_new)
    
    if V_new < min(piezo_limits) or V_new > max(piezo_limits):
        raise Exception('Limits of piezo reached: {:.4f}'.format(V_new))
    else:
        OWON_setV('COM17',V_new)
        print('Offset piezo new: {:+8.4f} V'.format(V_new))
    
    
    time.sleep(2)

#%% saving data
# np.savetxt('Longterm_Voltage.txt',np.array(V_new_arr),delimiter=',')
# np.savetxt('Longterm_Voltage_scanpiezo.txt',np.array(MV_arr),delimiter=',')


#%% old parts
# class PID:
#     def __init__(self, P=0, I=0, D=0, I_val=0, limit=[-1,1]):
#         self.P = P
#         self.I = I
#         self.D = D
#         self.I_val = I_val
#         self.start = I_val
#         self.e_prev, self.t_prev = None, None
#         self.MV = self.start
#         self.limit = limit
#         self.on = True
    
#     def check_limit(self):
#         max_lim = max(self.limit)
#         min_lim = min(self.limit)
#         if self.MV >= max_lim:
#             self.MV = max_lim
#             print("PID reached limit {}!".format(max_lim))
#         elif self.MV <= min_lim:
#             self.MV = min_lim
#             print("PID reached limit {}!".format(min_lim))
    
#     def update(self, e, t):
#         if (self.e_prev == None) & (self.t_prev == None):
#             self.e_prev, self.t_prev = e, t
#         else:
#             if self.on:
#                 self.I_val += self.I*e*(t-self.t_prev)
#                 self.MV = self.P*e + self.I_val + self.D*(e-self.e_prev)/(t-self.t_prev)
#             # check, whether PID output is within limits. 
#             self.check_limit()
#             self.e_prev, self.t_prev = e, t
#     def reset(self):
#         self.I_val = self.start
#         self.MV = self.start
#         self.e_prev, self.t_prev = None, None
