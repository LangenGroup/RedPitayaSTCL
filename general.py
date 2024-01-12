# -*- coding: utf-8 -*-
"""
Created on Fri Jul 15 10:42:04 2022

@author: epultinevicius
"""
import numpy as np
from math import factorial, log2

def duration(dec):
    return 2**14 * 8e-9 * dec # trace duration in s

def ms2index(ms, dec = 2**4):
    dur = duration(dec) * 1e3 # trace duration in ms
    return int(ms*2**14/dur)

def index2ms(i, dec = 2**4):
    dur = duration(dec) * 1e3 # trace duration in ms
    return i * dur/2**14

def flatten_list(ls):
    # returns a flattened list
    return [x for l in ls for x in l]

def check_range(laser, R, dec):
    # check whether the range R is valid! --> values in order, no overlap for master, in expected bound!
    dur = index2ms(2**14, dec = dec) # scan duration in ms
    if laser == 'Master':
        r = [0, *flatten_list(R), dur]
    else:
        r = [0, *R, dur]
    return r == sorted(r)

def check_lockpoint(laser, R, lp):
    # check whether the lockpoint lp is in the range R!
    if laser == 'Master':
        r = R[1]
    else:
        r = R
    return r[0] < lp < r[1]

def check_dec(dec):
    # check if decimation setting is fine
    power = log2(dec)
    if not power.is_integer():
        print('dec setting must be a power of 2!')
        return False
    elif not 0 <= power <= 9: # in principle everything up to a power of 2**13 should work, but at some point the trigg
        print('dec must be between 2**0 and 2**9!')
        return False
    else: 
        return True

def check_PID(PID_dict):
    for key, val in PID_dict.items():
        if key not in ["P", "I", "D", "I_val", 'limit']:
            print(f'{key} not an available setting for PID!')
            return False
        elif key == 'limit':
            if not val == sorted(val):
                print(f'limits {val} not in assending order!')
                return False
            if not all(abs(i) <= 1 for i in val):
                print(f'limits {val} out of bounds!')
                return False
            else:
                return True
        else:
            return True

def SG_array(window_size = 21, order = 2, deriv=0, rate=1): # based on https://scipy-cookbook.readthedocs.io/items/SavitzkyGolay.html
    """
    calculates an array which is used for convolution in an savitky-golay filter
    with a window_size, order to smoothen the deriv-th derivative of some data.
    """
    # precompute coefficients
    half_window = (window_size -1) // 2
    order_range = range(order+1)
    b = np.mat([[k**i for i in order_range] for k in range(-half_window, half_window+1)])
    m = np.linalg.pinv(b).A[deriv] * rate**deriv * factorial(deriv)
    return m

window_size = 21
order = 1
order_range = range(order+1)
half_window = (window_size -1) // 2

m = SG_array(window_size, order, deriv=1)

class BlitManager:
    '''
    This was copied from matplotlib and is used to deal with blitting.
    Essentially, this reduces the amount of calculation when updating a plot
    by keeping certain artists (x and y axes, ticks etc.) in a constant background
    while only updating the data.
    '''
    def __init__(self, canvas, animated_artists=()):
        
        self.canvas = canvas
        self._bg = None
        self._artists = []
        
        for a in animated_artists:
            self.add_artist(a)
        self.cid = canvas.mpl_connect('draw_event', self.on_draw)
        
    def on_draw(self, event):
        
        cv = self.canvas
        if event is not None:
            if event.canvas != cv:
                raise RuntimeError
        self._bg = cv.copy_from_bbox(cv.figure.bbox)
        self._draw_animated()
    
    def add_artist(self, art):
        if art.figure != self.canvas.figure:
            raise RuntimeError
        art.set_animated(True)
        self._artists.append(art)
        
    def _draw_animated(self):
        fig = self.canvas.figure
        for a in self._artists:
            fig.draw_artist(a)
    
    def update(self):
        cv = self.canvas
        fig = cv.figure
        
        if self._bg is None:
            self.on_draw(None)
        else:
            cv.restore_region(self._bg)
            self._draw_animated()
            cv.blit(fig.bbox)
        
        self.canvas.flush_events()