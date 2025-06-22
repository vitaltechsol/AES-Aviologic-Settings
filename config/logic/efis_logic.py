
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
     
        # print("EFITS ND mode")
        # print(self.vars.EFIS.ND_MODE.value)
        
        match self.vars.EFIS.ND_MODE.value:
            case 8192:
              self.send_key_value("S_MCP_EFIS1_MODE", 0)  
            case 16384:
              self.send_key_value("S_MCP_EFIS1_MODE", 1)  
            case 32768:
              self.send_key_value("S_MCP_EFIS1_MODE", 2)  
            case 65536:
              self.send_key_value("S_MCP_EFIS1_MODE", 3)  


        # for key, value in self.vars.EFIS.ND_MODE.items():
        #     print(f"{key}: {value}")

        # self.vars.clock.utc3.packet = combined
        # self.vars.clock.date3x.packet = 0x1046400d

        await asyncio.sleep(0.50)
