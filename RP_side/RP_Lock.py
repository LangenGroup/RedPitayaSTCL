# -*- coding: utf-8 -*-
"""
Created on Thu May 12 17:17:08 2022

@author: epultinevicius
"""

from redpitaya.overlay.mercury import mercury as overlay
import socket, selectors, traceback, libserver
import numpy as np
from time import perf_counter, sleep
from peak_finders import SG_array, peak_finders
from copy import deepcopy

class Receiver:
    def __init__(self, addr, action_dict = {}):
        self.sel = selectors.DefaultSelector() 
        self.addr = addr
        self.action_dict = action_dict
        self.iteration = None
    
    def accept_wrapper(self, sock, stop = True):
        '''
        a small wrapper to call whenever a command is received. The message
        class then handles the rest according to the 

        Parameters
        ----------
        sock : socket
            the socket which the communication relies on.
        '''
        
        conn, addr = sock.accept()  # Should be ready to read
        #print("Accepted connection from {}".format(addr))
        conn.setblocking(False) # non-blocking, to keep the lock running!
        #print(conn)
        message = libserver.Message(self.sel, conn, addr, action_dict = self.action_dict, stop = stop) # initialize the message object
        self.sel.register(conn, selectors.EVENT_READ, data=message) # register in selector
    
    def setup_server(self, loop = False):
        '''
        Starts the socket connection and initializes the event loop. During that
        loop, commands are avaited. Those are strings which may include actions
        with values that can be queried to the called functions. 

        Returns
        -------
        None.

        '''
        self.sel = selectors.DefaultSelector() # reinitialize the selector!
        # setup the socket to listen to external commands!
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # IPv4 TCP socket
        # Avoid bind() exception: OSError: [Errno 48] Address already in use
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        self.sock.bind(self.addr)
        self.sock.listen()
        print("Listening on {}".format(self.addr))
        self.loop = loop
        # start by accepting a socket connection! Even though we are using selectors,
        # we only deal with one connection at a time! The communication framework
        # in the message class is used to cleanly deal with the messaging.
        if loop:
            print('waiting to accept socket ...')
            self.accept_wrapper(self.sock, stop = False)
            self.sock.setblocking(False) # avoid blocking while waiting for commands
        else:
            self.sock.setblocking(False) # avoid blocking while waiting for commands
            self.sel.register(self.sock, selectors.EVENT_READ, data=None)
        self.server_running = True
        
    def start_server(self):
        # start the actual event loop!
        try:
            while self.server_running:
                #print('hi')
                sleep(1e-4)
                # if defined, run the iteration!
                if self.iteration != None:
                    self.iteration()
                if self.loop:
                    events = self.sel.select(timeout=1e-4) # check the handled socket connections
                else:
                    events = self.sel.select(timeout=None)
                for key, mask in events:
                    if (not self.loop) and (key.data == None):
                        self.accept_wrapper(key.fileobj)
                    else:
                        message = key.data
                        try:
                            message.process_events(mask) # initially: event = read --> await command. if command read out, carry out command and write response!
                        except Exception:
                            print(
                                "Main: Error: Exception for {}:\n {}".format(message.addr, traceback.format_exc())
                                )
                            message.close()
        
        except Exception as e:
            print(str(e)+"Caught keyboard interrupt, exiting")
        finally:
            self.sel.close()

    def stop(self, query): 
        # Some functions might take arguments, so by definition an argument is expected for all functions.
        # set boolean variable to False to stop server loop
        self.server_running = False
        self.sock.close()
        return 'Stopped!'

class reaction_loop(Receiver): #### USE THIS FOR THE LOCKING LOOP

    def __init__(self, addr):
        
        action_dict = {
            'stop' : self.stop, #By default, stop function must be provided!
            }
        Receiver.__init__(self, addr, action_dict = action_dict)
        self.iteration = None  # to be defined in children class
        self.var_dict = {} # a dictionary of variables (?)
        self.r_buff = '' # read buffer
        self.setup = None # optional setup function, set to None initially
        #dont start immediatley!        
    
    def start_loop(self):
        print('starting loop')
        self.setup_server(loop = True)
        print('server connection established! Calling loop setup!')
        # call the setup prior to starting the event loop, if defined
        if self.setup != None:
            self.setup()
        print('finished setup, starting server!')
        # start the event loop!
        self.start_server()

class RP_Server(Receiver): # handles socket communication from redpitaya side
    def __init__(self, host, port, port2, RP_mode = 'scan'):

        Receiver.__init__(self, (host, port)) # initialize the receiver which handles the event_loop
        if RP_mode == 'monitor':
            self.RP_mode = 'lock'
        else:
            self.RP_mode = RP_mode
        self.lock = RP_Lock((host, port2), mode = RP_mode)
        self.action_dict = {
            "acquire": self.action_acquire,
            "acquire_ch": self.action_acquire_ch,
            "echo": self.action_echo,
            "count": self.action_count,
            "close": self.action_close,
            "acquire_ch_n" :self.action_acquire_ch_n,
            "monitor": self.action_monitor,
            "acquire_peaks_ch": self.action_acquire_peaks_ch,
            "update_settings": self.action_update_settings,
            "start_lock": self.action_start_lock,
            "start_lock2": self.action_start_lock,
            "start_lock3": self.action_start_lock,
            "test": self.action_test,
            "set": self.action_set,
            "stop": self.stop,
            "set_dec": self.action_set_dec,
            "acquire_errs": self.action_acquire_errs,
            "set_peakfinder": self.action_set_peakfinder,
        }
            
    def action_set(self, query):
        query_list = query.split('|') # query contains to strings split by |
        mod = query_list[0]
        value = query_list[1]
    
    def action_set_dec(self, query):
        self.lock.set_dec(query)
        print('Set decimation to {}'.format(query))
        return 'Set decimation to {}'.format(query)
    
    def action_test(self, query): # has been used for testing timings
        times = []
        range = [0, 8000]
        for i in range(1000):
            dat = self.lock.acquire_ch(0)
            t0 = perf_counter()
            #np.argmax(dat[:8000])
            x,y = dat[range[0]:range[-1]], dat[range[0]:range[-1]]
            t1 = perf_counter()-t0
            times.append(t1)
        return times
    
    def action_update_settings(self, query):
        self.lock.update_settings(query)
        return 'Lock settings updated!'
    
    def action_start_lock(self, query):
        if self.RP_mode in ['scan', 'lock']:
            print('starting lock!')
            self.lock.start() # starts the lock --> after that method is done, the lock is finished
            # the below code is exectued after the lock is finished!
            print("lock stopped")
            for key, val in self.lock.settings.items(): # reset all PIDs
                val['PID'].reset()
            print("PIDs reset")
            self.lock.gen_ramp.offset = 0.0 # reset out1 offset to 0
            if self.RP_mode == 'lock':
                self.lock.gen_trig.offset = 0.0 # for laser lock only reset offset of out2 to 0
            print("outputs reset")
            return 'Done!'
        
    def action_close(self, query):
        self.server_running = False
        self.sock.close()
        print('closed!')
        return 'closed!'
    
    def action_echo(self, query):
        print("{}".format(query))
        return "{}".format(query)
    
    def action_count(self, query): # testing purpose
        answer = "\n"
        try:
            for i in range(int(query)):
                answer += str(i+1)
                if i < int(query) -1:
                    answer += '\n'
        except:
            answer = "Error: {} is not an integer!".format(query)
        return answer
    
    def action_acquire(self, query):
        print('Hi!')
        self.lock.acquire()
        data = self.lock.acquisition
        return data.tolist()

    def action_acquire_ch(self, query): # this is used to monitor the cavity signal
        ch = int(query)
        data = self.lock.acquire_ch(ch)
        duration = self.lock.times[-1] # instead of the full time trace, just give the last time value! the first one is always 0 and the number of data points is always the same
        return [duration, data.tolist()] 

    def action_acquire_ch_n(self, query):
        dat_list = []
        ch, n = int(query[0]), int(query[2:]) # syntax example: query =  '1|100' for 100 traces on ch1 (in2)
        if n <= 100:
            pass
        else:
            print('max 100 data sets!')
            n = 100
        t0 = perf_counter()
        for i in range(n):
            dat_list.append(self.lock.acquire_ch(ch))
        print(perf_counter()-t0)
        dat_arr = np.stack(dat_list, axis = 0)
        #return dat_list
        return dat_arr.tolist()
    
    def action_acquire_peaks_ch(self, query):
        # acquire the peak on a certain channel --> range must be given in query!
        # split the query in order to obtain ch, ranges(range from R1 to R2)
        query_list = query.split('|') # seperator: '|'
        ch = int(query_list[0])
        acq = self.lock.acquire_ch(ch) # obtain data trace
        peaks = []
        # Remaining query may contain a bunch of ranges --> two indices separated by ','
        for R in query_list[1:]: # iterate through each range string
            R1, R2 = R.split(',')
            try:
                P, FWHM = self.lock.acquire_peaks([int(R1), int(R2)]) # retrieve the peak
                peaks.append(P[0])
            except:
                peaks.append(None)
        return peaks # return the list of peaks!
        
    def action_acquire_errs(self, query):
        if self.lock.FSR_ref == None:
            self.lock.init_FSR_ref() # first, save the FSR for proper error calculation!
        self.lock.update_pos()
        if self.lock.skipped:
            return 'skipped'
        else:
            for key in self.lock.settings:
                self.lock.update_err(key)
            return self.lock.errs
    
    def action_set_peakfinder(self, query):
        # query is a dictionary
        name = query.pop('name')
        self.peak_finder = name
        if name[:2] == 'SG': # if savitzky golay filter is involved
            self.SG_m = SG_array(**query) # calculate conv. matrix
        return 'updated peakfinder {fname}'.format(fname=name)

    def action_monitor(self, query):
        addr = (self.addr[0], 5065)
        rl = reaction_loop(addr)
        rl.var_dict['dat_list'] = []
        rl.var_dict['i'] = 0
        rl.var_dict['j'] = 0
        rl.var_dict['settings'] = {}
        rl.var_dict2 = {}
        rl.var_dict2['j'] = 0
        t0 = perf_counter()
        i = 0
        def give(q):
            print('giving data')
            rl.var_dict['dat_list'].append(self.lock.acquisition)
            return 'giving data!'
        
        def update_settings(settings): 
            for key, val_dict in settings.items():              #iterate through the lasers
                
                if key not in rl.var_dict['settings'].keys():
                    rl.var_dict['settings'][key] = {}     # if settings dont exist yet, initialize dictionary
                for val_key, val_val in val_dict.items():       #iterate through the laser-settings
                    
                    if val_key == 'PID':                        #for PIDs, only the gains are sent!
                        pid = PID(**val_val)                    #gains stored in yet another dictionary...
                        rl.var_dict['settings'][key][val_key] = pid
                    else:
                        rl.var_dict['settings'][key][val_key] = val_val   #in each other case, the settings are transferred directly
                print(rl.var_dict['settings'][key])
                if rl.var_dict['settings'][key]['enabled'] == False:
                    rl.var_dict['settings'].pop(key) # if the respective laser lock is not enabled, remove it from the dictionary!
            print('updated settings: {}'.format(rl.var_dict['settings']))
            return 'updated settings!'
        
        def iteration():
            self.lock.acquire_ch(0)
            rl.var_dict['i'] += 1
        
        rl.action_dict['give'] = give
        rl.action_dict['update_settings'] = update_settings
        rl.action_dict["set_dec"] = self.action_set_dec
        rl.iteration = iteration
        rl.start_loop()
        t = perf_counter()-t0
        i = rl.var_dict['i']
        dat_list = rl.var_dict['dat_list']
        print(i, t/i)
        if len(dat_list) > 0: 
            dat_arr = np.stack(dat_list, axis = 0)
            print(dat_arr.shape)
            return dat_arr.tolist() 
        else: 
            return 'Done'   #self.lock.acquisition.tolist()

class PID:
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
            # check, whether PID output is within limits. 
            self.check_limit()
            self.e_prev, self.t_prev = e, t
    def reset(self):
        self.I_val = self.start
        self.MV = self.start
        self.e_prev, self.t_prev = None, None

class RP: # handles the functionality of the redpitaya
    def __init__(self, mode = 'scan'):
        # SETUP HARDWARE
        fpga = overlay() # established 'connection' with hardware
        self.osc = [fpga.osc(ch, 1.0) for ch in range(2)]
        self.gen_ramp = fpga.gen(1)
        self.gen_trig = fpga.gen(0)
        self.GPIO = fpga.gpio
        
        # configure gpio
        self.ext_trig1 = self.GPIO('p', 0, 'in') # use pin DIO0_p (EXT TRIG.) for output1
        self.ext_trig2 = self.GPIO('n', 0, 'in') # use pint DIO0_n for oiutput2
        
        self.sync_src = fpga.sync_src
        self.trig_src = fpga.trig_src
        
        N_osc = self.osc[0].buffer_size
        N_gen = self.gen_ramp.buffer_size
        dec = int(2**4)
        triangle = self.gen_ramp.sawtooth()
        square = self.gen_trig.square()
        
        self.N = N_osc
        dur = self.duration(dec) #duration in seconds
        self.times = np.linspace(0, dur-(8e-9*dec), self.N)*1e3 # in ms
        
        self.osc_kwargs = dict(
            decimation = dec,
            length = N_osc,
            trigger_pre = 0,
            trigger_post = N_osc,
            sync_src = self.sync_src['gen1'], 
            trig_src = 0
        )
        
        self.gen_ramp_kwargs = dict(
            waveform = triangle,
            amplitude = 0.5,
            offset = 0,
            enable = True,
            mode = 'BURST',
            burst_data_repetitions = int(2*dec), # basically the decimation of the signal
            burst_data_length = int(N_gen), #how much of the signals buffer should be used for the burst?
            burst_period_length = int(2*dec)*N_gen, # the full length of a period of the signal
            burst_period_number = 1, # only one ramp at a time.
        )
        
        self.gen_trig_kwargs = deepcopy(self.gen_ramp_kwargs)
        self.gen_trig_kwargs['burst_data_repetitions'] = int(2*dec)
        self.gen_trig_kwargs['burst_data_length'] = int(N_gen)
        self.gen_trig_kwargs['burst_period_length'] = int(2*dec)*N_gen
        self.gen_trig_kwargs['burst_period_number'] = 1
        
        self.gen_dc_kwargs = dict(
            waveform = triangle,
            amplitude = 0,
            offset = 0,
            enable = True,
            mode = 'PERIODIC',
        )
        
        for ch in range(2):
            self.set_osc_ch(ch, **self.osc_kwargs)
            self.set_osc_ch(ch, sync_src = self.sync_src['osc1'], trig_src = self.trig_src['osc1']) # set synchronysation to ch 2! The square wave goes in here!
            self.osc[ch].start()
        self.set_osc_ch(1, level = [-0.1,0.1], edge = 'pos')  # trigger settings!
        self.mode = mode
        
        if self.mode == 'scan': # Cavity lock only
            # setup trigger square wave on out 1
            self.set_mod(self.gen_trig, **self.gen_trig_kwargs)        
            self.set_mod(self.gen_trig, sync_src = self.sync_src['gen1'], waveform = square, offset = 0.0, amplitude = 0.9) # overwrite waveform to set a square wave signal
            self.set_mod(self.gen_ramp, **self.gen_ramp_kwargs) # setup cavity scan ramp on out2
        
        elif self.mode == 'lock':
            self.set_mod(self.gen_trig, **self.gen_dc_kwargs) # setup a dc signal on out1 for laser locking
            self.set_mod(self.gen_ramp, **self.gen_dc_kwargs) # setup a dc signal on out2 for laser locking
            self.gen_trig.start_trigger()
            self.gen_ramp.start_trigger()
        self.trigger_armed = False
    
    def duration(self, dec):
        return 8e-9 * self.N * dec # duration in seconds

    def set_dec(self, dec):
        kwargs = dict(
            burst_data_repetitions = int(2*dec), # basically the decimation of the signal
            burst_period_length = int(2*dec)*self.N, # the full length of a period of the signal
        )
        # set awg decimation
        if self.mode == 'scan':
            self.set_mod(self.gen_ramp, **kwargs)
            self.set_mod(self.gen_trig, **kwargs)
        # set oscilloscope decimation
        for ch in range(2):
            self.set_osc_ch(ch, decimation=dec)
        dur = self.duration(dec)
        self.times = np.linspace(0, dur-(8e-9*dec), self.N)*1e3
        
    def set_mod(self, mod, **kwargs): # set module!
        for key, value in kwargs.items():
            setattr(mod, key, value)

    def set_osc_ch(self,ch,**kwargs):
        self.set_mod(self.osc[ch], **kwargs)
    
    def trigger(self):
        if not self.trigger_armed:
            self.osc[1].reset()
            self.osc[1].start()
        if self.mode == 'scan':
            self.gen_ramp.reset()
            self.gen_ramp.start_trigger()
            
        while (self.osc[1].status_run()): pass
        
    ##################### acquisition functions ###############################
    
    def acquire(self):
        self.trigger()
        ch1 = self.osc[0].data(self.N)
        ch2 = self.osc[1].data(self.N)
        self.osc[1].reset()
        self.osc[1].start()
        #if self.times[-1] > 60: # if decimation roughly >= 2**9
        #    sleep(self.times[-1]*1e-3 * 1.2)
        self.trigger_armed = True
        self.acquisition = np.array([self.times, ch1, ch2])
        return self.acquisition
        
    def acquire_ch(self, ch):
        self.trigger()
        dat = self.osc[ch].data(int(self.N))
        self.osc[1].reset()
        self.osc[1].start()
        #if self.times[-1] > 60: # if decimation roughly >= 2**9
        #    sleep(self.times[-1]*1e-3 * 1.2)
        self.trigger_armed = True
        #self.acquisition = np.array([self.times, dat])
        return dat
    
    def close(self):
        for ch in range(2):
            del self.osc[ch]
        del self.gen_ramp
        del self.gen_laser
        
class RP_Lock(RP, reaction_loop):
    def __init__(self, addr, mode = 'lock'):
        RP.__init__(self, mode = mode)
        reaction_loop.__init__(self, (addr[0], 5065))
        
        self.action_dict['update_settings'] = self.update_settings
        self.ch = 0 #the channel detecting the cavity transmission
        self.Master_pos = 1.75 # will be initialized when the loop starts with the initial Peak position!
        # all of the methods iterate through this dict, so if its empty nothing should happen
        self.settings = {}
        # settings attribute will/must be loaded from the client side!
        # for that purpose the update_settings method is implemented
        self.t0 = perf_counter()
        self.t = 0
        self.iter_num = 0
        self.errs = dict()
        self.iteration = self.loop_iter
        self.setup = self.setup_lock
        self.mode = mode
        self.FSR_ref = None
        # This resets the outputs
        self.gen_trig.reset()
        self.gen_trig.start_trigger()
        self.gen_ramp.reset()
        self.gen_ramp.start_trigger()        
        self.feedback = True # a boolean used to filter out sudden peak jumps detected due to unexpected events in the system (such as trigger jumps etc.)
        # peak_finding stuff
        self.skipped = False
    
    def update_settings(self, settings): 
        for key, val_dict in settings.items():              #iterate through the lasers
            if key not in self.settings.keys():
                self.settings[key] = {}     # if settings dont exist yet, initialize dictionary
            if key == 'Master':
                self.Master_pos = val_dict['lockpoint']
                if self.mode == 'scan':
                    self.settings[key]['gen'] = self.gen_ramp   # if this is the cavity lock, then use output2 for master --> ramp offset!
            elif key == 'Slave1' and self.mode == 'lock':
                self.settings[key]['gen'] = self.gen_trig # Slave1 locked by Output1 
            elif key == 'Slave2'  and self.mode == 'lock':
                self.settings[key]['gen'] = self.gen_ramp # Slave2 locked by output2
            self.settings[key]['sign'] = +1 # use a default sign for the feedback.
            if key not in self.errs:
                self.errs[key] = 0
            for val_key, val_val in val_dict.items():       #iterate through the laser-settings
                if val_key == 'PID':                        #for PIDs, only the gains are sent!
                    self.update_PID(key, val_val)
                else:
                    self.settings[key][val_key] = val_val   #in each other case, the settings are transferred directly
                if val_key == 'peak_finder':
                    self.update_peak_finder(key, val_val)
            if self.settings[key]['enabled'] == False:
                # reset the output when disabling the lock!
                if key == 'Slave1':
                    self.gen_trig.offset = 0.0
                elif key == 'Slave2':
                    self.gen_ramp.offset = 0.0
                self.settings.pop(key) # if the respective laser lock is not enabled, remove it from the dictionary!
                self.errs.pop(key)
        #print('update settings: {}'.format(self.settings))
        return 'Updated lock setting!'
    
    def update_peak_finder(self, laser, values):
        name = values.pop('name') # remove name from peak_finder settings
        if name[:2] == 'SG': # if savitzky golay filter is involved
            self.settings[laser]['SG_m'] = SG_array(**values) # calculate conv. matrix
        self.settings[laser]['peak_finder'] = name
    
    def update_PID(self, laser, val):
        # updates PID with new settings (val) for a certain laser. If lock is already running,
        # only changes the PID gains!
        if 'PID' in self.settings[laser]: # if lock already running, the key is already in the dicitonary    
            val['I_val'] = self.settings[laser]['PID'].I_val # if lock running, keep the current I_val!
        pid = PID(**val)                    #gains stored in yet another dictionary...
        self.settings[laser]['PID'] = pid

    def check_gpio_ext_trig(self):
        val1 = self.ext_trig1.read()
        val2 = self.ext_trig2.read()
        for laser, val in zip(['Slave1', 'Slave2'], [val1, val2]):
            if laser in self.settings:
                self.settings[laser]['PID'].on = val
               
    def update_pos(self):
        '''
        Method to obtain the current peak positions from the cavity
        and write them into the setting dictionary.

        Returns
        -------
        None.

        '''
        try:
            self.update_data()
        except:
            self.skipped = True # something failed, skip point!
            return
        self.skipped = False
        for key in self.settings.keys():     # retrieve current cavity scan
            if key == 'Master':             # readout individual peak positions
                pos = self.data[key][:,1][0] #d- self.Master_pos    # Master is (currently) the only key, where multiple positions are stored!
            else:
                pos = self.data[key][0] - self.data['Master'][:,1][0] #take the relative position!
            # check whether a quick jump occured. This procedure should ignore outliers due to unexpected jumps! locking step ignored with feedback = Flase
            if 'position' in self.settings[key]:
                if np.abs(pos-self.settings[key]['position']) < 20e-3:
                    self.feedback = True
                else: 
                    self.feedback = False
                    print('skipped point!')
            self.settings[key]['position'] = pos
            
            
    def check_sign(self, iters = 100):
        '''
        Method to check whether the pid feedback has correct sign. 
        It runs the step method a number (iters) of iterations and flips the sign,
        if the peak position error increases over that duration.

        Parameters
        ----------
        iters : int, optional
            Number of locking step interations to determine 
            wheter the sign is correct. The default is 50.

        Returns
        -------
        None.

        '''
        for n in range(iters):
            self.step()                                                         # locking step
            if n == 0:
                errs_0 = self.errs                                              # at first step, save the intitial deviation
        for key, val in self.settings.items():
            if key != 'Master':                                                 # exclusion of the master peak, since the sign is always correct.
                if abs(self.errs[key]) - abs(errs_0[key]) >= 5e-3:              # if the error increased by more than 5 MHz, the sign is flipped.
                    val['sign'] = -val['sign']
                    print('Sign for {} flipped!'.format(key))
    
    def setup_lock(self):
        print('setting up lock')
        self.gen_ramp.offset = 0.0
        if self.mode == 'lock':
            self.gen_trig.offset = 0.0 # if laser lock, additionally reset the second output
        for key, val in self.settings.items():
            val['PID'].reset()
        # before starting the lock, do a number of acquire iterations --> steady state of successive cavity scans
        self.init_FSR_ref() # measure the FSR for the Master laser and save the average as attribute. used for error calculation
        # reset the locking stuff
        for key, val in self.settings.items():
            if key == 'Master':
                self.settings[key]['height'] = self.data[key][:,1][1] # readout current height of all peaks and save it
            else:
                self.settings[key]['height'] = self.data[key][1] # readout current height of all peaks and save it
        self.check_sign()
        print('Master_pos:', self.Master_pos)
    
    def init_FSR_ref(self, averages = 20):
        FSRs = []
        for i in range(averages):
            self.update_data()
            FSRs.append(self.FSR)
        self.FSR_ref = np.mean(FSRs)  # this is used to normalize the lockpoint --> average FSR
    
    def update_err(self, laser):
        '''
        calculates the error (deviation of position from lockpoint)

        Parameters
        ----------
        laser : TYPE
            DESCRIPTION.
        setting : TYPE
            DESCRIPTION.
        '''
        s = self.settings[laser]
        if laser == 'Master':    
            err = (s['position'] - s['lockpoint'])/self.FSR     # calculate individual errors
        else: 
            #err = (s['position'] - (s['lockpoint']-self.Master_pos))/self.FSR
            err = s['position']/self.FSR - (s['lockpoint']-self.Master_pos)/self.FSR_ref
        self.errs[laser] = err
      
    def step(self):
        '''
        Method for an individual locking step. During the step, check_positions
        is used to verify that the peaks have sufficient distance to their
        range borders.
        '''
        self.check_gpio_ext_trig()
        self.t = perf_counter()-self.t0
        self.update_pos()                                                       # retrieve current peak positions
        if self.feedback == True:
            for key, val in self.settings.items():
                self.update_err(key)      # calculate individual errors
                val['PID'].update(self.errs[key]*val['sign'], self.t)                          # update the corresponding PID!
                if key == 'Master' and self.mode == 'scan':
                    self.gen_ramp.offset = val['PID'].MV
                elif key != 'Master' and self.mode == 'lock':
                    val['gen'].offset = val['PID'].MV

        elif self.feedback == False:
            return
        #if np.abs(val['gen'].offset) > 0.99:
            #    self.running = False
            #    print('Error: offset limit reached!')
    
    def check_height(self):
        # essentially checks whether there is a peak in the range. checked by height threshhold.
        Bools = []
        for key, val in self.settings.items():
            if key == 'Master':
                h = self.data[key][:,1][1] # current height
            else:
                h = self.data[key][1] # current height
            #print('height', h, val['height'])
            if h < (val['height']*1/5):
                print('Peak {} too low/ dissapeared? out of range?'.format(key))
                Bools.append(False)
            else:
                Bools.append(True)
        return all(Bools)
    
    def check_lockpoints(self):
        '''
        Method for verifying, whether the current lockpoint actually lies in
        the provided range (with some free space of 15MHz). returns a boolean, 
        which can be used for looop break condition.

        Returns
        -------
        Boolean
            True if lockpoints are in the range, False if not.

        '''
        Bools = []
        for key, val in self.settings.items():
            if key == 'Master':    
                range = val['range'][1]
                i0 = self.times[range[0]]
                i1 = self.times[range[1]]
            else: 
                range = val['range']    
                i0 = self.times[range[0]]
                i1 = self.times[range[1]]
            v =  val['lockpoint']
            if not(i0 < v < i1):
                print('Lockpoint {} for {} out of range!'.format(v, key))
                Bools.append(False)
            else:
                Bools.append(True)
        return all(Bools)
    
    def check_positions(self, dmin = 5e-3):
        '''
        Method to check 

        Parameters
        ----------
        dmin : TYPE, optional
            DESCRIPTION. The default is 15e-3.

        Returns
        -------
        TYPE
            DESCRIPTION.

        '''
        
        Bools = []
        for key, val in self.settings.items():
            if key == 'Master':    
                range = val['range'][1]
                i0 = self.times[range[0]]-self.Master_pos
                i1 = self.times[range[1]]-self.Master_pos
            else: 
                range = val['range']
                i0 = self.times[range[0]]-self.Master_pos
                i1 = self.times[range[1]]-self.Master_pos
            pos = val['position']
            
            if (abs(pos-i0) <= dmin) or (abs(pos-i1) <= dmin):
                print('Position {} of {} too close to border!'.format(pos, key))
                Bools.append(False)
            else:
                Bools.append(True)
        return all(Bools)

    def loop_iter(self, *args, **kwargs):
        
        self.step() # make a locking step
        self.iter_num += 1
        
    def start(self, *args, **kwargs):
        self.feedback = True
        self.gen_ramp.offset = 0
        sleep(0.1)
        self.update_data()
        self.Master_pos = self.settings['Master']['lockpoint']                              # Set the zero position of the master laser
        self.iter_num = 0                                                       # starting index of the while loop    
        self.running = self.check_lockpoints()                                  # Set running to True, such that the loop will run!
        print(self.running)
                                                              # initialize error dictionary
        if self.running:
            self.errs = dict()
            self.errs_times = np.array([])
            self.errs_arr = []
            self.t0 = perf_counter()
            self.start_loop()
    
    
    def acquire_peaks(self, laser, r):
        name = self.settings[laser]['peak_finder']
        peak_finder = peak_finders[name]
        if name[:2] == 'SG':    # if savitzky golay filter involved, give the matrix
            m = self.settings[laser]['SG_m']
            return peak_finder(self.times, self.acquisition, r, m = m)
        else:
            return peak_finder(self.times, self.acquisition, r)
    
    def get_peaks(self, laser, setting):
        if laser == 'Master':
            P_l = []
            for r in setting['range']:  # 2 ranges for the master peak --> determination of frequency axis!
                P = self.acquire_peaks(laser, r)
                P_l.append(P)
            return np.stack(P_l, axis = 1)
        else:
            r = setting['range']
            P = self.acquire_peaks(laser, r)
            return P
    
    def update_data(self):
        '''
        Method to obtain the Master and Slave peaks and create data dictionary
        '''
        self.acquisition = self.acquire_ch(self.ch)  #acquire scope data and make a shortcut. only acquire the desired channel!
        self.data = dict()
        for key, val in self.settings.items():
            self.data[key] = self.get_peaks(key, val)
        self.FSR = np.abs(self.data['Master'][:,0][0] - self.data['Master'][:,1][0])