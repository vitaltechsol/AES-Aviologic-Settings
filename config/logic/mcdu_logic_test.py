import asyncio
from resources.libs.arinc_lib.arinc_lib import ArincLabel
import time
from enum import Enum
from typing import Callable

# Setup Definitions
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3


class MCDU:
    class ArgumentException(Exception):
        pass

    class Subsystem:
        COL: int = 24
        ROW: int = 14

        def __init__(self, sal_octal: int):
            # self._sal = _label_base_reverse_mask(
            #     _label_base_octal_to_decimal(sal_octal)
            # )

            self._sal = sal_octal
            self._block = []

        def _apply_par(self, label: int) -> int:
            label = label & 0x7FFFFFFF
            label |= ArincLabel.Base._parity(label) << 31
            return label

        def _char_label(self, sal: int, char: int, control: int = 0x0) -> int:
            char_base = sal | 0x300
            return self._apply_par(
                char_base | ((char & 0x7F) << 13) | ((control & 0x1FF) << 20)
            )

        def add_text(self, offset: int, text: str, color: int = 0, control: int = 0):
            block_base = self._sal | 0x400
            block2_base = block_base | 0x40000

            if offset <= 0:
                raise Exception("Offset should be bigger than 0")

            self._block += [
                # Text block open - Specifies the offset
                self._apply_par(block_base | (offset << 13)),
                # Text block configuration
                self._apply_par(block2_base | ((color & 0x1FF) << 20)),
            ]

            if len(text) > 0:
                self._block += [
                    self._char_label(self._sal, c, control)
                    for c in text.encode("iso-8859-5")
                ]

    class LightsEnum(Enum):
        """Enumeration for front light indicators"""

        FAIL = 0x2000
        MSG = 0x8000
        OFFSET = 0x10000
        EXEC = 0x20000

    class KeypadEnum(Enum):
        """Enumeration for all panel Buttons"""

        INIT = 0xC0
        RTE = 0xB0
        CLB = 0xA0
        CRZ = 0x90
        DES = 0x80
        LEGS = 0xB2
        DEP_ARR = 0xA2
        HOLD = 0x92
        PROG = 0x82
        EXEC = 0x72
        N1_LIMIT = 0x6A
        FIX = 0xC4
        A = 0xB4
        B = 0xA4
        C = 0x94
        D = 0x84
        E = 0x74
        PREV_PAGE = 0x6C
        NEXT_PAGE = 0xC6
        F = 0xB6
        G = 0xA6
        H = 0x96
        I = 0x86
        J = 0x76
        ONE = 0xEE
        TWO = 0xDE
        THREE = 0xCE
        K = 0xBE
        L = 0xAE
        M = 0x9E
        N = 0x8E
        O = 0x7E
        FOUR = 0xEC
        FIVE = 0xDC
        SIX = 0xCC
        P = 0xBC
        Q = 0xAC
        R = 0x9C
        S = 0x8C
        T = 0x7C
        SEVEN = 0xEA
        EIGHT = 0xDA
        NINE = 0xCA
        U = 0xBA
        V = 0xAA
        W = 0x9A
        X = 0x8A
        Y = 0x7A
        DOT = 0xE8
        ZERO = 0xD8
        PLUS_MINUS = 0xC8
        Z = 0xB8
        SPACE = 0xA8
        DELETE = 0x98
        SLASH = 0x88
        CLEAR = 0x6E
        LINE_LEFT_1 = 0xF4
        LINE_LEFT_2 = 0xF6
        LINE_LEFT_3 = 0xE4
        LINE_LEFT_4 = 0xE6
        LINE_LEFT_5 = 0xD4
        LINE_LEFT_6 = 0xD6
        LINE_RIGHT_1 = 0xF2
        LINE_RIGHT_2 = 0xF0
        LINE_RIGHT_3 = 0xE2
        LINE_RIGHT_4 = 0xE0
        LINE_RIGHT_5 = 0xD2
        LINE_RIGHT_6 = 0xD0

    def __init__(
        self,
        arinc_device: object,
        tx_chnl_number: int,
        rx_chnl_number: int,
        key_callback: Callable = None,
    ):
        self._device = arinc_device
        self._tx_chnl = tx_chnl_number
        self._rx_chnl = rx_chnl_number
        self._key_cb = key_callback
        self._subsystem = {}

        # Labels buffer to send to the panel
        self._tx_buffer = []

        # Get reference to receiving queue. This is to make things faster
        self._rx_queue = self._device._rx_chnl[self._rx_chnl]._label_queue

        # Ready to update subsystems flag
        self._trig_update = False

        self._light_bitmap = 0

        self._sal = 0x04

    def _apply_par(self, label: int) -> int:
        label = label & 0x7FFFFFFF
        label |= ArincLabel.Base._parity(label) << 31
        return label

    def _char_label(self, sal: int, char: int, control: int = 0x0) -> int:
        char_base = sal | 0x300
        return self._apply_par(
            char_base | ((char & 0x7F) << 13) | ((control & 0x1FF) << 20)
        )

    def _init_frame(self, light_status: int):
        scratchpad_base = self._sal | 0x200
        lights_base = self._sal | 0x100
        offset = 312

        self._tx_buffer = [
            0x0,
            self._apply_par(scratchpad_base | (offset << 13)),
        ]
        null_char = self._char_label(self._sal, 0x40)
        self._tx_buffer += [null_char] * 24
        self._tx_buffer += [
            self._apply_par(lights_base | light_status),  # << Lights bits here
            self._apply_par(scratchpad_base),
        ]

    def _close_frame(self) -> list:
        # Apply head of the entire frame. Specifies the size of the entire frame
        self._tx_buffer[0] = self._apply_par(self._sal | (len(self._tx_buffer) << 13))
        # Add end of frame label and return the list of labels to send to teh unit
        return self._tx_buffer + [self._apply_par(self._sal | 0x00001F00)]

    def _key_decode(self, label: int):
        try:
            key_enum = self.KeypadEnum((label >> 12) & 0xFF)
        except:
            # Is not a key so pass here
            pass
        else:
            if self._key_cb is not None:
                self._key_cb(key_enum.name)
                # print(hex(label), key_enum.name)

    def add_subsystem(self, name: str, id_octal: int):
        self._subsystem[name] = MCDU.Subsystem(id_octal)
        return self._subsystem[name]

    def set_light(self, light: LightsEnum, status: int | bool):
        """Set given indicator status. The status is ON or OFF.

        Args:
            indicator (LightsEnum): indicator Enum
            status (int | bool): Status of the indicator. On or OFF. The value
                                can be an integer 1/0 or a boolean True/False
        """

        if isinstance(status, (int, bool)) == False:
            raise self.ArgumentException(
                "The indicator status value type should be an int or boolean"
            )

        self._light_bitmap &= ~light.value
        if bool(status):
            self._light_bitmap |= light.value

    def loop(self):
        """HUD main update loop.
        This method should be called periodically as fast ast possible within the Logic loop
        """
        # The loop should run only if the arinc card is online
        if self._device.is_ready:
            # Consume all received labels from HUD channel
            while True:
                try:
                    label, _ = self._rx_queue.popleft()
                except Exception as e:
                    # No element in the queue... then skip
                    break
                else:
                    p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                    # print(
                    #     f"[{oct(label_id)}]({label_id}) {(label & 0x7FFFFF00):8X} {sdi}"
                    # )
                    if label_id == 4:
                        self._key_decode(label)
                        self._trig_update = True

            # Update subsystems only if the panel has reported back
            if self._trig_update:
                self._trig_update = False

                self._init_frame(self._light_bitmap)

                for _, subsystem in self._subsystem.items():

                    self._tx_buffer += subsystem._block
                    subsystem._block = []

                    file = self._close_frame()
                    # print(file)

                    lwc = []
                    for l in file:
                        lwc.append((ARINC_CARD_TX_CHNL, l))

                    # print(lwc)

                    """Update panel sending the TX buffer"""
                    try:
                        self._device.send_manual_list_fast(lwc)
                    except Exception:
                        pass


class Logic:
    def __init__(self):
        self.version = "v2.1.0"

        self.mcdu = MCDU(
            arinc_device=self.devices[ARINC_CARD_NAME],
            tx_chnl_number=ARINC_CARD_TX_CHNL,
            rx_chnl_number=ARINC_CARD_RX_CHNL,
            key_callback=self.key_pressed_callback,
        )

        self.tprev = time.time()
        self.test_label_increment = 0x00
        self.aux = 1

    def key_pressed_callback(self, name):
        print(name)

    async def update(self):
        self.mcdu.loop()

        if (time.time() - self.tprev) > 1.0:
            self.test_label_increment += 1
            print("trigger", hex(self.test_label_increment))
            self.tprev = time.time()
            self.aux <<= 1
            if self.aux > 1024:
                self.aux = 1

        # ----- TEST ZERO - START -----
        # Title: Make sure new code works as intended.
        # Description:
        # Simple print of information of the screen. Note that the screen has not
        # been cleaned so random characters will appear.
        # Uncomment here:
        # self.fmc_subsys = self.mcdu.add_subsystem("fmc", 0x04)
        # self.fmc_subsys.add_text(1, "Test Zero              ")
        # self.fmc_subsys.add_text(1, "Just see if works")
        # self.mcdu.set_light(MCDU.LightsEnum.MSG, True)

        # ----- TEST ZERO - END -----

        # ----- TEST ONE - START -----
        # Title: Check if color shows up, attempt 1!
        #
        # Uncomment here:
        # self.fmc_subsys = self.mcdu.add_subsystem("fmc", 0x04)
        # self.fmc_subsys.add_text(1, "Test One               ")
        # self.fmc_subsys.add_text(1, f"Setting: 0x{self.aux:03X}         ")
        # self.fmc_subsys.add_text(1, "Color", color=self.aux)
        # self.fmc_subsys.add_text(1, str(self.test_label_increment) + "          ")

        # ----- TEST ONE - END -----

        # ----- TEST TWO - START -----
        # Title: Check if color shows up, attempt 2!
        #
        # Uncomment here:
        self.fmc_subsys = self.mcdu.add_subsystem("fmc", 0x04)
        self.fmc_subsys.add_text(1, "Test Two               ")
        self.fmc_subsys.add_text(1, f"Setting: 0x{self.aux:03X}         ")
        self.fmc_subsys.add_text(1, "aux " + str(self.aux)+ "                 ")
        self.fmc_subsys.add_text(1, "Color", control=self.aux)
        self.fmc_subsys.add_text(1, str(self.test_label_increment) + "          ")
        

        # ----- TEST TWO - END -----

        # ----- TEST THREE - START -----
        # Title: Check is another subsystem shows up, attempt 1
        # Description:
        # To try to see if subsystems are represented by other labels, a scan will
        # be taking place.
        # Procedure:
        # 1. Reload and Stop the script
        # 2. Wait until MCDU shows menu in display
        # 3. Start Script and stare at the screen
        # 4. When a subsystems shows up it will be shown as an entry for a few seconds
        #    Note: During the process FMC subsystem will show up
        # NOTE: The test last 4 minutes 19 seconds exactly until the full scan is done.
        # Uncomment here:
        # self.fmc_subsys = self.mcdu.add_subsystem("fmc", self.test_label_increment)
        # self.fmc_subsys.add_text(1, "Test Three")

        # ----- TEST THREE - END -----

        # ----- TEST FOUR - START -----
        # Title: Check is another subsystem shows up, attempt 2
        # Description:
        # To try to see if subsystems are represented by other labels, a scan will
        # be taking place.
        # Procedure:
        # 1. Reload and Stop the script
        # 2. Wait until MCDU shows menu in display
        # 3. Start Script and stare at the screen
        # 4. When a subsystems shows up it will be shown as an entry for a few seconds
        #    Note: During the process FMC subsystem will show up
        # NOTE: The test last 4 minutes 19 seconds exactly until the full scan is done.
        # Uncomment here:
        # self.mcdu._sal = self.test_label_increment
        # self.fmc_subsys = self.mcdu.add_subsystem("fmc", self.test_label_increment)
        # self.fmc_subsys.add_text(1, "Test Four")

        # ----- TEST FOUR - END -----

        # time.sleep(1)

      