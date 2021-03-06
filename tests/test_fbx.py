"""Various tests to assess the performance of the FBX model."""
import pint.models.model_builder as mb
import pint.toa as toa
import astropy.units as u
from pint.residuals import resids
import numpy as np
import os, unittest
import test_derivative_utils as tdu
import logging
from pinttestdata import testdir, datadir

os.chdir(datadir)


class TestFBX(unittest.TestCase):
    """Compare delays and derivatives from the FBX parameterization with tempo
    and PINT
    """
    @classmethod
    def setUpClass(self):
        self.parfileJ0023 = 'J0023+0923_NANOGrav_11yv0.gls.par'
        self.timJ0023 = 'J0023+0923_NANOGrav_11yv0.tim'
        self.toasJ0023 = toa.get_TOAs(self.timJ0023, ephem="DE436",
                                      planets=False)
        self.modelJ0023 = mb.get_model(self.parfileJ0023)
        # tempo result
        self.ltres, self.ltbindelay = np.genfromtxt(self.parfileJ0023 + \
                                  '.tempo2_test',skip_header=1, unpack=True)
    def test_B1953_binary_delay(self):
        # Calculate binary delays with PINT
        pint_binary_delay = self.modelJ0023.binarymodel_delay(self.toasJ0023.table, None)
        assert np.all(np.abs(pint_binary_delay.value + self.ltbindelay) < 1e-9), 'B1953 binary delay test failed.'

    def test_J0023(self):
        pint_resids_us = resids(self.toasJ0023, self.modelJ0023, False).time_resids.to(u.s)
        assert np.all(np.abs(pint_resids_us.value - self.ltres) < 1e-8), 'J0023 residuals test failed.'

    def test_derivative(self):
        log= logging.getLogger( "test_J0023.derivative_test")
        testp = tdu.get_derivative_params(self.modelJ0023)
        delay = self.modelJ0023.delay(self.toasJ0023.table)
        for p in testp.keys():
            log.debug( "Runing derivative for %s", 'd_delay_d_'+p)
            if p in ['EPS2', 'EPS1']:
                testp[p] = 10
            ndf = self.modelJ0023.d_phase_d_param_num(self.toasJ0023.table, p, testp[p])
            adf = self.modelJ0023.d_phase_d_param(self.toasJ0023.table, delay, p)
            diff = adf - ndf
            if not np.all(diff.value) == 0.0:
                mean_der = (adf+ndf)/2.0
                relative_diff = np.abs(diff)/np.abs(mean_der)
                #print "Diff Max is :", np.abs(diff).max()
                msg = 'Derivative test failed at d_delay_d_%s with max relative difference %lf' % (p, np.nanmax(relative_diff).value)
                if p in ['PMELONG', 'ELONG']:
                    tol = 2e-2
                elif p in ['FB2', 'FB3']:
                    tol = 0.08
                else:
                    tol = 1e-3
                log.debug( "derivative relative diff for %s, %lf"%('d_delay_d_'+p, np.nanmax(relative_diff).value))
                assert np.nanmax(relative_diff) < tol, msg
            else:
                continue
