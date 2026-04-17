import math
from scipy import interpolate


class Logic:
    def __init__(self):
        # Logic version. Only use to track changes if necessary
        self.version = "v1.0.0"

        # Enable/Disable this logic file
        # When False, this logic will not be started
        self.is_enable = True

        # Define local variables here
        self.some_counter = 0       

        # Flaps Angles
        flaps_y = [0.0, 0.644, 1.309, 1.922, 2.56, 3.115, 3.655, 4.178, 4.696]
        # Flaps Prosim Values
        flaps_x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
        self.flpInpl = interpolate.interp1d(flaps_x, flaps_y, kind="linear")

        # Rudder Angles
        rudder_y = [-0.99, -0.95, -0.8, -0.4, -0.1, 0.24, 0.57, 0.95, 0.99]
        # Rudder prosim Values
        rudder_x = [-17, -15, -10, -5, 0, 5, 10, 15, 17]
        self.rdsInp = interpolate.interp1d(rudder_x, rudder_y, kind="linear")

        # SAI Vertical Needle Angles
        sai_needle_vt_y =  [3.0, -1.75, 0, 1.75]
        # SAI Vertical Needle prosim Values
        sai_needle_vt_x = [-40, -39, 0, 40]
        self.saiNdlVertInp = interpolate.interp1d(sai_needle_vt_x, sai_needle_vt_y, kind="linear")

        # SAI Horizontal Needle Angles
        sai_needle_hz_y =  [1.75, 0, -1.75, 3.0]
        # SAI Horizontal Needle prosim Values
        sai_needle_hz_x = [-25, 0, 24, 25]
        self.saiNdlHozInp = interpolate.interp1d(sai_needle_hz_x, sai_needle_hz_y, kind="linear")


    async def update(self):
        self.vars.flaps_r.value = float(self.flpInpl(self.datarefs.prosim.flaps_r.value))
        self.vars.flaps_l.value = float(self.flpInpl(self.datarefs.prosim.flaps_l.value))
        self.vars.rudder_trim.value = float(self.rdsInp(self.datarefs.prosim.rudder_trim.value))
        self.vars.sai_needle_vt.value = float(self.saiNdlVertInp(self.datarefs.prosim.sai_localiser.value))
        self.vars.sai_needle_hz.value = float(self.saiNdlHozInp(self.datarefs.prosim.sai_glideslope.value))


        # self.vars.flaps_r.value = self.some_counter
        # self.vars.flaps_l.value = self.some_counter

        # Example 3:
        # Increment counter to show something
        # self.some_counter += 0.0040

        