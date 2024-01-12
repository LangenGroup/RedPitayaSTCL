# -*- coding: utf-8 -*-
"""
Created on Tue May  2 18:59:11 2023

@author: epultinevicius
"""

import numpy as np
from math import factorial

def maximum(x, y, r):
    '''
    Simplest peak finder --> searches for maximum value in given range.
    '''
    x, y = x[r[0]:r[-1]], y[r[0]:r[-1]]  #extract data in range
    j = np.argmax(y) # peak index
    return np.array([x[j], y[j]]) # peak position and height

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

# some precalculated default value that worked well for our tests

m_1 = SG_array(deriv = 1)
m_0 = SG_array(deriv = 0, order = 2)    

def SG_filter(x,y,r, m=m_0):
    half_window = (len(m) - 1) // 2
    x, y = np.array(x[r[0]:r[-1]]), np.array(y[r[0]:r[-1]])  #extract data in range
    y2 = np.convolve( m[::-1], y[:], mode='valid')
    return np.array([x[half_window:-half_window], y2])
    
def SG_maximum(x,y,r, m = m_0):
    half_window = (len(m) - 1) // 2
    x, y = np.array(x[r[0]:r[-1]]), np.array(y[r[0]:r[-1]])  #extract data in range
    j = np.argmax(y)
    y2 = np.convolve( m[::-1], y[j-2*half_window : j+2*half_window], mode='valid')
    j2 = np.argmax(y2)
    return np.array([x[j-half_window + j2], y2[j2]])

def SG_deriv(x,y,r, m = m_1):
    half_window = (len(m) - 1) // 2
    x, y = np.array(x[r[0]:r[-1]]), np.array(y[r[0]:r[-1]])  #extract data in range
    j = np.argmax(y)
    dv = np.convolve( m[::-1], y[j-half_window : j+half_window+2], mode='valid')
    x_p = x[j] - dv[0] * (x[j+1]-x[j]) / (dv[1]- dv[0])
    if np.abs(x_p-x[j]) < (x[j+half_window]-x[j]):     # checking if the peakposition has an abnormal value due to interpolation error (bumpy peak shape...)
        return np.array([x_p, y[j]])
    else:
        return np.array([x[j], y[j]]) # if abnormal value, just take the maximum position.
    
    # dictionary containing all relevant peakfinders
peak_finders = dict(
    maximum = maximum,
    SG_deriv = SG_deriv,
    SG_maximum = SG_maximum
    )
    
################## old functions ##############################################    
def T123(x, y, r):
    x, y = x[r[0]:r[-1]], y[r[0]:r[-1]]  #extract data in range
    # Setheight!
    #height = (np.max(y) - np.min(y))*0.5 + np.min(y)
    height = -0.01
    mask = (y >= height)
    T1, T3 = x[mask][0], x[mask][-1]
    # Direct Method
    T2 = x[np.argmax(y)]
    # Method via derivative:
    #T2 = x[np.argmin(np.diff(y))]
    T_avg = np.mean([T1,T2,T3])
    #P_avg = y[np.argmin(np.abs(np.array(x)-T_avg))]
    return np.array([T_avg, 0])