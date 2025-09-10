from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

from fast_enum import FastEnum
from enum import IntEnum
from typing import List, Optional, Tuple
import time

# =========================
# Config
# =========================
LRU_SAL = 0o300                  # SAL we advertise via label 0o172
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3      # TX channel (pins 20/24 @ 12.5 kb/s)
ARINC_CARD_RX_CHNL: int = 3      # RX/sniffer channel (pins 16/17)
HEARTBEAT_SEC = 0.9

# ---- Demo content ----
HELLO_TEXT  = "HELLO"
WORLD_TEXT  = "WORLD"
HELLO_LINE  = 2
HELLO_COL   = 5
HELLO_COLOR = 1  # CYAN (0..7)
WORLD_LINE  = 3
WORLD_COL   = 10
WORLD_COLOR = 6  # AMBER (0..7)

# If the unit ignores CNTRL column, pad with spaces to reach the desired col.
ENABLE_SPACE_PADDING_FOR_COLUMN = True

# Optional small pacing between words (in seconds). 0 = disabled.
ARINC_WORD_GAP_SEC = 0.0

# =========================
# Enums / Codes
# =========================
class TransmissionState(metaclass=FastEnum):
    IDLE: "Idle" = 0
    RTS: "Enq" = 1
    SEND_DATA: "Send_Data" = 2
    SCRATCHPAD: "Keypress" = 3

class RequestType(metaclass=FastEnum):
    DATA: "Data" = 0
    MENU: "Menu" = 1

class Color(IntEnum):
    C0=0; C1=1; C2=2; C3=3; C4=4; C5=5; C6=6; C7=7

# =========================
# Helpers / DTOs
# =========================
def log(msg: str):
    print(msg)

class TextData:
    def __init__(self, text: str, color: int, lineIdx: int, initial_col: int = 1, disp_attr: int = 0):
        """
        color:       3-bit color (0..7)
        lineIdx:     1..31 (5 bits)
        initial_col: 1..24 (5 bits)
        disp_attr:   3-bit (0=normal; 1=reverse; 2=underscore; 4=flash) — vendor mapped
        """
        self.text = text
        self.color = color & 0x7
        self.lineIdx = max(1, min(31, lineIdx))
        self.initial_col = max(1, min(24, initial_col))
        self.disp_attr = disp_attr & 0x7

class A739:
    ENQ  = 0b0000101  # 0x05
    DC1  = 0b0010001  # 0x11
    DC2  = 0b0010010  # 0x12 (RTS)
    DC3  = 0b0010011  # 0x13 (CTS)
    SYN  = 0b0010110  # 0x16
    STX  = 0b10       # 0x02 (Start of Text / record header)
    CNTRL= 0b1        # 0x01 (Control word)
    ETX  = 0b11       # 0x03 (more records follow)
    EOT  = 0b100      # 0x04 (end of transmission)
    ACK  = 0b110      # 0x06
    NACK = 0b10101    # 0x15

    SAL_TYPE_MASK  = 0x7F
    SAL_TYPE_SHIFT = 24
    REQUEST_TYPE_SHIFT = 16
    REQUEST_TYPE_MASK  = 0xF
    MAL_MASK  = 0xFF
    MAL_SHIFT = 8

    @staticmethod
    def num_words_for_text(s: str) -> int:
        # 3 ASCII chars per ARINC-429 data word
        return (len(s) + 2) // 3

    @staticmethod
    def is_enq(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.ENQ
    @staticmethod
    def is_cts(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC3
    @staticmethod
    def is_keyboard(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC1
    @staticmethod
    def get_key_data(dw: int) -> Tuple[int, int, int]:
        key = (dw >> 16) & 0x7F; sequence = (dw >> 8) & 0x7F; repeat = (dw >> 23) & 0x1
        return key, sequence, repeat
    @staticmethod
    def is_syn(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.SYN
    @staticmethod
    def is_ack(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.ACK
    @staticmethod
    def is_nack(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.NACK
    @staticmethod
    def get_request_type(dw: int) -> int:
        return (dw >> A739.REQUEST_TYPE_SHIFT) & A739.REQUEST_TYPE_MASK
    @staticmethod
    def get_mal(dw: int) -> int:
        # Return octal label number encoded as MAL in payload
        return ArincLabel.Base._reverse_label_number((dw >> A739.MAL_SHIFT) & A739.MAL_MASK)

# =========================
# Two CNTRL encoders (field-adaptive)
# =========================
class ControlEncoder:
    """
    Two encoders:
      - Encoder A (spec-style): COLOR<<13 | LINE<<8 | ATTR<<5 | COL
      - Encoder B (field-proven): COLOR<<12 | lineCount<<8 | FUNCTION<<5 | lineStart
    Auto-detect which one the unit ACKs and cache it.
    """
    def __init__(self):
        self._preferred = None  # 'A' or 'B'

    def build_stx(self, mal_target: int, record_index: int, data_words: int) -> int:
        # >>> IMPORTANT: length must be DATA + CNTRL + trailer (ETX/EOT) = data_words + 3
        count = (data_words + 3) & 0xFF
        stx_payload = (A739.STX << 16) | ((record_index & 0xFF) << 8) | count
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, stx_payload)

    def build_etx_eot(self, mal_target: int, record_index: int, last: bool) -> int:
        end_code = A739.EOT if last else A739.ETX
        payload  = (end_code << 16) | ((record_index & 0xFF) << 8)
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def cntrl_A(self, mal_target: int, *, color: int, line: int, col: int, attr: int) -> int:
        line = max(1, min(31, line)); col = max(1, min(24, col))
        color &= 0x7; attr &= 0x7
        payload = ((A739.CNTRL << 16)
                   | ((color & 0x7) << 13)
                   | ((line  & 0x1F) << 8)
                   | ((attr  & 0x7)  << 5)
                   | (col    & 0x1F))
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def cntrl_B(self, mal_target: int, *, color: int, line: int, col_unused: int, attr_as_function: int) -> int:
        color &= 0x7
        lineStart  = max(1, min(31, line))
        lineCount  = 1
        function   = attr_as_function & 0x7
        payload = ((A739.CNTRL << 16)
                   | ((color     & 0x7) << 12)
                   | ((lineCount & 0xF) << 8)
                   | ((function  & 0x7) << 5)
                   | (lineStart  & 0x1F))
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def set_preferred(self, tag: str):
        if tag in ('A', 'B'):
            self._preferred = tag
    def get_preferred(self) -> Optional[str]:
        return self._preferred

# =========================
# Sender with automatic fallback on SYN
# =========================
class RobustSender:
    def __init__(self, dev: ArincAsync, channel: int):
        self.dev = dev
        self.channel = channel
        self.ctrl = ControlEncoder()

    def _send_word(self, word: int):
        self.dev.send_manual_single_fast(self.channel, word)
        if ARINC_WORD_GAP_SEC > 0:
            time.sleep(ARINC_WORD_GAP_SEC)

    def _send_data_words(self, mal_target: int, text: str):
        words = A739.num_words_for_text(text)
        sent = 0
        for _ in range(words):
            c1 = ord(text[sent])     if sent < len(text) else 0
            c2 = ord(text[sent + 1]) if (sent + 1) < len(text) else 0
            c3 = ord(text[sent + 2]) if (sent + 2) < len(text) else 0
            payload = (c3 << 16) | (c2 << 8) | c1
            word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)
            self._send_word(word)
            sent += 3
        return words

    def _try_send_once(self, mal_target: int, text: str, *, line: int, col: int, color: int, disp_attr: int, last: bool, rec_idx: int, encoder_tag: str) -> str:
        # Optional space-padding to guarantee horizontal placement on column-agnostic units
        if ENABLE_SPACE_PADDING_FOR_COLUMN and col > 1:
            text_to_send = (" " * (col - 1)) + text
            effective_col = 1
        else:
            text_to_send = text
            effective_col = col

        data_words = A739.num_words_for_text(text_to_send)
        stx = self.ctrl.build_stx(mal_target, rec_idx, data_words)
        self._send_word(stx)

        if encoder_tag == 'A':
            cntrl = self.ctrl.cntrl_A(mal_target, color=color, line=line, col=effective_col, attr=disp_attr)
        else:
            cntrl = self.ctrl.cntrl_B(mal_target, color=color, line=line, col_unused=effective_col, attr_as_function=0)
        self._send_word(cntrl)

        self._send_data_words(mal_target, text_to_send)

        end = self.ctrl.build_etx_eot(mal_target, rec_idx, last)
        self._send_word(end)

        return encoder_tag

    def send_text_adaptive(self, mal_target: int, text: str, *, line: int, col: int, color: int, disp_attr: int, last: bool, rec_idx: int, rx_labels: List[Tuple[int, float]]) -> bool:
        preferred = self.ctrl.get_preferred()
        order = ['A', 'B'] if preferred is None else [preferred, 'B' if preferred == 'A' else 'A']

        for attempt_tag in order:
            log(f"[send] rec={rec_idx} try CNTRL-{attempt_tag} line={line} col={col} color={color}")
            self._try_send_once(mal_target, text, line=line, col=col, color=color, disp_attr=disp_attr, last=last, rec_idx=rec_idx, encoder_tag=attempt_tag)

            # Look at immediate rx this tick
            saw_syn = False
            saw_ack = False
            for label, ts in rx_labels:
                if A739.is_syn(label): saw_syn = True
                if A739.is_ack(label): saw_ack = True

            if saw_ack and not saw_syn:
                self.ctrl.set_preferred(attempt_tag)
                log(f"[send] CNTRL-{attempt_tag} accepted (ACK).")
                return True

            if saw_syn and not saw_ack:
                log(f"[send] CNTRL-{attempt_tag} rejected (SYN). Trying alternative…")
                continue

            # Neither observed now; allow outer state machine to catch ACK shortly
            return True

        return False

# =========================
# LRU base + TEST LRU (two-line, two-color demo)
# =========================
class LRU:
    def __init__(self, name: str, sal: int, channel: int):
        self.name = name
        self.sal = sal
        self._channel = channel
    @property
    def channel(self) -> int: return self._channel
    @channel.setter
    def channel(self, value: int):
        if value < 0 or value > 4: raise Exception("Channel idx out of bounds")
        self._channel = value
    def get_page_records(self) -> int: return 0
    def get_page_text(self) -> List[TextData]: return []

class TEST_LRU(LRU):
    def __init__(self):
        super().__init__("DEMO", LRU_SAL, ARINC_CARD_TX_CHNL)
        self.page: List[TextData] = [
            TextData(HELLO_TEXT, HELLO_COLOR, HELLO_LINE, HELLO_COL, disp_attr=0),  # cyan
            TextData(WORLD_TEXT, WORLD_COLOR, WORLD_LINE, WORLD_COL, disp_attr=0),  # amber
        ]
    def get_page_records(self) -> int: return len(self.page)
    def get_page_text(self) -> List[TextData]: return self.page

# =========================
# State machine (uses RobustSender)
# =========================
class LRUData:
    def __init__(self, lru: LRU):
        self.state: TransmissionState = TransmissionState.IDLE
        self.next_state: TransmissionState = TransmissionState.IDLE

        self.heartbeat_elapsed_time: float = time.time()
        self.lru: LRU = lru

        self.message_response_elapsed_time: float = 0.0
        self.message_repeat_count: int = 0

        self.current_request_type: int = RequestType.MENU.value
        self.record_count: int = 1

        self.mal_target: Optional[int] = None
        self.locked_mal: Optional[int] = None

        self.repeat: bool = False
        self.sender: Optional[RobustSender] = None

    def queue(self, new_state: TransmissionState):
        if new_state != self.state:
            log(f"Transition: {self.state} -> {new_state}")
            self.next_state = new_state

    def update(self, logic, lru_data, rx):
        if self.next_state != self.state:
            self.repeat = False
            self.state = self.next_state

        if self.state == TransmissionState.IDLE:
            self._idle(logic, rx)
        elif self.state == TransmissionState.RTS:
            self._rts(logic, rx)
        elif self.state == TransmissionState.SEND_DATA:
            self._send_data(logic, rx)

    def _idle(self, logic, rx):
        if self.sender is None and logic.dev is not None:
            self.sender = RobustSender(logic.dev, self.lru.channel)

        for label, ts in rx:
            p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
            decoded_label = ArincLabel.Base._reverse_label_number(label_id)
            if decoded_label == self.lru.sal and A739.is_enq(label):
                req = A739.get_request_type(label)
                mal = A739.get_mal(label)
                if self.locked_mal is None:
                    self.locked_mal = mal
                    log(f"[lock] MAL {oct(mal)}")
                self.mal_target = self.locked_mal
                self.current_request_type = req
                log(f"ENQ Received (req={req}) MAL={oct(mal)}")
                self.queue(TransmissionState.RTS)
                return

        if not self.repeat:
            self.message_repeat_count = 0
            self.repeat = True

    def _rts(self, logic, rx):
        for label, ts in rx:
            if A739.is_cts(label):
                max_recs = (ArincLabel.Base.unpack_dec(label)[2] >> 16) & 0x7F
                log(f"CTS Received (max_recs={max_recs})")
                self.queue(TransmissionState.SEND_DATA)
                return

        if not self.repeat:
            if self.current_request_type == RequestType.MENU.value:
                self.record_count = 1
            else:
                self.record_count = self.lru.get_page_records()

            rts_payload = (A739.DC2 << 16) | ((self.current_request_type & 0xF) << 8) | (self.record_count & 0xFF)
            rts = ArincLabel.Base.pack_dec_no_sdi_no_ssm(self.mal_target, rts_payload)
            logic.dev.send_manual_single_fast(self.lru.channel, rts)
            log(f"RTS -> MAL {oct(self.mal_target)} (req={self.current_request_type}, recs={self.record_count})")
            self.repeat = True

    def _send_data(self, logic, rx):
        if self.repeat:
            for label, ts in rx:
                if A739.is_syn(label):
                    log("SYN → retry")
                    self._retry_or_idle()
                    return
                if A739.is_ack(label):
                    log("ACK")
                    self.queue(TransmissionState.IDLE)
                    return
                if A739.is_nack(label):
                    log("NAK → retry")
                    self._retry_or_idle()
                    return

            if time.time() - self.message_response_elapsed_time > 1.5:
                self._retry_or_idle()
            return

        # --- transmit ---
        if self.current_request_type == RequestType.MENU.value:
            # MENU label (units often force color; WHITE is a safe request)
            _ = self.sender.send_text_adaptive(
                self.mal_target, self.lru.name,
                line=1, col=1, color=Color.C7,
                disp_attr=0, last=True, rec_idx=1, rx_labels=rx
            )
        else:
            records = self.lru.get_page_text()
            for idx, rec in enumerate(records):
                ok = self.sender.send_text_adaptive(
                    self.mal_target, rec.text,
                    line=rec.lineIdx, col=rec.initial_col, color=rec.color,
                    disp_attr=rec.disp_attr,
                    last=(idx == len(records) - 1), rec_idx=idx + 1, rx_labels=rx
                )
                if not ok:
                    self._retry_or_idle()
                    return

        self.message_response_elapsed_time = time.time()
        self.repeat = True

    def _retry_or_idle(self):
        if self.message_repeat_count < 3:
            self.message_repeat_count += 1
            self.repeat = False
            self.queue(TransmissionState.RTS)
        else:
            self.queue(TransmissionState.IDLE)

# =========================
# Main Logic wrapper
# =========================
class Logic:
    def __init__(self):
        self.version = "mcdu_a739_adaptive_v2.1"
        self.lrus = [LRUData(TEST_LRU())]
        self.mcdu_rx_channel = ARINC_CARD_RX_CHNL
        self.data_recv = False
        self.dev = None

    async def update(self):
        if not hasattr(self, "devices") or self.devices is None or len(self.devices) == 0:
            log("[wait] No ARINC devices registered yet.")
            return

        if ARINC_CARD_NAME in self.devices:
            dev = self.devices[ARINC_CARD_NAME]
        else:
            first_key = next(iter(self.devices.keys()))
            log(f"[warn] '{ARINC_CARD_NAME}' not found; using '{first_key}'")
            dev = self.devices[first_key]

        self.dev = dev
        if not self.dev.is_ready:
            log("[wait] ARINC device exists but isn’t ready yet.")
            return

        received_labels: List[Tuple[int, float]] = []
        while True:
            try:
                label, ts = self.dev._rx_chnl[self.mcdu_rx_channel]._label_queue.popleft()
                received_labels.append((label, ts))
                p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                decoded_label = ArincLabel.Base._reverse_label_number(label_id)
                sal_field = (data >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK
                if sal_field in (A739.ENQ, A739.DC3, A739.ACK, A739.SYN):
                    print(f"[rx] {oct(decoded_label)} ctl={sal_field:02x} data={data}")
                else:
                    print(oct(decoded_label), ssm, sdi, data)
            except Exception:
                break

        if received_labels:
            self.data_recv = True

        now = time.time()
        for lru_data in self.lrus:
            if (now - lru_data.heartbeat_elapsed_time) >= HEARTBEAT_SEC and lru_data.state != TransmissionState.SEND_DATA:
                sal_payload = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
                sal_id = ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload)
                self.dev.send_manual_single_fast(lru_data.lru.channel, sal_id)
                lru_data.heartbeat_elapsed_time = now

            lru_data.update(self, lru_data, received_labels)
