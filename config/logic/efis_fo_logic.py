
import asyncio
from datetime import datetime, timezone


class Logic:
    def __init__(self):
        # Logic version. Only use to track changes if necessary
        self.version = "v1.1.0"

        # Enable/Disable this logic file
        # When False, this logic will not be started
        self.is_enable = True

        # Track last sent values to avoid unnecessary updates
        self._last_sent_values = {}
    
    def send_key_value(self, ref, value):
        # Only send the command if the value has changed
        if self._last_sent_values.get(ref) != value:
            self._last_sent_values[ref] = value
            getattr(self.datarefs.prosim, ref).value = value
            print(f"Set value {ref} to: {value}")  # Debug output
                               
    async def update(self):
        efis_num = 2
        efis = self.vars.EFIS_FO

        match efis.BUTTONS_275.value:
            case 8192:
                self.send_key_value(f"S_MCP_EFIS{efis_num}_MODE", 0)
            case 16384:
                self.send_key_value(f"S_MCP_EFIS{efis_num}_MODE", 1)
            case 32768:
                self.send_key_value(f"S_MCP_EFIS{efis_num}_MODE", 2)
            case 65536:
                self.send_key_value(f"S_MCP_EFIS{efis_num}_MODE", 3)

        # EFIS baro momentary [0:Center, 1:Up, 2:Down, 3:Up fast, 4:Down fast]
        if efis.BUTTONS_274.OFF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO", 0)
        if efis.BUTTONS_274.UP_SLOW:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO", 1)
        if efis.BUTTONS_274.DOWN_SLOW:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO", 2)
        if efis.BUTTONS_274.UP_FAST:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO", 3)
        if efis.BUTTONS_274.DOWN_FAST:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO", 4)

        # EFIS minimums momentary [0:Center, 1:Up, 2:Down, 3:Up fast, 4:Down fast]
        if efis.BUTTONS_273.OFF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS", 0)
        if efis.BUTTONS_273.UP_SLOW:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS", 1)
        if efis.BUTTONS_273.DOWN_SLOW:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS", 2)
        if efis.BUTTONS_273.UP_FAST:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS", 3)
        if efis.BUTTONS_273.DOWN_FAST:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS", 4)

        self.send_key_value(f"S_MCP_EFIS{efis_num}_WXR", efis.BUTTONS_275.WRX)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_STA", efis.BUTTONS_275.STA)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_WPT", efis.BUTTONS_275.WPT)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_ARPT", efis.BUTTONS_275.ARPT)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_DATA", efis.BUTTONS_275.DATA)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_POS", efis.BUTTONS_275.POS)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_CTR", efis.BUTTONS_275.CTR)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_TERR", efis.BUTTONS_273.TERR)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS_RESET", efis.BUTTONS_273.RST)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO_STD", efis.BUTTONS_274.STD)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_TFC", efis.BUTTONS_275.TFC)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_FPV", efis.BUTTONS_275.FPV)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_MTRS", efis.BUTTONS_275.MTRS)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO_MODE", efis.BUTTONS_274.BARO_IN)
        self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS_MODE", efis.BUTTONS_273.MIN_BARO)

        if efis.RANGE.five:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 0)
        if efis.RANGE.ten:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 1)
        if efis.RANGE.twenty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 2)
        if efis.RANGE.forty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 3)
        if efis.RANGE.eighty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 4)
        if efis.RANGE.onesixty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 5)
        if efis.RANGE.threetwenty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 6)
        if efis.RANGE.sixfourty:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_RANGE", 7)

        if efis.BUTTONS_273.MIN_RADIO:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS_MODE", 0)

        if efis.BUTTONS_273.MIN_BARO:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_MINIMUMS_MODE", 1)

        if efis.BUTTONS_274.BARO_IN:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO_MODE", 0)

        if efis.BUTTONS_274.BARO_HPA:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_BARO_MODE", 1)

        if efis.BUTTONS_273.VOR1_VOR:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL1", 1)

        if efis.BUTTONS_273.VOR1_ADF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL1", 2)

        if not efis.BUTTONS_273.VOR1_VOR and not efis.BUTTONS_273.VOR1_ADF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL1", 0)

        if efis.BUTTONS_274.VOR2_VOR:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL2", 1)

        if efis.BUTTONS_274.VOR2_ADF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL2", 2)

        if not efis.BUTTONS_274.VOR2_VOR and not efis.BUTTONS_274.VOR2_ADF:
            self.send_key_value(f"S_MCP_EFIS{efis_num}_SEL2", 0)

        await asyncio.sleep(0.01)
