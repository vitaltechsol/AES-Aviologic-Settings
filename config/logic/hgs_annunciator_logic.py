import asyncio


class Logic:

    def __init__(self):
        self.version = "v1.0.0"

        # Cache reference to the annunciator label from the equipment file
        self._ann = self.vars.hgs_annunciator.annunciator

    async def update(self):

        # ----- User Space START -----

        ps = self.datarefs.prosim

        self._ann.aiii = ps.I_HGS_AP_AIII.value == 2
        self._ann.noaiii = ps.I_HGS_AP_NOAIII.value == 2
        self._ann.flare = ps.I_HGS_AP_FLARE.value == 2
        self._ann.dash = ps.B_LIGHT_TEST.value == 1

        self._ann.ro = ps.I_HGS_AP_RO.value == 2
        self._ann.roctn = ps.B_LIGHT_TEST.value == 1  # -- Missing, using light test only for now
        self._ann.roarm = ps.I_HGS_AP_ROARM.value == 2
        self._ann.to_red = ps.I_HGS_AP_TOWARN.value == 2

        self._ann.to_grn = ps.I_HGS_AP_TO.value == 2
        self._ann.toctn = ps.I_HGS_AP_TOCTN.value == 2
        self._ann.app = ps.I_HGS_AP_APP.value == 2
        self._ann.warn = (ps.I_HGS_AP_TOWARN.value == 2) or (ps.I_HGS_AP_APP.value == 2)

        self._ann.hgsfail = ps.I_HGS_AP_HGSFAIL.value == 2

        # ----- User Space END -----

        await asyncio.sleep(0.05)