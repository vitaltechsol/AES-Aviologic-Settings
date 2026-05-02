import asyncio
from enum import Enum
from resources.libs.arinc_lib import arinc_lib

# Setup Definitions
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 2

# Annunciator label octal address
ANNUNCIATOR_LABEL_OCT: int = 270


class AnnunciatorEnum(Enum):
    """Enumeration for HGS annunciator bits.
    Bit values correspond to the hardware ARINC label data field.
    """
    AIII    = 0x01  # Panel AIII
    NOAIII  = 0x02  # Panel NO AIII
    FLARE   = 0x04  # Panel FLARE
    DASH    = 0x08  # Panel Dash
    
    RO      = 0x10  # Panel RO 
    ROCTN   = 0x20  # Panel RO CTN
    ROARM   = 0x40  # Panel RO ARM
    TO_RED  = 0x80  # Panel TO RED    

    TO_GRN  = 0x100  # Panel TO  Green
    TOCTN   = 0x200  # Panel TO CTN
    APP     = 0x400 # Panel APCH
    WARN    = 0x800 # Panel TO WARN
       
    HGSFAIL = 0x2000 # Panel HGS FAIL

def _build_annunciator_label(bitmap: int, tx_chnl: int) -> list:
    """Build a single ARINC label with all annunciator bits ORed together.
    Parity is calculated and applied so the panel accepts the label without blinking.

    Args:
        bitmap (int): OR-combination of AnnunciatorEnum values to illuminate
        tx_chnl (int): TX channel number to send on

    Returns:
        list: List of (channel, label) tuples ready for send_manual_list_fast
    """
    lab = arinc_lib.ArincLabel.Base.pack_oct(ANNUNCIATOR_LABEL_OCT, 0, 0, bitmap)
    lab = lab | (arinc_lib.ArincLabel.Base._parity(lab) << arinc_lib.ArincLabel.Base.PACKET_PARITY_POS)
    return [(tx_chnl, lab)]


class Logic:

    def __init__(self):
        self.version = "v1.1.0"

        self._device = self.devices[ARINC_CARD_NAME]

        # Bitmap holding all annunciators that should be illuminated.
        # OR in AnnunciatorEnum values to turn on, mask out to turn off.
        self._annunciator_bitmap: int = 0

    def set_annunciator(self, annunciator: AnnunciatorEnum, status: bool):
        """Turn an annunciator on or off.

        Args:
            annunciator (AnnunciatorEnum): The annunciator to control
            status (bool): True = on, False = off
        """
        self._annunciator_bitmap &= ~annunciator.value
        if status:
            self._annunciator_bitmap |= annunciator.value

    async def update(self):

        # ----- User Space START -----

        # Set each annunciator state from prosim datarefs
        self.set_annunciator(AnnunciatorEnum.AIII,    self.datarefs.prosim.I_HGS_AP_AIII.value == 2)
        self.set_annunciator(AnnunciatorEnum.NOAIII,  self.datarefs.prosim.I_HGS_AP_NOAIII.value == 2)
        self.set_annunciator(AnnunciatorEnum.FLARE,   self.datarefs.prosim.I_HGS_AP_FLARE.value == 2)

        self.set_annunciator(AnnunciatorEnum.RO,   self.datarefs.prosim.I_HGS_AP_RO.value == 2)
        self.set_annunciator(AnnunciatorEnum.ROCTN,   self.datarefs.prosim.B_LIGHT_TEST.value == 2) # -- Missing
        self.set_annunciator(AnnunciatorEnum.ROARM,   self.datarefs.prosim.I_HGS_AP_ROARM.value == 2)
        self.set_annunciator(AnnunciatorEnum.TO_RED,  self.datarefs.prosim.I_HGS_AP_TOWARN.value == 2)
        if (self.datarefs.prosim.I_HGS_AP_TOWARN.value == 2):
            self.set_annunciator(AnnunciatorEnum.WARN,  True)

        self.set_annunciator(AnnunciatorEnum.TO_GRN, self.datarefs.prosim.I_HGS_AP_TO.value == 2)
        self.set_annunciator(AnnunciatorEnum.TOCTN,   self.datarefs.prosim.I_HGS_AP_TOCTN.value == 2)
        self.set_annunciator(AnnunciatorEnum.APP,  self.datarefs.prosim.I_HGS_AP_APP.value == 2)
        if (self.datarefs.prosim.I_HGS_AP_APP.value == 2):
             self.set_annunciator(AnnunciatorEnum.WARN,  True)

        if (self.datarefs.prosim.I_HGS_AP_TOWARN.value == 0 and self.datarefs.prosim.I_HGS_AP_APP.value == 0):
            self.set_annunciator(AnnunciatorEnum.WARN,  False)

        self.set_annunciator(AnnunciatorEnum.DASH, self.datarefs.prosim.B_LIGHT_TEST.value == 1)
        self.set_annunciator(AnnunciatorEnum.HGSFAIL, self.datarefs.prosim.I_HGS_AP_HGSFAIL.value == 2)


        # ----- User Space END -----

        # Build one label with all active annunciator bits and send it only if device is ready
        if self._device.is_ready:
            labels = _build_annunciator_label(self._annunciator_bitmap, ARINC_CARD_TX_CHNL)
            self._device.send_manual_list_fast(labels)

        await asyncio.sleep(0.05)