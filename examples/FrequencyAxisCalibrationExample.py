# -*- coding: utf-8 -*-
"""
Created on Tue Oct 31 10:46:28 2023

@author: pgross
"""

'''
This example script demonstrates a method of calibrating the frequency axis of
a (diode) laser scan with the RedPitayaSTCL package.
The resulting frequency and timestamp arrays which are obtained from a wave-
meter can be used in an evaluation script to generate a transfer function bet-
ween the readings of the cavity error signal and the frequency readings of the
wavemeter.
'''

# =============================================================================
# First we import the usual packages.
# =============================================================================
import numpy as np
from time import sleep
import datetime
from LockClient2 import LockClient, RP_client

# =============================================================================
# Here we initialize the RPs dictionary. For more details see the operation
# example file.
# =============================================================================
RPs = dict(
    Cav     = RP_client(("192.168.0.101", 5000), {}, mode = 'scan'),
    Lock1   = RP_client(("192.168.0.102", 5000), {}, mode = 'lock'),
    Mon     = RP_client(("192.168.0.100", 5000), {}, mode = 'monitor') 
    )
Lock = LockClient(RPs)
sleep(1)
cavity_locked = False

# %% Initiate the cavity scan and monitor

# =============================================================================
# Here we start the lock and initiate the cavity scan and monitoring.
# =============================================================================
Lock.start()
sleep(1)
Lock.RPs['Cav'].lsock = None # listening server, if it is not properly closed
Lock.RPs['Cav'].loop_running = False
sleep(1)

print("Starting scan on the cavity RP...")
Lock.start_scan('Cav')
sleep(1)

print("Starting monitor...")
Lock.start_monitor('Mon')
sleep(1)

# %% Cell to update the lock settings

# =============================================================================
# Here we can adjust the locking parameters, like the ranges in which the peak
# is expected. Again, refer to the operation example file for more details.
# =============================================================================
Lock.update_setting('Cav', 'Master', 'range', [[0.1,0.35],[1.75, 2.05]])
Lock.update_setting('Cav', 'Master', 'lockpoint', 1.9)
Lock.update_setting('Lock1', 'Slave1', 'enabled', True)
Lock.update_setting('Lock1', 'Slave1', 'range', [0.36, 1.7])
Lock.update_setting('Lock1', 'Slave1', 'lockpoint', 1.04)

# %% Toggle cavity lock on and off

# =============================================================================
# This cell toggles the cavity lock on and off.
# =============================================================================
Lock.stop_loop('Cav')
sleep(0.5)
if not cavity_locked: Lock.start_lock('Cav'), print("Cavity: Start lock!")
if cavity_locked: Lock.start_scan('Cav'), print("Cavity: Stop lock!")
cavity_locked = not cavity_locked

# %% Activate error monitor

# =============================================================================
# Here we start the error monitor functionality in order to see the change of
# the peak position over time.
# =============================================================================
Lock.start_error_monitor('Mon', tmin = 30e-3)

# %% Initialize frequency calibration

# =============================================================================
# The array setpoints is used to control the frequency of the follower laser.
# This can be achieved with e.g. an external power supply controlling the angle
# of the diode laser grating with a variable voltage.
# =============================================================================
freq_min                = ...
freq_max                = ...
number_of_freq_steps    = ...
setpoints               = np.linspace(freq_min, freq_max, number_of_freq_steps)

# =============================================================================
# We also initialize some arrays to store the wavemeter readings and the cor-
# responding timestamps.
# =============================================================================
timestamps_min_voltage  = np.array([])
frequencies_min_voltage = np.array([])
timestamps_max_voltage  = np.array([])
frequencies_max_voltage = np.array([])

# =============================================================================
# The function nmtoTHz converts a wavelength in nm into a frequency in THz.
# =============================================================================
def nmtoTHz(wavelength):
    c = 299792458 # m/s
    return c/wavelength * 1e-3

# =============================================================================
# The function read_wavelength is used to retrieve the reading of a wavemeter.
# =============================================================================
def read_wavelength():
    wavelength = ...
    return wavelength

# =============================================================================
# The function set_piezo_voltage is used to communicate with an external power
# supply to change the piezo voltage of a diode laser.
# =============================================================================
def set_piezo_voltage(voltage = None):
    ...

# =============================================================================
# The frequency axis calibration begins by setting the follower laser to a
# frequency that corresponds to one end of the set range. A short sleep() com-
# mand allows the piezo to settle a bit, reducing the residual drift.
# =============================================================================
set_piezo_voltage(setpoints[0])
print(f"Setting piezo voltage to {setpoints[0]} V.")
sleep(2)
print("Gathering samples...")

# =============================================================================
# The acquisition of samples is performed in a try-except loop so that the user
# can perform a keyboard interrupt (Ctrl + C) once a sufficient number of sam-
# ples has been recorded.
# =============================================================================
try:
    number_of_benchmark_samples_1 = 0
    
# =============================================================================
# As long as the user does not interrupt the acquisition, the script just keeps
# recording wavemeter samples and the corresponding timestamps.
# =============================================================================
    while True:
        timestamp  = datetime.datetime.now()
        frequency  = nmtoTHz(read_wavelength)
        
# =============================================================================
# For monitoring purposes to ensure that nothing went wrong during the cali-
# bration, the script displays the acquired frequency readings.
# =============================================================================
        print(f"Press Ctrl + C to continue. Frequency: {frequency:3.6f}, Timestamp: {timestamp}")
        
# =============================================================================
# The values are appended to the respective arrays.
# =============================================================================
        timestamps_min_voltage  = np.append(timestamps_min_voltage,  timestamp)
        frequencies_min_voltage = np.append(frequencies_min_voltage, frequency)
        number_of_benchmark_samples_1 += 1
        sleep(0.1)
        
# =============================================================================
# Once the user interrupts the acquisition, the script displays the number of
# recorded samples.
# =============================================================================
except:
    print(f"Gathered {number_of_benchmark_samples_1} samples.")


# =============================================================================
# Then the laser is tuned to the other end of the frequency range and the same 
# acquisition procedure is repeated. This second loop does the same thing as the
# first loop, only at a different set point. 
# =============================================================================
set_piezo_voltage(setpoints[-1])
print(f"Setting piezo voltage to {setpoints[-1]} V.")
sleep(2)
print("Gathering samples...")
try:
    number_of_benchmark_samples_2 = 0
    while True:
        timestamp  = datetime.datetime.now()
        frequency  = nmtoTHz(read_wavelength)
        print(f"Press Ctrl + C to continue. Frequency: {frequency:3.6f}, Timestamp: {timestamp}")
        timestamps_max_voltage  = np.append(timestamps_max_voltage,  timestamp)
        frequencies_max_voltage = np.append(frequencies_max_voltage, frequency)
        number_of_benchmark_samples_2 += 1
        sleep(0.1)
except:
    input(f"Gathered {number_of_benchmark_samples_2} samples.\nPress Return to start the measurement.")


# =============================================================================
# Any actual measurement code would be executed at this point in the script.
# =============================================================================



# =============================================================================
# After the measurement is done, the error array and calibration need to be
# saved.
# =============================================================================

# =============================================================================
# run_dir is the folder in which the measurement run is saved. Here we save the
# calibration data.
# =============================================================================
run_dir = ...
np.savetxt(run_dir + r'\frequencies_min_voltage.txt', np.array([frequencies_min_voltage]), delimiter='\n')
np.savetxt(run_dir + r'\timestamps_min_voltage.txt', np.array([dt.strftime('%Y-%m-%d %H:%M:%S') for dt in timestamps_min_voltage]), delimiter=',', fmt = "%s")
np.savetxt(run_dir + r'\frequencies_max_voltage.txt', np.array([frequencies_max_voltage]), delimiter='\n')
np.savetxt(run_dir + r'\timestamps_max_voltage.txt', np.array([dt.strftime('%Y-%m-%d %H:%M:%S') for dt in timestamps_max_voltage]), delimiter=',', fmt = "%s")

# =============================================================================
# We usually save the error array in a folder one level above the folder of an
# individual measurment run. The reason for this is that the error acquisition
# can just keep running while different measurement are started and stopped.
# data_dir is the folder in which the error array should be saved. 
# =============================================================================
data_dir = ...
Lock.monitors['Mon']['queue_err'].put(('save', data_dir + '\\error_array_' + str(int(datetime.now().timestamp()))))
print("Saved error array.")