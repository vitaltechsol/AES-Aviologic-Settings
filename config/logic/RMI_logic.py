import asyncio


class Logic:
    def __init__(self):
        self.version = "v1.0.0"

    async def update(self):
        heading = 40.0

        # Set magnetic heading in degrees.
        self.vars.rmi_irs.hdg_m.value = heading

        # Set VOR and ADF bearings in degrees. These values
        # are absolute bearings to the stations, not relative to the aircraft heading.
        self.vars.vor_adf1.adf_bear.value = 50.0 - heading
        self.vars.vor_adf1.vor_bear.value = 100.0 - heading
        self.vars.vor_adf2.adf_bear.value = 150.0 - heading
        self.vars.vor_adf2.vor_bear.value = 200.0 - heading

        # ----- User Space END -----
        await asyncio.sleep(0.05)
