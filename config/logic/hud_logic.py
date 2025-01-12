""" Head Up Display control panel Logic script

Author: Lucas M. Angarola (737goodness@gmail.com)
LICENSE: GPLv2

This script implements an API to interface the HUD control panel from Flight Dynamics.
The script also binds the HUD inputs/outputs to Prosim datarefs.

- Getting Started

1. Configuring the Arinc Card
To be able to talk with the HUD we need 2 channels. One Transmitting and one Receiving.
a. Open the arinc device configuration
b. Select any free TX channel
c. Select mode: Manual
d. Select speed: 12.5KHz
e. Select enable channel
f. Select any free RX channel
g. Select mode: Normal
h. Select speed: 100Khz
i. Select enable channel

2. Script Definitions
The scripts needs to know which arinc card should use and also which channel numbers on this card.
The following defines should be modified according to your setup:
ARINC_CARD_NAME: String to set the card name as per configured under device configuration
ARINC_CARD_TX_CHNL: Integer to set transmitting channel number. This is a number from 0 to 3.
                    This number is as per specified under device configuration
ARINC_CARD_RX_CHNL: Integer to set receiving channel number. This is a number from 0 to 3.
                    This number is as per specified under device configuration.

Change Log:
v1.0.0
- Initial Release

v1.1.0
- Send data to panel only when panel reports alive
- Implement panel Timeout

v1.2.0
- Send additional labels to extinguish FAULT signal.
"""

import asyncio
from enum import Enum
from time import time
from resources.libs.arinc_lib.arinc_lib import ArincLabel
import queue

# Setup Definitions
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 1


class HUD:
    """_summary_

    Raises:
        Exception: _description_
        Exception: _description_

    Returns:
        _type_: _description_
    """

    class Display:
        """_summary_

        Raises:
            Exception: _description_

        Returns:
            _type_: _description_
        """

        DISP_COL: int = 8
        DISP_ROW: int = 4
        line_id = [21, 41, 61, 101]

        class Label:
            """_summary_

            Raises:
                Exception: _description_

            Returns:
                _type_: _description_
            """

            CHAR_MSB_POS: int = 11
            CHAR_MSB_MASK: int = 0x0007F800
            CHAR_LSB_POS: int = 3
            CHAR_LSB_MASK: int = 0x000007F8

            class Char:
                """_summary_"""

                def __init__(self, parent: "HUD.Display.Label", position: str):
                    self._parent = parent
                    self._value = 0x20
                    if position == "MSB":
                        self._data_mask = HUD.Display.Label.CHAR_MSB_MASK
                        self._data_pos = HUD.Display.Label.CHAR_MSB_POS
                    elif position == "LSB":
                        self._data_mask = HUD.Display.Label.CHAR_LSB_MASK
                        self._data_pos = HUD.Display.Label.CHAR_LSB_POS
                    else:
                        raise Exception(f'Char position "{position}" not recognized')

                @property
                def value(self) -> int:
                    return self._value

                @value.setter
                def value(self, value: int):
                    if value != self._value:
                        # print(value, hex(self._parent.data))
                        self._parent.data = (self._parent.data & (~self._data_mask)) | (
                            (value << self._data_pos) & self._data_mask
                        )
                        self._value = value

            def __init__(self, row: int, column: int):
                octal = HUD.Display.line_id[row] + column
                self._label = ArincLabel.Base.pack_oct(octal, 0x3, 0x0, 0x10100)
                self._data_mask = (
                    ArincLabel.Base.PACKET_DATA_MASK << 3
                ) & ArincLabel.Base.PACKET_DATA_MASK

                self._data_reset = ~(
                    self._data_mask | ArincLabel.Base.PACKET_PARITY_MASK
                )
                # print(hex(self._data_reset))
                self._data_changed = True
                self._msb_char = HUD.Display.Label.Char(self, "MSB")
                self._lsb_char = HUD.Display.Label.Char(self, "LSB")

            @property
            def label(self) -> int:
                self._data_changed = False
                return self._label

            @property
            def changed(self) -> bool:
                return self._data_changed

            @property
            def data(self) -> int:
                return (
                    self._label & ArincLabel.Base.PACKET_DATA_MASK
                ) >> ArincLabel.Base.PACKET_DATA_POS

            @data.setter
            def data(self, data: int):
                label = (self._label & self._data_reset) | (
                    (data << ArincLabel.Base.PACKET_DATA_POS) & self._data_mask
                )
                self._label = label | (
                    ArincLabel.Base._parity(label) << ArincLabel.Base.PACKET_PARITY_POS
                )
                self._data_changed = True

        def __init__(self):
            self._labels = []
            self._buffer = []
            for i in range(self.DISP_ROW):
                label_line = []
                disp_line = []
                for j in range(4):
                    l = HUD.Display.Label(i, j)
                    label_line.append(l)
                    disp_line.append(l._lsb_char)
                    disp_line.append(l._msb_char)
                self._buffer.append(disp_line)
                self._labels.append(label_line)

        def get_labels(self, always: bool = True) -> list:
            labels = []
            for i in range(self.DISP_ROW):
                for j in range(4):
                    l = self._labels[i][j]
                    if l.changed or always:
                        labels.append((3, self._labels[i][j].label))
            return labels

        def write_str(self, row: int, column: int, text: str):
            col = column
            text = text.replace('\xb0', '*') #replace degrees symbol
            for char in text.encode("iso-8859-5"):
                if col >= HUD.Display.DISP_COL:
                    break
         
                self._buffer[row][col].value = int(char)
                col += 1

        def write(self, row: int, column: int, data: bytearray):
            col = column
            for char in data:
                if col >= HUD.Display.DISP_COL:
                    break
                self._buffer[row][col].value = int(char)
                col += 1

    class IndicatorEnum(Enum):
        """Enumeration for LED indicators"""

        LED_RWY = 0x00800000
        LED_GS = 0x01000000
        LED_CLR = 0x02000000
        LED_TEST = 0x04000000
        LED_ALL = 0x07800000

    class ButtonEnum(Enum):
        """Enumeration for all panel Buttons"""

        NR_1 = 0x00000400
        NR_2 = 0x00000800
        NR_3 = 0x00001000
        NR_4 = 0x00008000
        NR_5 = 0x00010000
        NR_6 = 0x00020000
        NR_7 = 0x00100000
        NR_8 = 0x00200000
        NR_9 = 0x00400000
        NR_0 = 0x04000000
        TEST = 0x08000000
        ENTER = 0x02000000
        DIM_M = 0x00004000
        DIM_P = 0x00080000
        CLR = 0x00000200
        GS = 0x00800000
        RWY = 0x00040000
        STBY = 0x00002000
        MODE = 0x00000100
        ALL_KEYS = 0x0FFFFF00

    # Timeout in seconds to detect panel inactivity.
    RX_CHNL_TIMEOUT: float = 5.0

    class ArgumentException(Exception):
        pass

    def __init__(
        self,
        arinc_device: object,
        tx_chnl_number: int,
        rx_chnl_number: int,
        debug: bool = False,
    ):
        """HUD class Init method

        Args:
            arinc_device (object): Arinc device object provided by aviologic
            tx_chnl_number (int): TX channel number
            rx_chnl_number (int): RX channel number
        """
        self._device = arinc_device
        self._tx_chnl = tx_chnl_number
        self._rx_chnl = rx_chnl_number
        self._debug = debug

        # Initialize or reset class variables
        self._reset()

        # Get reference to receiving queue. This is to make things faster
        self._rx_queue = self._device._rx_chnl[self._rx_chnl]._label_queue

    def _reset(self):
        """Initialize or reset internal class variables. This method
        is intended to be use internally to this class in synchronous
        manner.
        """
        self._display = self.Display()

         # Create queue for key presses
        self._key_q = queue.Queue()

        # Container for the holding the parsed received labels
        self._rx_label = {}

        # Label timeout. This is to detect that the panel has stop
        # sending labels, in which case we should reset buttons bitmap.
        self._timestamp_prev = 0

        # Brightness value should be between 60 and 127
        self._brightness = 80

        # Indicators flags. Off by default
        self._indicators_bitmap = 0

        # Buttons bitmap
        self._buttons_bitmap = 0

        # Labels buffer to send to the panel
        self._tx_buffer = []

        # Indicates if the panel is alive, this means we
        # receive arinc data from panel.
        self._panel_is_alive = False

    def _handle_keypad_dimmer(self, keypad: int):
        """Handle the DIM+ and DIM- buttons to change
        the display brightness

        Args:
            keypad (int): keypad bitmap
        """
        if keypad & self.ButtonEnum.DIM_P.value:
            self._brightness += 1
            if self._brightness > 127:
                self._brightness = 127
        elif keypad & self.ButtonEnum.DIM_M.value:
            self._brightness -= 1
            if self._brightness < 60:
                self._brightness = 60
        else:
            pass

    def _tx_buffer_append_label(self, label: int):
        """Append given label to TX buffer.
        The buffer is finally sent with method _update_panel

        NOTE: The label packet should contain a valid parity bit.

        Args:
            label (int): label packet
        """
        self._tx_buffer.append((self._tx_chnl, label))

    def _update_panel(self):
        """Update panel sending the TX buffer"""
        self._tx_buffer += self._display.get_labels()
        try:
            self._device.send_manual_list_fast(self._tx_buffer)
        except Exception:
            self._reset()
        else:
            self._tx_buffer = []

    def _brightness_label(self, brightness: int) -> int:
        """Create brightness label

        Args:
            brightness (int): Brightness value

        Returns:
            int: ready to send label for brightness control
        """
        lab = ArincLabel.Base.pack_oct(3, 0x3, 0x0, brightness << 8)
        return lab | (ArincLabel.Base._parity(lab) << ArincLabel.Base.PACKET_PARITY_POS)

    def _indicator_label(self, indicator_bitmap: int):
        lab = 0x60000080  # ArincLabel.Base.pack_oct(1, 0x3, 0x0, 0x00010000)
        lab |= indicator_bitmap & 0x07800000
        return lab | (ArincLabel.Base._parity(lab) << ArincLabel.Base.PACKET_PARITY_POS)

    def set_indicator(self, indicator: IndicatorEnum, status: int | bool):
        """Set given indicator status. The status is ON or OFF.

        Args:
            indicator (IndicatorEnum): indicator Enum
            status (int | bool): Status of the indicator. On or OFF. The value
                                 can be an integer 1/0 or a boolean True/False
        """

        if isinstance(status, (int, bool)) == False:
            raise self.ArgumentException(
                "The indicator status value type should be an int or boolean"
            )

        self._indicators_bitmap &= ~indicator.value
        if bool(status):
            self._indicators_bitmap |= indicator.value

    def set_text(self, line_number: int, text: str):
        """Set HUD display text

        Args:
            line_number (int): Display line number. from 0 to 3
            text (str): Text to write. Maximum 8 chars
        """
        if line_number >= HUD.Display.DISP_ROW:
            raise self.ArgumentException(
                f"Given display line number ({line_number}) exceeds the maximum the display lines = {HUD.Display.DISP_ROW}.\n"
                f"Please use a number between 0 and {HUD.Display.DISP_ROW-1}"
            )
        if len(text) > HUD.Display.DISP_COL:
            raise self.ArgumentException(
                f"Given text length ({len(text)}) is longer than what the display can show = {HUD.Display.DISP_COL}"
            )
        # self._display.write(0, 0, [0x68, 0x65, 0x79  | 0x80])
        self._display.write_str(row=line_number, column=0, text=text)
        

    def get_button(self, button: ButtonEnum) -> bool:
        """Get panel button status. Pressed or unpressed.

        Args:
            button (ButtonEnum): Button type to read

        Returns:
            bool: Button status. True=Pressed or False=Unpressed
        """
        return True if self._buttons_bitmap & button.value else False

    def loop(self):
        """HUD main update loop.
        This method should be called periodically as fast ast possible within the Logic loop
        """
        # The loop should run only if the arinc card is online
        if self._device.is_ready:
            # Consume all received labels from HUD channel
            while True:
                try:
                    label, timestamp = self._rx_queue.popleft()
                except Exception as e:
                    # No element in the queue... then skip
                    break
                else:
                    p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                    if label_id in self._rx_label:
                        self._rx_label[label_id]["ssm"] = ssm
                        self._rx_label[label_id]["sdi"] = sdi
                        self._rx_label[label_id]["data"] = data
                        self._rx_label[label_id]["raw"] = label
                    else:
                        self._rx_label[label_id] = {
                            "ssm": ssm,
                            "sdi": sdi,
                            "data": data,
                            "raw": label,
                        }
                    self._timestamp_prev = time()
                    self._panel_is_alive = True

            if self._debug:
                # Print table of received labels
                for label_id, obj in self._rx_label.items():
                    # print(f'[{oct(label_id)}] {obj["data"]:8X} ssm: {obj["ssm"]} sdi: {obj["sdi"]}')
                    print(
                        f'[{oct(label_id)}]({label_id}) {(obj["raw"] & 0x7FFFFF00):8X}'
                    )
                print("")

            # Clean variables if timeout occurred
            if (time() - self._timestamp_prev) > self.RX_CHNL_TIMEOUT:
                self._reset()

            # Process keypad inputs
            if 192 in self._rx_label:
                self._buttons_bitmap = (
                    self._rx_label[192]["raw"] & self.ButtonEnum.ALL_KEYS.value
                )
                self._handle_keypad_dimmer(self._buttons_bitmap)

            # NOTE: Keep this commented code as reference. If blinking needs to
            # be implemented this is the way to do it
            # Blinking is activated by the last bit of the character
            # self.text = "hey"
            # # self.disp.write(0, 0, [0x68, 0x65 | 0x80, 0x79])
            # self._display.write_str(0, 0, self._scratch_pad)

            # Update panel sending labels only if the panel is alive
            if self._panel_is_alive:
                # Add indicators label. This will update the panel status LEDs. Label octal 1
                self._tx_buffer_append_label(
                    self._indicator_label(self._indicators_bitmap)
                )

                # Send label octal 2. This label is require to extinguish FAULT light.
                self._tx_buffer_append_label(0x64040040)

                # Add brightness label to buffer. Label octal 3.
                self._tx_buffer_append_label(self._brightness_label(self._brightness))

                # Send label octal 4. This label is require to extinguish FAULT light.
                self._tx_buffer_append_label(0x64040020)

                # Send data to panel
                self._update_panel()


class Logic:
    def __init__(self):
        self.version = "v1.2.0"
        self.is_enable = True
        self.count = 0
        self.init = False
        self.key_states = {}

        # Create new HUD class
        self.hud = HUD(
            arinc_device=self.devices[ARINC_CARD_NAME],
            tx_chnl_number=ARINC_CARD_TX_CHNL,
            rx_chnl_number=ARINC_CARD_RX_CHNL,
        )
    def check_key(self, button: HUD.ButtonEnum, ref: str):
        # Ensure each key has its state initialized
        if button not in self.key_states:
            self.key_states[button] = False  # Initialize state as "not pressed"

        if self.hud.get_button(button):  # Check if the key is pressed
            if not self.key_states[button]:  # Key is pressed for the first time
                self.key_states[button] = True
                self.send_key_value(ref, 1)  # Send "on" command
        else:
            if self.key_states[button]:  # Key was released
                self.key_states[button] = False
                self.send_key_value(ref, 0)  # Send "off" command"

    def send_key_value(self, ref, value):
        # Send the command to prosim
        getattr(self.datarefs.prosim, ref).value = value
        print(f"Set value {ref} to: {value}")  # Debug output

    async def update(self):
        # Update HUD
        self.hud.loop()

        # ----- User Space START -----

        # Prosim Mapping
        self.hud.set_text(0, self.datarefs.prosim.hgscp_display_line1.value)
        self.hud.set_text(1, self.datarefs.prosim.hgscp_display_line2.value)
        self.hud.set_text(2, self.datarefs.prosim.hgscp_display_line3.value)
        self.hud.set_text(3, self.datarefs.prosim.hgscp_display_line4.value)

        test_is_pressed = self.hud.get_button(HUD.ButtonEnum.TEST)

        # system.indicators.I_HGS_CLR HGS CP CLR System.Byte
        self.hud.set_indicator(HUD.IndicatorEnum.LED_CLR, True)
        # system.indicators.I_HGS_GS HGS CP G/S System.Byte
        self.hud.set_indicator(HUD.IndicatorEnum.LED_GS, True)
        # system.indicators.I_HGS_RWY HGS CP RWY System.Byte
        self.hud.set_indicator(HUD.IndicatorEnum.LED_RWY, True)
        # system.indicators.I_HGS_TEST HGS CP TEST System.Byte
        self.hud.set_indicator(HUD.IndicatorEnum.LED_TEST, test_is_pressed)

        # system.switches.S_HGS_BRTTEST HGS CP TEST [0:Normal, 1:Pushed] System.Int32
        # self.hud.get_button(HUD.ButtonEnum.TEST)
        # system.switches.S_HGS_GS HGS CP G/S [0:Normal, 1:Pushed] System.Int32
        # self.hud.get_button(HUD.ButtonEnum.GS)
        # system.switches.S_HGS_KEY0 HGS CP Key 0 [0:Normal, 1:Pushed] System.Int32

        self.check_key(HUD.ButtonEnum.NR_0, "S_HGS_KEY0")
        self.check_key(HUD.ButtonEnum.NR_1, "S_HGS_KEY1")
        self.check_key(HUD.ButtonEnum.NR_2, "S_HGS_KEY2")
        self.check_key(HUD.ButtonEnum.NR_3, "S_HGS_KEY3")
        self.check_key(HUD.ButtonEnum.NR_4, "S_HGS_KEY4")
        self.check_key(HUD.ButtonEnum.NR_5, "S_HGS_KEY5")
        self.check_key(HUD.ButtonEnum.NR_6, "S_HGS_KEY6")
        self.check_key(HUD.ButtonEnum.NR_7, "S_HGS_KEY7")
        self.check_key(HUD.ButtonEnum.NR_8, "S_HGS_KEY8")
        self.check_key(HUD.ButtonEnum.NR_9, "S_HGS_KEY9")
        self.check_key(HUD.ButtonEnum.RWY, "S_HGS_RWY")
        self.check_key(HUD.ButtonEnum.CLR, "S_HGS_CLR")
        self.check_key(HUD.ButtonEnum.ENTER, "S_HGS_ENTER")
             

        # system.switches.S_HGS_MODE HGS CP MODE [0:Normal, 1:Pushed] System.Int32
        # self.hud.get_button(HUD.ButtonEnum.MODE)
        # system.switches.S_HGS_RWY HGS CP RWY [0:Normal, 1:Pushed] System.Int32
        # self.hud.get_button(HUD.ButtonEnum.RWY)
        # system.switches.S_HGS_STBY HGS CP STBY [0:Normal, 1:Pushed] System.Int32
        # self.hud.get_button(HUD.ButtonEnum.STBY)

        # ----- User Space END -----

        # Limit update loop frequency

        await asyncio.sleep(0.08)
