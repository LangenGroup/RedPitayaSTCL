# -*- coding: utf-8 -*-
"""
Created on Wed Jul 19 14:51:42 2023

@author: ColdMolBaFExp

This code connects the T-piece to a normal cavity ramp signal, reads the scan piezo offset,
and applies a PID-based feed-forward correction to the offset piezo via an OWON power supply.
It also plots the error between the set voltage (-4 V) and the measured offset voltage over time.
!!!
IMPORTANT: turn on SCPI server on the feed-forward RedPitaya via the web interface
see: https://redpitaya.readthedocs.io/en/latest/appsFeatures/remoteControl/remoteControl.html
!!!
"""

import numpy as np
import time
import matplotlib.pyplot as plt
from redpitaya_scpi import scpi
from serial import Serial
import socket

#%% Network connection test to RedPitaya
HOST = "192.168.0.105"
PORT = 5000

try:
    rp_s_test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    rp_s_test.settimeout(5)  # 5-second timeout
    rp_s_test.connect((HOST, PORT))
    print("Connection successful!")
    rp_s_test.close()
except Exception as e:
    print(f"Connection failed: {e}")

#%% Definitions of parameters
RP_host         = '192.168.0.105'  # IP address of the RedPitaya, password is "admin"
RP_bits         = 14               # bit resolution of the RedPitaya version
Ch              = 1                # Channel of RedPitaya for scan signal
rep_data_aqu    = 2                # repetitions of the data acquisition from the RedPitaya

V_set           = -4.0             # Set voltage [V] for stabilization
piezo_limits    = [5, 60]          # Voltage limits [V] for the offset piezo (OWON)
PID_limits      = dict(P=0.3, I=0.01, D=0.01, limit=[-0.15, 0.15]) #
delta_t         = 0.01             # time delta [s] between one step of the feed-forward

#%% Initialize RedPitaya and set acquisition parameters
rp_s = scpi(host=RP_host)
rp_s.tx_txt('ACQ:RST')
rp_s.tx_txt('ACQ:DEC 64')      # decimation: time resolution = decimation * 8 ns
rp_s.tx_txt('ACQ:TRIG:LEV 0.5 V')
rp_s.tx_txt('ACQ:SOUR1:GAIN HV')  # high voltage (HV) or low voltage (LV)
rp_s.tx_txt('ACQ:SOUR2:GAIN HV')

#%% Function definitions

class PID:
    """Proportional-Integral-Differential (PID) controller."""
    def __init__(self, P=0, I=0, D=0, I_val=0, limit=[-1, 1]):
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
        if (self.e_prev is None) and (self.t_prev is None):
            self.e_prev, self.t_prev = e, t
        else:
            if self.on:
                self.I_val += self.I * e * (t - self.t_prev)
                self.MV = self.P * e + self.I_val + self.D * (e - self.e_prev) / (t - self.t_prev)
            self.check_limit()
            self.e_prev, self.t_prev = e, t

    def reset(self):
        self.I_val = self.start
        self.MV = self.start
        self.e_prev, self.t_prev = None, None

def get_scanpiezo_offset(Ch, rep=10):
    """Waits for a trigger, reads the scan piezo data from the RedPitaya, and returns the average offset."""
    def wait_for_Trig_Ch(rp_):
        rp_.tx_txt('ACQ:START')
        rp_.tx_txt('ACQ:TRIG CH2_PE')
        while True:
            rp_.tx_txt('ACQ:TRIG:STAT?')
            if rp_.rx_txt() == 'TD':
                break

    def get_data(rp_, Ch=Ch):
        rp_.tx_txt(f'ACQ:SOUR{Ch}:DATA?')
        buff_string = rp_.rx_txt()
        # print(list(map(float, buff_string.strip('{}\n\r').replace("  ", "").split(','))))
        return list(map(float, buff_string.strip('{}\n\r').replace("  ", "").split(',')))

    chData_arr = np.zeros([rep, 2**RP_bits])
    for i in range(rep):
        wait_for_Trig_Ch(rp_s)
        chData_arr[i, :] = get_data(rp_s, Ch=Ch)
        time.sleep(0.1)
    
    mean_voltage_at_beginning = chData_arr[:, 4000:7000].mean()
    
    return mean_voltage_at_beginning

def OWON_query(conn, s):
    time.sleep(0.05)
    conn.write(str.encode(s + '\n'))
    time.sleep(0.05)
    return conn.readline().decode().split('\r\n')[0]

def OWON_getV(port):
    """Acquire the voltage from the OWON power supply."""
    with Serial(port=port, timeout=0.5, baudrate=115200) as conn:
        value = OWON_query(conn, 'VOLT?')
        print("OWON reading: ", value)
    return float(value)

def OWON_setV(port, value):
    """Set the voltage of the OWON power supply."""
    with Serial(port=port, timeout=0.5, baudrate=115200) as conn:
        conn.write(str.encode('VOLTAGE {} \n'.format(value)))
        conn.write(str.encode('OUTPut 1 \n'))

#%% Initialize PID controller
pid = PID(**PID_limits)

#%% Set up live plotting for error (V_set - V_actual)
#plt.ion()  # Enable interactive mode
#fig, ax = plt.subplots()
#line, = ax.plot([], [], 'b-', label='Error (V_set - V_actual)')
#ax.set_xlabel('Time (s)')
#ax.set_ylabel('Error (V)')
#ax.set_title('Evolution of Voltage Error Over Time')
#ax.legend()
#time_data = []
#error_data = []
#plot_start_time = time.time()

#%% Prepare COM port connection (if needed)
try:
    with Serial(port="COM14", timeout=0.5, baudrate=115200) as conn:
        conn.open()
        conn.flush()
except Exception as e:
    pass

#%% Main loop for feed-forward and real-time plotting
while True:
    # Acquire scan piezo offset
    V_scanpiezo = get_scanpiezo_offset(Ch=Ch, rep=rep_data_aqu)
    print('Scan piezo: {:+8.4f} V'.format(V_scanpiezo), end=', ')
    
    # Update PID using error computed from scan piezo and set voltage
    pid.update(e=V_scanpiezo - V_set, t=time.perf_counter())
    print('MV: {:+8.4f} V'.format(pid.MV), end=', ')
    
    # Read current voltage from OWON
    V_old = OWON_getV('COM14')
    V_new = V_old - pid.MV  # Compute new voltage to apply
    
    print('Offset piezo old: {:+8.4f} V'.format(V_old), end=', ')
    print('Offset piezo new: {:+8.4f} V'.format(V_new))
    
    # Update live plot with error (set voltage - measured voltage)
    #current_time = time.time() - plot_start_time
   # error = V_scanpiezo - V_set
    #time_data.append(current_time)
    #error_data.append(error)
    
    #line.set_data(time_data, error_data)
    #ax.relim()
    #ax.autoscale_view()
    #plt.draw()
    #plt.pause(0.001)
    
    # Check if the new voltage is within allowed piezo limits.
    if V_new < min(piezo_limits) or V_new > max(piezo_limits):
        raise Exception('Limits of piezo reached: {:.4f}'.format(V_new))
    else:
        OWON_setV('COM14', V_new)
    
    # Optional sleep for next loop iteration.
    time.sleep(delta_t)
