import asyncio
import math


class Logic:
    def __init__(self):
        self.version = "v1.0.0"

    async def update(self):

        # prosim datarefs
        ps = self.datarefs.prosim
        heading = ps.IRS1_TRACK.value  # Heading in degrees, 0-360
        irs_aligning = ps.IRS1_ALIGNING.value # for heading flag
        heading_flag = ps.IRS1_HEADING_FLAG.value # for heading flag

        # Check for NaN values and set to 0
        if math.isnan(heading):
            heading = 0

        # Set magnetic heading in degrees.
        self.vars.rmi_irs.hdg_m.value = heading

        # Heading flag
        self.vars.rmi_irs.hdg_m.ssm = 0 if irs_aligning == True or heading_flag == True else 3
        self.vars.vor_adf1.vor_bear.ssm = 3 # hide flag
        self.vars.vor_adf2.vor_bear.ssm = 3 # hide flag

        # Set VOR and ADF bearings in degrees. These values
        # are absolute bearings to the stations, not relative to the aircraft heading.
        adf1_bearing = ps.NAV_ADF_1_BEARING.value
        vor1_bearing = ps.NAV_VOR_1_BEARING.value
        adf2_bearing = ps.NAV_ADF_2_BEARING.value
        vor2_bearing = ps.NAV_VOR_2_BEARING.value

        # Check for NaN values and set to 0
        if math.isnan(adf1_bearing):
            adf1_bearing = 0
        if math.isnan(vor1_bearing):
            vor1_bearing = 0
            self.vars.vor_adf1.vor_bear.ssm = 0 # show flag
        if math.isnan(adf2_bearing):
            adf2_bearing = 0
        if math.isnan(vor2_bearing):
            vor2_bearing = 0
            self.vars.vor_adf2.vor_bear.ssm = 0 # show flag

        self.vars.vor_adf1.adf_bear.value = adf1_bearing + heading
        self.vars.vor_adf1.vor_bear.value = vor1_bearing + heading
        self.vars.vor_adf2.adf_bear.value = adf2_bearing + heading
        self.vars.vor_adf2.vor_bear.value = vor2_bearing + heading

        # ----- User Space END -----
        await asyncio.sleep(0.10)
