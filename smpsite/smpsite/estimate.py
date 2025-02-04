import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import haversine_distances

import pmagpy.pmag as pmag
import pmagpy.ipmag as ipmag

from .kappa import lat_correction, kappa2angular, kappa_from_latitude
from .sampling import generate_samples

import warnings 
warnings.filterwarnings('default')


class NoPointsForMean(Exception):
    """
    This error should never happen, but it does. 
    There is something with the groupby() operation that leaves empty objects.
    """
    pass

def robust_fisher_mean(decs, incs):
    
    assert len(decs) == len(incs)
    
    if len(decs) == 0:
        raise NoPointsForMean("No points to compute the mean")
    
    if len(decs) == 1:
        return {'vgp_dec': decs[0], 
                'vgp_inc': incs[0], 
                'n_samples': 1, 
                'resultant_length': 1.0}
    
    else:
        pole_mean = ipmag.fisher_mean(dec=decs, inc=incs)
        return {'vgp_dec': pole_mean['dec'], 
                'vgp_inc': pole_mean['inc'], 
                'n_samples': pole_mean['n'], 
                'resultant_length': pole_mean['r']}

def S2_within_site(resultant_length, n_samples, lat, degrees=True):
    """
    Calculation of S^2 within site
    """
    if n_samples == 1:
        return 0.0
    k_wi = (n_samples - 1) / (n_samples - resultant_length)
    assert k_wi >= 0.0
    return 2 * (180 / np.pi) ** 2 * lat_correction(lat, degrees=degrees) / k_wi 


def estimate_pole(df_sample, params, ignore_outliers):
    '''
    Function to estimate the Fisher estimate for the paloemagnetic pole
    Returns:
     - Pole coordinates
     - Number of samples (total)
     - Number of samples per site.
    '''
    
    # Outliers at the site-leve, if True, we discard the outliers at the site-level
    # Outliers at the VGP-level: we consider all the directions within each site, and after tranform to VGP, 
    # we can apply Vandamme cutoff
    
    assert ignore_outliers in ["True", "False", "vandamme"], "Ignore outlier method is not supported."
    
    if ignore_outliers == "True":        
        df = df_sample[df_sample.is_outlier==0]
    else:
        df = df_sample
    
    
    df_site = df.groupby('sample_site').apply(lambda row : pd.Series(robust_fisher_mean(row.vgp_dec.values, row.vgp_inc.values)))
    
    # Within site dispersion 
    df_site["S2_within"] = df_site.apply(lambda row: S2_within_site(row.resultant_length,
                                                                    row.n_samples,
                                                                    params.site_lat, 
                                                                    degrees=True), axis=1)
    df_site["S2_within_norm"] = df_site["S2_within"] / df_site["n_samples"]
    S2_within_total = np.mean(df_site.S2_within_norm.values) 
    
    # Now we need to move this to (lat, lon) space. 
    vgp_long, vgp_lat, _, _ = pmag.dia_vgp(df_site.vgp_dec, 
                                           df_site.vgp_inc, 
                                           0, 
                                           params.site_lat, 
                                           params.site_long)
 
    df_site["vgp_long"] = vgp_long
    df_site["vgp_lat"]  = vgp_lat
    
    # Filter VGPs based on Vandamme method
    if ignore_outliers == "vandamme": 
        df_site, _, _ = pmag.dovandamme(df_site)

    # Final fisher mean
    pole_estimate = ipmag.fisher_mean(dec=df_site.vgp_long.values, 
                                      inc=df_site.vgp_lat.values)
    
    pole_dec = pole_estimate['dec']
    pole_inc = pole_estimate['inc']
    
    # Estimation of the VGP dispersion
    df_site["Delta_pole"] = df_site.apply(lambda row: (180/np.pi) * haversine_distances([(np.pi/180) * np.array([row.vgp_lat, row.vgp_long]),
                                                                                         (np.pi/180) * np.array([pole_inc, pole_dec])])[0,1], axis=1) 
 
    S2_total = np.sum(df_site.Delta_pole.values ** 2) / (params.N - 1)
    S2_vgp = S2_total - S2_within_total
    
    return {"pole_dec": pole_dec, 
            "pole_inc": pole_inc,
            "S2_vgp": S2_vgp, 
            "total_samples": df_site.n_samples.sum(), 
            "samples_per_site": params.n0 }
    

            
def simulate_estimations(params, n_iters=100, ignore_outliers=False, seed=None):
    '''
    Given a sampling strategy (samples per site and total number of samples)
    returns a DF with results of n_iters simulated poles.
    '''
    
    poles = {'plong':[], 'plat':[], 'total_samples':[], 'samples_per_sites':[], 'S2_vgp': [] }
    
    if seed is not None:
        np.random.seed(seed)
    
    _iter = 0 
    
    while _iter < n_iters:

        df_sample = generate_samples(params)

        try:
            pole_estimate = estimate_pole(df_sample, params, ignore_outliers=ignore_outliers)
            _iter += 1
        except NoPointsForMean:
            warnings.warn("No points to compute mean in one simulation.")
            
        poles['plong'].append(pole_estimate["pole_dec"])
        poles['plat'].append(pole_estimate["pole_inc"])
        poles['total_samples'].append(pole_estimate["total_samples"])
        poles['samples_per_sites'].append(pole_estimate["samples_per_site"])
        poles['S2_vgp'].append(pole_estimate["S2_vgp"])

    df_poles = pd.DataFrame(poles)
    
    df_poles['error_angle'] = 90.0 - df_poles.plat
    
    # Add real secular variation of VGPs
    if params.secular_method == 'G':
        _kappa_secular = kappa_from_latitude(params.site_lat, degrees=True)
    elif params.secular_method == 'Fisher':
        _kappa_secular = params.kappa_secular
    df_poles['S2_vgp_real'] = kappa2angular(_kappa_secular) ** 2
    
    # Add all parameters to simulation to keep track of them
    df_poles['n_tot'] = params.N * params.n0
    df_poles['N'] = params.N
    df_poles['n0'] = params.n0
    df_poles['kappa_within_site'] = params.kappa_within_site
    df_poles['site_lat'] = params.site_lat
    df_poles['site_long'] = params.site_long
    df_poles['outlier_rate'] = params.outlier_rate
    df_poles['secular_method'] = params.secular_method
    df_poles['kappa_secular'] = params.kappa_secular
    df_poles['ignore_outliers'] = ignore_outliers
    
    return df_poles


def summary_simulations(df_tot):
    """
    Create summary statistics of simulations
    """
    
    stats = dict(df_tot['error_angle'].describe(percentiles=[.05, .25, .50, .75, .95]))
    df = pd.DataFrame.from_dict({'error_angle_mean': [stats['mean']], 
                                 'error_angle_median': [stats['50%']], 
                                 'error_angle_25': [stats['25%']], 
                                 'error_angle_75': [stats['75%']],                                  
                                 'error_angle_95': [stats['95%']],
                                 'error_angle_std': [stats['std']]})
    
    # Mean square error
    df['error_angle_S2'] = np.mean(df_tot.error_angle.values ** 2)
    # Root mean square error
    df['error_angle_S']  = df['error_angle_S2'] ** .5
    
    df['error_vgp_scatter'] = np.mean( (df_tot['S2_vgp'] ** .5 - df_tot['S2_vgp_real'] ** .5 ) ** 2 ) ** .5
    
    # Add parameters to the final simulation table
    
    for attribute in ['n_tot', 'N', 'n0', 'kappa_within_site', 'site_lat', 'site_long', 'outlier_rate', 'secular_method', 'kappa_secular', 'ignore_outliers']:
        attribute_all = np.unique(df_tot[attribute])
        assert len(attribute_all) == 1, print(attribute_all)
        df[attribute] = attribute_all[0]
    
    df['total_simulations'] = df_tot.shape[0]
    
    return df