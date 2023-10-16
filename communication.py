# -*- coding: utf-8 -*-
"""
Created on Fri May 13 10:23:32 2022

@author: epultinevicius


In this module, a sender class is defined which handles all of the
communication with the RedPitaya based on socket servers.
This will be the base for the LockClient class which will be used to handle
the STCL remotely using individual RedPitayas.

"""
# modules used for socket communication
import socket
import selectors
import traceback
import libclient
import threading

# module for ssh communication
import paramiko

# used for waiting whenever code is remotely excecuted on a RedPitaya,
# since that can take some time.
from time import sleep

# for path finding in both windows and unix operating systems
from pathlib import (
    PurePosixPath,
    Path,
)  # just PosixPath did not work on our Windows machine...
import os
import sys

# dictionary of files required for the lock to run on the redpitaya and the
# directory they are stored in.
directory = Path("RP_side")
filenames = dict(
    Run="RunLock.py", Lock="RP_Lock.py", Lib="libserver.py", Peaks="peak_finders.py"
)

# find the required filepaths! They are expected to be found in the pythonpath:
paths = sys.path
# initialize empty dictionary for the filepaths
filepaths = dict()
# Find the files in the filepaths. The directory should have a unique name to avoid confusion with other libraries.
for p in paths:
    for key, val in filenames.items():  # search for each filename
        filepath = Path(p, Path(directory, val))
        if filepath.exists():  # if found, then add it to the dictionary
            the_path = p
            filepaths[key] = filepath

DIR = Path(the_path, "settings")  # save the found pythonpath


class Sender:
    """
    This class is the framework used to establish the communication
    between the PC and Redpitaya. Most of this is based of the RealPython socket
    programming guide (https://realpython.com/python-sockets/ , 23.02.2023).
    """

    def __init__(self, DIR=DIR):
        """

        Parameters
        ----------
        DIR : Path
            This path will be used by default for storing the lock settings
            json-files. Can be changed as desired. The default is the directory
            where all the modules are loaded from.

        """
        self.sel = selectors.DefaultSelector()
        self.mode = "scan"  # by default, assume the redpitaya scans the cavity.
        self.state = 0
        self.running = False
        self.DIR = DIR

    def event_loop(self):
        """
        This is the event_loop which handles the communication. Whenever multiple
        traces are to be acquired from the redpitaya, (acquire_ch_n), the buffersize is
        increased to reduce the time to send data. The eventloop is properly
        described in the RealPython socket example. Here, the state variable is added
        in order to properly deal with loop_action().

        Returns
        -------
        whatever the remotely executed function on the redpitaya returns.

        """
        self.running = True  # set the running variable to True
        # self.sel = selectors.DefaultSelector()
        try:
            pass
            while True:
                if (
                    not self.sel.get_map()
                ):  # check whether there is something registered on the selector!
                    sleep(0)
                    pass
                else:
                    events = self.sel.select(
                        timeout=1
                    )  # select returns list of tuples, each for a socket.
                    for (
                        key,
                        mask,
                    ) in (
                        events
                    ):  # each tuple contains key and mask --> selectorkey | eventmask --> this iterates through each socket connection!
                        message = key.data  # retrieve message
                        if key.data != None:
                            try:
                                # this is for quicker data acquisition if multiple traces are subsequently captured
                                if (
                                    self.mode == "monitor"
                                ):  # increase size if more data needs to be transferred at a time
                                    message.buffersize = int(2**18)
                                else:
                                    message.buffersize = int(2**12)
                                message.process_events(
                                    mask
                                )  # Process the event according to the mask! --> read or write.
                            except Exception:
                                print(
                                    f"Main: Error: Exception for {message.addr}:\n"
                                    f"{traceback.format_exc()}"
                                )
                                message.close()  # if exception, close the messsage
                    # Check whether the event_loop should keep running:
                    if (
                        not self.running
                    ):  # if running is set to False using stop_event_loop, the event_loop stops.
                        break

        except KeyboardInterrupt:
            print("Caught keyboard interrupt, exiting")
            message.close()
        finally:
            return  # this is necessary for the thread to stop after stoppin the event_loop

    def start_event_loop(self):
        """
        Start an event loop which handles all the communication between the PC
        and the RedPitayas. A Selector is used to handle the different
        sent/received messages. See class 'Sender' for more details.
        A thread is used to run this in the background.
        """
        if not self.running:  # only if the event loop is not running already!
            self.el_thread = threading.Thread(
                target=self.event_loop
            )  # use threading to run the event_loop in the background
            self.el_thread.daemon = (
                True  # a daemon thread will shut down if the program exits.
            )
            self.el_thread.start()  # start the event loop thread! This should run in the background
        else:
            print("Event loop already running!")

    def stop_event_loop(self):
        # stops the event_loop by setting running to False.
        # The event_loop is usually run in a background thread for this to work!
        self.running = False


class RP_connection:
    def __init__(self, addr, mode="scan"):
        self.addr = addr  # tuple of IP address and port used for socket
        self.mode = mode  # defines whether RP scans cavity or not.
        self.lsock = None  # socket for interaction during loop.
        self.loop_running = False  # boolean, whether loop is running or not.
        self.connected = False

    def _check_ext_scan(func):
        """
        Decorator which is applied to each method of RP_communication. Checks,
        whether the object is fake, e.g. when using external cavity scans with
        a fake RP object, or not. Nothing should happen if no real RP object
        exists.
        """

        # checks if a loop is already running before starting a new one.
        def inner(self, *args, **kwargs):
            if self.mode == "ext_scan":  # no communication!
                return None
            else:
                return func(self, *args, **kwargs)
        return inner

    @_check_ext_scan
    def reboot(self):
        ssh = (
            paramiko.SSHClient()
        )  # save the ssh client as attribute in order to close it later!
        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy
        )  # used for not yet known hostnames!
        ssh.connect(
            self.addr[0], port=22, username="root", password="root", timeout=5
        )  # the standard port 22 is hardcoded here.
        ssh.exec_command("reboot")  # run the script which initiates socket server!
        ssh.close()  # close the ssh connection afterwards, otherwise there are problems with multiprocessing...
        print("Rebooting, please wait a bit before attempting to reconnect.")
        return

    @_check_ext_scan
    def upload_current(self):
        """
        Used for uploading python scripts from PC to RedPitaya. The required scripts
        are searched for in PYTHON_PATH (in this case, in spyders PYTHON_PATH).
        After that, the IP-address for communication is updated in the textfiles
        that are sent to the RedPitaya via SSH.

        Returns
        -------
        None.

        """
        # find the required filepaths! They are expected to be found in the pythonpath:
        paths = sys.path
        # initialize empty dictionary for the filepaths
        filepaths = dict()
        # Find the files in the filepaths. The directory should have a unique name to avoid confusion with other libraries.
        for p in paths:
            for key, val in filenames.items():  # search for each filename
                filepath = Path(p, Path(directory, val))
                if filepath.exists():  # if found, then add it to the dictionary
                    filepaths[key] = filepath
        # save hostname in variable to facilitate coding.
        hostname = self.addr[0]
        # create SSH connection with paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy
        )  # used for not yet known hostnames!
        ssh.connect(hostname, port=22, username="root", password="root", timeout=5)
        # start sftp in order to be able to send files.
        sftp = ssh.open_sftp()
        # iterate through each file and update it on the RedPitaya
        for key in ["Lock", "Lib", "Run", "Peaks"]:
            path = PurePosixPath(
                "/home/jupyter/RedPitaya", filenames[key]
            )  # path on RP
            localpath = filepaths[key]  # path on PC
            if (
                key == "Run"
            ):  # This is the one file on the redpitaya requiring the hostname!
                # read the file
                with localpath.open("r", encoding="utf-8") as f:
                    lines = f.readlines()
                # update certain lines of the script with the necessary information.
                lines[4] = f"host, port = '{hostname}', 5000\n"
                lines[
                    5
                ] = f"Lock = RP_Server(host, port, 5065, RP_mode = '{self.mode}')\n"
                # now, overwrite the file!
                with localpath.open("w", encoding="utf-8") as f:
                    f.writelines(lines)
            sftp.put(str(localpath), str(path))  # send updated script to the redpitaya.
        # close the connection again.
        sftp.close()
        ssh.close()

    @_check_ext_scan
    def start_host_server(self):
        """
        This function starts the host server on the redpitaya by running a certain script.
        This is done via establishing an ssh connection from which the socket server is started.
        Using this ssh communication, any other commands can be sent from the PC to the redpitaya.

        Returns
        -------
        None.

        """
        ssh = (
            paramiko.SSHClient()
        )  # save the ssh client as attribute in order to close it later!
        ssh.set_missing_host_key_policy(
            paramiko.AutoAddPolicy
        )  # used for not yet known hostnames!
        ssh.connect(
            self.addr[0], port=22, username="root", password="root", timeout=5
        )  # the standard port 22 is hardcoded here.
        ssh.exec_command(
            "python3 /home/jupyter/RedPitaya/RunLock.py"
        )  # run the script which initiates socket server!
        ssh.close()  # close the ssh connection afterwards, otherwise there are problems with multiprocessing...
        self.connected = True
        return "connected"

    @_check_ext_scan
    def connect_socket(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # IPv4 TCP socket
        sock.settimeout(5)  # 10 second timeout instead of default 120s
        try:
            sock.connect_ex(addr)  # start the connection to the redpitaya!
        except sock.error as exc:  # hopefully this exception handling is useful...
            print(f"Caught exception: {exc}")
            sock == None
        sock.setblocking(False)  # non-blocking mode
        return sock

    @_check_ext_scan
    def send(
        self, Sender, action, value="Hello World!", loop_action=False, loop=False
    ):  # Sender contains the event_loop that handles the multiple communications
        # used to send commands (so-called actions) to the redpitaya. e.g. send("echo")
        if Sender.running:  # check if event_loop is running!
            request = self.create_request(
                action, value
            )  # this is used to work with the RealPython socket example
            # establishes socket connection to host
            if not loop:
                sock = self.connect_socket(self.addr)
                addr = self.addr
                stop = True
            else:
                sock = self.lsock
                addr = (self.addr[0], 5065)
                stop = False
                if action == "stop":
                    stop = True

            # define message and event for the selector
            event_state = (
                selectors.EVENT_READ | selectors.EVENT_WRITE
            )  # either read or write
            message = libclient.Message(Sender.sel, sock, addr, request, stop=stop)
            # here, the socket connection is registered on the selector of the event_loop!
            Sender.sel.register(sock, event_state, data=message)
            # Here, the function has to wait for  a response!
            # In the Message class, when the connection is unregistered, the
            # used method saves the selectorkey! this is the indication for a
            # finished response! initially set to None.

            if loop_action:
                self.loop_running = True

            while True:
                sleep(0)
                # the following is done whenever a loop is started remotely --> setup loop socket 'lsock'!
                if loop_action and self.loop_running:
                    if self.lsock == None:
                        if Sender.sel.get_key(sock).events & selectors.EVENT_READ:
                            # after a loop has been initiated, start a second socket connection on port 50
                            laddr = (self.addr[0], 5065)
                            sleep(2)
                            self.lsock = self.connect_socket(
                                laddr
                            )  # the second socket connection has to be established!
                            sleep(0.5)
                            try:
                                self.lsock.getpeername()
                            except Exception as exp:
                                print(f"Exception occured during connection: {exp}")
                                self.loop_running = False
                                return "Exception occured during connection..."
                            print(f"connected to {self.lsock}")

                if message.selkey != None:
                    if self.loop_running and action == "stop":
                        self.loop_running = False
                    break  # break whenever message closes connection --> also when exception occurs during event_loop!

            # retrieve the response!
            result = message.response["result"]
            if loop_action:
                self.lsock = None
        else:  # if no event_loop is running, return None
            print("Event_loop not running!")
            result = None

        return result

    @_check_ext_scan
    def create_request(self, action, value):  # copied from RealPython.
        """
        orders the content of requests that are sent during communication.
        """
        return dict(
            type="text/json",
            encoding="utf-8",
            content=dict(action=action, value=value),
        )
