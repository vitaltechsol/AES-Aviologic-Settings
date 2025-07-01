
import asyncio
from datetime import datetime, timezone


class Logic:
    def __init__(self):
        # Logic version. Only use to track changes if necessary
        self.version = "v1.0.0"

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
             
        match self.vars.EFIS.BUTTONS_275.value:
            case 8192:
              self.send_key_value("S_MCP_EFIS1_MODE", 0)  
            case 16384:
              self.send_key_value("S_MCP_EFIS1_MODE", 1)  
            case 32768:
              self.send_key_value("S_MCP_EFIS1_MODE", 2)  
            case 65536:
              self.send_key_value("S_MCP_EFIS1_MODE", 3)  

        print("EFIS RANGE BARO")
        print(self.vars.EFIS.BUTTONS_274.value)

        #EFIS 1 baro momentary [0:Center, 1:Up, 2:Down, 3:Up fast, 4:Down fast]
        match self.vars.EFIS.BUTTONS_274.value:
            case 528:
                self.send_key_value("S_MCP_EFIS1_BARO", 0)  
            case 514:
                self.send_key_value("S_MCP_EFIS1_BARO", 1)  
            case 520:
                self.send_key_value("S_MCP_EFIS1_BARO", 2)  
            case 513:
                self.send_key_value("S_MCP_EFIS1_BARO", 3) 
            case 516:
                self.send_key_value("S_MCP_EFIS1_BARO", 4)


        #EFIS 1 minimums momentary [0:Center, 1:Up, 2:Down, 3:Up fast, 4:Down fast]
        match self.vars.EFIS.BUTTONS_273.value:
            case 8192:
                self.send_key_value("S_MCP_EFIS1_MINIMUMS", 0)  
            case 16384:
                self.send_key_value("S_MCP_EFIS1_MINIMUMS", 1)  
            case 32768:
                self.send_key_value("S_MCP_EFIS1_MINIMUMS", 2)  
            case 65536:
                self.send_key_value("S_MCP_EFIS1_MINIMUMS", 3) 

        self.send_key_value("S_MCP_EFIS1_WXR", self.vars.EFIS.BUTTONS_275.WRX)
        self.send_key_value("S_MCP_EFIS1_STA", self.vars.EFIS.BUTTONS_275.STA) 
        self.send_key_value("S_MCP_EFIS1_WPT", self.vars.EFIS.BUTTONS_275.WPT)
        self.send_key_value("S_MCP_EFIS1_ARPT", self.vars.EFIS.BUTTONS_275.ARPT) 
        self.send_key_value("S_MCP_EFIS1_DATA", self.vars.EFIS.BUTTONS_275.DATA) 
        self.send_key_value("S_MCP_EFIS1_POS", self.vars.EFIS.BUTTONS_275.POS) 
        self.send_key_value("S_MCP_EFIS1_TERR", self.vars.EFIS.BUTTONS_273.TERR)
        self.send_key_value("S_MCP_EFIS1_MINIMUMS_RESET", self.vars.EFIS.BUTTONS_273.RST)
        self.send_key_value("S_MCP_EFIS1_BARO_STD", self.vars.EFIS.BUTTONS_274.STD) 
        self.send_key_value("S_MCP_EFIS1_CTR", self.vars.EFIS.BUTTONS_275.CTR)
        self.send_key_value("S_MCP_EFIS1_TFC", self.vars.EFIS.BUTTONS_275.TFC)
        self.send_key_value("S_MCP_EFIS1_FPV", self.vars.EFIS.BUTTONS_275.FPV)
        self.send_key_value("S_MCP_EFIS1_MTRS", self.vars.EFIS.BUTTONS_275.MTRS)
        self.send_key_value("S_MCP_EFIS1_BARO_MODE", self.vars.EFIS.BUTTONS_274.BARO_IN)
        self.send_key_value("S_MCP_EFIS1_MINIMUMS_MODE", self.vars.EFIS.BUTTONS_273.MIN_BARO)
            
        match self.vars.EFIS.RANGE.value:
            case 8:
              self.send_key_value("S_MCP_EFIS1_RANGE", 0)  
            case 16:
              self.send_key_value("S_MCP_EFIS1_RANGE", 1) 
            case 0:
              self.send_key_value("S_MCP_EFIS1_RANGE", 2)               
            case 32:
              self.send_key_value("S_MCP_EFIS1_RANGE", 3)  
            case 64:
              self.send_key_value("S_MCP_EFIS1_RANGE", 4)  
            case 128:    
              self.send_key_value("S_MCP_EFIS1_RANGE", 5)  
            case 512:    
              self.send_key_value("S_MCP_EFIS1_RANGE", 6)
            case 1024:    
              self.send_key_value("S_MCP_EFIS1_RANGE", 7)

        if self.vars.EFIS.BUTTONS_273.VOR1_VOR:
            self.send_key_value("S_MCP_EFIS1_SEL1", 1)

        if self.vars.EFIS.BUTTONS_273.VOR1_ADF:
            self.send_key_value("S_MCP_EFIS1_SEL1", 2)

        if not self.vars.EFIS.BUTTONS_273.VOR1_VOR and not self.vars.EFIS.BUTTONS_273.VOR1_ADF:
            self.send_key_value("S_MCP_EFIS1_SEL1", 0)

        if self.vars.EFIS.BUTTONS_274.VOR2_VOR:
            self.send_key_value("S_MCP_EFIS1_SEL2", 1)

        if self.vars.EFIS.BUTTONS_274.VOR2_ADF:
            self.send_key_value("S_MCP_EFIS1_SEL2", 2)

        if not self.vars.EFIS.BUTTONS_274.VOR2_VOR and not self.vars.EFIS.BUTTONS_274.VOR2_ADF:
            self.send_key_value("S_MCP_EFIS1_SEL2", 0)

        await asyncio.sleep(0.05)
