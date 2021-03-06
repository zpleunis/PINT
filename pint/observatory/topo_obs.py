# topo_obs.py
# Code for dealing with "standard" ground-based observatories.
from __future__ import absolute_import, print_function, division
from . import Observatory
from .clock_file import ClockFile
import os
import numpy
import astropy.units as u
import astropy.constants as c
from astropy import log
from astropy.coordinates import EarthLocation
from astropy.time import Time
from ..utils import PosVel, has_astropy_unit
from ..solar_system_ephemerides import objPosVel_wrt_SSB, get_tdb_tt_ephem_geocenter
from ..config import datapath
from ..erfautils import gcrs_posvel_from_itrf, SECS_PER_DAY
from pint import JD_MJD


class TopoObs(Observatory):
    """Class for representing observatories that are at a fixed location
    on the surface of the Earth.  This behaves very similarly to "standard"
    site definitions in tempo/tempo2.  Clock correction files are read and
    computed, observatory coordinates are specified in ITRF XYZ, etc."""

    def __init__(self, name, tempo_code=None, itoa_code=None, aliases=None,
                 itrf_xyz=None, clock_file='time.dat', clock_dir='PINT',
                 clock_fmt='tempo', include_gps=True, include_bipm=True,
                 bipm_version='BIPM2015'):
        """
        Required arguments:

            name     = The name of the observatory
            itrf_xyz = IRTF site coordinates (len-3 array).  Can include
                       astropy units.  If no units are given, meters are
                       assumed.

        Optional arguments:

            tempo_code  = 1-character tempo code for the site.  Will be
                          automatically added to aliases.  Note, this is
                          REQUIRED only if using TEMPO time.dat clock file.
            itoa_code   = 2-character ITOA code.  Will be added to aliases.
            aliases     = List of other aliases for the observatory name.
            clock_file  = Name of the clock correction file.
                          Default='time.dat'
            clock_dir   = Location of the clock file.  Special values
                          'TEMPO', 'TEMPO2', or 'PINT' mean to use the
                          standard directory for the package.  Otherwise
                          can be set to a full path to the directory
                          containing the clock_file.  Default='TEMPO'
            clock_fmt   = Format of clock file (see ClockFile class for allowed
                          values).  Default='tempo'
            include_gps = Set False to disable UTC(GPS)->UTC clock
                          correction.
            include_bipm= Set False to disable UTC-> TT BIPM clock
                          correction. If False, it only apply TAI->TT correction
                          TT = TAI+32.184s, the same as TEMPO2 TT(TAI) in the
                          parfile. If Ture, it will apply the correction from
                          BIPM TT=TT(BIPMYYYY). See the link:
                          http://www.bipm.org/en/bipm-services/timescales/time-ftp/ttbipm.html
            bipm_version= Set the version of TT BIPM clock correction file to
                          use, the default is BIPM2015.  It has to be in the format
                          like 'BIPM2015'
        """

        # ITRF coordinates are required
        if itrf_xyz is None:
            raise ValueError(
                    "ITRF coordinates not given for observatory '%s'" % name)

        # Convert coords to standard format.  If no units are given, assume
        # meters.
        if not has_astropy_unit(itrf_xyz):
            xyz = numpy.array(itrf_xyz) * u.m
        else:
            xyz = itrf_xyz.to(u.m)

        # Check for correct array dims
        if xyz.shape != (3,):
            raise ValueError(
                    "Incorrect coordinate dimensions for observatory '%s'" % (
                        name))

        # Convert to astropy EarthLocation, ensuring use of ITRF geocentric coordinates
        self._loc_itrf = EarthLocation.from_geocentric(*xyz)

        # Save clock file info, the data will be read only if clock
        # corrections for this site are requested.
        self.clock_file = clock_file
        self.clock_dir = clock_dir
        self.clock_fmt = clock_fmt
        self._clock = None # The ClockFile object, will be read on demand

        # If using TEMPO time.dat we need to know the 1-char tempo-style
        # observatory code.
        if (clock_dir=='TEMPO' and clock_file=='time.dat'
                and tempo_code is None):
            raise ValueError("No tempo_code set for observatory '%s'" % name)

        # GPS corrections not implemented yet
        self.include_gps = include_gps
        self._gps_clock = None

        # BIPM corrections not implemented yet
        self.include_bipm = include_bipm
        self.bipm_version = bipm_version
        self._bipm_clock = None

        self.tempo_code = tempo_code
        if aliases is None: aliases = []
        for code in (tempo_code, itoa_code):
            if code is not None: aliases.append(code)

        super(TopoObs,self).__init__(name,aliases=aliases)

    @property
    def clock_fullpath(self):
        """Returns the full path to the clock file."""
        if self.clock_dir=='PINT':
            return datapath(self.clock_file)
        elif self.clock_dir=='TEMPO':
            # Technically should read $TEMPO/tempo.cfg and get clock file
            # location from CLKDIR line...
            dir = os.path.join(os.getenv('TEMPO'),'clock')
        elif self.clock_dir=='TEMPO2':
            dir = os.path.join(os.getenv('TEMPO2'),'clock')
        else:
            dir = self.clock_dir
        return os.path.join(dir,self.clock_file)

    @property
    def gps_fullpath(self):
        """Returns full path to the GPS-UTC clock file.  Will first try PINT
        data dirs, then fall back on $TEMPO2/clock."""
        fname = 'gps2utc.clk'
        fullpath = datapath(fname)
        if fullpath is not None:
            return fullpath
        return os.path.join(os.getenv('TEMPO2'),'clock',fname)

    @property
    def bipm_fullpath(self,):
        """Returns full path to the TAI TT(BIPM) clock file.  Will first try PINT
        data dirs, then fall back on $TEMPO2/clock."""
        fname = 'tai2tt_' + self.bipm_version.lower() + '.clk'
        fullpath = datapath(fname)
        if fullpath is not None:
            return fullpath
        else:
            try:
                return os.path.join(os.getenv('TEMPO2'),'clock',fname)
            except:
                return None

    @property
    def timescale(self):
        return 'utc'

    def earth_location_itrf(self, time=None):
        return self._loc_itrf

    def clock_corrections(self, t):
        # Read clock file if necessary
        # TODO provide some method for re-reading the clock file?
        if self._clock is None:
            log.info('Observatory {0}, loading clock file {1}'.format(self.name, self.clock_fullpath))
            self._clock = ClockFile.read(self.clock_fullpath,
                    format=self.clock_fmt, obscode=self.tempo_code)
        corr = self._clock.evaluate(t)
        if self.include_gps:
            if self._gps_clock is None:
                log.info('Observatory {0}, loading GPS clock file {1}'.format(self.name, self.gps_fullpath))
                self._gps_clock = ClockFile.read(self.gps_fullpath,
                        format='tempo2')
            corr += self._gps_clock.evaluate(t)
        if self.include_bipm:
            tt2tai = 32.184 * 1e6 * u.us
            if self._bipm_clock is None:
                try:
                    log.info('Observatory {0}, loading BIPM clock file {1}'.format(self.name, self.bipm_fullpath))
                    self._bipm_clock = ClockFile.read(self.bipm_fullpath,
                                                      format='tempo2')
                except:
                    raise ValueError("Can not find TT BIPM file '%s'. " % self.bipm_version)
            corr += self._bipm_clock.evaluate(t) - tt2tai
        return corr

    def _get_TDB_ephem(self, t, ephem):
        """This is a function that reads the ephem TDB-TT column. This column is
            provided by DE4XXt version of ephemeris. This function is only for
            the ground-based observatories
        """
        geo_tdb_tt = get_tdb_tt_ephem_geocenter(t.tt, ephem)
        # NOTE The earth velocity is need to compute the time correcion from
        # Topocenter to Geocenter
        # Since earth velocity is not going to change a lot in 3ms. The
        # differences between TT and TDB can be ignored.
        earth_pv = objPosVel_wrt_SSB('earth', t.tdb, ephem)
        obs_geocenter_pv = gcrs_posvel_from_itrf(self.earth_location_itrf(), t,\
                                               obsname=self.name)
        # NOTE
        # Moyer (1981) and Murray (1983), with fundamental arguments adapted
        # from Simon et al. 1994.
        topo_time_corr = numpy.sum(earth_pv.vel/c.c * obs_geocenter_pv.pos /c.c,
                                       axis=0)
        topo_tdb_tt = geo_tdb_tt - topo_time_corr
        result = Time(t.tt.jd1 - JD_MJD, \
                      t.tt.jd2 - topo_tdb_tt.to(u.day).value, \
                      format='pulsar_mjd', scale='tdb', \
                      location=self.earth_location_itrf())
        return result

    def posvel(self, t, ephem):
        if t.isscalar: t = Time([t])
        earth_pv = objPosVel_wrt_SSB('earth', t, ephem)
        obs_geocenter_pv = gcrs_posvel_from_itrf(self.earth_location_itrf(), t, \
                                           obsname=self.name)
        return obs_geocenter_pv + earth_pv
