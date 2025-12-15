# -*- coding: utf-8 -*-
"""
Created on Wed Jul 19 14:51:42 2023

@author: ColdMolBaFExp

connect T-piece to normal cavity ramp signal, read this into this feed-forward pitaya
also connect trigger from scan red pitaya to the feed-forward pitaya Ch2.
Essentially copies the outputs from the scanning RP, could also be a voltage regulator of some kind
code processes this data and provides feedback to offset pitaya via OWON power supply

!!!
IMPORTANT: turn on SCPI server on the feed-forward redpitaya via the web interface
see: https://redpitaya.readthedocs.io/en/latest/appsFeatures/remoteControl/remoteControl.html
!!!
"""
import numpy as np
import time
from redpitaya_scpi import scpi
from serial import Serial

#%% definitions of parameters
RP_host         = '192.168.0.105' # IP address of the RedPitaya, password is "admin"
RP_bits         = 14 # bit of the RedPitaya version
Ch              = 1 # Channel of RedPitaya
rep_data_aqu    = 2 # repetitions of the data aquisition of the RedPitaya # 10

V_set           = -4 # Set voltage [V] of the scanning piezo to be stabilized with the offset piezo
piezo_limits    = [5,60] # Voltage limits [V] of the offset piezo used for PID
PID_limits      = dict(P=0.01, I=0.0001, D=0.001, limit=[-0.15,0.15])
delta_t         = 0.01 # time delta [s] between one step of the feed-forward

#%% initialize RedPitaya
rp_s = scpi(host=RP_host)
rp_s.tx_txt('ACQ:RST')
rp_s.tx_txt('ACQ:DEC 64') #decimation: time resolution = decimation * 8ns
# rp_s.tx_txt('ACQ:TRIG:LEVEL 500') # trigger threshold level in mV
rp_s.tx_txt('ACQ:TRIG:LEV 0.5 V')
rp_s.tx_txt('ACQ:SOUR1:GAIN HV') # high voltage (HV) or low voltage (LV)
rp_s.tx_txt('ACQ:SOUR2:GAIN HV')

#%% function definitions
class PID: # proportional-integral-differential
    def __init__(self, P=0, I=0, D=0, I_val=0, limit=[-1,1]):
        self.P = P
        self.I = I
        self.D = D
        self.I_val = I_val
        self.start = I_val
        self.e_prev, self.t_prev = None, None
        self.MV = self.start
        self.limit = limit
        self.on = True
    
    def check_limit(self):
        max_lim = max(self.limit)
        min_lim = min(self.limit)
        if self.MV >= max_lim:
            self.MV = max_lim
            print("PID reached limit {}!".format(max_lim))
        elif self.MV <= min_lim:
            self.MV = min_lim
            print("PID reached limit {}!".format(min_lim))
    
    def update(self, e, t):
        if (self.e_prev == None) & (self.t_prev == None):
            self.e_prev, self.t_prev = e, t
        else:
            if self.on:
                self.I_val += self.I*e*(t-self.t_prev)
                self.MV = self.P*e + self.I_val + self.D*(e-self.e_prev)/(t-self.t_prev)
            # check whether PID output is within limits. 
            self.check_limit()
            self.e_prev, self.t_prev = e, t
    def reset(self):
        self.I_val = self.start
        self.MV = self.start
        self.e_prev, self.t_prev = None, None

def get_scanpiezo_offset(Ch,rep=10):
    '''Function waits for the trigger into the RedPitaya, receives the scan signal,
    and calculates the current offset of the this scan piezo.
    
    Parameters
    ----------
    rep : int, optional
        repetitions of receiving the signal for averaging. The default is 10.

    Returns
    -------
    float
        scan piezo offset.
    '''
    
    def wait_for_Trig_Ch(rp_): # function waits until Trigger is detected
        rp_.tx_txt('ACQ:START')
        rp_.tx_txt('ACQ:TRIG CH2_PE')
        while 1:
            rp_.tx_txt('ACQ:TRIG:STAT?')
            if rp_.rx_txt() == 'TD':
                break
    
    def get_data(rp_, Ch=Ch): # acquire data from RedPitaya
        rp_.tx_txt(f'ACQ:SOUR{Ch}:DATA?')
        buff_string = rp_.rx_txt()
        return list(map(float, buff_string.strip('{}\n\r').replace("  ", "").split(',')))
    
    chData_arr  = np.zeros([rep, 2**RP_bits])
    for i in range(rep):
        wait_for_Trig_Ch(rp_s)
        chData_arr[i,:] = get_data(rp_s,Ch=Ch)
        time.sleep(0.1)
        
    return chData_arr[:,4000:7000].mean()

def OWON_query(conn,s):
    time.sleep(0.05)
    conn.write(str.encode(s+'\n'))
    time.sleep(0.05)
    return conn.readline().decode().split('\r\n')[0]

def OWON_getV(port): # aquire the voltage of the OWON
    with Serial(port=port,timeout=0.5,baudrate=115200) as conn:
        value = OWON_query(conn,'VOLT?')
        print(value)
        conn.close()
    return float(value)

def OWON_setV(port,value): # set the voltage of the OWON
    with Serial(port=port,timeout=0.5,baudrate=115200) as conn:
        conn.write(str.encode('VOLTAGE {} \n'.format(value)))
        conn.write(str.encode('OUTPut 1 \n'))
        conn.close()

#%% initialize PID
pid = PID(**PID_limits)

#%% Running loop for feed forward algorithm
MV_arr          = [] # correction voltage for offset piezo
V_new_arr       = [] # set voltages of the offset piezo
V_scanpiezo_arr = [] # read DC voltages of the scan piezo ramp

try:
    with Serial(port="COM14",timeout=0.5,baudrate=115200) as conn:
        conn.open()
        conn.flush()
        conn.close()
except: pass

while True:
    V_scanpiezo = get_scanpiezo_offset(Ch=Ch,rep=rep_data_aqu)
    
    # import matplotlib.pyplot as plt
    # plt.plot(V_scanpiezo.T)
    # V_scanpiezo_arr.append(V_scanpiezo)
    # plt.xlabel("Samples")
    # plt.ylabel("Voltage")
    
    
    print('Scan piezo: {:+8.4f} V'.format(V_scanpiezo),end=', ')
    
    pid.update(e=V_scanpiezo-V_set, t=time.perf_counter())
    print('MV: {:+8.4f} V'.format(pid.MV),end=', ')
    V_old = OWON_getV('COM14') # previous voltage of OWON
    V_new = V_old - pid.MV # new voltage
    MV_arr.append(pid.MV)
    V_new_arr.append(V_new)
    
    #check for limits of the piezo or of the power supply
    if V_new < min(piezo_limits) or V_new > max(piezo_limits):
        raise Exception('Limits of piezo reached: {:.4f}'.format(V_new))
    else:
        OWON_setV('COM14',V_new)
        print('Offset piezo new: {:+8.4f} V'.format(V_new))
    
    # optional additional sleep time
    time.sleep(delta_t)

