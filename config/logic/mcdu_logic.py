import asyncio
from resources.libs.arinc_lib.arinc_lib import ArincLabel
from datetime import datetime

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

    def add_text(self, offset: int, text: str, end_line=False, control: int = 0):
        block = [
            self._apply_par(self._block_base | (offset << 13)),
            self._apply_par(self._block2_base),
        ]
        # for i in block:
        #     print(hex(i))
        if len(text) > 0:
            block += [self._char_label(c, control) for c in text.encode("iso-8859-5")]
            if end_line:
                block[-1] |= 0x3 << 11
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

        self.loading = ""

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

            self.loading

            file = self.screen.pack()
            # print(file)

            lwc = []
            for l in file:
                lwc.append((3, l))

            # print(lwc)
            self.dev.send_manual_list_fast(lwc)
            # self.dev.send_manual_list_fast(buffer)
            await asyncio.sleep(0.05)

            self.screen = Screen(40)
            self.screen.add_text(1, "     N1 LIMIT          " + "sel/aot                 " + "<FROM Lucas              " + "                       " + "<TO OC737.COM         ")
            # self.screen.add_text(self.first, "> WHAT THE WHAT THEWHAT >        []     WHAT 1 > Option [] THEWHAT THEWHAT THEWHAT THE    "  , control=0)

            self.loading    
            self.screen.add_text(295 - self.first, self.loading, control=0)
            # self.first += 1
            # self.loading = datetime.today().strftime('%H:%M:%S')
            if self.first > 250:
                self.first = 1
