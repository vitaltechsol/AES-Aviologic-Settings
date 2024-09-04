import asyncio
from resources.libs.arinc_lib.arinc_lib import ArincLabel
import re
import xml.etree.ElementTree as ET

def _label_base_reverse_mask(x: int) -> int:
    return (
        ((x & 0x1) << 7)
        | ((x & 0x2) << 5)
        | ((x & 0x4) << 3)
        | ((x & 0x8) << 1)
        | ((x & 0x10) >> 1)
        | ((x & 0x20) >> 3)
        | ((x & 0x40) >> 5)
        | ((x & 0x80) >> 7)
    )


def _label_base_octal_to_decimal(octal: int) -> int:
    num = octal
    dec_value = 0

    # Initializing base value
    # to 1, i.e 8^0
    base = 1

    temp = num
    while temp:
        # Extracting last digit
        last_digit = temp % 10
        temp = int(temp / 10)

        # Multiplying last digit
        # with appropriate base
        # value and adding it
        # to dec_value
        dec_value += last_digit * base

        base = base * 8

    return dec_value


class Screen:
    COL: int = 24
    ROW: int = 14

    def __init__(self, sal_octal: int):
        self._sal = _label_base_reverse_mask(_label_base_octal_to_decimal(sal_octal))
        self._char_base = self._sal | 0x300
        self._block_base = self._sal | 0x400
        self._block2_base = self._block_base | 0x40000
        self._init_frame()

    def _apply_par(self, label: int) -> int:
        label = label & 0x7FFFFFFF
        label |= ArincLabel.Base._parity(label) << 31
        return label

    def _char_label(self, char: int, control: int = 0x0) -> int:
        return self._apply_par(
            self._char_base
            | ((char & 0x7F) << 13)
            | ((control & 0x3) << 11)
            | ((0x3 & 0x7F) << 21)
        )

    def _head_label(self, total_words: int) -> int:
        return self._sal | (total_words << 13)

    def _init_frame(self):
        self._labels = [0x0, 0x80270204]
        null_char = self._char_label(0x20)
        self._labels += [null_char] * 24
        self._labels += [0x00008104, 0x80000204]

    def add_text(self, offset: int, text: str, lower_case=False, control: int = 0):
        block = [
            self._apply_par(self._block_base | (offset << 13)),
            self._apply_par(self._block2_base),
        ]
        # for i in block:
        #     print(hex(i))
        if len(text) > 0:

             if lower_case:
                 text = text.lower()

             for c in text:
                if c == "#":
                    # Special case for `#` which is the empty box, add the corresponding int (64)
                    block += [self._char_label(64, control)]
                    # for lower case digits use the special character
                elif c == "`":
                    # for degrees symbol prosim uses `
                    block += [self._char_label(36, control)]
                elif c.isdigit() and lower_case:
                    block += [self._char_label(16 + int(c), control)]
                else:
                    # Encode other characters in ISO-8859-5 and add them to the block
                    block += [self._char_label(b, control) for b in c.encode("iso-8859-5")]
            
        self._labels += block

    def block_open(self, offset: int):
        self._labels += [self._apply_par(self._block_base | (offset << 13))]

    def block_cfg(self, cfg: int = 0):
        self._labels += [self._apply_par(self._block2_base | ((cfg << 12) & 0x3F000))]

    def block_add_data(self, data: int, control: int = 0):
        self._labels += [self._char_label(data, control)]

    def pack(self) -> list:
        self._labels[0] = self._head_label(len(self._labels))
        # self._labels += [0x80001f04]
        return self._labels + [0x80001F04]

    def format_row(self, left="", center="", right=""):
        # Start with an empty 24-character line filled with spaces
        row = [' '] * 24
    
        # Add the left text, starting at index 0
        for i, char in enumerate(left):
            if i < 24:  # Ensure we do not overflow the row
                row[i] = char
    
        # Add the right text, aligned to the right, starting at the correct index
        right_start = 24 - len(right)
        for i, char in enumerate(right):
            if right_start + i >= 0 and right_start + i < 24:  # Ensure we do not overflow the row
                row[right_start + i] = char
    
        # Add the center text, centered within the row
        center_start = (24 - len(center)) // 2
        for i, char in enumerate(center):
            if center_start + i >= 0 and center_start + i < 24:  # Ensure we do not overflow the row
                row[center_start + i] = char
    
        # Join the list of characters into a single string and return it
        return ''.join(row)


    def parse_display_line(self, input_str):
        DELIMITER = "\u00A8"
        left = ""
        center = ""
        right = ""

        
        # Find and handle text wrapped in [s][/s] for lowercase conversion

        input_str = re.sub(r'\[s\](.*?)\[/s\]', lambda m: m.group(1).lower(), input_str)
        input_str = re.sub(r'\[S\](.*?)\[/S\]', lambda m: m.group(1).lower(), input_str)
        # Prosim uses [] for a box, but need to replace to a single character to keep the space count correct
        input_str = input_str.replace("[]", "#")
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

class Logic:
    def __init__(self):
        self.version = "v2.0.0"
        self.is_enable = True
        self.count = 0
        self.init = False
        self.dev = self.devices["arinc_1"]

        self.screen = Screen(40)
        self.rx_label = {}

        for i in range(13):
            self.screen.add_text(1, "                       ")        

        self.first = 1
        self.other = 1
        self.char = 0x00

    async def update(self):
        if self.dev.is_ready:
            while True:
                try:
                    label, timestamp = self.dev._rx_chnl[3]._label_queue.popleft()
                except Exception as e:
                    break
                else:
                    p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                    if label_id in self.rx_label:
                        self.rx_label[label_id]["ssm"] = ssm
                        self.rx_label[label_id]["sdi"] = sdi
                        self.rx_label[label_id]["data"] = data
                        self.rx_label[label_id]["raw"] = label
                    else:
                        self.rx_label[label_id] = {
                            "ssm": ssm,
                            "sdi": sdi,
                            "data": data,
                            "raw": label,
                        }

            # Print table of received labels
            # for label_id, obj in self.rx_label.items():
            #     #print(f'[{oct(label_id)}] {obj["data"]:8X} ssm: {obj["ssm"]} sdi: {obj["sdi"]}')
            #     print(f'[{oct(label_id)}]({label_id}) {(obj["raw"] & 0x7FFFFF00):8X} {obj["sdi"]}')
            # print("")

            file = self.screen.pack()
            # print(file)

            lwc = []
            for l in file:
                lwc.append((3, l))

            # print(lwc)
            self.dev.send_manual_list_fast(lwc)
            # self.dev.send_manual_list_fast(buffer)
            await asyncio.sleep(0.60)

            self.screen = Screen(40)


            xml_string = self.datarefs.prosim.cdu1.value
            
            xml_result = self.screen.parse_xml(xml_string)
            xml_lines = xml_result["lines"]
            xml_title_page = xml_result["title_page"]
            xml_title =  self.screen.parse_display_line(xml_result["title"])

            self.screen.add_text(0,  self.screen.format_row("", xml_title[2], xml_title_page if xml_title_page else "" ))

            for ln in range(12):
                xml1 = self.screen.parse_display_line(xml_lines[ln])
                self.screen.add_text(0, 
                    self.screen.format_row(*xml1), ln % 2 == 0
                )

