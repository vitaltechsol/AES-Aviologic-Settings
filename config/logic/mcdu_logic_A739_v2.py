# mcdu_a739_prosim_bridge.py
# v2.5 — Keypress bridge fixed:
#   * Legacy scan decode now tries 7-bit AND 8-bit paths before giving up.
#   * Extra logs show both raw codes and which one mapped.
#   * Small de-bounce/dedupe so repeated scans don’t spam ProSim.

from enum import IntEnum
from typing import List, Optional, Tuple, Deque, Dict
from dataclasses import dataclass, field
from collections import deque
import time
import re
import xml.etree.ElementTree as ET

from fast_enum import FastEnum
from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

# =========================
# Config / Wiring
# =========================
LRU_SAL = 0o004

ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3
HEARTBEAT_SEC = 0.5

DEFAULT_RTS_RECORD_CAP = 4
ENABLE_SPACE_PADDING_FOR_COLUMN = True
ARINC_WORD_GAP_SEC = 0.0

# Debounce for ProSim key release (seconds)
KEY_RELEASE_AFTER = 0.12
# Ignore re-presses of same logical key within this many seconds
KEY_DEDUPE_WINDOW = 0.06

# =========================
# Enums / Codes
# =========================
class TransmissionState(metaclass=FastEnum):
    IDLE: "Idle" = 0
    RTS: "Enq" = 1
    SEND_DATA: "Send_Data" = 2

class RequestType(metaclass=FastEnum):
    DATA: "Data" = 0
    MENU: "Menu" = 1

class Color(IntEnum):
    C0=0; C1=1; C2=2; C3=3; C4=4; C5=5; C6=6; C7=7

# =========================
# Helpers / DTOs
# =========================
def log(msg: str):
    print(f"[mcdu_logic_A739_v2] {msg}")

class TextData:
    def __init__(self, text: str, color: int, lineIdx: int, initial_col: int = 1, disp_attr: int = 0):
        self.text = text
        self.color = color & 0x7
        self.lineIdx = max(1, min(31, lineIdx))
        self.initial_col = max(1, min(24, initial_col))
        self.disp_attr = disp_attr & 0x7

class A739:
    ENQ  = 0b0000101
    DC1  = 0b0010001  # keyboard
    DC2  = 0b0010010  # RTS
    DC3  = 0b0010011  # CTS
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
    def num_words_for_text(s: str) -> int:
        return (len(s) + 2) // 3

    @staticmethod
    def is_enq(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.ENQ
    @staticmethod
    def is_cts(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC3
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
    def is_keyboard(dw: int) -> bool:
        return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC1
    @staticmethod
    def get_request_type(dw: int) -> int:
        return (dw >> A739.REQUEST_TYPE_SHIFT) & A739.REQUEST_TYPE_MASK
    @staticmethod
    def get_mal(dw: int) -> int:
        return ArincLabel.Base._reverse_label_number((dw >> A739.MAL_SHIFT) & A739.MAL_MASK)
    @staticmethod
    def get_key_data(dw: int) -> Tuple[int, int, int]:
        key = (dw >> 16) & 0x7F
        sequence = (dw >> 8) & 0x7F
        repeat = (dw >> 23) & 0x1
        return key, sequence, repeat

# =========================
# Control encoder
# =========================
class ControlEncoder:
    def __init__(self):
        self._preferred = None  # 'A' or 'B'

    def build_stx(self, mal_target: int, record_index: int, data_words: int) -> int:
        count = (data_words + 3) & 0xFF  # CNTRL + DATA + trailer
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
    def toggle(self):
        if self._preferred is None:
            self._preferred = 'B'
        else:
            self._preferred = 'A' if self._preferred == 'B' else 'B'

# =========================
# Sender
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
        if not text.strip():
            text = " "

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

            saw_syn = False
            saw_ack = False
            saw_nak = False
            for label, ts in rx_labels:
                if A739.is_syn(label):  saw_syn = True
                if A739.is_ack(label):  saw_ack = True
                if A739.is_nack(label): saw_nak = True

            if saw_ack and not (saw_syn or saw_nak):
                self.ctrl.set_preferred(attempt_tag)
                log(f"[send] CNTRL-{attempt_tag} accepted (ACK).")
                return True

            if saw_syn or saw_nak:
                log(f"[send] CNTRL-{attempt_tag} rejected ({'SYN' if saw_syn else 'NAK'}). Trying alternative…")
                continue

            return True

        return False

# =========================
# LRU base
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
    def get_planned_records(self) -> int: return 0
    def prepare_batch(self, count: int) -> None: ...
    def get_page_text(self) -> List['TextData']: return []

# =========================
# ProSim XML → 14×24 + diffs
# =========================
LINE_COUNT = 14
COLS = 24
COLOR_CYAN = 1
COLOR_AMBER = 6
COLOR_WHITE = 7

DATA_MIN_LINE = 3    # only send lines 3–14 in DATA

@dataclass
class LineRender:
    text: str = ""
    color: int = COLOR_WHITE
    col: int = 1
    attr: int = 0

@dataclass
class Frame:
    lines: List[LineRender] = field(default_factory=lambda: [LineRender(" " * COLS) for _ in range(LINE_COUNT)])

class ProSimNormalizer:
    def __init__(self):
        self._num_to_cyr = str.maketrans("0123456789", "АБВГДЕЖЗИЙ")

    def _fmt_row(self, left: str="", center: str="", right: str="") -> str:
        buf = [ " " ] * COLS
        rs = max(0, COLS - len(right))
        for i,ch in enumerate(right[:COLS]): buf[rs+i] = ch
        for i,ch in enumerate(left[:COLS]): buf[i] = ch
        cs = max(0, (COLS - len(center))//2)
        for i,ch in enumerate(center[:COLS]): buf[cs+i] = ch
        return "".join(buf)

    def _parse_line_frag(self, s: str) -> Tuple[str,str,str,int,int]:
        if not s: return "", "", "", COLOR_WHITE, 0
        s = s.replace("[]", "#").replace("`", "°")
        m = re.search(r'\[m\](.*?)\[/m\]', s)
        center = m.group(1) if m else ""
        if m: s = s.replace(m.group(0), "")
        parts = s.split("\u00A8")
        left  = parts[0] if len(parts)>=1 else ""
        right = parts[1] if len(parts)>=2 else ""
        attr = 1 if ("[I]" in s or "[/I]" in s) else 0
        left  = left.replace("[I]","").replace("[/I]","")
        right = right.replace("[I]","").replace("[/I]","")
        center= center.replace("[I]","").replace("[/I]","")
        color = COLOR_CYAN if "cyan" in s.lower() else COLOR_WHITE
        return left, center, right, color, attr

    def parse_xml_to_frame(self, xml_str: str) -> Frame:
        f = Frame()
        try:
            root = ET.fromstring(xml_str)
        except Exception:
            return f

        title       = (root.findtext("title") or "").strip()
        title_page  = (root.findtext("titlePage") or "").strip()
        scratchpad  = (root.findtext("scratchpad") or "").strip()
        lines       = [ (ln.text or "") for ln in root.findall("line") ]
        while len(lines) < 12: lines.append("")
        lines = lines[:12]

        f.lines[0] = LineRender(
            text=self._fmt_row("", title, title_page),
            color=COLOR_WHITE, col=1, attr=0
        )
        for i in range(12):
            left,center,right,color,attr = self._parse_line_frag(lines[i])
            txt = self._fmt_row(left, center, right)
            f.lines[i+1] = LineRender(text=txt, color=color, col=1, attr=attr)
        sp = (scratchpad or "")[:COLS].ljust(COLS)
        f.lines[13] = LineRender(text=sp, color=COLOR_WHITE, col=1, attr=0)
        return f

class LineDiffQueue:
    def __init__(self):
        self.prev: Optional[Frame] = None
        self.q: Deque[int] = deque()

    def ingest(self, newf: Frame):
        if self.prev is None:
            for i in range(DATA_MIN_LINE-1, LINE_COUNT):   # enqueue 3..14
                self.q.append(i+1)
            self.prev = newf
            return
        for i in range(LINE_COUNT):
            if (i+1) < DATA_MIN_LINE:
                continue
            if newf.lines[i].text != self.prev.lines[i].text or \
               newf.lines[i].color != self.prev.lines[i].color or \
               newf.lines[i].attr  != self.prev.lines[i].attr:
                self.q.append(i+1)
        self.prev = newf

    def pending_count(self) -> int:
        return len(self.q)

    def pop_next(self) -> Optional[int]:
        return self.q.popleft() if self.q else None

    def push_front_many(self, indices: List[int]):
        for idx in reversed(indices):
            self.q.appendleft(idx)

    def push_back(self, idx: int):
        self.q.append(idx)

    def has_any(self) -> bool:
        return bool(self.q)

# =========================
# ProSim-backed LRU (only 3–14 via DATA)
# =========================
class ProSimLRU(LRU):
    def __init__(self, sal_octal: int, channel: int):
        super().__init__("FMC", sal_octal, channel)
        self.norm = ProSimNormalizer()
        self.diffq = LineDiffQueue()
        self._pending_list: List[Tuple[int, LineRender]] = []
        self._first_paint_done: bool = False
        self._last_planned: int = 0
        self._last_batch_indices: List[int] = []

    def update_from_xml(self, xml_str: str):
        f = self.norm.parse_xml_to_frame(xml_str)
        self.diffq.ingest(f)
        if self.diffq.pending_count() == 0:
            self._first_paint_done = True

    def has_more_to_paint(self) -> bool:
        return self.diffq.pending_count() > 0

    def get_planned_records(self) -> int:
        pending = self.diffq.pending_count()
        if pending == 0:
            self._last_planned = 0
            self._first_paint_done = True
            return 0

        if not self._first_paint_done:
            self._last_planned = min(pending, DEFAULT_RTS_RECORD_CAP)
        else:
            self._last_planned = 1
        return self._last_planned

    def prepare_batch(self, count: int) -> None:
        self._pending_list.clear()
        self._last_batch_indices = []
        for _ in range(count):
            idx = self.diffq.pop_next()
            if idx is None:
                break
            if idx < DATA_MIN_LINE:
                continue
            self._pending_list.append((idx, self.diffq.prev.lines[idx-1]))
            self._last_batch_indices.append(idx)

    def get_page_text(self) -> List[TextData]:
        if not self._pending_list:
            return []
        out: List[TextData] = []
        for idx, lr in self._pending_list:
            text = lr.text if lr.text.strip() else " "
            out.append(TextData(
                text=text,
                color=lr.color,
                lineIdx=idx,
                initial_col=lr.col,
                disp_attr=lr.attr
            ))
        self._pending_list.clear()
        return out

    def requeue_last_batch_front(self):
        if self._last_batch_indices:
            log(f"[requeue] returning lines {self._last_batch_indices} to send-queue")
            self.diffq.push_front_many(self._last_batch_indices)
            self._last_batch_indices = []

# =========================
# ProSim key mapping (from your earlier working build)
# =========================
KEY_MAP: Dict[int, str] = {
    39: "S_CDU1_KEY_0", 17: "S_CDU1_KEY_1", 33: "S_CDU1_KEY_2", 49: "S_CDU1_KEY_3",
    19: "S_CDU1_KEY_4", 35: "S_CDU1_KEY_5", 51: "S_CDU1_KEY_6", 21: "S_CDU1_KEY_7",
    37: "S_CDU1_KEY_8", 53: "S_CDU1_KEY_9",
    75: "S_CDU1_KEY_A", 91: "S_CDU1_KEY_B", 107: "S_CDU1_KEY_C", 123: "S_CDU1_KEY_D",
    139: "S_CDU1_KEY_E", 73: "S_CDU1_KEY_F", 89: "S_CDU1_KEY_G", 105: "S_CDU1_KEY_H",
    121: "S_CDU1_KEY_I", 137: "S_CDU1_KEY_J", 65: "S_CDU1_KEY_K", 81: "S_CDU1_KEY_L",
    97: "S_CDU1_KEY_M", 113: "S_CDU1_KEY_N", 129: "S_CDU1_KEY_O", 67: "S_CDU1_KEY_P",
    83: "S_CDU1_KEY_Q", 99: "S_CDU1_KEY_R", 115: "S_CDU1_KEY_S", 131: "S_CDU1_KEY_T",
    69: "S_CDU1_KEY_U", 85: "S_CDU1_KEY_V", 101: "S_CDU1_KEY_W", 117: "S_CDU1_KEY_X",
    133: "S_CDU1_KEY_Y", 71: "S_CDU1_KEY_Z",

    145: "S_CDU1_KEY_CLEAR", 103: "S_CDU1_KEY_DEL",
    23: "S_CDU1_KEY_DOT", 55: "S_CDU1_KEY_MINUS", 119: "S_CDU1_KEY_SLASH", 87: "S_CDU1_KEY_SPACE",

    11: "S_CDU1_KEY_LSK1L", 13: "S_CDU1_KEY_LSK1R",
    9:  "S_CDU1_KEY_LSK2L", 15: "S_CDU1_KEY_LSK2R",
    27: "S_CDU1_KEY_LSK3L", 29: "S_CDU1_KEY_LSK3R",
    25: "S_CDU1_KEY_LSK4L", 31: "S_CDU1_KEY_LSK4R",
    43: "S_CDU1_KEY_LSK5L", 45: "S_CDU1_KEY_LSK5R",
    41: "S_CDU1_KEY_LSK6L", 47: "S_CDU1_KEY_LSK6R",

    141: "S_CDU1_KEY_EXEC",
    63:  "S_CDU1_KEY_INIT_REF",
    125: "S_CDU1_KEY_PROG",
    79:  "S_CDU1_KEY_RTE",
    93:  "S_CDU1_KEY_DEP_ARR",
    59:  "S_CDU1_KEY_FIX",
    95:  "S_CDU1_KEY_CLB",
    111: "S_CDU1_KEY_CRZ",
    127: "S_CDU1_KEY_DES",
    57:  "S_CDU1_KEY_NEXT_PAGE",
    147: "S_CDU1_KEY_PREV_PAGE",
    149: "S_CDU1_KEY_N1_LIMIT",
}

# =========================
# LRU state machine
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

        self.cts_max_recs: int = 1

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
                log(f"[MENU/DATA] ENQ for SAL={oct(self.lru.sal)} req={self.current_request_type} MAL={oct(self.mal_target)}")
                self.queue(TransmissionState.RTS)
                return

        if not self.repeat:
            self.message_repeat_count = 0
            self.repeat = True

    def _rts(self, logic, rx):
        for label, ts in rx:
            if A739.is_cts(label):
                self.cts_max_recs = (ArincLabel.Base.unpack_dec(label)[2] >> 16) & 0x7F
                log(f"[CTS] max_recs={self.cts_max_recs}")
                if self.current_request_type != RequestType.MENU.value:
                    desired = self.record_count
                    allowed = max(1, min(desired, self.cts_max_recs))
                    self.lru.prepare_batch(allowed)
                    self.record_count = allowed
                self.queue(TransmissionState.SEND_DATA)
                return

        if not self.repeat:
            if self.current_request_type == RequestType.MENU.value:
                self.record_count = 1
            else:
                planned = self.lru.get_planned_records()
                if planned == 0:
                    self.repeat = True
                    return
                self.record_count = max(1, min(planned, DEFAULT_RTS_RECORD_CAP))

            log(f"[RTS] sending RTS: req={self.current_request_type} recs={self.record_count} to MAL={oct(self.mal_target)}")
            rts_payload = (A739.DC2 << 16) | ((self.current_request_type & 0xF) << 8) | (self.record_count & 0xFF)
            rts = ArincLabel.Base.pack_dec_no_sdi_no_ssm(self.mal_target, rts_payload)
            logic.dev.send_manual_single_fast(self.lru.channel, rts)
            self.repeat = True

    def _send_data(self, logic, rx):
        if self.repeat:
            for label, ts in rx:
                if A739.is_syn(label):
                    log("[SEND] got SYN → retry")
                    self._retry_or_idle()
                    return
                if A739.is_ack(label):
                    log("[SEND] got ACK")
                    if self.current_request_type == RequestType.DATA.value:
                        if isinstance(self.lru, ProSimLRU) and self.lru.has_more_to_paint():
                            self.repeat = False
                            self.queue(TransmissionState.RTS)
                            return
                    self.queue(TransmissionState.IDLE)
                    return
                if A739.is_nack(label):
                    log("[SEND] got NAK → requeue & continue")
                    if isinstance(self.lru, ProSimLRU):
                        failed = getattr(self.lru, "_last_batch_indices", [])
                        for idx in failed:
                            if idx >= DATA_MIN_LINE:
                                self.lru.diffq.push_back(idx)
                        self.lru._last_batch_indices = []
                    if self.sender:
                        self.sender.ctrl.toggle()
                    self._retry_or_idle()
                    return

            if time.time() - self.message_response_elapsed_time > 1.5:
                log("[SEND] timeout → retry")
                self._retry_or_idle()
            return

        log(f"[SEND] req={self.current_request_type}")
        if self.current_request_type == RequestType.MENU.value:
            _ = self.sender.send_text_adaptive(
                self.mal_target, self.lru.name,
                line=1, col=1, color=Color.C7,
                disp_attr=0, last=True, rec_idx=1, rx_labels=rx
            )
        else:
            records = self.lru.get_page_text()
            if not records:
                self.queue(TransmissionState.IDLE)
                return
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
            self.locked_mal = None
            self.queue(TransmissionState.IDLE)

# =========================
# Main Logic wrapper (+ keyboard bridge)
# =========================
class Logic:
    def __init__(self):
        self.version = "mcdu_a739_prosim_bridge_v2.5"
        self.lru = ProSimLRU(LRU_SAL, ARINC_CARD_TX_CHNL)
        self.lrus = [LRUData(self.lru)]
        self.mcdu_rx_channel = ARINC_CARD_RX_CHNL
        self.dev: Optional[ArincAsync] = None
        self.data_recv = False
        self._last_xml = ""

        # Track pressed keys for auto-release + dedupe
        self._keys_down: Dict[str, float] = {}
        self._last_logical_key: Tuple[str, float] = ("", 0.0)

    # ---- Keyboard handling (to ProSim datarefs) ----
    def _set_prosim_key(self, name: str, val: int):
        try:
            if not hasattr(self, "datarefs") or not hasattr(self.datarefs, "prosim"):
                log("[key] datarefs.prosim NOT available")
                return False
            if not hasattr(self.datarefs.prosim, name):
                log(f"[key] datarefs.prosim.{name} attr missing")
                return False
            getattr(self.datarefs.prosim, name).value = val
            return True
        except Exception as e:
            log(f"[key] ERROR setting {name} -> {val}: {e}")
            return False

    def handle_key_press(self, logical_code: int, source: str, raw7: int = 0, raw8: int = 0):
        name = KEY_MAP.get(logical_code, "")
        log(f"[key] source={source} code={logical_code} mapped_to='{name}' (raw7={raw7}, raw8={raw8})")
        if not name:
            return

        # Dedupe very fast repeats of same logical key
        now = time.time()
        last_name, last_t = self._last_logical_key
        if last_name == name and (now - last_t) < KEY_DEDUPE_WINDOW:
            log(f"[key] dedupe {name} (Δt={(now-last_t):.3f}s)")
            return
        self._last_logical_key = (name, now)

        if name in self._keys_down:
            # already pressed; just refresh timestamp for release
            self._keys_down[name] = now
            return

        if self._set_prosim_key(name, 1):
            self._keys_down[name] = now
            log(f"[key] {name} -> 1 (pressed)")

    def _release_old_keys(self):
        if not self._keys_down:
            return
        now = time.time()
        to_release = [k for k,t0 in self._keys_down.items() if (now - t0) >= KEY_RELEASE_AFTER]
        for k in to_release:
            if self._set_prosim_key(k, 0):
                log(f"[key] {k} -> 0 (released)")
            self._keys_down.pop(k, None)

    async def update(self):
        if not hasattr(self, "devices") or self.devices is None or len(self.devices) == 0:
            log("[wait] No ARINC devices registered yet.")
            return

        dev = self.devices.get(ARINC_CARD_NAME) or self.devices[next(iter(self.devices.keys()))]
        self.dev = dev
        if not self.dev.is_ready:
            log("[wait] ARINC device exists but isn’t ready yet.")
            return

        # Drain RX — detect keyboard immediately (works in any state)
        received_labels: List[Tuple[int, float]] = []
        while True:
            try:
                label, ts = self.dev._rx_chnl[self.mcdu_rx_channel]._label_queue.popleft()
                received_labels.append((label, ts))
                p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                decoded_label = ArincLabel.Base._reverse_label_number(label_id)
                sal_field = (data >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK

                if sal_field in (A739.ENQ, A739.DC3, A739.ACK, A739.SYN, A739.NACK, A739.DC1):
                    log(f"[rx] label={oct(decoded_label)} ctl={sal_field:02x} data=0x{data:06X}")

                # ---- Path 1: ARINC-739 DC1 keyboard (preferred) ----
                if A739.is_keyboard(data):
                    key, seq, rep = A739.get_key_data(data)
                    log(f"[rx-key/739] key={key} seq={seq} rep={rep} (label={oct(decoded_label)})")
                    # Try 739 key directly
                    self.handle_key_press(key, source="A739-DC1", raw7=key, raw8=0)

                # ---- Path 2: Legacy raw scan on label 0o004 (your unit path)
                # CHAR was packed at bits [19:13] in your original code.
                if decoded_label == self.lru.sal and not A739.is_keyboard(data):
                    raw7 = (data >> 13) & 0x7F
                    raw8 = (data >> 12) & 0xFF
                    mapped7 = KEY_MAP.get(raw7, "")
                    mapped8 = KEY_MAP.get(raw8, "")

                    if mapped7 or mapped8:
                        # Pick whichever actually maps; prefer 7-bit if valid
                        if mapped7:
                            log(f"[rx-key/LEGACY] good_bits key_raw_7bit={raw7} → {mapped7}")
                            self.handle_key_press(raw7, source="LEGACY-7BIT", raw7=raw7, raw8=raw8)
                        else:
                            log(f"[rx-key/LEGACY] fallback key_raw_8bit={raw8} → {mapped8}")
                            self.handle_key_press(raw8, source="LEGACY-8BIT", raw7=raw7, raw8=raw8)
                    else:
                        # Log both so we can expand the table if needed
                        log(f"[rx-key/LEGACY] unknown raw7={raw7} raw8={raw8} (no map)")

            except Exception:
                break

        if received_labels:
            self.data_recv = True

        # Feed latest ProSim XML
        try:
            xml_string = self.datarefs.prosim.cdu1.value
        except Exception:
            xml_string = ""

        if xml_string and xml_string != self._last_xml:
            self.lru.update_from_xml(xml_string)
            self._last_xml = xml_string

        # Release keys after debounce
        self._release_old_keys()

        # Heartbeat + state update
        now = time.time()
        for lru_data in self.lrus:
            if (now - lru_data.heartbeat_elapsed_time) >= HEARTBEAT_SEC:
                sal_payload = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
                sal_id = ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload)
                self.dev.send_manual_single_fast(lru_data.lru.channel, sal_id)
                lru_data.heartbeat_elapsed_time = now

            lru_data.update(self, lru_data, received_labels)
