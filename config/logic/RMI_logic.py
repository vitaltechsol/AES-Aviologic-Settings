import asyncio
import datetime
import math
import time


def smooth_angle(current, target, dt, speed=5.0):
    """
    Smooths angle interpolation to prevent choppy movement.
    Uses time-based exponential decay so the rate of rotation is 
    independent of frame rate. speed regulates how fast the needle catches up.
    """
    if current is None:
        return target
    diff = (target - current + 180) % 360 - 180
    return (current + diff * (1.0 - math.exp(-speed * dt))) % 360


class Logic:
    def __init__(self):
        self.version = "v1.0.1"
        self.last_log_time = time.time()
        self.last_update_time = time.time()
        self.last_raw_heading = None
        self.sm_hdg = None
        self.sm_adf1 = None
        self.sm_vor1 = None
        self.sm_adf2 = None
        self.sm_vor2 = None

    async def update(self):

        # prosim datarefs
        ps = self.datarefs.prosim
        heading = ps.IRS1_TRACK.value  # Heading in degrees, 0-360
        irs_aligning = ps.IRS1_ALIGNING.value # for heading flag
        heading_flag = ps.IRS1_HEADING_FLAG.value # for heading flag

        # Check for NaN values and set to 0
        if math.isnan(heading):
            heading = 0

        # Calculate delta time for time-based smoothing
        current_time = time.time()
        dt = current_time - self.last_update_time
        if dt > 0.5:
            dt = 0.5  # Cap dt to avoid large jumps if thread stalls

        self.last_update_time = current_time

        # Apply low-pass filter to smooth the heading over frames
        self.sm_hdg = smooth_angle(self.sm_hdg, heading, dt, speed=3.0)

        # Set magnetic heading in degrees.
        self.vars.rmi_irs.hdg_m.value = self.sm_hdg

        # Heading flag
        self.vars.rmi_irs.hdg_m.ssm = 0 if irs_aligning == True or heading_flag == True else 3
        self.vars.vor_adf1.vor_bear.ssm = 3 # hide flag
        self.vars.vor_adf2.vor_bear.ssm = 3 # hide flag
        self.vars.vor_adf1.adf_bear.ssm = 3 # hide flag
        self.vars.vor_adf2.adf_bear.ssm = 3 # hide flag

        # Set VOR and ADF bearings in degrees. These values
        # are absolute bearings to the stations, not relative to the aircraft heading.
        adf1_bearing = ps.NAV_ADF_1_BEARING.value
        vor1_bearing = ps.NAV_VOR_1_BEARING.value
        adf2_bearing = ps.NAV_ADF_2_BEARING.value
        vor2_bearing = ps.NAV_VOR_2_BEARING.value

        # Check for NaN values and set to 0
        if math.isnan(adf1_bearing):
            adf1_bearing = 0
            self.vars.vor_adf1.adf_bear.ssm = 0 # show flag
        if math.isnan(vor1_bearing):
            vor1_bearing = 0
            self.vars.vor_adf1.vor_bear.ssm = 0 # show flag
        if math.isnan(adf2_bearing):
            adf2_bearing = 0
            self.vars.vor_adf2.adf_bear.ssm = 0 # show flag
        if math.isnan(vor2_bearing):
            vor2_bearing = 0
            self.vars.vor_adf2.vor_bear.ssm = 0 # show flag

        # Smooth VOR and ADF needles using time-based math
        self.sm_adf1 = smooth_angle(self.sm_adf1, adf1_bearing + heading, dt, speed=3.0)
        self.sm_vor1 = smooth_angle(self.sm_vor1, vor1_bearing + heading, dt, speed=3.0)
        self.sm_adf2 = smooth_angle(self.sm_adf2, adf2_bearing + heading, dt, speed=3.0)
        self.sm_vor2 = smooth_angle(self.sm_vor2, vor2_bearing + heading, dt, speed=3.0)

        self.vars.vor_adf1.adf_bear.value = self.sm_adf1
        self.vars.vor_adf1.vor_bear.value = self.sm_vor1
        self.vars.vor_adf2.adf_bear.value = self.sm_adf2
        self.vars.vor_adf2.vor_bear.value = self.sm_vor2

        now_str = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]

        # 1. Log whenever ProSim gives us a new heading (shows ProSim's native update rate)
        if heading != self.last_raw_heading:
            if self.last_raw_heading is not None:
                pass # remove redundant print for now to reduce log clutter
            self.last_raw_heading = heading

        # 2. Periodically log sample data
        if current_time - self.last_log_time >= 1.0:
            # print(f"[{now_str}] 1-SEC SAMPLE -> SmHdg: {self.sm_hdg:.2f} (Raw: {heading:.2f})")
            self.last_log_time = current_time

        # ----- User Space END -----
  
