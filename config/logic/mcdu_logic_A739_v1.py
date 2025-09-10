from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

from fast_enum import FastEnum
from typing import List, Optional, Tuple
import time

# =========================
# Config
# =========================
LRU_SAL = 0o300                  # Your test SAL (advertised via label 0o172)
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3

# Probe controls
PROBE_ENABLE = True                 # set False to disable probing
PROBE_MALS = [0o220, 0o221, 0o222, 0o230]  # typical MCDU MALs
PROBE_ENQ_TIMEOUT = 2.0             # if no ENQ seen for this many seconds, start probing
PROBE_RTS_PERIOD = 2.0              # min interval between probe rounds
PROBE_FASTPATH_SEND_HELLO = True    # send one HELLO record immediately after CTS (debug cannon)


# =========================
# Enums
# =========================
class TransmissionState(metaclass=FastEnum):
    IDLE: "Idle" = 0
    RTS: "Enq" = 1
    SEND_DATA: "Send_Data" = 2
    ACK: "Ack" = 3
    SCRATCHPAD: "Keypress" = 4


class RequestType(metaclass=FastEnum):
    DATA: "Data" = 0     # Normal Page Text Request
    MENU: "Menu" = 1     # Menu Text Request


# =========================
# Helpers / DTOs
# =========================
def log(msg: str):
    print(msg)


class TextData:
    def __init__(self, text: str, color: int, lineIdx: int):
        self.text = text
        self.color = color & 0x7     # 3-bit color per spec
        self.lineIdx = lineIdx       # 1..n line start


class A739Utils:
    # Control/handshake codes
    ENQ  = 0b0000101  # 0x05
    DC1  = 0b0010001  # 0x11 (Scratchpad/Button Push)
    DC2  = 0b0010010  # 0x12 (RTS)
    DC3  = 0b0010011  # 0x13 (CTS)
    SYN  = 0b0010110  # 0x16
    STX  = 0b10       # 0x02 (Start of Text record)
    CNTRL= 0b1        # 0x01 (Control word)
    ETX  = 0b11       # 0x03 (End of Text record, more to follow)
    EOT  = 0b100      # 0x04 (End of Transmission - last record)
    ACK  = 0b110      # 0x06
    NACK = 0b10101    # 0x15 (NAK)

    CLR  = 0b1000     # example “CLR” key code for test logic

    # Bit fields inside 32-bit word
    SAL_TYPE_MASK  = 0x7F
    SAL_TYPE_SHIFT = 24

    REQUEST_TYPE_SHIFT = 16
    REQUEST_TYPE_MASK  = 0xF

    MAL_MASK  = 0xFF
    MAL_SHIFT = 8

    @staticmethod
    def num_of_data_record_per_string(s: str) -> int:
        # 3 printable chars per 429 data word
        return (len(s) + 2) // 3

    @staticmethod
    def is_enq(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.ENQ

    @staticmethod
    def is_cts(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.DC3

    @staticmethod
    def is_keyboard(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.DC1

    @staticmethod
    def get_key_data(data_word: int) -> Tuple[int, int, int]:
        key = (data_word >> 16) & 0x7F
        sequence = (data_word >> 8) & 0x7F
        repeat = (data_word >> 23) & 0x1
        return key, sequence, repeat

    @staticmethod
    def is_syn(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.SYN

    @staticmethod
    def is_ack(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.ACK

    @staticmethod
    def is_nack(data_word: int) -> bool:
        return ((data_word >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK) == A739Utils.NACK

    @staticmethod
    def get_request_type(data_word: int) -> int:
        return (data_word >> A739Utils.REQUEST_TYPE_SHIFT) & A739Utils.REQUEST_TYPE_MASK

    @staticmethod
    def get_mal(data_word: int) -> int:
        # MAL is in bits 1..8 of the payload in ENQ; return octal label number
        octal_label = ArincLabel.Base._reverse_label_number((data_word >> A739Utils.MAL_SHIFT) & A739Utils.MAL_MASK)
        return octal_label

    @staticmethod
    def send_record(
        dev: ArincAsync,
        mal_target: int,
        channel: int,
        message_text: str,
        recordIdx: int,
        lastRecord: bool,
        colorCode: int = 0x7,
        lineStart: int = 1,
        lineCount: int = 1,
        function: int = 0
    ):
        """
        Send one text 'record' as: STX -> CNTRL -> DATA words (3 chars each) -> ETX/EOT.
        mal_target: MAL label (octal), ex: 0o220..0o230
        """
        log("Sending data words")

        num_data_words = A739Utils.num_of_data_record_per_string(message_text)

        # STX:  record index, and a "count" (using your prior scheme: num_data_words + 3)
        stx_payload = (A739Utils.STX << 16) | ((recordIdx & 0xFF) << 8) | ((num_data_words + 3) & 0xFF)
        stx = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, stx_payload)
        dev.send_manual_single_fast(channel, stx)

        # CNTRL: color(3) lineCount(4) function(3) lineStart(5)
        cntrl_payload = (
            (A739Utils.CNTRL << 16)
            | ((colorCode & 0x7) << 12)
            | ((lineCount & 0xF) << 8)
            | ((function & 0x7) << 5)
            | (lineStart & 0x1F)
        )
        cntrl = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, cntrl_payload)
        dev.send_manual_single_fast(channel, cntrl)

        # DATA words: 3 chars per 429 data word (low->high = char1, char2, char3)
        for i in range(num_data_words):
            c1 = ord(message_text[i * 3]) if (i * 3) < len(message_text) else 0
            c2 = ord(message_text[i * 3 + 1]) if (i * 3 + 1) < len(message_text) else 0
            c3 = ord(message_text[i * 3 + 2]) if (i * 3 + 2) < len(message_text) else 0
            data_payload = (c3 << 16) | (c2 << 8) | c1
            data_word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, data_payload)
            dev.send_manual_single_fast(channel, data_word)

        # End code
        end_code = A739Utils.EOT if lastRecord else A739Utils.ETX
        end_payload = (end_code << 16) | ((recordIdx & 0xFF) << 8)
        end_word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, end_payload)
        dev.send_manual_single_fast(channel, end_word)


# =========================
# LRU base + TEST LRU
# =========================
class LRU:
    def __init__(self, name: str, sal: int, channel: int):
        self.name = name  # name shown in menu
        self.sal = sal    # subsystem SAL
        self._channel = channel
        self.active = False

    @property
    def channel(self) -> int:
        return self._channel

    @channel.setter
    def channel(self, value: int):
        if value < 0 or value > 4:
            raise Exception("Channel idx out of bounds")
        self._channel = value

    def on_key_press(self, key: int, sequence: int, repeat: int):
        pass

    def has_scratchpad(self) -> bool:
        return False

    def get_scratchpad(self) -> List[str]:
        return [""] * 16

    def has_page_text(self) -> bool:
        return False

    def get_page_records(self) -> int:
        return 0

    def get_page_text(self) -> List[TextData]:
        return []


class TEST_LRU(LRU):
    def __init__(self):
        super().__init__("HELLO", LRU_SAL, ARINC_CARD_TX_CHNL)
        self.new_scratchpad_available: bool = False
        self.scratchpad: List[str] = [' '] * 16
        self.current_page: List[TextData] = [
            TextData("Hello world!! ", 0x5, 1),
            TextData("LINE 2 ",        0x4, 2),
            TextData("LINE 3 ",        0x4, 3),
        ]
        self.clear_set = False
        self.scratchpad_index = 0

    def on_key_press(self, key: int, sequence: int, repeat: int):
        log(f"Received chr {chr(key) if key>=32 else key} in seq {sequence} is repeat {bool(repeat)}")

        idx = max(0, min(15, sequence))  # bound to 0..15

        if key == A739Utils.CLR:
            if self.scratchpad_index == 0 and not self.clear_set:
                self.scratchpad[0] = 'C'
                self.scratchpad[1] = 'L'
                self.scratchpad[2] = 'R'
                self.clear_set = True
                self.scratchpad_index = 2
            else:
                self.scratchpad[self.scratchpad_index] = ' '
                self.scratchpad_index = max(0, self.scratchpad_index - 1)
        else:
            if self.clear_set:
                self.scratchpad = [' '] * 16
                self.scratchpad_index = 0
                self.clear_set = False

            self.scratchpad[idx] = chr(key)
            self.scratchpad_index = idx

        self.new_scratchpad_available = True

    def has_scratchpad(self) -> bool:
        return self.new_scratchpad_available

    def get_scratchpad(self) -> List[str]:
        self.new_scratchpad_available = False
        return self.scratchpad

    def has_page_text(self) -> bool:
        return True

    def get_page_records(self) -> int:
        return len(self.current_page)

    def get_page_text(self) -> List[TextData]:
        return self.current_page


# =========================
# State machine
# =========================
class LRUData:
    def __init__(self, lru: LRU):
        self.state: TransmissionState = TransmissionState.IDLE
        self.next_state: TransmissionState = TransmissionState.IDLE

        # heart-beat for label 0o172 (~1Hz)
        self.heartbeat_elapsed_time: float = time.time()

        self.lru: LRU = lru
        self.message_response_elapsed_time: float = 0
        self.message_repeat_count: int = 0
        self.current_request_type: int = RequestType.MENU.value
        self.repeat: bool = False
        self.error_count: int = 0
        self.record_count: int = 1
        self.mal_target: int = 0       # 0o220..0o230 once ENQ is seen

        # probe tracking
        self.last_enq_seen_ts: float = 0.0
        self.last_probe_ts: float = 0.0
        self.did_probe_once: bool = False

        self.states = {
            TransmissionState.IDLE: Idle(),
            TransmissionState.RTS: RTS(),
            TransmissionState.SEND_DATA: SendData(),
            TransmissionState.SCRATCHPAD: Scratchpad(),
        }

    def queue_transition_to_state(self, new_state: TransmissionState):
        if new_state != self.state:
            log(f"Transition from: {self.state} to: {new_state}")
            self.next_state = new_state

    def update(self, logic, lru_data, received_labels):
        if self.next_state != self.state:
            prev_state = self.state
            self.states[self.state].on_de_activate(self.next_state)
            self.repeat = False
            self.state = self.next_state
            self.states[self.state].on_activate(prev_state)

        self.states[self.state].update(logic, lru_data, received_labels)


class State:
    def __init__(self, name: str, version: str, id: TransmissionState):
        self.version = version
        self.name = name
        self.id = id

    def on_activate(self, prev_state: TransmissionState):
        pass

    def update(self, logic, lru_data: LRUData, received_labels):
        pass

    def on_de_activate(self, next_state: TransmissionState):
        pass


class Idle(State):
    def __init__(self):
        super().__init__("IDLE", "1.0.0", TransmissionState.IDLE)

    def update(self, logic, lru_data: LRUData, received_labels):
        for label, timestamp in received_labels:
            p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
            decoded_label = ArincLabel.Base._reverse_label_number(label_id)

            # If addressed to our SAL (ENQ path uses SAL)
            if decoded_label == lru_data.lru.sal:
                if A739Utils.is_enq(label):
                    lru_data.last_enq_seen_ts = time.time()  # mark ENQ seen
                    log("ENQ Received")
                    req_id = A739Utils.get_request_type(label)
                    lru_data.mal_target = A739Utils.get_mal(label)
                    log(f"MAL is {oct(lru_data.mal_target)}")
                    log(f"Request type is {req_id}")
                    lru_data.current_request_type = req_id
                    lru_data.queue_transition_to_state(TransmissionState.RTS)

            if A739Utils.is_keyboard(label):
                log(f"Keyboard Received {timestamp}")
                key, sequence, repeat = A739Utils.get_key_data(label)
                lru_data.lru.on_key_press(key, sequence, repeat)
                # ACK must be within ~200ms
                ack = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.ACK << 16)
                logic.dev.send_manual_single_fast(lru_data.lru.channel, ack)

            # reset counters when returning to idle (first time only)
            if not lru_data.repeat:
                lru_data.message_repeat_count = 0
                lru_data.error_count = 0
                lru_data.repeat = True

            # if scratchpad has data ready, push it
            if lru_data.lru.has_scratchpad():
                lru_data.queue_transition_to_state(TransmissionState.SCRATCHPAD)


class RTS(State):
    def __init__(self):
        super().__init__("RTS", "1.0.0", TransmissionState.RTS)

    def update(self, logic, lru_data: LRUData, received_labels):
        # If we already got CTS, jump to SEND_DATA
        for label, timestamp in received_labels:
            if A739Utils.is_cts(label):
                max_records = (label >> 16) & 0x7F
                log(f"CTS Received with record count: {max_records}")
                lru_data.queue_transition_to_state(TransmissionState.SEND_DATA)
                return

        # Otherwise send RTS once per entry into this state
        if not lru_data.repeat:
            lru_data.record_count = 1 if lru_data.current_request_type == RequestType.MENU.value else lru_data.lru.get_page_records()

            rts_payload = (A739Utils.DC2 << 16) | ((lru_data.current_request_type & 0xF) << 8) | (lru_data.record_count & 0xFF)
            rts = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, rts_payload)
            logic.dev.send_manual_single_fast(lru_data.lru.channel, rts)
            print(oct(lru_data.mal_target), hex(rts))
            lru_data.repeat = True


class SendData(State):
    def __init__(self):
        super().__init__("SEND_DATA", "1.0.0", TransmissionState.SEND_DATA)
        self.wait_for_ack = False
        self.error_count = 0

    def handle_error(self) -> TransmissionState:
        self.error_count += 1
        if self.error_count < 3:
            return TransmissionState.IDLE
        self.error_count = 0
        return TransmissionState.IDLE

    def update(self, logic, lru_data: LRUData, received_labels):
        if self.wait_for_ack:
            for label, timestamp in received_labels:
                if A739Utils.is_syn(label):
                    log("SYN Received")
                    lru_data.queue_transition_to_state(self.handle_error())
                    return
                if A739Utils.is_ack(label):
                    log("ACK Received")
                    lru_data.queue_transition_to_state(TransmissionState.IDLE)
                    return
                if A739Utils.is_nack(label):
                    log("NACK Received")
                    lru_data.queue_transition_to_state(self.handle_error())
                    return

            # Wait for reply up to ~1.5s, then optionally retry
            if time.time() - lru_data.message_response_elapsed_time > 1.5:
                if lru_data.message_repeat_count <= 3:
                    lru_data.message_repeat_count += 1
                    lru_data.message_response_elapsed_time = time.time()
                    self.wait_for_ack = False
                else:
                    lru_data.queue_transition_to_state(TransmissionState.IDLE)
        else:
            # Transmit menu name or full page text
            if lru_data.current_request_type == RequestType.MENU.value:
                A739Utils.send_record(
                    logic.dev, lru_data.mal_target, lru_data.lru.channel,
                    lru_data.lru.name, 1, True
                )
            else:
                records = lru_data.lru.get_page_text()
                for idx, record in enumerate(records):
                    A739Utils.send_record(
                        logic.dev, lru_data.mal_target, lru_data.lru.channel,
                        record.text, idx + 1, (idx == len(records) - 1),
                        record.color, record.lineIdx
                    )
            self.wait_for_ack = True
            lru_data.message_response_elapsed_time = time.time()


class Scratchpad(State):
    def __init__(self):
        super().__init__("SCRATCHPAD", "1.0.0", TransmissionState.SCRATCHPAD)
        self.wait_for_ack = False
        self.error_count = 0
        self.current_scratchpad: Optional[List[str]] = None
        self.current_idx = 0

    def handle_error(self) -> TransmissionState:
        self.error_count += 1
        if self.error_count < 3:
            return TransmissionState.IDLE
        self.error_count = 0
        return TransmissionState.IDLE

    def on_de_activate(self, next_state: TransmissionState):
        if next_state == TransmissionState.IDLE:
            self.current_scratchpad = None
            self.current_idx = 0

    def update(self, logic, lru_data: LRUData, received_labels):
        if self.current_scratchpad is None:
            self.current_scratchpad = lru_data.lru.get_scratchpad()
            self.current_idx = 0

        for label, timestamp in received_labels:
            if A739Utils.is_keyboard(label):
                log(f"Keyboard Received {timestamp}")
                key, sequence, repeat = A739Utils.get_key_data(label)
                lru_data.lru.on_key_press(key, sequence, repeat)
                ack = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.ACK << 16)
                logic.dev.send_manual_single_fast(lru_data.lru.channel, ack)
                self.error_count = 0
                self.current_scratchpad = lru_data.lru.get_scratchpad()
                self.current_idx = 0
                self.wait_for_ack = False

            if self.wait_for_ack:
                if A739Utils.is_syn(label):
                    log("SYN Received")
                    lru_data.queue_transition_to_state(self.handle_error())
                    return
                if A739Utils.is_ack(label):
                    log("ACK Received")
                    self.current_idx += 1
                    if self.current_idx >= len(self.current_scratchpad):
                        lru_data.queue_transition_to_state(TransmissionState.IDLE)
                    self.wait_for_ack = False
                    return
                if A739Utils.is_nack(label):
                    log("NACK Received")
                    lru_data.queue_transition_to_state(self.handle_error())
                    return

        if not self.wait_for_ack:
            if self.current_scratchpad and len(self.current_scratchpad) > 0:
                ch = self.current_scratchpad[self.current_idx] if self.current_idx < len(self.current_scratchpad) else ' '
                payload = (A739Utils.DC1 << 16) | (ord(ch) << 8) | (0x4 << 5) | ((self.current_idx + 1) & 0x1F)
                log(f"Scratchpad index: {self.current_idx + 1} key: {ch}")
                word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, payload)
                logic.dev.send_manual_single_fast(lru_data.lru.channel, word)
                self.wait_for_ack = True
            else:
                payload = (A739Utils.DC1 << 16) | (ord(' ') << 8) | (0x4 << 5) | 1
                log("Sending empty scratchpad")
                word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, payload)
                logic.dev.send_manual_single_fast(lru_data.lru.channel, word)
                self.wait_for_ack = True


# =========================
# Probe helpers
# =========================
def send_probe_rts(dev, channel: int, mal: int, request_type: int = RequestType.MENU.value, record_count: int = 1):
    rts_payload = (A739Utils.DC2 << 16) | ((request_type & 0xF) << 8) | (record_count & 0xFF)
    rts = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal, rts_payload)
    dev.send_manual_single_fast(channel, rts)
    log(f"[probe] RTS -> MAL {oct(mal)} (req={request_type}, recs={record_count})")


# =========================
# Main Logic wrapper
# =========================
class Logic:
    def __init__(self):
        self.version = "v1.0.2"
        self.mal_target = 0
        self.current_lru = None
        self.lrus = [LRUData(TEST_LRU())]  # add more LRUs if desired
        self.mcdu_rx_channel = ARINC_CARD_RX_CHNL
        self.data_recv = False
        self.data_aux = 0

    async def update(self):
        self.dev = self.devices[ARINC_CARD_NAME]

        if self.dev.is_ready:
            received_labels = []

            # Drain RX queue for our MCDU channel
            while True:
                try:
                    label, timestamp = self.dev._rx_chnl[self.mcdu_rx_channel]._label_queue.popleft()
                    received_labels.append((label, timestamp))

                    # DEBUG decode every word we see
                    p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
                    decoded_label = ArincLabel.Base._reverse_label_number(label_id)
                    print(oct(decoded_label), ssm, sdi, data)

                    # Extra decode: show CTS/ACK/NAK/SYN loudly
                    sal_field = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
                    if sal_field == A739Utils.DC3:
                        mal_guess = ArincLabel.Base._reverse_label_number(((data >> A739Utils.MAL_SHIFT) & A739Utils.MAL_MASK))
                        log(f"[probe] <<< CTS seen from MAL {oct(mal_guess)}")
                        if PROBE_FASTPATH_SEND_HELLO:
                            # blast one HELLO record for bring-up
                            for lru_data in self.lrus:
                                log(f"[probe] CTS fast-path: sending HELLO to MAL {oct(mal_guess)} on ch {lru_data.lru.channel}")
                                A739Utils.send_record(self.dev, mal_guess, lru_data.lru.channel, "HELLO WORLD", 1, True, colorCode=0x5, lineStart=1)
                    elif sal_field == A739Utils.ACK:
                        log("[probe] <<< ACK seen")
                    elif sal_field == A739Utils.NACK:
                        log("[probe] <<< NAK seen")
                    elif sal_field == A739Utils.SYN:
                        log("[probe] <<< SYN seen")
                except Exception:
                    break

            if received_labels:
                self.data_recv = True

            now = time.time()

            # Probe: if no ENQ has been seen recently, actively try RTS to common MALs
            if PROBE_ENABLE:
                for lru_data in self.lrus:
                    # If we've seen ENQ within the timeout window, don't probe
                    if now - lru_data.last_enq_seen_ts > PROBE_ENQ_TIMEOUT:
                        if now - lru_data.last_probe_ts >= PROBE_RTS_PERIOD:
                            # Ensure SAL heartbeat is going out on THIS TX pair before probing
                            sal_payload = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
                            lru_identifier = ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload)
                            self.dev.send_manual_single_fast(lru_data.lru.channel, lru_identifier)
                            log("[probe] Sent SAL heartbeat 0o172 before RTS")

                            # Try RTS to candidate MALs
                            for mal in PROBE_MALS:
                                send_probe_rts(self.dev, lru_data.lru.channel, mal, RequestType.MENU.value, 1)
                                send_probe_rts(self.dev, lru_data.lru.channel, mal, RequestType.DATA.value, 1)
                                # optionally also try DATA:
                                

                            lru_data.last_probe_ts = now
                            lru_data.did_probe_once = True

            # Regular per-LRU loop (heartbeat + state machine)
            for lru_data in self.lrus:
                channel = lru_data.lru.channel

                # 1) Advertise SAL via label 0o172 about once per second (when not mid SEND_DATA)
                if (time.time() - lru_data.heartbeat_elapsed_time) >= 0.9 and lru_data.state != TransmissionState.SEND_DATA:
                    sal_payload = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
                    lru_identifier = ArincLabel.Base.pack_dec_no_sdi_no_ssm(0o172, sal_payload)
                    self.dev.send_manual_single_fast(channel, lru_identifier)

                    lru_data.heartbeat_elapsed_time = time.time()
                    self.data_aux += 1

                # 2) Run the state machine
                lru_data.update(self, lru_data, received_labels)
