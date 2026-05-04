from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

from fast_enum import FastEnum
from enum import IntEnum
import time

# =========================
# Config
# =========================
LRU_SAL = 0o300
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3
HEARTBEAT_SEC = 0.9
ARINC_WORD_GAP_SEC = 0.0
MCDU_COLS = 24
RANGE_START = 28
RANGE_END = 29
#48 min starts with number 0 small
#96 max
# 28 Degree
# 29 Box

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

class TextData:
    def __init__(self, text: str, color: int, lineIdx: int, initial_col: int = 1, disp_attr: int = 0):
        self.text = text
        self.color = color & 0x7
        self.lineIdx = max(1, min(31, lineIdx))
        self.initial_col = max(1, min(24, initial_col))
        self.disp_attr = disp_attr & 0x7

class A739:
    ENQ  = 0b0000101
    DC2  = 0b0010010
    DC3  = 0b0010011
    SYN  = 0b0010110
    STX  = 0b10
    CNTRL= 0b1
    ETX  = 0b11
    EOT  = 0b100
    ACK  = 0b110
    NACK = 0b10101
    SAL_TYPE_MASK  = 0x7F
    SAL_TYPE_SHIFT = 24
    REQUEST_TYPE_SHIFT = 16
    REQUEST_TYPE_MASK  = 0xF
    MAL_MASK  = 0xFF
    MAL_SHIFT = 8

    @staticmethod
    def num_words_for_text(s): return (len(s) + 2) // 3
    @staticmethod
    def is_enq(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.ENQ
    @staticmethod
    def is_cts(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC3
    @staticmethod
    def is_syn(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.SYN
    @staticmethod
    def is_ack(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.ACK
    @staticmethod
    def is_nack(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.NACK
    @staticmethod
    def get_request_type(dw): return (dw >> A739.REQUEST_TYPE_SHIFT) & A739.REQUEST_TYPE_MASK
    @staticmethod
    def get_mal(dw): return ArincLabel.Base._reverse_label_number((dw >> A739.MAL_SHIFT) & A739.MAL_MASK)

class ControlEncoder:
    def __init__(self):
        self._preferred = None

    def build_stx(self, mal_target, record_index, data_words):
        count = (data_words + 3) & 0xFF
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, (A739.STX << 16) | ((record_index & 0xFF) << 8) | count)

    def build_etx_eot(self, mal_target, record_index, last):
        end_code = A739.EOT if last else A739.ETX
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, (end_code << 16) | ((record_index & 0xFF) << 8))

    def cntrl_A(self, mal_target, *, color, line, col, attr):
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, ((A739.CNTRL << 16) | ((color & 0x7) << 13) | ((line & 0x1F) << 8) | ((attr & 0x7) << 5) | (col & 0x1F)))

    def cntrl_B(self, mal_target, *, color, line, col_unused, attr_as_function):
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, ((A739.CNTRL << 16) | ((color & 0x7) << 12) | ((1 & 0xF) << 8) | ((attr_as_function & 0x7) << 5) | (line & 0x1F)))

class RobustSender:
    def __init__(self, dev, channel):
        self.dev = dev; self.channel = channel; self.ctrl = ControlEncoder()

    def _send_word(self, word):
        self.dev.send_manual_single_fast(self.channel, word)

    def _try_send_once(self, mal_target, text, line, col, color, disp_attr, last, rec_idx, encoder_tag):
        data_words = A739.num_words_for_text(text)
        self._send_word(self.ctrl.build_stx(mal_target, rec_idx, data_words))
        if encoder_tag == 'A':
            self._send_word(self.ctrl.cntrl_A(mal_target, color=color, line=line, col=col, attr=disp_attr))
        else:
            self._send_word(self.ctrl.cntrl_B(mal_target, color=color, line=line, col_unused=col, attr_as_function=0))

        sent = 0
        for _ in range(data_words):
            c1 = ord(text[sent])     if sent     < len(text) else 0
            c2 = ord(text[sent + 1]) if sent + 1 < len(text) else 0
            c3 = ord(text[sent + 2]) if sent + 2 < len(text) else 0
            self._send_word(ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, (c3 << 16) | (c2 << 8) | c1))
            sent += 3

        self._send_word(self.ctrl.build_etx_eot(mal_target, rec_idx, last))
        return True

    def send_text_adaptive(self, mal_target, text, *, line, col, color, disp_attr, last, rec_idx, rx_labels):
        self._try_send_once(mal_target, text, line, col, color, disp_attr, last, rec_idx, 'A')
        return True

class LRUData:
    def __init__(self):
        self.state = TransmissionState.IDLE
        self.next_state = TransmissionState.IDLE
        self.heartbeat_elapsed_time = time.time()
        self.message_response_elapsed_time = 0.0
        self.current_request_type = RequestType.MENU.value
        self.mal_target = None
        self.locked_mal = None
        self.repeat = False
        self.sender = None
        self.records = []

        # Precompute the test page
        for i in range(RANGE_START, RANGE_END, 2):
            idx = (i - RANGE_START) // 2
            text = f"{i}:{chr(i)} {i+1}:{chr(i+1)}"
            self.records.append(TextData(text.ljust(MCDU_COLS)[:MCDU_COLS], Color.C2, lineIdx=idx+1))

    def update(self, logic, rx):
        if self.next_state != self.state:
            self.repeat = False; self.state = self.next_state
        if self.state == TransmissionState.IDLE: self._idle(logic, rx)
        elif self.state == TransmissionState.RTS: self._rts(logic, rx)
        elif self.state == TransmissionState.SEND_DATA: self._send_data(logic, rx)

    def _idle(self, logic, rx):
        if self.sender is None and logic.dev is not None:
            self.sender = RobustSender(logic.dev, ARINC_CARD_TX_CHNL)
        for label, ts in rx:
            label_id = ArincLabel.Base.unpack_dec(label)[4]
            decoded_label = ArincLabel.Base._reverse_label_number(label_id)
            if decoded_label == LRU_SAL and A739.is_enq(label):
                self.mal_target = A739.get_mal(label)
                self.current_request_type = A739.get_request_type(label)
                self.next_state = TransmissionState.RTS; return
        if not self.repeat: self.repeat = True

    def _rts(self, logic, rx):
        for label, ts in rx:
            if A739.is_cts(label):
                self.next_state = TransmissionState.SEND_DATA; return
        if not self.repeat:
            recs = 1 if self.current_request_type == RequestType.MENU.value else len(self.records)
            payload = (A739.DC2 << 16) | ((self.current_request_type & 0xF) << 8) | (recs & 0xFF)
            logic.dev.send_manual_single_fast(ARINC_CARD_TX_CHNL, ArincLabel.Base.pack_dec_no_sdi_no_ssm(self.mal_target, payload))
            self.repeat = True

    def _send_data(self, logic, rx):
        if self.repeat:
            for label, ts in rx:
                if A739.is_syn(label) or A739.is_nack(label) or A739.is_ack(label):
                    self.next_state = TransmissionState.IDLE; return
            if time.time() - self.message_response_elapsed_time > 1.5: 
                self.next_state = TransmissionState.IDLE
            return

        if self.current_request_type == RequestType.MENU.value:
            self.sender.send_text_adaptive(self.mal_target, "TEST MODE", line=1, col=1, color=Color.C7, disp_attr=0, last=True, rec_idx=1, rx_labels=rx)
        else:
            for idx, rec in enumerate(self.records):
                self.sender.send_text_adaptive(self.mal_target, rec.text, line=rec.lineIdx, col=rec.initial_col, color=rec.color, disp_attr=rec.disp_attr, last=(idx == len(self.records) - 1), rec_idx=idx + 1, rx_labels=rx)
        self.message_response_elapsed_time = time.time(); self.repeat = True

# =========================
# Main Logic wrapper
# =========================
class Logic:
    def __init__(self):
        self.version = "char_test_v2"
        self.lru_data = LRUData()
        self.dev = None

    async def update(self):
        if not hasattr(self, "devices") or not self.devices: return
        self.dev = self.devices.get(ARINC_CARD_NAME, next(iter(self.devices.values())))
        if not self.dev.is_ready: return

        rx = []
        while True:
            try:
                rx.append(self.dev._rx_chnl[ARINC_CARD_RX_CHNL]._label_queue.popleft())
            except:
                break

        now = time.time()
        if (now - self.lru_data.heartbeat_elapsed_time) >= HEARTBEAT_SEC and self.lru_data.state != TransmissionState.SEND_DATA:
            sal_payload = ArincLabel.Base._reverse_label_number(LRU_SAL)
            self.dev.send_manual_single_fast(ARINC_CARD_TX_CHNL, ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload))
            self.lru_data.heartbeat_elapsed_time = now

            # Force trigger page cycle occasionally to test chars
            if self.lru_data.state == TransmissionState.IDLE and self.lru_data.mal_target:
                self.lru_data.current_request_type = RequestType.DATA.value
                self.lru_data.next_state = TransmissionState.RTS
                self.lru_data.repeat = False

        self.lru_data.update(self, rx)
