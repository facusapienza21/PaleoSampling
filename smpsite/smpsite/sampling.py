import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

import pmagpy.pmag as pmag
import pmagpy.ipmag as ipmag

from typing import NamedTuple

from .estimate import robust_fisher_mean, estimate_pole



# class Params(NamedTuple):
    
#     kappa_vgp : float    
#     kappa_secular : float 
#     outlier_rate : float
#     N_per_site: int
#     N : int
#     site_lat : float
#     site_long : float
    
class Params(NamedTuple):
    
    kappa_within_site : float    
    site_lat : float # Governing parameter of the concentration
    outlier_rate : float
    N_per_site: int
    N : int    
    site_long : float

    
def generate_design(params): 
    '''
    Given the number of possible samples to collect and how many samples do we 
    want per site, returns a list whose lenght is the number of sites and the repeated
    number of samples per site
    '''
    
    equal_template = np.array([params.N_per_site] * int(params.N/params.N_per_site))
    equal_template[:params.N % params.N_per_site] += 1
    assert np.sum(equal_template) == params.N, 'this happens because there is no way of keeping the right sampling'
    assert np.min(equal_template) >= params.N_per_site
    assert np.max(equal_template) <= params.N_per_site+1
    return equal_template
        
    
def generate_samples(params):
    '''
    Fuction to generate experimental design 
    
    Arguments:
        - n: total number of samples we are able to recollect
        - n_site: number of samples per site (fixed and constant for all sites for now)
        - p: value between [0,1] representing the probabilty of outlier. 
    Returns:
        - List of number of samples needed to take per site
    '''
    
    design = generate_design(params)
    N_sites = len(design)
    latitude = params.site_lat
    
    # We can sample directions directly from TK03
    directions_tk03 = ipmag.tk03(n=N_sites, dec=0, lat=latitude, rev='no', G1=-18e3, G2=0, G3=0, B_threshold=0)
    declinations_tk03, inclinations_tk03 = np.asarray(directions_tk03)[:,0], np.asarray(directions_tk03)[:,1]
    
    
    for i, nk in enumerate(design):
        
        ''' i is a counter representing the site number.
            nk is the number of samples in the i_th site
        '''
        outliers = np.random.binomial(1, params.outlier_rate, nk) # probability of outliers 
        outliers = sorted(outliers)
        n_outliers = np.sum(outliers)
        n_samples = nk - n_outliers
        
        # add within site-dispersion
        # Note: Worth exploring the NAM database to see the actual range of this parameter before applying any 'selection criteria'
        declinations, inclinations = ipmag.fishrot(k=params.kappa_within_site, 
                                                   n=n_samples,
                                                   dec=declinations_tk03[i],
                                                   inc=inclinations_tk03[i],
                                                   di_block=False)

        # Convert specimen/sample/directions to VGP space
        for j in range(len(declinations)):
            vgp_lon, vgp_lat, _, _ = pmag.dia_vgp(declinations[j], inclinations[j], 0, params.site_lat, params.site_long)

        
        # Sample VGP outliers (same as sampling a direction and then transform to VGP)
        vgp_lon_out, vgp_lat_out = pmag.get_unf(n_outliers).T
        
        vgp_lon = np.concatenate((vgp_lon, vgp_lon_out))
        vgp_lat = np.concatenate((vgp_lat, vgp_lat_out))
        
        df_ = pd.DataFrame({'sample_site': i,
                            'vgp_lon': vgp_lon,
                            'vgp_lat': vgp_lat,
                            'is_outlier': outliers})
        if i==0:
            df = df_
        else:
            df = pd.concat([df, df_], axis=0, ignore_index=True)
            
    return df



def simulate_estimations(params, n_iters=100, ignore_outliers=False, seed=None):

    poles_dec, poles_inc, all_total_samples = [], [], []

    if seed is not None:
        np.random.seed(seed)
    
    for _ in range(n_iters):

        df_sample = generate_samples(params)
        pole_dec, pole_inc, total_samples = estimate_pole(df_sample, ignore_outliers=ignore_outliers)
        poles_dec.append(pole_dec)
        poles_inc.append(pole_inc)
        all_total_samples.append(total_samples)

    df_poles = pd.DataFrame({'declination': poles_dec, 
                             'inclination': poles_inc, 
                             'total_samples': all_total_samples})
    df_poles['error_angle'] = 90.0 - df_poles.inclination
    
    return df_poles