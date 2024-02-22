# -*- coding: utf-8 -*-
"""
Created on Mon Feb 27 10:45:59 2023

@author: epultinevicius
"""

from communication import Sender, RP_connection, Path
import matplotlib

matplotlib.use("Qt5Agg")  # for plotting in another process
import matplotlib.pyplot as plt
import numpy as np
import json
from time import sleep, perf_counter
from general import *
import threading
import multiprocessing as mp
import queue  # for exception handling using multiprocessing.Queue
from copy import deepcopy
import sys
from scipy.constants import golden  # golden ratio
from RP_side.peak_finders import peak_finders, SG_array, SG_filter

window_size = 21
order = 1
order_range = range(order + 1)
half_window = (window_size - 1) // 2

m = SG_array(window_size, order, deriv=1)


def monitor(v, *args):
    m = Monitor(*args, bool_var=v)
    m.start_event_loop()
    m.start_monitor()
    v.value = False  # set monitor running to false after the monitor is finished, in any case!
    return


def monitor_errors(v, *args, **kwargs):
    m = ErrorMonitor(*args, bool_var=v, **kwargs)
    m.start_event_loop()
    m.start_monitor()
    v.value = False
    return


def init_mon_dict():
    d = dict(
        running=mp.Value("i", False),  # use mp.Value for sharing between processes!
        running_err=mp.Value("i", False),  # same but for error monitor process
        queue=mp.Queue(),  # used to communicate to cavity monitor process
        queue_err=mp.Queue(),  # used to communicate to error monitor process
    )
    return d


class LockClient(Sender):
    def __init__(self, redpitayas, FSR=906, DIR=None):
        """
        This class handles the communication to all redpitayas involved in the lock.
        The redpitayas (RP_client objects) are stored in a dictionary, where the
        respective keys are used as a reference to individual devices throughout
        all of the defined methods. The free spectral range of the cavities used
        is used for scaling of monitored error signals, while a directory can be
        provided to store json files with locksettings.

        Parameters
        ----------
        redpitayas : dict
            Contains objects of class RP_client.
        FSR : float, optional
            Free spectral range [MHz] of the cavities used in the system. Only used for
            scaling of monitored errors. The default is 906.
        DIR : string, optional
            directory to save settings files. If None, a default directory from
            the repository is used. The default is None.
        Ext_Scan : bool, optional
            if the transfer cavity is scanned externally (e.g. a function generator),
            then set this variable to True in order to be able to acquire cavity signals.
        """

        if DIR != None:  # if a directory is given, initiate use it for the Sender class
            Sender.__init__(self, DIR=DIR)
        else:  # this is the default. DIR is the directory where the modules are loaded from.
            Sender.__init__(self)
        self.FSR = FSR  # FSR of the used transfer cavity
        self.RPs = (
            redpitayas  # dictionary of RP_client objects with respective settings
        )
        self.masters = []
        self.monitors = dict()
        # load the settings from the respective json files
        for key, val in self.RPs.items():
            val.label = key  # set the key as an attribute for the RP objects!
            val.upload_current()
            if val.mode in ["scan", "ext_scan"]:
                self.masters.append(key)
            elif val.mode == "monitor":
                self.monitors[key] = init_mon_dict()
            filepath = Path(self.DIR, f"{key}.json")
            if filepath.exists():
                with open(filepath, "r") as file:
                    val.settings = json.load(file)
            else:
                self._load_default_settings(key)
            self.save_settings(key)  # afterwards, create a file with these settings!

    def start(self):
        """
        Starts up the LockClient, which includes the event loop and synchronizes
        the decimation settings on all redpitayas. This requires a connection
        on all redpitayas.
        """
        self.start_event_loop()
        # initializing the dec settings
        for m in self.masters:  # initialize the dec settings!
            dec = self.RPs[m].settings["Master"]["dec"]
            self.set_dec(m, dec)

    def close(self):
        """
        Close the LockClient and everything related to it. The order is important here:
         - first, monitors are closed.
         - next, any loops running on redpitayas (mode = lock or monitor) are closed.
         - only then loops running on master redpitayas (mode = scan) are closed,
             since they are triggering the other redpitayas.
         - After all redpitaya loops are stopped, the listening servers on the redpitayas
             are stopped (disconnected)
         - Finally, the event loop used for communication is closed.
        """
        # monitors
        for key, val in self.monitors.items():
            if val["running"].value:
                self.stop_monitor(key)
        # looping redpitayas
        for master_RP in self.masters:
            RPs = self.find_slave_RPs(master_RP)
            # the last entry in that list is the cavity scanning redpitaya, so it is closed last!
            for RP in RPs:
                if self.RPs[RP].loop_running:
                    self.stop_loop(RP)
        for RP in self.RPs:  # disconnect all the redpitayas
            self.disconnect(RP)
        self.stop_event_loop()  # finally, stop the event loop which handles communication!

    ################### Finding stuff ######################################

    def find_master_RP(self, RP):
        """
        Finds the master redpitaya associated with RP

        Parameters
        ----------
        RP : string
            Key of the RedPitaya in question.

        Returns
        -------
        master_RP : string
            Key of the master RedPitaya, which scans the cavity that RP refers to.
        """
        if RP not in self.masters:
            master_RP = self.RPs[RP].settings["Master"]
        else:
            master_RP = RP
        return master_RP

    def find_monitor_RP(self, RP):
        """
        Find the monitor redpitaya that watches the cavity associated with RP.

        Parameters
        ----------
        RP : string
            Key of the RedPitaya in question.

        Returns
        -------
        monitor_RP : string
            Key of the RedPitaya which monitors the cavity that RP refers to.
        """

        master_RP = self.find_master_RP(RP)
        slaves = self.find_slave_RPs(master_RP)
        for key in slaves:
            if key in self.monitors:
                return key

    def find_slave_RPs(self, master_RP):
        """
        Finds all slave RPs that are associated with the master_RP.
        --> redpitayas that are working with the same cavity given by master_RP

        Parameters
        ----------
        master_RP : string
            Key of the RedPitaya in question.

        Returns
        -------
        RPs : list of strings
            Keys of the laserlocking RedPitayas, which refer to the cavity of master_RP
        """

        RPs = []
        for key, val in self.RPs.items():
            if val.settings["Master"] == master_RP and val.mode in ["lock", "monitor"]:
                RPs.append(key)
        RPs.append(
            master_RP
        )  # add the master_RP, since it is also associated with the same cavity. its the last entry.
        return RPs

    ################# decorators #######################################

    def _apply_to_monitor(func):
        # decorator for functions that change something visible on the cavity monitor
        def inner(self, RP, *args, **kwargs):
            result = func(
                self, RP, *args, **kwargs
            )  # call the function first! --> settings are changed
            # afterwards, the settings are sent to the monitor
            self.set_monitor(RP)
            return result

        return inner

    def _check_cavity_scanned(func):
        # another decorator, used to check if acquisition is possible! --> is cavity scanned/ redpitaya triggered?
        def inner(
            self, RP, *args, **kwargs
        ):  # IMPORTANT: at least RP as argument is expected!
            if self.check_cavity_scanned(RP):
                return func(
                    self, RP, *args, **kwargs
                )  # output of the function shall be returned!
            else:
                # usually an array is expected as output. If no acquisition is possible, an empty array is returned.
                return np.array([])

        return inner

    def _check_for_loop(func):
        # checks if a loop is already running before starting a new one.
        def inner(
            self, RP, *args, **kwargs
        ):  # IMPORTANT: at least RP as argument is expected!
            if self.RPs[RP].loop_running:
                print(
                    f"Loop currently running on {RP}! Stop it before running this function!"
                )
                return np.array([])
            else:
                return func(self, RP, *args, **kwargs)

        return inner

    def check_cavity_scanned(self, RP):
        """
        used to check if the cavity associated with RP is currently scanned.
        If not, then this means that it is not triggered, and no response would arrive,
        blocking the entire script...
        """
        master = self.RPs[RP].settings["Master"]
        if (
            type(master) == str
        ):  # if not master RP, then check if cavity is scanned first!
            if self.RPs[master].loop_running or self.RPs[master].mode == "ext_scan":
                return True
            else:
                print(f"No scanning loop running on {master}!")
                return False
        else:  # if RP is the master, then it scans the cavity itself!
            return True

    def check_new_settings(self, RP, laser, key, val):
        """
        Used when updating settings.
        Checks if the new settings are valid.

        Parameters
        ----------
        see documentation for 'update_setting'

        Returns
        -------
        bool
            True if the new setting is valid, False otherwise.

        """
        if key == "range":
            if not check_range(laser, val, self.get_current_dec(RP)):
                print(
                    f"range {val} will not work! pay attention to the order and limits!"
                )
                return False
            else:  # if range is fine, also adjust the lockpoint if necessary!
                print("check if lockpoint is still fine")
                return self.new_range_new_lp(RP, laser, val)
        if key == "lockpoint":
            R = self.RPs[RP].settings[laser]["range"]
            if not check_lockpoint(laser, R, val):
                print(
                    f"lockpoint {val} is not valid. Either not float or outside of range {R}! (second range for Master!)"
                )
                return False
        if key == "enabled":
            if not type(val) == bool:
                print(f"{key} has to be of type bool!")
                return False
        if key == "PID":
            if not type(val) == dict:
                print(f"{key} has to be a dictionary!")
                return False
            else:
                return check_PID(val)
        else:
            return True

    def check_range_contains_lp(self, RP, laser, R):
        """
        Used when updating 'range' setting.
        Checks whether the new range contains the old lockpoint.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        laser : str
            Key of the Output/Laser in question.
            For scanning RPs: 'Master'
            For laser locking RPs: 'Slave1' or 'Slave2' for outputs 1 or 2 respectively
        R : list
            New range setting.

        Returns
        -------
        bool
            True if the new setting is valid, False otherwise.

        """
        # checks whether the new range setting R includes lockpoint
        lp = self.RPs[RP].settings[laser]["lockpoint"]
        if laser == "Master":
            r = R[1]
        else:
            r = R
        return r[0] < lp < r[1]

    def new_range_new_lp(self, RP, laser, R):
        """
        Used when updating 'range' setting.
        If the new range setting does not contain the old lockpoint, this method
        allows for the choice of a new lockpoint.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        laser : str
            Key of the Output/Laser in question.
            For scanning RPs: 'Master'
            For laser locking RPs: 'Slave1' or 'Slave2' for outputs 1 or 2 respectively
        R : list
            New range setting.

        Returns
        -------
        bool
            True if the new lockpoint is valid, False otherwise.

        """
        # if new range does not include the lockpoint, the lockpoint lp can be set to a new value
        if not self.check_range_contains_lp(RP, laser, R):
            query = input(
                f"range {R} does not contain the current lockpoint. If this is intended, input new lockpoint here (non-valid value to cancel):\n"
            )
            if check_lockpoint(
                laser, R, float(query)
            ):  # if valid lockpoint is chosen, apply it.
                self.RPs[RP].settings[laser]["lockpoint"] = float(query)
                return True
            else:
                print(f"canceling...")
                return False
        else:
            return True

    def _check_update_setting(func):
        # decorator specificly for update_setting!
        def inner(self, RP, laser, key, val):
            if (
                laser not in self.RPs[RP].settings
            ):  # do not accidently add another output to the redpitaya!
                print(f"There is no laser {laser} in the settings!")
                return
            elif type(self.RPs[RP].settings[laser]) == dict:
                if (
                    key not in self.RPs[RP].settings[laser]
                ):  # do not accidently add another setting!
                    var = input(f"{key} does not exist in settings! Add it? (y/n)")
                    if var == 'y':
                        pass
                    else:
                        print(f'{key} not added.')
                        return
            if laser == 'Master' and not (RP in self.masters):
                print("Master settings can not be changed with this command for a non-scanning RP. If you want to change the scanning cavity, use the method 'change_cavity'")
                return

            if not self.check_new_settings(RP, laser, key, val):
                return
            return func(
                self, RP, laser, key, val
            )  # if every check worked out, finally run the function!

        return inner

    #################### Locking related functions ############################

    def stop_loop(self, RP):
        """
        Stops the loop running on the RedPitaya. This includes lock and scan loops.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.

        """
        # stops any loop
        return self.send(RP, "stop")

    @_check_cavity_scanned
    def start_scan(self, RP):
        """
        starts repetitive scanning of the cavity without any locking.
        Useful for monitoring of the cavity signal before the cavity is stabilized.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya which scans the cavity.
        """
        return self.start_loop(RP, "monitor")

    @_check_for_loop
    def start_loop(self, RP, action):
        """
        Start any kind of loop on the RedPitaya remotely using this command.
        This method runs the sending loop, which awaits a response,
        in the backround using threading.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        action : str
            Name of the action which starts a loop on RP.

        """
        # Start any kind of loop remotely using this command.
        # it runs the sending loop, which awaits a response, in the backround using threading.
        t = threading.Thread(
            target=self.send, args=(RP, action), kwargs=dict(loop_action=True)
        )
        t.daemon = True
        t.start()

    @_check_cavity_scanned  # only start lock if cavity is scanned.
    def start_lock(self, RP):
        """
        Initiate the lock with the current settings on one redpitaya. This
        starts a second host (port 5065) on the redpitaya which can be accessed
        in order to stop the loop!

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        """
        self.update_settings(RP)
        return self.start_loop(RP, "start_lock")

    ##################### settings related functions ###########################

    def _load_default_settings(self, RP):
        """
        Load default settings, if the redpitaya does not yet have any.
        """
        print(
            f"No settings for {RP} found, creating new setting file based on defaults."
        )
        filepath = Path(self.DIR, "Default.json")
        with open(filepath, "r") as file:
            default = json.load(file)
        if self.RPs[RP].mode in ["scan", "ext_scan"]:
            settings = dict(Master=default["Master"])
        else:
            if len(self.masters) > 0:
                default["Master"] = self.masters[
                    0
                ]  # reference the first cavity by default
            else:
                default["Master"] = "Cav"
            print(f"Master set to {default['Master']}")
            settings = default
        self.RPs[RP].settings = settings

    def change_cavity(self, RP, RP_master):
        """
        Update the cavity which the redpitaya RP corresponds to RP_master.
        --> change the master cavity, which the laser corresponds to.
        """
        if RP_master not in self.masters:
            print(f"{RP_master} is not scanning a cavity.")
            return
        if RP not in self.masters:
            self.RPs[RP].settings["Master"] = RP_master

    @_apply_to_monitor  # this is a decorator. see https://www.programiz.com/python-programming/decorator
    def update_settings(self, RP):
        """
        updates all locking settings of one RedPitaya by loading them from the
        corresponding json file.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        """
        RP_ = self.RPs[RP]
        # load the current settings from the json file!
        with open(Path(self.DIR, f"{RP}.json"), "r") as file:
            settings = json.load(file)
        RP_.settings = settings
        # the following sets up the settings as required for the redpitaya
        settings = self.retrieve_settings(RP)
        # then send the settings to the redpiaya
        self.send(RP, "update_settings", value=settings)

    @_check_update_setting
    @_apply_to_monitor
    def update_setting(self, RP, laser, key, val):
        """
        Update a setting of the lock on a RedPitaya. This can be used before as well
        as during the lock, allowing in principle for scans of the laser frequency
        over the whole range.

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        laser : str
            Denotes which laser is addressed. the following inputs are possible:

            'Master': Only available for a scanning redpitaya (mode = 'scan'). This is used
                    for the cavity stabilization based on the reference laser. For
                    RedPitayas of mode = 'lock', the setting would correspond to
                    the key of the scanning redpitaya (in this example: 'Cav')

            'Slave1' or 'Slave2': Only available for laser locking redpitayas (mode = 'lock').
                    The number (1 or 2) denotes the output of the redpitaya, which is
                    providing the feedback for the locked laser!
        key : str
            Key refering to the updated setting. The following settings are
            available:

                'range': region of interest used for peak-detection
                'lockpoint': point in the scan to lock the resonance to
                'enabled': Whether the lock for the respective laser is enabled or not.
                'PID': Settings containing the PID gains and limits for the respective laser.
        val : list, float, bool or dict
            the new value for the setting. Type depends on the setting:
                'range': list (length 2, for 'Master': nested list ).
                    The region in the scan, where the the cavity resonance
                    shall be detected. for reference (Master), two ranges must be given
                    (e.g. [[0.1,0.4], [1.7, 2.0]]). values in ms, as on the xaxis.
                    for Slave1 or Slave2, something like [0.5, 0.8] is expected.
                'lockpoint': float,
                    The time value [ms] in the cavity signal, to which
                    the resonance position should be moved by the lock. This information
                    is converted to relative distances to the reference peak
                    on the redpitaya. Should be in the range.
                'enabled': bool
                'PID': dict,
                    contains the parameters of the PID which generates the feedback.
                    this dictionary contains the following items:

                        'P': proportional gain
                        'I': Integral gain
                        'D': derivative gain
                        'limit': list of two values that serve as extremes of the
                                desired feedback (default: maximum range [-1,1] --> between -1 and +1 V output possible)

        """
        #  updates a specific setting for the lock!
        self.RPs[RP].settings[laser][
            key
        ] = val  # update the setting with the considered value
        self.save_settings(
            RP
        )  # save the updated settings in an external json file for later!
        settings = self.retrieve_settings(RP)
        return self.send(
            RP, "update_settings", value=settings
        )  # then, send the actual settings!

    def save_settings(self, RP):
        """
        Saves all locking settings of one RedPitaya to a json file

        Parameters
        ----------
        RP : str
            Key of the RedPitaya in question.
        """
        with open(
            Path(self.DIR, f"{RP}.json"), "w"
        ) as file:  # the file is called after the RP key!
            json.dump(self.RPs[RP].settings, file, indent=4)

    def retrieve_settings(self, RP):
        """
        Used when sending settings to the RedPitaya. Mainly converts ms values
        in the ranges to indexes.

        Parameters
        ----------
        RP :
            Key of the RedPitaya in question.

        Returns
        -------
        settings : dict
            Lock settings which are generated in such a way, that the
            RedPitayas can properly work with them.

        """
        RP_ = self.RPs[RP]
        if not (RP_.mode in ["scan", "ext_scan"]):
            settings = deepcopy(RP_.settings)
            settings["Master"] = deepcopy(
                self.RPs[RP_.settings["Master"]].settings["Master"]
            )
        else:
            settings = deepcopy(RP_.settings)
        # convert range values from ms to index values, which are used by the redpitaya!
        for key in settings:
            dec = settings["Master"]["dec"]
            if key == "Master":
                R = settings[key]["range"]
                settings[key]["range"] = [
                    [ms2index(x, dec) for x in r] for r in R
                ]  # nested list comprehension
            else:
                R = settings[key]["range"]
                settings[key]["range"] = [ms2index(x, dec) for x in R]
        return settings

    def retrieve_monitor_settings(self, master_RP):
        """
        Retrieves all combined settings of redpitayas associated with  master_RP.
        Usually helpful to collect the settings for the monitor, hence the name of this function.
        """
        settings = {}
        RPs = self.find_slave_RPs(
            master_RP
        )  # collect all redpitayas associated with master_RP
        for key in RPs:  # key: RP identifier
            for val_key, val_val in self.RPs[key].settings.items():
                # val_key: Laser identifier
                # find master settings
                s = deepcopy(self.retrieve_settings(key))[val_key]
                if key in self.masters and val_key == "Master":
                    settings[val_key] = s
                elif (
                    val_key != "Master" and self.RPs[key].mode == "lock"
                ):  # each other case should contain laser locking settings
                    settings[f"{key} : {val_key}"] = s
        return settings

    ###################### DEC / Scan frequency ###############################

    def get_current_dec(self, RP):
        """
        Get the current dec setting for the cavity scan associated with RP
        """
        settings = deepcopy(self.RPs[RP].settings)  # copy of the settings
        for key in settings:
            if (
                key == "Master" and type(settings[key]) != str
            ):  # RP is scanning the cavity
                dec0 = settings[key]["dec"]
            else:
                dec0 = self.RPs[settings["Master"]].settings["Master"][
                    "dec"
                ]  # dec from associated master settings
        return dec0

    def rescale_settings(self, RP, c):
        """
        Scales the settings associated with a scan time axis by a factor. Used
        for updating the dec settings!
        """
        settings = self.RPs[RP].settings
        for key in settings:
            if (
                key == "Master" and type(settings[key]) != str
            ):  # range for master settings
                R = settings[key]["range"]
                settings[key]["range"] = [
                    [x * c for x in r] for r in R
                ]  # nested list comprehension
                settings[key]["lockpoint"] *= c
            elif key != "Master":  # range for slave settings
                R = settings[key]["range"]
                settings[key]["range"] = [x * c for x in R]
                settings[key]["lockpoint"] *= c

    @_apply_to_monitor
    def set_dec(self, master_RP, dec):
        """
        Set the dec setting for redpitayas associated with a specific master RP
        --> adjusts the scan frequency for a specific cavity!
        """
        if not check_dec(dec):
            return
        #  first, find the redpitayas associated with master_RP
        RPs = self.find_slave_RPs(master_RP)
        # then, get the recent dec setting and use it to rescale the relevant settings
        for RP in RPs:
            dec0 = self.get_current_dec(RP)
            self.rescale_settings(RP, dec / dec0)  # adjust the settings accordingly!
        # afterwards, overwrite the setting for the master laser!
        self.RPs[master_RP].settings["Master"]["dec"] = dec
        for RP in RPs:
            self.save_settings(RP)  # finally save all the settings to the json files!
            # ... and send the setting to the redpitayas!
            self.send(RP, "set_dec", value=dec)
        sleep(0.5)  # wait a bit until the decimation on the redpitayas is set up!

    ################ Monitoring related functions ######################
    @_check_for_loop
    @_check_cavity_scanned
    def start_error_monitor(self, RP, tmin=10e-3):
        """
        Starts the error monitoring. Using multiprocessing, an event loop is run
        to repeatedly read out locking errors from the monitoring RedPitaya. These
        are visualized using a repeatedly updated plot.

        Parameters
        ----------
        RP : str
            Key of the monitoring RedPitaya in question.
        tmin : float, optional
            Minimum waiting time for between each step in seconds. Is used to optimize the
            data transfer for this monitoring application. The default is 10e-3.

        """
        if RP in self.monitors:
            mon = self.monitors[RP]
            master_RP = self.find_master_RP(RP)
            settings = self.retrieve_monitor_settings(master_RP)
            print("Starting background process")
            self.p = mp.Process(
                target=monitor_errors,
                args=(mon["running_err"], self.RPs[RP], mon["queue_err"], settings),
                kwargs=dict(FSR=self.FSR, tmin=tmin),
            )
            self.p.daemon = True
            self.p.start()
            print("monitoring process started")

    @_check_for_loop
    @_check_cavity_scanned
    def start_monitor(self, RP):
        """
        Starts the monitoring of the cavity signal. Using multiprocessing,
        an event loop is run to repeatedly read out the cavity signal data from
        the monitoring RedPitaya. The signal is repeatedly updated in a plot.

        Parameters
        ----------
        RP : str
            Key of the monitoring RedPitaya in question.

        """
        if RP in self.monitors:
            mon = self.monitors[RP]
            master_RP = self.find_master_RP(RP)
            settings = self.retrieve_monitor_settings(master_RP)
            print("Starting background process")
            self.p = mp.Process(
                target=monitor,
                args=(mon["running"], self.RPs[RP], mon["queue"], settings),
            )
            self.p.daemon = True
            self.p.start()
            print("monitoring process started")

    def filter_monitor(self, RP, on=True):
        if RP in self.monitors:
            if self.monitors[RP]["running"].value:
                self.monitors[RP]["queue"].put(("filter", on))

    def set_monitor_of_type(self, monitor_RP, Type="cavity"):
        if Type == "cavity":
            queue = self.monitors[monitor_RP]["queue"]
        else:
            queue = self.monitors[monitor_RP]["queue_err"]
        master_RP = self.find_master_RP(monitor_RP)
        settings = self.retrieve_monitor_settings(master_RP)
        queue.put(("settings", settings))

    def set_monitor(self, RP):
        if len(self.monitors) == 0:
            return
        # get monitor settings, which contains all lasers
        monitor_RP = self.find_monitor_RP(RP)
        if monitor_RP is not None:
            if self.monitors[monitor_RP]["running"].value:
                self.set_monitor_of_type(monitor_RP, Type="cavity")
            elif self.monitors[monitor_RP]["running_err"].value:
                self.set_monitor_of_type(monitor_RP, Type="errors")
        else:
            warnings.warn('Tried to set a monitor, but did not find one in the dictionary')

    def stop_monitor(self, RP):
        """
        Stops any monitoring (error_monitor or monitor) on the RedPitaya.

        Parameters
        ----------
        RP : str
            Key of the monitoring RedPitaya in question.

        """
        if RP in self.monitors:
            if self.monitors[RP]["running"].value:
                self.monitors[RP]["queue"].put(("stop", None))
            elif self.monitors[RP]["running_err"].value:
                self.monitors[RP]["queue_err"].put(("stop", None))
        else:
            print("Monitor not running!")

    ############## RP related functions #######################################

    def init_SG_settings(self, RP, laser, **kwargs):
        """
        Checks for mandatory settings for SG-filter based peak finders. If not
        given, default values are taken.
        """
        settings = self.RPs[RP].settings[laser]["peak_finder"]
        if "window_size" not in kwargs:
            kwargs["window_size"] = settings["window_size"]  # use already window size
        elif "order" not in kwargs:
            kwargs["order"] = settings["order"]  # use already used order
        return kwargs

    def set_peakfinder(self, RP, laser, peak_finder, **kwargs):
        """
        Sets up a peakfinder that is used on the redpitaya (RP) for a certain laser during the locking loop.
        The peakfinder is denoted by a string, and if necessary, keyword arguments
        (kwargs) of the respective algorithm can be provided. The following
        peakfinders have been implemented by default on the redpitayas:
            - "maximum" : simply finds the maximum position of the data
            - "SG_deriv" : finds max of raw data, then filters the signal around
                the maximum using a savitzky-golay filter for first order derivative
                and detects the zero-crossing using linear interpolation
            - "SG_maximum" : finds max of raw data, then filters the signal around
                the maximum using a savitzky-golay filter (0th order) and detects
                the maximum again.
        If SG-filter is involved, the following kwargs should be provided:
            - "window_size" : number of data points used for convolution of the signal.
                            Default: 21
            - "order" : polynomial order of the "fit" that is attempted with the filter.
                        An order of 0 with deriv = 0 results in a moving average.
                        For even order derivatives, use even orders. For odd order derivatives, use odd orders.
                        Default: 2 for SG_maximum, 1 for SG_deriv.
            - "deriv" : Order of the derivative that is applied to the data using the filter.
                        Default: 0 for SG_maximum, 1 for SG_deriv. Do not change, this will
                        be applied automatically dependent on the filter.

        The optimal peakfinder may depend on the quality of the cavity signal.
        """

        value = kwargs  # use kwargs dictionary as base
        value["name"] = peak_finder  # add the name to the dict
        if peak_finder[:2] == "SG":
            value = self.init_SG_settings(RP, laser, **value)
        if peak_finder == "SG_deriv":
            value["deriv"] = 1
            if value["order"] < 1:
                value["order"] = 1
        elif peak_finder == "SG_maximum":
            value["deriv"] = 0
            if value["order"] < 0:
                value["order"] = 0
        self.update_setting(RP, laser, "peak_finder", value)  # update the settings!
        # return self.send(RP, 'set_peakfinder', value =  value)

    def show_current(self, RP):
        """
        show the current data on the inputs of redpitaya RP in a plot.

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.
        """
        acq = self.acquire(RP)
        plt.close(RP)
        if acq.size > 0:  # if a list is returned!
            plt.figure(RP)
            plt.plot(acq[0], acq[1], label="Ch1")
            plt.plot(acq[0], acq[2], label="Ch2")
            plt.legend()
            plt.grid()
            plt.xlabel("Time [ms]")
            plt.ylabel("Signal [a.u.]")

    @_check_for_loop
    @_check_cavity_scanned
    def acquire(self, RP):
        """
        collect current data from the inputs on the redpitaya RP

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.

        Returns
        -------
        np.array
            acquired data. Also saved as self.acquisition.

        """
        acquisition = np.array(self.send(RP, "acquire"))
        return acquisition

    @_check_for_loop
    @_check_cavity_scanned
    def acquire_ch_n(self, RP, ch, n):
        """
        collect data from a certain input (ch) on the redpitaya (RP) n times in sequence.
        If n is larger than 100,the redpitaya CPU start having problems to save and transfer the data.
        Thus, the acquisition is split into several sets of max. 100 traces. for n > 100.

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.
        ch : int
            input channel of the redpitaya oscilloscope.
        n : int
            number of subsequent data sets to retrieve from the redpitaya.

        Returns
        -------
        dat : np.array
            data of all the collected traces, concatenated into a single array.

        """
        # acquire n traces on channel ch
        if n > 100:
            # if more than 100 traces, then split this task auch that the redpitaya only saves 100 traces at once!
            dat = np.empty((0, int(2**14)))
            n_remaining = n
            while n_remaining > 0:
                if n_remaining >= 100:
                    action, value = "acquire_ch_n", f"{ch},100"
                else:
                    action, value = "acquire_ch_n", f"{ch},{n_remaining}"
                d = np.array(self.send(RP, action, value=value))
                dat = np.concatenate([dat, d])
                n_remaining -= 100
        else:
            action, value = "acquire_ch_n", f"{ch}, {n}"
            dat = self.send(RP, action, value=value)
        return dat

    ############## communication stuff ###########################

    def send(self, RP, action, value="Hello world!", loop_action=False):
        """
        Sends a message to the respective redpitaya (RP). Messages consist of
        an action that is to be carried out. Some actions also require a value.
        That way, it is possible to send commands to the redpitaya to carry out
        certain tasks!

        Parameters
        ----------
        RP : str
            Key in self.RPs for the respective redpitaya.
        action : str
            defines the action to be carried out on the redpitaya.
            Must be recognized by the code on the redpitaya
        value : str, optional
            defines a value that is queried in combination with the action.
            The default is 'Hello world!'.

        Returns
        -------
        str
            respone from the redpitaya. Depends on the action. If no RP found,
            None is returned.

        """
        if RP in self.RPs:
            if (
                self.RPs[RP].mode == "ext_scan"
            ):  # if external scan, no connection exists!
                return None
            loop = self.RPs[RP].loop_running
            return self.RPs[RP].send(
                self, action, value=value, loop_action=loop_action, loop=loop
            )  # call the respective send method.
        else:
            print(f"{RP} not found.")
            return None

    def connect(self, RP):
        """
        star the host server on an individual redpitaya. This is mandatory in order
        to send messages to the redpitaya. takes up to 5s for the redpitaya to
        load all the required packages.

        Parameters
        ----------
        RP : str
            Key in self.RPs for the respective redpitaya.
        """
        # start the host server on an individual redpitaya
        if RP in self.RPs:
            if not self.RPs[RP].connected:
                print("connecting...")
                self.RPs[RP].start_host_server()
                sleep(5)
            else:
                print(f"{RP} already connected.")
        else:
            print(f"{RP} not found.")

    def connect_all(self):
        """
        Start the host server on all of the redpitayas. This is mandatory
        in order to send messages to the redpitayas! Individual redpitayas take 5s to
        load all the required packages. Because of that, threading is used to
        reduce waiting time.
        """
        print("connecting...")
        for RP in self.RPs:
            t = threading.Thread(
                target=self.RPs[RP].start_host_server, daemon=True
            )  # collect all connection functions in threads
            t.start()
            t.join()  # join the thread such that the main program waits for all redpitayas to connect!
        sleep(
            5
        )  # sleep for 5 seconds while each redpitaya loads the respective libraries.

    def disconnect(self, RP):
        """
        Used to close the socket communication (listening server) on a RedPitaya.

        Parameters
        ----------
        RP : str
            Key in self.RPs for the respective redpitaya.

        """
        # closes the ssh connection
        if self.RPs[RP].connected:
            self.send(RP, "stop")
            self.RPs[RP].connected = False
        else:
            print(f"{RP} not connected.")


######################## Monitoring Classes ###################################


class Monitor(Sender):
    def __init__(self, RP, queue, settings, bool_var=None):
        Sender.__init__(self)
        self.mode = "monitor"
        self.RP = RP
        self.queue = queue
        self._fig = None
        self.settings = settings
        self.monitor_running = bool_var  # a shared boolean variable
        self.filter = False

    ################ Cavity monitoring related functions ######################
    def stop_monitor(self, event):
        self.monitor_running.value = (
            False  # this is used to stop the monitor if figure is closed!
        )

    def start_monitor(self):
        """
        starts the monitoring of the cavity signal on the redpitaya RP.
        If enabled, the peak positions can also be detected in order to check
        how stable the detection scheme works.
        """
        # create a thread to run the monitor in the background
        self.setup_monitor()
        self.monitor_running.value = True
        while self.monitor_running.value:
            sleep(10e-3)
            try:
                query = self.queue.get_nowait()
                if query[0] == "stop":  # stop the monitor!
                    self.stop_monitor(None)
                if query[0] == "settings":  # update the settings of the lock!
                    self.update_settings(query[1])
                if query[0] == "filter":  # toggle filter
                    self.toggle_filter(query[1])
            except queue.Empty:
                pass  # if nothing is in the queue, just repeat the loop!
            self.update_monitor()
        # after the loop has finished, close the monitor!
        self.close()
        # send a message to the main process to notify that the monitor is closed!
        return  # return required for thread to close properly.

    def acquire(self):
        a = self.RP.send(self, "acquire_ch", value="0")
        dur, self.acquisition = a
        self.times = np.linspace(0, dur, 2**14)  # in ms
        # save data in dictionary
        self.data = dict(
            Cavity=np.array([self.times[1:], self.acquisition[1:]]),
        )
        if self.filter:
            self.filter_signals()

    def toggle_filter(self, on=True):
        if on and not self.filter:
            self.filter = True
            self.acquire()
            self.plot_filtered_signals()
        elif not on and self.filter:
            self.filter = False
            self.remove_filtered_signals()

    def filter_signals(self):
        for laser in self.settings:
            kwargs = deepcopy(self.settings[laser]["peak_finder"])
            name = kwargs.pop("name")
            if laser == "Master":
                r = self.settings[laser]["range"][1]
            else:
                r = self.settings[laser]["range"]
            if name[:2] == "SG":
                m = SG_array(**kwargs)
                x, y = self.times[1:], self.acquisition[1:]
                self.data[laser + "filtered"] = SG_filter(x, y, r, m=m)

    def set_monitor_title(self):
        if type(self.settings["Master"]) == str:
            title = f'Cavity Monitor - {self.settings["Master"]}'  # This case is currently never true...
        else:
            title = f"Cavity Monitor - {self.RP.label}"
        self._fig.canvas.manager.set_window_title(title)

    def _decorate_figure(self):
        # an estimate for initial ylims based on the detected signal
        acq = self.data["Cavity"][1]
        ymin = max(acq) - (max(acq) - min(acq)) * 1.2
        ymax = max(acq) - min(acq) * 3 + min(acq)
        self._ax.set_ylim(ymin, ymax)
        self._ax.set_xlabel("Time [ms]")
        self._ax.set_ylabel("Voltage [V]")
        self._ax.grid()

    def _setup_figure(self):
        self._fig, self._ax = plt.subplots(1, 1, figsize=(7 * golden, 7))
        self.set_monitor_title()
        self.acquire()  # acquire the signal once
        self._lines = []
        for key, val in self.data.items():
            l = self._ax.plot(val[0], val[1], label=key)
            self._lines.append(l[0])
        self._decorate_figure()

    def setup_monitor(self):
        """
        sets the monitoring of the cavity signal up. Prepares a corresponding figure.

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.
        peaks : boolean, optional
            whether to detect peaks or not. The default is False.
        """
        # initialize the figure
        self._setup_figure()
        self.plot_settings()  # add ranges and setpoints to the plot (significant details from locksettings)
        self._fig.canvas.draw()  # draw the initial canvas of the figure
        plt.show(
            block=False
        )  # this is required in order to see the figure when using multiprocessing
        # initialize the BlitManager in order to only update the data points in the plot!
        self._bm = BlitManager(self._fig.canvas, animated_artists=self._lines)
        self._fig.canvas.mpl_connect(
            "close_event", self.stop_monitor
        )  # close the monitor whenever the plot is closed!

    def create_label(self, key):
        # create a label for the lockpoint in the plot
        if "label" in self.settings[key]:
            label = f'{self.settings[key]["label"]} | {key}'
        else:
            label = key
        return label

    def plot_filtered_signals(self):
        # adds filtered signals to the plot
        for key, val in self.data.items():
            if key != "Cavity":  # do not replot the actual data!
                l = self._ax.plot(val[0], val[1])[0]
                self._lines.append(l)
                self._bm.add_artist(l)

    def remove_filtered_signals(self):
        # removes filtered signals from the plot
        for j in range(len(self._lines[1:])):
            # 3 steps are used to properly remove all references to the plotted objects
            ref = self._lines[1:].pop(0)
            ref.remove()
            del ref
        for key in self.data:
            if key != "Cavity":
                self.data.pop(key)

    def plot_settings(self):
        self._setrefs = []  # used for collecting line references
        ymin, ymax = self._ax.get_ylim()  # get the current ylim
        xlim = self._ax.get_xlim()
        i = 1  # counting integer used for coloring
        for key, val in self.settings.items():
            if val["enabled"]:
                if key == "Master":
                    c = "k"
                    for R in val[
                        "range"
                    ]:  # indicate ranges using axvspan and setpoints using vlines
                        ref = plt.axvspan(
                            self.times[R[0]], self.times[R[1]], alpha=0.2, facecolor=c
                        )
                        self._setrefs.append(ref)
                else:
                    c = f"C{i}"
                    R = val["range"]
                    ref = plt.axvspan(
                        self.times[R[0]], self.times[R[1]], alpha=0.2, facecolor=c
                    )
                    self._setrefs.append(ref)
                ref = plt.vlines(
                    [val["lockpoint"]], -1, 1, color=c, label=self.create_label(key)
                )
                self._setrefs.append(ref)
                i += 1
        self._ax.set_xlim(xlim)
        self._ax.set_ylim(ymin, ymax)
        self._ax.relim()
        self._ax.legend()
        print("Settings added to plot", flush=True)

    def remove_settings(self):
        # remove significant settings from the plot:
        self._ax.legend().remove()
        for j in range(len(self._setrefs)):
            # 3 steps are used to properly remove all references to the plotted objects
            ref = self._setrefs.pop(0)
            ref.remove()
            del ref

    def reset_background(self):
        # sets a new background for the blitting!
        for l in self._lines:
            l.set_data([], [])  # empty the line data for the background!
        self._fig.canvas.draw()
        self._bm.on_draw(None)  # this should set another background for the plot!
        self.plot_lines()  # replot the lines

    def update_settings(self, settings):
        # update the settings!
        self.acquire()  # obtain new settings (relevant for new time-axis when changing decimation)
        self.settings = (
            settings  # update the settings attribute for the following functions!
        )
        self.remove_settings()  # remove old settings from plot
        self.plot_settings()  # plot the new settings!
        self.reset_background()

    def plot_lines(self):
        # plots the data lines
        for l, d in zip(self._lines, self.data.values()):
            l.set_data(d[0], d[1])
            self._bm.update()

    def update_monitor(self):
        """
        iteration for the monitoring of the cavity signal on a redpitaya RP.

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.
        peaks : boolean, optional
            whether to detect peaks or not. The default is False.
        """
        self.acquire()
        self.plot_lines()

    def close(self):
        self.monitor_running.value = False
        self.stop_event_loop()


class ErrorMonitor(Sender):
    def __init__(self, RP, queue, settings, FSR=906, tmin=10e-3, bool_var=None):
        Sender.__init__(self)
        self.mode = "monitor"
        self.FSR = FSR
        self.tmin = tmin
        self.RP = RP
        self.queue = queue
        self._fig = None
        self.settings = settings
        self.monitor_running = bool_var  # a shared boolean variable

    def stop_monitor(self, event):
        self.monitor_running.value = (
            False  # this is used to stop the monitor if figure is closed!
        )

    def close(self):
        self.monitor_running.value = False
        self.stop_event_loop()

    def start_monitor(self):
        """
        starts the monitoring of the cavity signal on the redpitaya RP.
        If enabled, the peak positions can also be detected in order to check
        how stable the detection scheme works.

        Parameters
        ----------
        RP : str
            Key of the respective redpitaya that is adressed.
        peaks : boolean, optional
            whether to detect peaks or not. The default is False.
        """
        # create a thread to run the monitor in the background
        self.setup_monitor()
        self.monitor_running.value = True
        while self.monitor_running.value:
            try:
                sleep(self.tmin)
                query = self.queue.get_nowait()
                if query[0] == "stop":  # stop the monitor!
                    self.stop_monitor(None)
                if query[0] == "settings":  # update the settings of the lock!
                    self.update_settings(query[1])
                if query[0] == "save":
                    self.save_errors(query[1])
            except queue.Empty:
                pass  # if nothing is in the queue, just repeat the loop!
            self.update_monitor()
        # after the loop has finished, close the monitor!
        self.close()
        # send a message to the main process to notify that the monitor is closed!
        return  # return required for thread to close properly.

    def setup_monitor(self):
        """
        Initializes the figure that is used to monitor the laser frequency deviations.
        """
        self.RP.send(self, "update_settings", self.settings)
        self._setup_figure()
        self._t0 = perf_counter()  # initial timestamp for time axis
        self.times = []  # time axis
        self._fig.canvas.draw()
        plt.show(
            block=False
        )  # this is required in order to see the figure when using multiprocessing
        self._bm = BlitManager(
            self._fig.canvas, animated_artists=list(self._lines.values())
        )  # for blitting only
        self._fig.canvas.mpl_connect(
            "close_event", self.stop_monitor
        )  # close the monitor whenever the plot is closed!

    def _setup_figure(self):
        self._fig, self._ax = plt.subplots(1, 1, figsize=(5 * golden, 5))
        self.set_monitor_title()
        self._lines, self.errs = dict(), dict()
        for key, val in self.settings.items():
            # if val['enabled']: # only if the lock is enabled
            l = self._ax.plot([], [], marker="o", label=key)[0]
            self._lines[key] = l
            self.errs[key] = []
        self._decorate_figure()

    def set_monitor_title(self):
        if type(self.settings["Master"]) == str:
            title = f'Error Monitor - {self.settings["Master"]}'  # This case is currently never true...
        else:
            title = f"Error Monitor - {self.RP.label}"
        self._fig.canvas.manager.set_window_title(title)

    def _decorate_figure(self):
        self._ax.set_ylim([-50, 50])  # error range of +-50 MHz
        self._ax.legend()
        self._ax.grid()
        self._ax.set_ylabel("Error [MHz]")
        self._ax.set_xlabel("Locking time [s]")

    def save_errors(self, filename):
        """
        Save recorded laser frequency drift after monitoring in a textfile.

        Parameters
        ----------
        filename : str
            name of the file to save the recorded errors.
        """
        # first, combine the respective arrays in a dictionary --> helps keep track of what is what...
        dat = deepcopy(self.errs)
        dat["times"] = self.times
        with open(
            f"{filename}.json", "w"
        ) as file:  # dump the data into a json file, since it is a dictionary.
            json.dump(dat, file, indent=4)

    def update_settings(self, settings):
        self.settings = settings
        self.RP.send(self, "update_settings", value=settings)
        return "done"

    def update_errs(self):
        new_errs = self.RP.send(self, "acquire_errs")
        for key in self.errs:
            if new_errs == "skipped":
                self.errs[key].append(np.nan)
            else:
                if key in new_errs:  # if the error is measured on the redpitaya:
                    self.errs[key].append(
                        new_errs[key] * self.FSR
                    )  # update the error value
                else:
                    self.errs[key].append(np.nan)  # otherwise, fill it with nan value.

    def update_monitor(self):
        """
        Iteration of the monitoring of laser frequency drifts measured on the cavity.
        Data is recorded and can be saved using 'self.save_errors(filename)'.
        """

        self.update_errs()  # update error values
        self.times.append(perf_counter() - self._t0)
        for key, l in self._lines.items():
            if (
                len(self.times) >= 300
            ):  # only plot last 100 points --> choose first index accordingly
                i0 = -300
            else:
                i0 = 0
            l.set_xdata(self.times[i0:])
            l.set_ydata(self.errs[key][i0:])
            if len(self.times) > 2:
                self._ax.set_xlim(
                    self.times[i0], self.times[-1]
                )  # updating the xlim accordingly, since new points get added
                self._ax.relim()
        self._bm.update()  # Currently this is done with blitting.


class RP_client(RP_connection):
    def __init__(self, address, settings, mode="lock"):
        RP_connection.__init__(self, address, mode=mode)
        self.settings = settings
        self.label = "Default"
