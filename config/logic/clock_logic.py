
import asyncio
from datetime import datetime, timezone


class Logic:
    def __init__(self):
        # Logic version. Only use to track changes if necessary
        self.version = "v1.0.0"

        # Enable/Disable this logic file
        # When False, this logic will not be started
        self.is_enable = True
                               
    async def update(self):
        # self.vars.clock.mest3k.packet = 0x70300c
        # self.vars.clock.utc3x.packet = 0x550a0aa
        # self.vars.clock.utcf3x.packet = 0x68682b06
        # self.vars.clock.utff3x.packet = 0x66280086
        # self.vars.clock.utc3.packet = 0x67d58416
        # self.vars.clock.date3x.packet = 0x1046400d
        # self.vars.clock.utc3.packet = 0x65d58202 ## 11:42
        # self.vars.clock.date3x.packet = 0x67d58416 
        # self.vars.clock.date3x.value = 202005.0
        # self.vars.clock.gss3d.packet = 0x64408dd
        # self.vars.clock.cmdwordback.packet = 0x3e00b7
        # self.vars.clock.e13.packet = 0x2cff
        # self.vars.clock.date3x.packet = 0x1046400d

        
        current_time = datetime.now(timezone.utc)
        hours = current_time.hour
        minutes = current_time.minute
        seconds = current_time.second
                        
        # Parity + SSM (00 if no gps)
        value1 = 0b0000 if self.datarefs.prosim.I_OH_GPS.value >= 1 else 0b0110
        # hour
        value2 = int(bin(hours)[2:], 2)
        # minutes
        value3 = int(bin(minutes)[2:], 2)
        # seconds
        value4 = int(bin(seconds)[2:], 2) 
        # FL + SDI
        value5 = 0b100         
        # 8 bits
        value6 = 0b00000000                

        combined = (
            (value1 << 28) | 
            (value2 << 23) | 
            (value3 << 17) | 
            (value4 << 11) | 
            (value5 << 8)  | 
            value6           
        )
        # Example: 01101011111101100000010000000000

        print("combined")
        print(combined)

        self.vars.clock.utc3.packet = combined
        self.vars.clock.date3x.packet = 0x1046400d

        await asyncio.sleep(0.50)
