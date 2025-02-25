import asyncio
import time
import xml.etree.ElementTree as ET
import re
import queue
from enum import Enum
from typing import Callable
from resources.libs.arinc_lib.arinc_lib import ArincLabel

# Setup Definitions
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3

class MCDU:
    COLUMNS: int = 24
    ROWS: int = 14

    class ArgumentException(Exception):
        pass

    class LightsEnum(Enum):
        FAIL   = 0x2000
        MSG    = 0x8000
        OFFSET = 0x10000
        EXEC   = 0x20000

    class StringSplitter:
        GROUP_N: int = 2

        @staticmethod
        def _append(lst: list, text: str, rep_char: bool, position: int):
            lst.append({"text": text, "rep_char": rep_char, "position": position})

        @staticmethod
        def split(text: str) -> list:
            output = []
            text_serializer = ""
            rep_text_serializer = ""
            char_position = -1
            for i in range(1, len(text)):
                if text[i] != text[i-1]:
                    if len(rep_text_serializer) < MCDU.StringSplitter.GROUP_N:
                        text_serializer += rep_text_serializer + text[i-1]
                        if char_position < 0:
                            char_position = i-1
                    else:
                        if rep_text_serializer[-1] == text[i-1]:
                            rep_text_serializer += text[i-1]
                        MCDU.StringSplitter._append(output, rep_text_serializer, True, char_position)
                        char_position = -1
                    rep_text_serializer = ""
                else:
                    rep_text_serializer += text[i-1]
                    if char_position < 0:
                        char_position = i-1
                    if len(text_serializer) > MCDU.StringSplitter.GROUP_N:
                        MCDU.StringSplitter._append(output, text_serializer, False, char_position)
                        text_serializer = ""
                        char_position = -1
            if len(text_serializer) > 0:
                MCDU.StringSplitter._append(output, text_serializer + text[-1], False, char_position)
            elif len(rep_text_serializer) > 0:
                MCDU.StringSplitter._append(output, rep_text_serializer + text[-1], True, char_position)
            return output

    def __init__(
        self, arinc_device: object, 
                 tx_chnl_number: int, 
                 rx_chnl_number: int, 
                 key_callback: 
                 Callable = None
    ):
        self._device = arinc_device
        self._tx_chnl = tx_chnl_number
        self._rx_chnl = rx_chnl_number
        self._key_cb = key_callback

        self._sal = 0x04
        self._block = []      # Buffer for text blocks
        self._tx_buffer = []  # Buffer for labels to send
        self._rx_queue = self._device._rx_chnl[self._rx_chnl]._label_queue
        self._trig_update = False
        self._light_bitmap = 0
        self._scratchpad_text = ""
        self._key_queue = queue.Queue()  # For key press handling

    def _apply_par(self, label: int) -> int:
        label = label & 0x7FFFFFFF
        label |= ArincLabel.Base._parity(label) << 31
        return label

    def _char_label(self, sal: int, char: int, control: int = 0x0) -> int:
        char_base = sal | 0x300
        return self._apply_par(char_base | ((char & 0x7F) << 13) | ((control & 0x1FF) << 20))

    def _init_frame(self, light_status: int):
        scratchpad_base = self._sal | 0x200
        lights_base = self._sal | 0x100
        offset = 312
        self._tx_buffer = [
            0x0,
            self._apply_par(scratchpad_base | (offset << 13)),
        ]
        self._tx_buffer += [
            self._char_label(self._sal, c, 0x40)
            for c in self._scratchpad_text.ljust(self.COLUMNS).encode('iso-8859-5')
        ]
        self._tx_buffer += [
            self._apply_par(lights_base | self._light_bitmap),
            self._apply_par(scratchpad_base),
        ]

    def _close_frame(self) -> list:
        # Apply head of the entire frame. Specifies the size of the entire frame
        self._tx_buffer[0] = self._apply_par(self._sal | (len(self._tx_buffer) << 13))
        # Add end of frame label and return the list of labels to send to teh unit
        self._tx_buffer += [self._apply_par(self._sal | 0x00001F00)]
        return self._tx_buffer

    def _key_decode(self, label: int):
        self._key_cb(label)
        # try:
        #     key_enum = self.KeypadEnum((label >> 12) & 0xFF)
        # except Exception:
        #     pass
        # else:
        #     if self._key_cb is not None:
        #         self._key_cb(label)
        #     self._key_queue.put(key_enum.name)

    def key_queue_pop(self):
        if not self._key_queue.empty():
            return self._key_queue.get()
        return None

    def set_screen(self, text: str):
        # Truncate text to 312 characters and split into sections
        sections = self.StringSplitter.split(text[:312])
        blocks = []
        current_block = None

        for section in sections:
            # If there's no current block, start one from this section.
            if current_block is None:
                current_block = {
                    "text": section["text"][1:] if len(section["text"]) > 1 else "",
                    "pos": 1,
                    "fill": section["text"][0],
                    "rep_char": section["rep_char"],
                    "position": section.get("position", 0)
                }
            else:
                # If this section is the same type as the current block, simply append.
                if section["rep_char"] == current_block["rep_char"]:
                    current_block["text"] += section["text"]
                else:
                    # Different type: finish the current block and start a new one.
                    blocks.append(current_block)
                    if section["rep_char"]:
                        new_block = {
                            "text": "",
                            "pos": len(section["text"]),
                            "fill": section["text"][0],
                            "rep_char": True,
                            "position": section.get("position", 0)
                        }
                    else:
                        new_block = {
                            "text": section["text"][1:] if len(section["text"]) > 1 else "",
                            "pos": 1,
                            "fill": section["text"][0],
                            "rep_char": False,
                            "position": section.get("position", 0)
                        }
                    current_block = new_block

        if current_block:
            blocks.append(current_block)

        # Build the ARINC text blocks from each simplified block.
        for block in blocks:
            self._add_text_block(block["pos"], block["text"], block["fill"])

    def _add_text_block(self, offset: int, text: str, fill_char: str = " "):
        if offset <= 0:
            raise Exception("Offset has to be bigger than zero")
        # Create the header labels (offset and fill character)
        self._block += [
            self._apply_par(self._sal | 0x400 | (offset << 13)),
            self._apply_par(self._sal | 0x400 | ((fill_char.encode('iso-8859-5')[0] & 0x7F) << 13)),
        ]
        # Mapping for Cyrillic characters to corresponding numbers.
        cyrillic_to_number = {
            'А': '0',
            'Б': '1',
            'В': '2',
            'Г': '3',
            'Д': '4',
            'Е': '5',
            'Ж': '6',
            'З': '7',
            'И': '8',
            'Й': '9'
        }
        control = 0  # Normal text control value
        i = 0
        while i < len(text):
            c = text[i]
            # Special case for '#' (empty box) - use the value 64.
            if c == "#":
                self._block += [self._char_label(self._sal, 64, control)]
            # Inverted color: using "Ф" to start and "Ю" to end inverted text.
            elif c == "Ф":
                control = 1
            elif c == "Ю":
                control = 0
            # For the backtick character, map to 36 (e.g. for a degrees symbol)
            elif c == "`":
                self._block += [self._char_label(self._sal, 36, control)]
            # Map Cyrillic characters to small font numbers.
            elif c in cyrillic_to_number:
                n = cyrillic_to_number[c]
                self._block += [self._char_label(self._sal, 16 + int(n), control)]
            else:
                # For all other characters, encode them in ISO-8859-5.
                for b in c.encode("iso-8859-5"):
                    self._block += [self._char_label(self._sal, b, control)]
            i += 1


    @property
    def scratchpad(self) -> str:
        return self._scratchpad_text

    @scratchpad.setter
    def scratchpad(self, text: str):
        self._scratchpad_text = (text or "")[:self.COLUMNS]

    def set_light(self, light: LightsEnum, status: int | bool):
        if not isinstance(status, (int, bool)):
            raise self.ArgumentException("The indicator status value type should be an int or boolean")
        self._light_bitmap &= ~light.value
        if bool(status):
            self._light_bitmap |= light.value

    # New method: map a key hex code to the corresponding dataref name.
    def get_ps_key(self, key: int) -> str:
        key_map = {
            39: "S_CDU1_KEY_0",
            17: "S_CDU1_KEY_1",
            33: "S_CDU1_KEY_2",
            49: "S_CDU1_KEY_3",
            19: "S_CDU1_KEY_4",
            35: "S_CDU1_KEY_5",
            51: "S_CDU1_KEY_6",
            21: "S_CDU1_KEY_7",
            37: "S_CDU1_KEY_8",
            53: "S_CDU1_KEY_9",
            75: "S_CDU1_KEY_A",
            91: "S_CDU1_KEY_B",
            107: "S_CDU1_KEY_C",
            95: "S_CDU1_KEY_CLB",
            145: "S_CDU1_KEY_CLEAR",
            111: "S_CDU1_KEY_CRZ",
            123: "S_CDU1_KEY_D",
            103: "S_CDU1_KEY_DEL",
            93: "S_CDU1_KEY_DEP_ARR",
            127: "S_CDU1_KEY_DES",
            23: "S_CDU1_KEY_DOT",
            139: "S_CDU1_KEY_E",
            141: "S_CDU1_KEY_EXEC",
            73: "S_CDU1_KEY_F",
            59: "S_CDU1_KEY_FIX",
            89: "S_CDU1_KEY_G",
            105: "S_CDU1_KEY_H",
            109: "S_CDU1_KEY_HOLD",
            121: "S_CDU1_KEY_I",
            63: "S_CDU1_KEY_INIT_REF",
            137: "S_CDU1_KEY_J",
            65: "S_CDU1_KEY_K",
            81: "S_CDU1_KEY_L",
            77: "S_CDU1_KEY_LEGS",
            11: "S_CDU1_KEY_LSK1L",
            13: "S_CDU1_KEY_LSK1R",
            9:  "S_CDU1_KEY_LSK2L",
            15: "S_CDU1_KEY_LSK2R",
            27: "S_CDU1_KEY_LSK3L",
            29: "S_CDU1_KEY_LSK3R",
            25: "S_CDU1_KEY_LSK4L",
            31: "S_CDU1_KEY_LSK4R",
            43: "S_CDU1_KEY_LSK5L",
            45: "S_CDU1_KEY_LSK5R",
            41: "S_CDU1_KEY_LSK6L",
            47: "S_CDU1_KEY_LSK6R",
            97: "S_CDU1_KEY_M",
            55: "S_CDU1_KEY_MINUS",
            113: "S_CDU1_KEY_N",
            149: "S_CDU1_KEY_N1_LIMIT",
            57: "S_CDU1_KEY_NEXT_PAGE",
            129: "S_CDU1_KEY_O",
            67: "S_CDU1_KEY_P",
            147: "S_CDU1_KEY_PREV_PAGE",
            125: "S_CDU1_KEY_PROG",
            83: "S_CDU1_KEY_Q",
            99: "S_CDU1_KEY_R",
            79: "S_CDU1_KEY_RTE",
            115: "S_CDU1_KEY_S",
            119: "S_CDU1_KEY_SLASH",
            87: "S_CDU1_KEY_SPACE",
            131: "S_CDU1_KEY_T",
            69: "S_CDU1_KEY_U",
            85: "S_CDU1_KEY_V",
            101: "S_CDU1_KEY_W",
            117: "S_CDU1_KEY_X",
            133: "S_CDU1_KEY_Y",
            71: "S_CDU1_KEY_Z"
        }
        return key_map.get(key, "")

    def loop(self):
        """main main update loop.
        This method should be called periodically as fast ast possible within the Logic loop
        """
        # The loop should run only if the arinc card is online
        if self._device.is_ready:
           # Consume all received labels from the MCDU channel
            while True:
                try:
                    label, _ = self._rx_queue.popleft()
                except Exception:
                    break
                else:
                    p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                    if label_id == 4:
                        self._key_decode(label)
                        self._trig_update = True
            # Update subsystems only if the panel has reported back
            if self._trig_update:
                self._trig_update = False
                self._init_frame(self._light_bitmap)
                self._tx_buffer += self._block
                self._block = []
                file = self._close_frame()
                lwc = [(ARINC_CARD_TX_CHNL, l) for l in file]
                try:
                    self._device.send_manual_list_fast(lwc)
                except Exception:
                    pass

    # XML Parsing and Display Formatting Methods

    def parse_xml(self, xml_string: str) -> dict:
        root = ET.fromstring(xml_string)
        title = root.find('title').text if root.find('title') is not None else ""
        title_page = root.find('titlePage').text if root.find('titlePage') is not None else ""
        scratchpad = root.find('scratchpad').text if root.find('scratchpad') is not None else ""
        lines = [line.text for line in root.findall('line')]
        lines = (lines + [""] * 12)[:12]
        return {"title": title, "title_page": title_page, "scratchpad": scratchpad, "lines": lines}

    def convert_numbers_to_cyrillic(self, text: str) -> str:
        mapping = {'0': 'А', '1': 'Б', '2': 'В', '3': 'Г', '4': 'Д',
                   '5': 'Е', '6': 'Ж', '7': 'З', '8': 'И', '9': 'Й'}
        return ''.join(mapping.get(ch, ch) for ch in text)

    def parse_display_line(self, input_str: str, lower_case: bool = False) -> list:
        DELIMITER = "\u00A8"
        left, center, right = "", "", ""
        if not input_str:
            return ["", "", ""]
        def process_s_tags(content):
            content = content.lower()
            return self.convert_numbers_to_cyrillic(content)
        def replace_nested_s_tags(s):
            s = re.sub(r'\[s\](.*?)\[/s\]', lambda m: process_s_tags(m.group(1)), s)
            s = re.sub(r'\[S\](.*?)\[/S\]', lambda m: process_s_tags(m.group(1)), s)
            return s.replace("[s]", "").replace("[/s]", "")
        if lower_case and input_str:
            input_str = input_str.lower()
            input_str = self.convert_numbers_to_cyrillic(input_str)
        input_str = replace_nested_s_tags(input_str)
        input_str = input_str.replace("[]", "#")
        input_str = input_str.replace("[l]", "").replace("[/l]", "")
        input_str = input_str.replace("[I]", "Ф").replace("[/I]", "Ю")
        input_str = input_str.replace("[1]", "Ф").replace("[/1]", "Ю")
        input_str = input_str.replace("[2]", "Ф").replace("[/2]", "Ю")
        input_str = input_str.replace("[3]", "Ф").replace("[/3]", "Ю")
        delimiter_count = input_str.count(DELIMITER)
        if delimiter_count == 2:
            left, center, right = input_str.split(DELIMITER, 2)
        elif delimiter_count == 1:
            left, right = input_str.split(DELIMITER, 1)
            center = ""
        else:
            left, center, right = input_str, "", ""
        center_match = re.search(r'\[m\](.*?)\[/m\]', input_str)
        if center_match:
            center = center_match.group(1)
            left = left.replace(center_match.group(0), '')
            right = right.replace(center_match.group(0), '')
        return [left, center, right]

    def format_row(self, left="", center="", right=""):
        special_chars = ['Ф', 'Ю']
        max_chars = self.COLUMNS
        for char in special_chars:
            max_chars += (left or "").count(char)
            max_chars += (center or "").count(char)
            max_chars += (right or "").count(char)
        row = [' '] * max_chars
        for i, char in enumerate(left):
            if i < max_chars:
                row[i] = char
        right_start = max_chars - len(right)
        for i, char in enumerate(right):
            if 0 <= right_start + i < max_chars:
                row[right_start + i] = char
        center_start = (max_chars - len(center)) // 2
        for i, char in enumerate(center):
            if 0 <= center_start + i < max_chars:
                row[center_start + i] = char
        return ''.join(row)

class Logic:
    def __init__(self):
        self.version = "v3.1.0"
        self.mcdu = MCDU(
            arinc_device=self.devices[ARINC_CARD_NAME],
            tx_chnl_number=ARINC_CARD_TX_CHNL,
            rx_chnl_number=ARINC_CARD_RX_CHNL,
            key_callback=self.key_pressed_callback,
        )
        self.tprev = time.time()
        self.cdu1_text = ""
        self.cdu_xml = {
            "xml_title": "",
            "xml_title_page": "",
            "xml_lines": [""] * 12,
            "xml_scratchpad": ""
        }
        self.run_again = 0

    def key_pressed_callback(self, label):
        if label != 4612:
            print("label")
            print(label)
            key_hex = (label >> 12) & 0xFF
            if key_hex > 0:
                selected_key = self.mcdu.get_ps_key(key_hex)
                if selected_key != "":
                    getattr(self.datarefs.prosim, selected_key).value = 1
                    print(selected_key)
                    self.mcdu._key_queue.put(selected_key)

    async def update(self):
        self.mcdu.loop()

        xml_string   = self.datarefs.prosim.cdu1.value
        light_exec   = self.datarefs.prosim.I_CDU1_EXEC.value
        light_fail   = self.datarefs.prosim.I_CDU1_FAIL.value
        light_msg    = self.datarefs.prosim.I_CDU1_MSG.value
        light_offset = self.datarefs.prosim.I_CDU1_OFFSET.value

        self.mcdu.set_light(MCDU.LightsEnum.EXEC,   light_exec == 2)
        self.mcdu.set_light(MCDU.LightsEnum.FAIL,   light_fail == 2)
        self.mcdu.set_light(MCDU.LightsEnum.MSG,    light_msg == 2)
        self.mcdu.set_light(MCDU.LightsEnum.OFFSET, light_offset == 2)

        if xml_string.startswith("<") and xml_string != self.cdu1_text and self.run_again <= 2:
            # print("xml_string")
            # print(xml_string)
            # print(len(xml_string))
            if self.run_again == 1:
                self.cdu1_text = xml_string
                self.run_again = 0
            self.run_again += 1

            xml_result      = self.mcdu.parse_xml(xml_string)
            xml_lines       = xml_result["lines"]
            xml_title_page  = xml_result["title_page"]
            xml_scratchpad  = xml_result["scratchpad"]
            xml_title       = self.mcdu.parse_display_line(xml_result["title"])
            xml_title_spaces     = int(xml_title[1]) if xml_title[1] else 0
            xml_title_left_align = xml_title[0] if xml_title[0] else ""

            title_line = self.mcdu.format_row(
                (' ' * xml_title_spaces + xml_title[2]) if xml_title_left_align == "True" else "",
                xml_title[2] if xml_title_left_align == "False" else "",
                self.mcdu.convert_numbers_to_cyrillic(xml_title_page) if xml_title_page else ""
            )

            # Build the complete screen text by concatenating the title and each of the 12 lines.
            rows = [title_line]
            for ln in range(12):
                xml1 = self.mcdu.parse_display_line(xml_lines[ln], ln % 2 == 0)
                rows.append(self.mcdu.format_row(*xml1))
            screen_text = "".join(rows)
            self.mcdu.set_screen(screen_text)
            self.mcdu.scratchpad = xml_scratchpad

            self.mcdu._trig_update = True

        off_key = self.mcdu.key_queue_pop()
        if off_key:
            getattr(self.datarefs.prosim, off_key).value = 0

        await asyncio.sleep(0.04)
