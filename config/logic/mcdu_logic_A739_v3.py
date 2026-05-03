from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

from fast_enum import FastEnum
from enum import IntEnum
from typing import List, Optional, Tuple
import time
import re
import xml.etree.ElementTree as ET
import queue

# =========================
# Config
# =========================
LRU_SAL = 0o300
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3
HEARTBEAT_SEC = 0.9
ENABLE_SPACE_PADDING_FOR_COLUMN = True
ARINC_WORD_GAP_SEC = 0.0
MCDU_COLS = 24
MCDU_DATA_LINES = 12
COLOR_WHITE = 7
COLOR_GREEN = 2
ROW_COLORS = (7,7,2,7,2,7,2,7,2,7,2,7,2,7)

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

def log(msg: str):
    print(msg)

class TextData:
    def __init__(self, text: str, color: int, lineIdx: int, initial_col: int = 1, disp_attr: int = 0):
        self.text = text
        self.color = color & 0x7
        self.lineIdx = max(1, min(31, lineIdx))
        self.initial_col = max(1, min(24, initial_col))
        self.disp_attr = disp_attr & 0x7

class A739:
    ENQ  = 0b0000101
    DC1  = 0b0010001
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
    def is_keyboard(dw): return ((dw >> A739.SAL_TYPE_SHIFT) & A739.SAL_TYPE_MASK) == A739.DC1
    @staticmethod
    def get_key_data(dw):
        return (dw >> 16) & 0x7F, (dw >> 8) & 0x7F, (dw >> 23) & 0x1
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
        stx_payload = (A739.STX << 16) | ((record_index & 0xFF) << 8) | count
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, stx_payload)

    def build_etx_eot(self, mal_target, record_index, last):
        end_code = A739.EOT if last else A739.ETX
        payload  = (end_code << 16) | ((record_index & 0xFF) << 8)
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def cntrl_A(self, mal_target, *, color, line, col, attr):
        line = max(1, min(31, line)); col = max(1, min(24, col))
        color &= 0x7; attr &= 0x7
        payload = ((A739.CNTRL << 16) | ((color & 0x7) << 13) | ((line & 0x1F) << 8) | ((attr & 0x7) << 5) | (col & 0x1F))
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def cntrl_B(self, mal_target, *, color, line, col_unused, attr_as_function):
        color &= 0x7; lineStart = max(1, min(31, line)); lineCount = 1; function = attr_as_function & 0x7
        payload = ((A739.CNTRL << 16) | ((color & 0x7) << 12) | ((lineCount & 0xF) << 8) | ((function & 0x7) << 5) | (lineStart & 0x1F))
        return ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload)

    def set_preferred(self, tag):
        if tag in ('A', 'B'): self._preferred = tag
    def get_preferred(self): return self._preferred

class RobustSender:
    def __init__(self, dev, channel):
        self.dev = dev; self.channel = channel; self.ctrl = ControlEncoder()

    def _send_word(self, word):
        self.dev.send_manual_single_fast(self.channel, word)
        if ARINC_WORD_GAP_SEC > 0: time.sleep(ARINC_WORD_GAP_SEC)

    def _send_data_words(self, mal_target, text):
        words = A739.num_words_for_text(text); sent = 0
        for _ in range(words):
            c1 = ord(text[sent])     if sent     < len(text) else 0
            c2 = ord(text[sent + 1]) if sent + 1 < len(text) else 0
            c3 = ord(text[sent + 2]) if sent + 2 < len(text) else 0
            payload = (c3 << 16) | (c2 << 8) | c1
            self._send_word(ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, payload))
            sent += 3
        return words

    def _try_send_once(self, mal_target, text, *, line, col, color, disp_attr, last, rec_idx, encoder_tag):
        if ENABLE_SPACE_PADDING_FOR_COLUMN and col > 1:
            text_to_send = (" " * (col - 1)) + text; effective_col = 1
        else:
            text_to_send = text; effective_col = col
        data_words = A739.num_words_for_text(text_to_send)
        self._send_word(self.ctrl.build_stx(mal_target, rec_idx, data_words))
        if encoder_tag == 'A':
            self._send_word(self.ctrl.cntrl_A(mal_target, color=color, line=line, col=effective_col, attr=disp_attr))
        else:
            self._send_word(self.ctrl.cntrl_B(mal_target, color=color, line=line, col_unused=effective_col, attr_as_function=0))
        self._send_data_words(mal_target, text_to_send)
        self._send_word(self.ctrl.build_etx_eot(mal_target, rec_idx, last))
        return encoder_tag

    def send_text_adaptive(self, mal_target, text, *, line, col, color, disp_attr, last, rec_idx, rx_labels):
        preferred = self.ctrl.get_preferred()
        order = ['A', 'B'] if preferred is None else [preferred, 'B' if preferred == 'A' else 'A']
        for attempt_tag in order:
            log(f"[send] rec={rec_idx} try CNTRL-{attempt_tag} line={line} col={col} color={color}")
            self._try_send_once(mal_target, text, line=line, col=col, color=color, disp_attr=disp_attr, last=last, rec_idx=rec_idx, encoder_tag=attempt_tag)
            saw_syn = any(A739.is_syn(l) for l, _ in rx_labels)
            saw_ack = any(A739.is_ack(l) for l, _ in rx_labels)
            if saw_ack and not saw_syn:
                self.ctrl.set_preferred(attempt_tag); log(f"[send] CNTRL-{attempt_tag} accepted (ACK)."); return True
            if saw_syn and not saw_ack:
                log(f"[send] CNTRL-{attempt_tag} rejected (SYN). Trying alternative..."); continue
            return True
        return False

# =========================
# XML / display parsing helpers
# =========================
_CYRILLIC_TO_NUMBER = {'A':'0','B':'1','B':'2','G':'3','D':'4','E':'5','ZH':'6','Z':'7','I':'8','J':'9'}
_CYRILLIC_MAP = {'А':'0','Б':'1','В':'2','Г':'3','Д':'4','Е':'5','Ж':'6','З':'7','И':'8','Й':'9'}
_NUMBER_TO_CYRILLIC = {v: k for k, v in _CYRILLIC_MAP.items()}

def _convert_numbers_to_cyrillic(text):
    return ''.join(_NUMBER_TO_CYRILLIC.get(c, c) for c in text)

def _strip_display_controls(text):
    result = []
    for c in text:
        if c in ('Ф', 'Ю'): continue
        result.append(_CYRILLIC_MAP.get(c, c))
    return ''.join(result)

def _parse_display_line(input_str, lower_case=False):
    DELIMITER = "\u00A8"
    if not input_str: return ["", "", ""]

    def process_s(content):
        return _convert_numbers_to_cyrillic(content.lower())

    def strip_s_tags(s):
        s = re.sub(r'\[s\](.*?)\[/s\]', lambda m: process_s(m.group(1)), s)
        s = re.sub(r'\[S\](.*?)\[/S\]', lambda m: process_s(m.group(1)), s)
        return s.replace("[s]", "").replace("[/s]", "")

    if lower_case:
        input_str = _convert_numbers_to_cyrillic(input_str.lower())
    input_str = strip_s_tags(input_str)
    input_str = input_str.replace("[]", "#").replace("[l]", "").replace("[/l]", "")
    for t in ("[I]","[1]","[2]","[3]","[/I]","[/1]","[/2]","[/3]"): input_str = input_str.replace(t, "")

    dc = input_str.count(DELIMITER); left = center = right = ""
    if dc == 2: left, center, right = input_str.split(DELIMITER, 2)
    elif dc == 1: left, right = input_str.split(DELIMITER, 1)
    else: left = input_str

    m = re.search(r'\[m\](.*?)\[/m\]', input_str)
    if m:
        center = m.group(1)
        left = left.replace(m.group(0), ''); right = right.replace(m.group(0), '')
    return [left, center, right]

def _format_row(left="", center="", right="", cols=MCDU_COLS):
    row = [' '] * cols
    for i, ch in enumerate(left):
        if i < cols: row[i] = ch
    rs = cols - len(right)
    for i, ch in enumerate(right):
        if 0 <= rs + i < cols: row[rs + i] = ch
    cs = (cols - len(center)) // 2
    for i, ch in enumerate(center):
        if 0 <= cs + i < cols: row[cs + i] = ch
    return ''.join(row)

def _parse_xml(xml_string):
    root = ET.fromstring(xml_string)
    def txt(tag): n = root.find(tag); return (n.text or "") if n is not None else ""
    lines = [l.text or "" for l in root.findall('line')]
    lines = (lines + [""] * MCDU_DATA_LINES)[:MCDU_DATA_LINES]
    return {"title": txt('title'), "title_page": txt('titlePage'), "scratchpad": txt('scratchpad'), "lines": lines}

def _xml_to_text_data(xml_result):
    records = []
    title_parts = _parse_display_line(xml_result["title"])
    left_align = title_parts[0]
    try: title_spaces = int(title_parts[1]) if title_parts[1] else 0
    except ValueError: title_spaces = 0
    title_text = _format_row(
        ' ' * title_spaces + title_parts[2] if left_align == "True" else "",
        title_parts[2] if left_align != "True" else "",
        _convert_numbers_to_cyrillic(xml_result["title_page"]) if xml_result["title_page"] else "",
    )
    title_text = _strip_display_controls(title_text).ljust(MCDU_COLS)[:MCDU_COLS]
    records.append(TextData(title_text, ROW_COLORS[0], lineIdx=1, initial_col=1))
    for ln, raw in enumerate(xml_result["lines"]):
        parts = _parse_display_line(raw, lower_case=(ln % 2 == 0))
        row_text = _strip_display_controls(_format_row(*parts)).ljust(MCDU_COLS)[:MCDU_COLS]
        records.append(TextData(row_text, ROW_COLORS[ln + 1], lineIdx=ln + 2, initial_col=1))
    sp = _strip_display_controls(xml_result["scratchpad"]).ljust(MCDU_COLS)[:MCDU_COLS]
    records.append(TextData(sp, ROW_COLORS[13], lineIdx=14, initial_col=1))
    return records

# =========================
# LRU base
# =========================
class LRU:
    def __init__(self, name, sal, channel):
        self.name = name; self.sal = sal; self._channel = channel
    @property
    def channel(self): return self._channel
    @channel.setter
    def channel(self, value):
        if value < 0 or value > 4: raise Exception("Channel idx out of bounds")
        self._channel = value
    def get_page_records(self): return 0
    def get_page_text(self): return []

class ProSimLRU(LRU):
    def __init__(self):
        super().__init__("PROSIM", LRU_SAL, ARINC_CARD_TX_CHNL)
        self._page = []

    def update_from_xml(self, xml_string):
        try:
            self._page = _xml_to_text_data(_parse_xml(xml_string))
            log(f"[prosim] page updated ({len(self._page)} records)")
        except Exception as e:
            log(f"[prosim] XML parse error: {e}")

    def get_page_records(self): return len(self._page)
    def get_page_text(self): return list(self._page)

# =========================
# State machine
# =========================
class LRUData:
    def __init__(self, lru):
        self.state = TransmissionState.IDLE
        self.next_state = TransmissionState.IDLE
        self.heartbeat_elapsed_time = time.time()
        self.lru = lru
        self.message_response_elapsed_time = 0.0
        self.message_repeat_count = 0
        self.current_request_type = RequestType.MENU.value
        self.record_count = 1
        self.mal_target = None
        self.locked_mal = None
        self.repeat = False
        self.sender = None

    def queue(self, new_state):
        if new_state != self.state:
            log(f"Transition: {self.state} -> {new_state}")
            self.next_state = new_state

    def update(self, logic, lru_data, rx):
        if self.next_state != self.state:
            self.repeat = False; self.state = self.next_state
        if self.state == TransmissionState.IDLE: self._idle(logic, rx)
        elif self.state == TransmissionState.RTS: self._rts(logic, rx)
        elif self.state == TransmissionState.SEND_DATA: self._send_data(logic, rx)

    def _idle(self, logic, rx):
        if self.sender is None and logic.dev is not None:
            self.sender = RobustSender(logic.dev, self.lru.channel)
        for label, ts in rx:
            p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
            decoded_label = ArincLabel.Base._reverse_label_number(label_id)
            if decoded_label == self.lru.sal and A739.is_enq(label):
                req = A739.get_request_type(label); mal = A739.get_mal(label)
                if self.locked_mal is None:
                    self.locked_mal = mal; log(f"[lock] MAL {oct(mal)}")
                self.mal_target = self.locked_mal; self.current_request_type = req
                log(f"ENQ Received (req={req}) MAL={oct(mal)}")
                self.queue(TransmissionState.RTS); return
        if not self.repeat:
            self.message_repeat_count = 0; self.repeat = True

    def _rts(self, logic, rx):
        for label, ts in rx:
            if A739.is_cts(label):
                max_recs = (ArincLabel.Base.unpack_dec(label)[2] >> 16) & 0x7F
                log(f"CTS Received (max_recs={max_recs})")
                self.queue(TransmissionState.SEND_DATA); return
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
                if A739.is_syn(label): log("SYN -> retry"); self._retry_or_idle(); return
                if A739.is_ack(label): log("ACK"); self.queue(TransmissionState.IDLE); return
                if A739.is_nack(label): log("NAK -> retry"); self._retry_or_idle(); return
            if time.time() - self.message_response_elapsed_time > 1.5: self._retry_or_idle()
            return
        if self.current_request_type == RequestType.MENU.value:
            self.sender.send_text_adaptive(self.mal_target, self.lru.name, line=1, col=1, color=Color.C7, disp_attr=0, last=True, rec_idx=1, rx_labels=rx)
        else:
            records = self.lru.get_page_text()
            if not records: self.queue(TransmissionState.IDLE); return
            for idx, rec in enumerate(records):
                ok = self.sender.send_text_adaptive(self.mal_target, rec.text, line=rec.lineIdx, col=rec.initial_col, color=rec.color, disp_attr=rec.disp_attr, last=(idx == len(records) - 1), rec_idx=idx + 1, rx_labels=rx)
                if not ok: self._retry_or_idle(); return
        self.message_response_elapsed_time = time.time(); self.repeat = True

    def _retry_or_idle(self):
        if self.message_repeat_count < 3:
            self.message_repeat_count += 1; self.repeat = False; self.queue(TransmissionState.RTS)
        else:
            self.queue(TransmissionState.IDLE)

# =========================
# Key map: A739 DC1 key code -> ProSim dataref name
# =========================
_KEY_MAP = {
     39: "S_CDU1_KEY_0",   17: "S_CDU1_KEY_1",   33: "S_CDU1_KEY_2",
     49: "S_CDU1_KEY_3",   19: "S_CDU1_KEY_4",   35: "S_CDU1_KEY_5",
     51: "S_CDU1_KEY_6",   21: "S_CDU1_KEY_7",   37: "S_CDU1_KEY_8",
     53: "S_CDU1_KEY_9",   75: "S_CDU1_KEY_A",   91: "S_CDU1_KEY_B",
    107: "S_CDU1_KEY_C",   95: "S_CDU1_KEY_CLB", 145: "S_CDU1_KEY_CLEAR",
    111: "S_CDU1_KEY_CRZ", 123: "S_CDU1_KEY_D",  103: "S_CDU1_KEY_DEL",
     93: "S_CDU1_KEY_DEP_ARR", 127: "S_CDU1_KEY_DES", 23: "S_CDU1_KEY_DOT",
    139: "S_CDU1_KEY_E",   141: "S_CDU1_KEY_EXEC", 73: "S_CDU1_KEY_F",
     59: "S_CDU1_KEY_FIX",  89: "S_CDU1_KEY_G",  105: "S_CDU1_KEY_H",
    109: "S_CDU1_KEY_HOLD", 121: "S_CDU1_KEY_I",   63: "S_CDU1_KEY_INIT_REF",
    137: "S_CDU1_KEY_J",    65: "S_CDU1_KEY_K",    81: "S_CDU1_KEY_L",
     77: "S_CDU1_KEY_LEGS",  11: "S_CDU1_KEY_LSK1L", 13: "S_CDU1_KEY_LSK1R",
      9: "S_CDU1_KEY_LSK2L", 15: "S_CDU1_KEY_LSK2R", 27: "S_CDU1_KEY_LSK3L",
     29: "S_CDU1_KEY_LSK3R", 25: "S_CDU1_KEY_LSK4L", 31: "S_CDU1_KEY_LSK4R",
     43: "S_CDU1_KEY_LSK5L", 45: "S_CDU1_KEY_LSK5R", 41: "S_CDU1_KEY_LSK6L",
     47: "S_CDU1_KEY_LSK6R", 97: "S_CDU1_KEY_M",    55: "S_CDU1_KEY_MINUS",
    113: "S_CDU1_KEY_N",   149: "S_CDU1_KEY_N1_LIMIT", 57: "S_CDU1_KEY_NEXT_PAGE",
    129: "S_CDU1_KEY_O",    67: "S_CDU1_KEY_P",   147: "S_CDU1_KEY_PREV_PAGE",
    125: "S_CDU1_KEY_PROG", 83: "S_CDU1_KEY_Q",    99: "S_CDU1_KEY_R",
     79: "S_CDU1_KEY_RTE", 115: "S_CDU1_KEY_S",   119: "S_CDU1_KEY_SLASH",
     87: "S_CDU1_KEY_SPACE",131: "S_CDU1_KEY_T",    69: "S_CDU1_KEY_U",
     85: "S_CDU1_KEY_V",   101: "S_CDU1_KEY_W",   117: "S_CDU1_KEY_X",
    133: "S_CDU1_KEY_Y",    71: "S_CDU1_KEY_Z",
}

# =========================
# Main Logic wrapper
# =========================
class Logic:
    def __init__(self):
        self.version = "mcdu_a739_prosim_v3.0"
        self._prosim_lru = ProSimLRU()
        self.lrus = [LRUData(self._prosim_lru)]
        self.mcdu_rx_channel = ARINC_CARD_RX_CHNL
        self.data_recv = False
        self.dev = None
        self._cdu1_text_prev = ""
        self._key_q = queue.Queue()

    def _handle_key(self, key_code):
        dataref_name = _KEY_MAP.get(key_code, "")
        if dataref_name:
            log(f"[key] {dataref_name} (code={key_code})")
            try:
                getattr(self.datarefs.prosim, dataref_name).value = 1
                self._key_q.put(dataref_name)
            except Exception as e:
                log(f"[key] dataref error: {e}")

    def _release_pending_keys(self):
        while not self._key_q.empty():
            try:
                getattr(self.datarefs.prosim, self._key_q.get_nowait()).value = 0
            except Exception:
                pass

    async def update(self):
        if not hasattr(self, "devices") or self.devices is None or len(self.devices) == 0:
            log("[wait] No ARINC devices registered yet."); return
        if ARINC_CARD_NAME in self.devices:
            dev = self.devices[ARINC_CARD_NAME]
        else:
            first_key = next(iter(self.devices.keys()))
            log(f"[warn] '{ARINC_CARD_NAME}' not found; using '{first_key}'"); dev = self.devices[first_key]
        self.dev = dev
        if not self.dev.is_ready:
            log("[wait] ARINC device exists but isn't ready yet."); return

        received_labels = []
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

        if received_labels: self.data_recv = True

        self._release_pending_keys()
        for label, ts in received_labels:
            # Primary: handle label 4 (hardware key codes, same format as v2)
            p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
            if label_id == 4:
                key_hex = (label >> 12) & 0xFF
                if key_hex > 0:
                    self._handle_key(key_hex)
            # Secondary: handle ARINC 739 DC1 keyboard labels if present
            elif A739.is_keyboard(label):
                key_code, sequence, repeat = A739.get_key_data(label)
                if not repeat:
                    self._handle_key(key_code)

        try:
            xml_string = self.datarefs.prosim.cdu1.value
            if xml_string and xml_string.startswith("<") and xml_string != self._cdu1_text_prev:
                self._prosim_lru.update_from_xml(xml_string)
                self._cdu1_text_prev = xml_string
                # Force immediate heartbeat so the MCDU gets an ENQ prompt right away
                for lru_data in self.lrus:
                    lru_data.heartbeat_elapsed_time = 0
        except Exception as e:
            log(f"[prosim] dataref read error: {e}")

        now = time.time()
        for lru_data in self.lrus:
            if (now - lru_data.heartbeat_elapsed_time) >= HEARTBEAT_SEC and lru_data.state != TransmissionState.SEND_DATA:
                sal_payload = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
                sal_id = ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload)
                self.dev.send_manual_single_fast(lru_data.lru.channel, sal_id)
                lru_data.heartbeat_elapsed_time = now
            lru_data.update(self, lru_data, received_labels)
