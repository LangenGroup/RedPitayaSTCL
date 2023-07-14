# -*- coding: utf-8 -*-
"""
Created on Fri May 26 10:26:16 2023

@author: epultinevicius

This example serves as an introduction to the usage of the STCL.

After all Connections are made, the necessary modules LockClient and RP_client can be loaded:
"""
from lockclient import LockClient, RP_client

"""
Initialize all of the RedPitayas using the RP_client class as follows:
    
    RP_client( (ADDR, PORT), {}, mode = MODE)
    
    ADDR: IPv4-address of the RedPitaya
    PORT: port for communicatioon with the redpitaya. set it to 5000.
    MODE: the following modes are used:
        'scan': This redpitaya scans and stabilizes the transfercavity! At least one scan redpitya is mandatory!
        'monitor': This redpitaya is used for monitoring of the STCL
        'lock': This redpitaya is used for locking lasers.
        
Those objects should be stored in a dictionary for the initialization of the LockClient object.
The keys are used to reference the specific redpitaya during the use of the STCL!
example:
"""

RPs = dict(
    Cav = RP_client(("192.168.0.101", 5000), {}, mode = 'scan'),
    Lock1 = RP_client(("192.168.0.102", 5000), {}, mode = 'lock'),
    Mon = RP_client( ('192.168.0.100', 5000), {}, mode = 'monitor') 
    )

Lock = LockClient(RPs)
#%%
"""
In this example, Lock is now the LockClient object used to control the STCL from here on.
The RP_client dictionary can be accessed as 

    Lock.RPs
    
Before working with the STCL, the listening servers on the RedPitayas need to be started.
This can be done in two ways:
    
    1) connect manually to the individual RedPitayas via the command line with 
        "ssh root@ADDR" using the password "root" (alternatively, use Putty).
        Then, on the RedPitaya, run python3 /home/jupyter/RedPitaya/RunLock.py". 
    2) use the command "Lock.connect(RP)" for the individual RedPitayas, where  
        RP denotes the key in the above defined dictionary, or simply use
        "Lock.connect_all()" to automatically start the servers on all devices listed
        in the Lock object.

method 1) will allow to monitor any commmand line outputs on the RedPitayas CPU.

After that, the STCL can be initialized using "Lock.start()". 
This starts an event_loop for the communication in the background.
    
For this example:
"""

Lock.connect_all()
Lock.start()

#%%
"""
Now you are able to communicate with the redpitayas! to send commands, use

    Lock.send(RP, COMMAND)

where COMMAND denotes a string which is recognized on the redpitayas. For locking,
most commands do not have to be sent manually like this. For that, specific functions
have been written. 

For example, the cavity signal can be scanned and displayed with the scanning as follwos:
"""

Lock.show_current('Cav')

#%%
"""
!!!
Data acquisition on all other redpitayas (Lock.show_current(RP) or Lock.acquire(RP)),
that do NOT scan the cavity ('lock', 'monitor') require that the cavity is
repeatedly scanned. To start such a scan, use

    Lock.start_scan('Cav')

!!!
With that in mind, one can monitor the cavity signal using the following commands:
"""

Lock.start_scan('Cav')
Lock.start_monitor('Mon')

"""
Now, a window should appear with an updating cavity signal. The monitoring can be
clsoed with the command 'Lock.stop_monitor('Mon'), or using the upper right 'x'
of the window. With this as reference, the cavity scan offset and gain can be 
adjusted to fit two resonances reference laser
into the scanned range.

The Lock settings of a RedPitaya RP can be initialized and modified using two commands:
    
    1) changing a single setting directly:
    
            Lock.update_setting(RP, LASER, SETTING, VALUE)
        
        LASER: string. denotes which laser is addressed. the following inputs are possible:
            
            'Master': Only available for a scanning redpitaya (mode = 'scan'). This is used
                    for the cavity stabilization based on the reference laser. For 
                    RedPitayas of mode = 'lock', the setting would correspond to 
                    the key of the scanning redpitaya (in this example: 'Cav')
                    
            'Slave1' or 'Slave2': Only available for laser locking redpitayas (mode = 'lock').
                    The number (1 or 2) denotes the output of the redpitaya, which is
                    providing the feedback for the locked laser!
        
        SETTING: string. The following settings are the most relevant for the lock:
            'range': list. The region in the scan, where the the cavity resonance 
                    shall be detected. for reference (Master), two ranges must be given
                    (e.g. [[0.1,0.4], [1.7, 2.0]]). values in ms, as on the xaxis.
                    for Slave1 or Slave2, something like [0.5, 0.8] is expected.
            
            'lockpoint': float. The time value [ms] in the cavity signal, to which 
                    the resonance position should be moved by the lock. This information
                    is converted to relative distances to the reference peak
                    on the redpitaya. Should be in the range.
            
            'PID': dict. contains the parameters of the PID which generates the feedback.
                    this dictionary contains the following items:
                        'P': proportional gain
                        'I': Integral gain
                        'D': derivative gain
                        'limit': list of two values that serve as extremes of the 
                                desired feedback (default: maximum range [-1,1] --> between -1 and +1 V output possible)
                                
            'enabled': boolean. Controls whether the lock is enabled for the specific
                        laser or not. For 'Master', this should always be True.
                        For Slave1 and Slave2, this can be used to toggle the lock on
                        and off.
                                
    2) modifying the respective settings file (RP.json) directly. This is useful when changing
        multiple settings at once. To apply changes, use 
        
            Lock.update_settings(RP)
            
    Both of these methods should be applicable during the lock. Method 1) is the safer method.
    
for example:
"""

Lock.update_setting('Cav', 'Master', 'range', [[0.1,0.4],[1.7, 2.0]])
Lock.update_setting('Cav', 'Master', 'lockpoint', 1.8)

Lock.update_setting('Lock1', 'Slave1', 'enagbled', True)
Lock.update_setting('Lock1', 'Slave1', 'range', [0.5, 0.8])
Lock.update_setting('Lock1', 'Slave1', 'lockpoint', 0.6)


#%%

"""
Now that the settings are chosen appropriately, one can start the actual locking!

First, the cavity is stabilized! To start the cavity lock, the scan should be interrupted first:
"""

Lock.stop_loop('Cav')

#%%

"""
This will halt the monitoring until the scan is restarted or the lock is started.
Now to lock the cavity, simply call:

"""
Lock.start_lock('Cav')

#%%

"""
If the lock is succesful, the refrence peaks should travel to the chosen 
lockpoint. If that is the case, and the resonances are still in their respective
ranges, the laser lock can be enabled:
"""

Lock.start_lock('Lock1')


#%%
"""
Now the laser should be locked! To interrrupt this, use
"""

Lock.stop_loop('Lock1')

"""
The very same syntax is used to stop any lock as well as the cavity scan.
"""

#%%

"""
Monitoring the cavity signal might use some resoureces of the PC. A more efficient way
to monitor the Lock during the operation would be to just monitor the error signals.
This is done as follows:
    
    IF THE MONITOR FREEZES just stop and restart the monitor twice!
"""

Lock.stop_monitor('Mon') # stop the cavity monitor if it is still running
Lock.start_error_monitor('Mon', tmin = 30e-3) 
# the keyword argument can be used to tune the timeintervalls at which data is requested from the redpitaya! Default at tmin = 10e-3


#%%

"""
The whole lock and communication can be closed with one command:
"""

Lock.close()

"""
This should stop any locks, monitors and scans and also disconnect any communication with
The redpitayas. If the latter is not the case, manually interrupt the python script if
the communication was started manually using ssh. Otherwise, power the redpitaya off and on again.
"""

#%%

"""
During debugging, sometimes something occured during startup of the lock.
This is something that is not expected to happen. But if something like that might happen 
and "Lock.start_lock('RP')" does not work again, then try the following steps:

    Lock.RPs['RP'].lsock = None # listening server, if it is not properly closed
    Lock.RPs['RP'].loop_running = False
    
Rebooting the respective redpitaya or canceling and restarting the respective communication
might also be required.
"""
