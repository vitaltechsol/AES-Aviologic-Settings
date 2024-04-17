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
        rudder_y = [-0.9, -0.8, -0.5, -0.3, -0.03, 0.3, 0.5, 0.8, 0.9]
        # Rudder prosim Values
        rudder_x = [-17.0, -15.0, -10.0, -5.0, 0, 5.0, 10.0, 15.0, 17.0]
        self.rdsInp = interpolate.interp1d(rudder_x, rudder_y, kind="linear")

        # Roll Angles
        sai_roll_y = [6, 3.15, 1.55, 0, -3]
        # Roll prosim Values
        sai_roll_x = [-180, -90.0, 0, 90.0, 180]
        self.saiRollInp = interpolate.interp1d(sai_roll_x, sai_roll_y, kind="linear")

        # Pitch Angles
        sai_pitch_y =  [6, 3.85, 1.55, -0.5, -3]
        # Pitch prosim Values
        sai_pitch_x = [-180, -90.0, 0, 90.0, 180]
        self.saiPitchInp = interpolate.interp1d(sai_pitch_x, sai_pitch_y, kind="linear")


    async def update(self):
        self.vars.flaps_r.value = float(self.flpInpl(self.datarefs.prosim.flaps_r.value))
        self.vars.flaps_l.value = float(self.flpInpl(self.datarefs.prosim.flaps_l.value))
        self.vars.rudder_trim.value = float(self.rdsInp(self.datarefs.prosim.rudder_trim.value))
        self.vars.sai_roll.value = float(self.saiRollInp(self.datarefs.prosim.sai_roll.value))
        self.vars.sai_pitch.value = float(self.saiPitchInp(self.datarefs.prosim.sai_pitch.value))


        # self.vars.flaps_r.value = self.some_counter
        # self.vars.flaps_l.value = self.some_counter

        # Example 3:
        # Increment counter to show something
        # self.some_counter += 0.0040

        