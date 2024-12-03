import asyncio
from resources.libs.arinc_lib.arinc_lib import ArincLabel
import time
from enum import Enum
from typing import Callable
import re
import xml.etree.ElementTree as ET
import queue

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

        def add_text_base(self, offset: int, text: str, color: int = 0, control: int = 0):
            block_base = self._sal | 0x400
            block2_base = block_base | 0x40000

            if offset < 0:
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

        def add_text(self, offset: int, text: str, color: int = 0):
            block_base = self._sal | 0x400
            block2_base = block_base | 0x40000
            control = 0;

            
             # Mapping of Cyrillic characters to corresponding numbers. Used to show small font numbers
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

            if offset < 0:
                raise Exception("Offset should be bigger than 0")

            self._block += [
                # Text block open - Specifies the offset
                self._apply_par(block_base | (offset << 13)),
                # Text block configuration
                self._apply_par(block2_base | ((color & 0x1FF) << 20)),
            ]

            # if len(text) > 0:
            #     self._block += [
            #         self._char_label(self._sal, c, control)
            #         for c in text.encode("iso-8859-5")
            #     ]

            i = 0
            while i < len(text):
                c = text[i]

                # Special case for `#` which is the empty box, add the corresponding int (64)
                if c == "#":
                    self._block += [self._char_label(0x04, 64, control)]

                # # Check for the sequence "[I]" (start inverted text)
                # elif c == "[" and i + 2 < len(text) and text[i + 1:i + 3] == "I]":
                #     # Add empty space to replace the special wrapper
          
                #     self._block += [self._char_label(0x04, b, 0) for b in "        ".encode("iso-8859-5")]
                #     self._block += [self._char_label(0x04, b, 1) for b in " ".encode("iso-8859-5")]
                #     control = 1 # Start inverted text
                #     i += 3  # Skip past "[I]"
                # # Check for the sequence "[/I]" (ende inverted text)
                # elif c == "[" and i + 3 < len(text) and text[i + 1:i + 4] == "/I]":
                #     control = 0 # End inverted tex
                #     i += 4  # Skip past "[/I]"
    
                # Inverted, Color 1, 2, Color 3
                elif c == "Ф":
                    control = 1 # Start inverted text

                elif c == "Ю":
                    control = 0 # End inverted text

                elif c == "`":
                    # for degrees symbol prosim uses `
                    self._block += [self._char_label(0x04, 36, control)]

                elif c in cyrillic_to_number:
                    # Map Cyrillic characters to numbers and use the same logic as for digits
                    n = cyrillic_to_number[c]
                    self._block += [self._char_label(0x04, 16 + int(n), control)]

                else:
                    # Encode other characters in ISO-8859-5 and add them to the block
                    self._block += [self._char_label(0x04, b, control) for b in c.encode("iso-8859-5")]

                i += 1



        def format_row(self, left="", center="", right=""):
            # Start with an empty 24-character line filled with spaces
            special_chars = ['Ф', 'Ю']
            max_chars = 24;
            # Check each string for occurrences of the special characters then add more spaces for when they are removed
            for char in special_chars:
                max_chars += (left or "").count(char)
                max_chars += (center or "").count(char)
                max_chars += (right or "").count(char)

            row = [' '] * max_chars
            print("max_chars")
            print(max_chars);
    
            # Add the left text, starting at index 0
            if (left):
                for i, char in enumerate(left):
                    if i < max_chars:  # Ensure we do not overflow the row
                        row[i] = char
    
            # Add the right text, aligned to the right, starting at the correct index
            right_start = max_chars - len(right)
            for i, char in enumerate(right):
                if right_start + i >= 0 and right_start + i < max_chars:  # Ensure we do not overflow the row
                    row[right_start + i] = char
    
            # Add the center text, centered within the row
            center_start = (max_chars - len(center)) // 2
            for i, char in enumerate(center):
                if center_start + i >= 0 and center_start + i < max_chars:  # Ensure we do not overflow the row
                    row[center_start + i] = char
    
            # Join the list of characters into a single string and return it
            return ''.join(row)


        # Function to convert numbers to Cyrillic
        # used to convert numbers to a special character that can later
        # be used to be shown as a small font number instead
        def convert_numbers_to_cyrillic(self, text):

            # Mapping of numbers to Cyrillic letters (ISO-8859-5)
            number_to_cyrillic = {
                '0': 'А',  # ISO-8859-5 0410
                '1': 'Б',  # ISO-8859-5 0411
                '2': 'В',  # ISO-8859-5 0412
                '3': 'Г',  # ISO-8859-5 0413
                '4': 'Д',  # ISO-8859-5 0414
                '5': 'Е',  # ISO-8859-5 0415
                '6': 'Ж',  # ISO-8859-5 0416
                '7': 'З',  # ISO-8859-5 0417
                '8': 'И',  # ISO-8859-5 0418
                '9': 'Й'   # ISO-8859-5 0419
            }

            return ''.join(number_to_cyrillic.get(c, c) for c in text)


        def parse_display_line(self, input_str, lower_case = False):
            DELIMITER = "\u00A8"
            left = ""
            center = ""
            right = ""

            if not input_str:
                return ["", "", ""]

            # Find and handle text wrapped in [s][/s] for lowercase conversion and small number conversion
            def process_s_tags(content):
                # Convert to lowercase
                content = content.lower()
                # Convert numbers to Cyrillic
                return self.convert_numbers_to_cyrillic(content)

            def replace_nested_s_tags(input_str):
                # Replace the innermost [s][/s] or [S][/S] first
                new_str = re.sub(r'\[s\](.*?)\[/s\]', lambda m: process_s_tags(m.group(1)), input_str)
                new_str = re.sub(r'\[S\](.*?)\[/S\]', lambda m: process_s_tags(m.group(1)), new_str)
                input_str = new_str
                # Replace any remaining [s] from nested
                input_str = input_str.replace("[s]", "").replace("[/s]", "")
                return input_str

            if (lower_case and input_str):
                input_str = input_str.lower()
                input_str = self.convert_numbers_to_cyrillic(input_str)

            # Process nested [s][/s] and [S][/S] tags
            input_str = replace_nested_s_tags(input_str)

            # Replace Prosim's box symbols with '#'
            input_str = input_str.replace("[]", "#")
        
            # Replace any [L] and [/L] tags with an empty string (Supposed to be large but not used)
            input_str = input_str.replace("[l]", "").replace("[/l]", "")

            # Replace any [3] and [/3] tags with special characters
            input_str = input_str.replace("[I]", "Ф").replace("[/I]", "Ю")
            input_str = input_str.replace("[1]", "Ф").replace("[/1]", "Ю")
            input_str = input_str.replace("[2]", "Ф").replace("[/2]", "Ю")
            input_str = input_str.replace("[3]", "Ф").replace("[/3]", "Ю")
            
            delimiter_count = input_str.count(DELIMITER)
    
            # Handle cases with two delimiters (left, center, right)
            if delimiter_count == 2:
                left, center, right = input_str.split(DELIMITER, 2)
            # Handle cases with one delimiter (left, right)
            elif delimiter_count == 1:
                left, right = input_str.split(DELIMITER, 1)
                center = ""
            # Handle cases with no delimiters
            else:
                left, center, right = input_str, "", ""


            # Find the text wrapped in [m][/m] tags for the center part
            center_match = re.search(r'\[m\](.*?)\[/m\]', input_str)
            if center_match:
                center = center_match.group(1)
                # Remove the center text and tags from left and right parts
                left = left.replace(center_match.group(0), '')
                right = right.replace(center_match.group(0), '')

            # Return the left, center, and right as an array
            return [left, center, right]

        def parse_xml(self, xml_string):
            # Parse the XML string

            root = ET.fromstring(xml_string)
            title = root.find('title').text if root.find('title') is not None else ""
            title_page = root.find('titlePage').text if root.find('titlePage') is not None else ""
            scratchpad = root.find('scratchpad').text if root.find('scratchpad') is not None else ""
            lines = [line.text for line in root.findall('line')]
    
            # Ensure we have exactly 12 lines, fill with empty strings if less
            lines = (lines + [""] * 12)[:12]
    
            return {
                "title": title,
                "title_page": title_page,
                "scratchpad": scratchpad,
                "lines": lines
            }


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
            # 90011: "S_CDU1_KEY_ATC",
            91: "S_CDU1_KEY_B",
            107: "S_CDU1_KEY_C",
            95: "S_CDU1_KEY_CLB",
            145: "S_CDU1_KEY_CLEAR",
            # 90016: "S_CDU1_KEY_CLEARLINE",
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
            # 90027: "S_CDU1_KEY_FMC_COMM",
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
            9: "S_CDU1_KEY_LSK2L",
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
            # 90050: "S_CDU1_KEY_MENU",
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
            # 90068: "S_CDU1_KEY_VNAV",
            101: "S_CDU1_KEY_W",
            117: "S_CDU1_KEY_X",
            133: "S_CDU1_KEY_Y",
            71: "S_CDU1_KEY_Z"
        }

    # Create queue for key presses
    key_q = queue.Queue()
    
    class LightsEnum(Enum):
        """Enumeration for front light indicators"""

        FAIL = 0x2000
        MSG = 0x8000
        OFFSET = 0x10000
        EXEC = 0x20000
     
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
          #  self._apply_par(scratchpad_base | (offset << 13)),
        ]
        null_char = self._char_label(self._sal, 0x40)
        # self._tx_buffer += [null_char] * 24
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
        self._key_cb(label)

        # try:
        #     key_enum = self.KeypadEnum((label >> 12) & 0xFF)
        # except:
        #     # Is not a key so pass here
        #     pass
        # else:
        #     if self._key_cb is not None:
        #         self._key_cb(key_enum.name)
        #         # print(hex(label), key_enum.name)

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
    
    def get_ps_key(self, key: int):
        if key in self.key_map:
            return self.key_map[key]
        else:
            return ""
    def key_queue_add(self, item: str):
        self.key_q.put(item)

    def key_queue_pop(self):
        if not self.key_q.empty():
            item = self.key_q.get()  # Get and remove the first item from the queue
            return item

    def loop(self):
        """ main update loop.
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
                        # print("label")
                        # print(label)

            # Update subsystems only if the panel has reported back
            if self._trig_update:
                self._trig_update = False

                self._init_frame(self._light_bitmap)

                for _, subsystem in self._subsystem.items():

                    self._tx_buffer += subsystem._block
                    subsystem._block = []

                    file = self._close_frame()
                    # print("file")
                    # print(file)

                    lwc = []
                    for l in file:
                        lwc.append((ARINC_CARD_TX_CHNL, l))

                    # print("lwc")
                    # print(file)

                    """Update panel sending the TX buffer"""
                    try:
                        self._device.send_manual_list_fast(lwc)
                    except Exception:
                        pass

            # time.sleep(0.05)


class Logic:
    def __init__(self):
        self.version = "v3.1.0"

        self.mcdu = MCDU(
            arinc_device=self.devices[ARINC_CARD_NAME],
            tx_chnl_number=ARINC_CARD_TX_CHNL,
            rx_chnl_number=ARINC_CARD_RX_CHNL,
            key_callback=self.key_pressed_callback,
        )
        self.fmc_subsys = self.mcdu.add_subsystem("fmc", 0x04)
        self.tprev = time.time()
        self.test_label_increment = 0x00
        self.aux = 1
        self.cdu1_text = ""
        self.cdu_xml = {
            "xml_title": "",
            "xml_title_page": "",
            "xml_lines": ["","","","","","","","","","","",""],
            "xml_scratchpad": ""
        }
        self.run_again = 0

    def key_pressed_callback(self, name):
        if name != 4612:

            key_hex = (name >> 12) & 0xFF
               
            if (key_hex > 0):
                selected_key = self.mcdu.get_ps_key(key_hex)
                # if hasattr(self, 'fmc_subsys') and self.fmc_subsys is not None:
                #     self.fmc_subsys.add_text(0, 
                #         str(key_hex) + "  "
                #     )
                if (selected_key != ""):
                    getattr(self.datarefs.prosim, selected_key).value = 1
                    self.mcdu.key_queue_add(selected_key)
             
             
            # print(name)

    async def update(self):
        self.mcdu.loop()

       
      
        # print("xml_string")
        # print(xml_string)
        # print("cdu1_text")
        # print(self.cdu1_text)
        # print("")

        xml_string = self.datarefs.prosim.cdu1.value
        light_exec = self.datarefs.prosim.I_CDU1_EXEC.value
        light_fail = self.datarefs.prosim.I_CDU1_FAIL.value
        light_msg = self.datarefs.prosim.I_CDU1_MSG.value
        light_offset = self.datarefs.prosim.I_CDU1_OFFSET.value

        self.mcdu.set_light(MCDU.LightsEnum.EXEC, light_exec == 2)
        self.mcdu.set_light(MCDU.LightsEnum.FAIL, light_fail == 2)
        self.mcdu.set_light(MCDU.LightsEnum.MSG, light_msg == 2)
        self.mcdu.set_light(MCDU.LightsEnum.OFFSET, light_offset == 2)

        # inverted color


        if (xml_string != self.cdu1_text and self.run_again <= 2):
      #  if (xml_string != self.cdu1_text):

            # self.fmc_subsys.add_text(1, "inversed", control=1)

            # print("***** update")
            # print(self.run_again)
            # print(xml_string)
            if (self.run_again == 1):
                self.cdu1_text = xml_string
                self.run_again = 0

            offset = 0;
            self.run_again = self.run_again + 1
            
            xml_result = self.fmc_subsys.parse_xml(xml_string)
            xml_lines = xml_result["lines"]
            xml_title_page = xml_result["title_page"]
            xml_scratchpad = xml_result["scratchpad"]
            xml_title = self.fmc_subsys.parse_display_line(xml_result["title"])
            xml_title_spaces = int(xml_title[1]) if xml_title[1] else "" 
            xml_title_left_align = xml_title[0]  if xml_title[0] else ""

            # Add Page Title. If title has spaces in the xml, then add the spaces and flush to the left
            # If the title doesn't have spaces then center it.
            self.fmc_subsys.add_text(0,  
                self.fmc_subsys.format_row(
                    ' ' * xml_title_spaces + xml_title[2] if xml_title_left_align == "True" else "",
                    xml_title[2] if xml_title_left_align == "False" else "", 
                self.fmc_subsys.convert_numbers_to_cyrillic(xml_title_page) if xml_title_page else "" ))
            
            #Add Lines
            for ln in range(12):
                # check that the line has changed
                # if (xml_lines[ln] != self.cdu_xml["xml_lines"][ln]):
                xml1 = self.fmc_subsys.parse_display_line(xml_lines[ln], ln % 2 == 0)
                self.fmc_subsys.add_text(offset, 
                    self.fmc_subsys.format_row(*xml1)
                )
                # else:
                #     offset = offset + 0 #100

            # test with updating loop numbert count
            # self.fmc_subsys.add_text(0,  
            #     self.fmc_subsys.format_row(str(self.run_again), "", "")
            # )

            # check the scratch pad has changed and update
            # if (self.cdu_xml["xml_scratchpad"] != xml_scratchpad):
            self.fmc_subsys.add_text(offset,  
                self.fmc_subsys.format_row(xml_scratchpad, "", "")
            )
            # print("offset")
            # print(offset)

            self.cdu_xml["xml_scratchpad"] = xml_scratchpad;
            self.cdu_xml["xml_lines"] = xml_lines;

            self.mcdu._trig_update = True
            # print("mcdu._trig_update", self.mcdu._trig_update)

        # check queue and turn off keys
        off_key = self.mcdu.key_queue_pop()
        if (off_key):
            getattr(self.datarefs.prosim, off_key).value = 0
   
      
        time.sleep(0.08)
        

        