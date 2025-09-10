
from resources.libs.arinc_lib.arinc_lib import ArincLabel
from resources.driver.arinc.arinc_async import ArincAsync

from fast_enum import FastEnum
from typing import List
import time

LRU_SAL = 0o300
ARINC_CARD_NAME: str = "arinc_1"
ARINC_CARD_TX_CHNL: int = 3
ARINC_CARD_RX_CHNL: int = 3

class TransmissionState(metaclass=FastEnum):
	IDLE: "Idle" = 0
	RTS: "Enq" = 1
	SEND_DATA: "Send_Data" = 2
	ACK: "Ack" = 3
	SCRATCHPAD: "Keypress" = 4
 
class RequestType(metaclass=FastEnum):
	DATA: "Data" = 0
	MENU: "Menu" = 1

def log(logText: str):
	print(logText)

class TextData():
	def __init__(self, text: str, color: int, lineIdx: int):
		self.text = text
		self.color = color
		self.lineIdx = lineIdx

class A739Utils:

	ENQ = 0b0000101 
	DC1 = 0b0010001
	DC2 = 0b0010010
	DC3 = 0b0010011
	SYN = 0b0010110
	STX = 0b10
	CNTRL = 0b1
	ETX = 0b11
	EOT = 0b100
	ACK = 0b110
	NACK = 0b110
	NACK = 0b10101
	CLR = 0b1000
 
	SAL_TYPE_MASK = 0x7F
	SAL_TYPE_SHIFT = 24

	REQUEST_TYPE_SHIFT = 16
	REQUEST_TYPE_MASK = 0xF

	MAL_MASK = 0xFF
	MAL_SHIFT = 8
    
	# returns the number of data words needed to trasmit this entire string
	@staticmethod
	def num_of_data_record_per_string(data: str) -> int:
		return  int(len(data) / 3)

	@staticmethod
	def is_enq(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.ENQ

	@staticmethod
	def is_cts(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.DC3

	@staticmethod
	def is_keyboard(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.DC1

	@staticmethod
	def get_key_data(data):
		key = (data >> 16) & 0x7F
		sequence = (data >> 8) & 0x7F
		repeat = (data >> 23) & 0x1
		return key, sequence, repeat

	@staticmethod
	def is_syn(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.SYN

	@staticmethod
	def is_ack(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.ACK
	
	@staticmethod
	def is_nack(data):
		word = (data >> A739Utils.SAL_TYPE_SHIFT) & A739Utils.SAL_TYPE_MASK
		return word == A739Utils.NACK
	
	@staticmethod
	def get_request_type(data):
		word = (data >> A739Utils.REQUEST_TYPE_SHIFT) & A739Utils.REQUEST_TYPE_MASK
		return word
	
	@staticmethod
	def get_mal(data):
		word = (data >> A739Utils.MAL_SHIFT) & A739Utils.MAL_MASK
		return ArincLabel.Base._reverse_label_number(word)
    
	@staticmethod
	def send_record(dev: ArincAsync, mal_target: int, channel: int, message_text:str, recordIdx: int, lastRecord: bool, colorCode:int = 0x7, lineCount:int = 1, function:int = 0, lineStart:int = 1, ):
		log("Sending data words")
				
		#determine number of data words to send, 1 word for 3 chars
		num_data_word = A739Utils.num_of_data_record_per_string(message_text) + 1
		stx = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, A739Utils.STX << 16 | recordIdx << 8 | num_data_word  + 3)
		dev.send_manual_single_fast(channel, stx)

		cntrl = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, A739Utils.CNTRL << 16 | (colorCode & 0x7) << 12 | (lineCount & 0xF) << 8 | (function & 0x7) << 5 | (lineStart & 0x1F))
		dev.send_manual_single_fast(channel, cntrl)
				
		data_word_count = 0
		while data_word_count < num_data_word:
			char_1 = 0 if len(message_text) <= data_word_count * 3 else  ord(message_text[data_word_count * 3])
			char_2 = 0 if len(message_text) <= data_word_count * 3 + 1 else  ord(message_text[data_word_count * 3 + 1])
			char_3 = 0 if len(message_text) <= data_word_count * 3 + 2 else  ord(message_text[data_word_count * 3 + 2])
			data = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, char_3 << 16 | char_2 << 8 | char_1)
			dev.send_manual_single_fast(channel, data)
			data_word_count = data_word_count + 1
		
		eot = ArincLabel.Base.pack_dec_no_sdi_no_ssm(mal_target, int(A739Utils.EOT if lastRecord else A739Utils.ETX) << 16 | recordIdx << 8)
		dev.send_manual_single_fast(channel, eot)

# Represents a Line Replaceable unit that can interface with an MCDU
class LRU:
	def __init__(self, name: str, sal: int, channel: int):
        # Name used for the menu
		self.name = name
        # SAL of the unit
		self.sal = sal
        # Channel this unit is connected on
		self.channel = channel
		# If this LRU is the active system
		self.active = False
    
	@property
	def channel(self) -> int:
		return self._channel
    
	@channel.setter
	def channel(self, value: int):
		if value < 0 or value > 4:
			raise Exception("Channel idx out of bounds")
		else:
			self._channel = value
   
	def on_key_press(self, key: int, sequence: int, repeat:int):
		pass

	def has_scratchpad(self) -> bool:
		return False

	def get_scratchpad(self) -> List[chr]:
		return [""] * 16

	def has_page_text(self) -> bool:
		return False

	def get_page_records(self) -> int:
		return 0

	def get_page_text(self) -> List[TextData]:
		return [""]

class TEST_LRU(LRU):
	def __init__(self):
		LRU.__init__(self, "HELLO", LRU_SAL, ARINC_CARD_TX_CHNL)
		self.new_scratchpad_available: bool = False
		self.scratchpad: List[chr] = [' '] * 16
		self.current_page: List[TextData] =  [TextData("FUCKING ALEEE!! ", 0x5, 1), TextData("LINE 2 ", 0x4, 2), TextData("LINE 3 ", 0x4, 3)]
		self.clear_set = False
		self.scratchpad_index = 0
  
	def on_key_press(self, key: int, sequence: int, repeat:int):
		log("Received chr " + chr(key) + " in seq " + str(sequence) + " is repeat " + str(bool(repeat)))
		if key == A739Utils.CLR:
			if self.scratchpad_index == 0 and not self.clear_set:
				self.scratchpad[0] = ['C']
				self.scratchpad[1] = ['L']
				self.scratchpad[2] = ['R']
				self.clear_set = True
			else:
				self.scratchpad[self.scratchpad_index] = ' '
				self.scratchpad_index = self.scratchpad_index - 1
		else:
			if self.clear_set:
				self.scratchpad.clear()
				self.scratchpad_index = 0
				self.clear_set = False

			self.scratchpad[sequence] = chr(key)
			self.scratchpad_index = sequence
    
		self.new_scratchpad_available = True

	def has_scratchpad(self) -> bool:
		return self.new_scratchpad_available

	def get_scratchpad(self) -> List[chr]:
		self.new_scratchpad_available = False
		return self.scratchpad

	def has_page_text(self) -> bool:
		return False

	def get_page_records(self) -> int:
		return len(self.current_page)

	def get_page_text(self) -> TextData:
		return self.current_page

class LRUData():
	def __init__(self, lru):
		self.state: TransmissionState = TransmissionState.IDLE
		self.next_state : TransmissionState = TransmissionState.IDLE
  		# Heartbeat for the 172 label, should be sent every sec
		self.heartbeat_elapsed_time: float = time.time()
		self.lru:LRU = lru
		#time to wait for an ack or nak until the message needs to be resent 
		self.message_response_elapsed_time = 0
		self.message_repeat_count: int = 0
		self.current_request_type: int = RequestType.MENU.value
		self.repeat: bool = False
		#count of the currently received NAK or SYN
		self.error_count: int = 0
		self.record_count = 1
		self.states : dict[TransmissionState, State] = {
			TransmissionState.IDLE : Idle(),
			TransmissionState.RTS : RTS(),
			TransmissionState.SEND_DATA : SendData(),
			TransmissionState.SCRATCHPAD : Scratchpad(),
		}
		self.mal_target: int = 0#145
   
	def queue_transition_to_state(self, new_state: TransmissionState):
		if new_state != self.state:
			log("Transition from : " + str(self.state) + " to State : " + str(new_state))
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
	def __init__(self, name: str, version: str, id : TransmissionState):
		self.version = version
		self.name = name
		self.id = id

	def on_activate(self, prev_state : TransmissionState):
		pass

	def update(self, logic, lru_data: LRUData, received_labels):
		pass

	def on_de_activate(self, next_state : TransmissionState):
		pass

class Idle(State):
	def __init__(self):
		State.__init__(self, "IDLE", "1.0.0", TransmissionState.IDLE)
  
	def on_activate(self, prev_state : TransmissionState):
		pass

	def update(self, logic, lru_data: LRUData, received_labels):
		for label, timestamp in received_labels:
			p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
			decoded_label = ArincLabel.Base._reverse_label_number(label_id)
     
			if decoded_label == lru_data.lru.sal:
				log("SAL Label received")
						
				#We are getting an enq from the MCDU
				if A739Utils.is_enq(label):
					log("ENQ Received")
					req_id = A739Utils.get_request_type(label)
					lru_data.mal_target = A739Utils.get_mal(label)
					log("Mal is " + str(oct(lru_data.mal_target)))
					log("Request type is " + str(req_id))
					lru_data.current_request_type = req_id
					lru_data.queue_transition_to_state(TransmissionState.RTS)
			
			if A739Utils.is_keyboard(label):
				log("Keyboard Received " + str(timestamp))
				key, sequence, repeat = A739Utils.get_key_data(label)
				lru_data.lru.on_key_press(key, sequence, repeat)
				# we need to send an ack immediately, range is only 200 ms
				ack = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.ACK << 16)
				logic.dev.send_manual_single_fast(lru_data.lru.channel, ack)
       
			#moving into idle means resetting all prev counters
			if not lru_data.repeat:
				lru_data.message_repeat_count = 0
				lru_data.error_count = 0
				lru_data.repeat = True
			if lru_data.lru.has_scratchpad():
				lru_data.queue_transition_to_state(TransmissionState.SCRATCHPAD)

	def on_de_activate(self, next_state : TransmissionState):
		pass

class RTS(State):
	def __init__(self):
		State.__init__(self, "RTS", "1.0.0", TransmissionState.RTS)

	def on_activate(self, prev_state : TransmissionState):
		pass

	def update(self, logic, lru_data: LRUData, received_labels):
		for label, timestamp in received_labels:

   			#We are getting a cts from the MCDU
			if A739Utils.is_cts(label):
				#extract max record count
				max_record_count = label >> 16 & 0x7F
				log("CTS Received with record count : " + str(max_record_count))
				lru_data.queue_transition_to_state(TransmissionState.SEND_DATA)
				#cts already received, no need for an RTS
				return

		# we received an enq, time to send an RTS
		if not lru_data.repeat:	
			if lru_data.current_request_type == RequestType.MENU.value:
				lru_data.record_count = 1
			else:
				lru_data.record_count = lru_data.lru.get_page_records()
					    
		rts = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.DC2 << 16 | lru_data.current_request_type << 8 | lru_data.record_count)
		logic.dev.send_manual_single_fast(lru_data.lru.channel, rts)
		print(oct(lru_data.mal_target), hex(rts))
		lru_data.repeat = True

	def on_de_activate(self, next_state : TransmissionState):
		pass

class SendData(State):
	def __init__(self):
		State.__init__(self, "SEND_DATA", "1.0.0", TransmissionState.SEND_DATA)
		self.wait_for_ack = False
		self.error_count = 0
  
	def handle_error(self) -> TransmissionState:
		self.error_count = self.error_count + 1
		if self.error_count < 3:
			return TransmissionState.IDLE
		else: #error count too high, we have to discard the message
			self.error_count = 0
			return TransmissionState.IDLE

	def on_activate(self, prev_state : TransmissionState):
		pass

	def update(self, logic, lru_data: LRUData, received_labels):
		
		if self.wait_for_ack:
			for label, timestamp in received_labels:
        	#We are getting a syn from the MCDU
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

			if time.time() - lru_data.message_response_elapsed_time > 1.5:
				#check if we should resend or simply just stop
				if lru_data.message_repeat_count <= 3:
					lru_data.message_repeat_count = lru_data.message_repeat_count + 1
					lru_data.message_response_elapsed_time = time.time()
					self.wait_for_ack = False
			else:
				lru_data.queue_transition_to_state(TransmissionState.IDLE)
		else:
			if lru_data.current_request_type == RequestType.MENU.value:
				A739Utils.send_record(logic.dev, lru_data.mal_target, lru_data.lru.channel, lru_data.lru.name, 1, True)
				#lru_data.queue_transition_to_state(TransmissionState.WAIT)	
			else:
				records = lru_data.lru.get_page_text()
				for index, record in enumerate(records):
					A739Utils.send_record(logic.dev, lru_data.mal_target, lru_data.lru.channel, record.text, index + 1, True if index == len(records) - 1 else False, record.color, record.lineIdx)
					#lru_data.queue_transition_to_state(TransmissionState.WAIT)	
			self.wait_for_ack = True
   
	def on_de_activate(self, next_state : TransmissionState):
		
		pass
class Scratchpad(State):
	def __init__(self):
		State.__init__(self, "SCRATCHPAD", "1.0.0", TransmissionState.SCRATCHPAD)
		self.wait_for_ack = False
		self.error_count = 0
		self.current_scratchpad: List[str] = None
		self.current_scratchpad_index = 0
  
	def handle_error(self) -> TransmissionState:
		self.error_count = self.error_count + 1
		if self.error_count < 3:
			return TransmissionState.IDLE
		else: #error count too high, we have to discard the message
			self.error_count = 0
			return TransmissionState.IDLE

	def on_activate(self, prev_state : TransmissionState):
		pass

	def update(self, logic, lru_data: LRUData, received_labels):
     
		if self.current_scratchpad == None:
			self.current_scratchpad = lru_data.lru.get_scratchpad()
			self.current_scratchpad_index = 0

		for label, timestamp in received_labels:
			if A739Utils.is_keyboard(label):
				log("Keyboard Received " + str(timestamp))
				key, sequence, repeat = A739Utils.get_key_data(label)
				lru_data.lru.on_key_press(key, sequence, repeat)
				# we need to send an ack immediately, range is only 200 ms
				ack = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.ACK << 16)
				logic.dev.send_manual_single_fast(lru_data.lru.channel, ack)
				self.error_count = 0
				self.current_scratchpad = lru_data.lru.get_scratchpad()
				self.current_scratchpad_index = 0
				self.wait_for_ack = False
    
			if self.wait_for_ack:
        		#We are getting a syn from the MCDU
				if A739Utils.is_syn(label):
					log("SYN Received")
					lru_data.queue_transition_to_state(self.handle_error())
					return

				if A739Utils.is_ack(label):
					log("ACK Received")
					self.current_scratchpad_index = self.current_scratchpad_index + 1
					if self.current_scratchpad_index >= len(self.current_scratchpad):
						lru_data.queue_transition_to_state(TransmissionState.IDLE)
					self.wait_for_ack = False
					return

				if A739Utils.is_nack(label):
					log("NACK Received")
					lru_data.queue_transition_to_state(self.handle_error())
					return
		
		if not self.wait_for_ack:
			if len(self.current_scratchpad) > 0:
				scratchpad_word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.DC1 << 16 | ord(self.current_scratchpad[self.current_scratchpad_index]) << 8 | 0x4 << 5 | self.current_scratchpad_index + 1)
				log("Schratchpad index: "  + str(self.current_scratchpad_index + 1) + " key: " + str(self.current_scratchpad[self.current_scratchpad_index]))
				logic.dev.send_manual_single_fast(lru_data.lru.channel, scratchpad_word)
				self.wait_for_ack = True
			else:
				scratchpad_word = ArincLabel.Base.pack_dec_no_sdi_no_ssm(lru_data.mal_target, A739Utils.DC1 << 16 | ord(" ") << 8 | 0x4 << 5 | 1)
				log("Sending empty schratchpad")
				logic.dev.send_manual_single_fast(lru_data.lru.channel, scratchpad_word)
				self.wait_for_ack = True
  
	def on_de_activate(self, next_state : TransmissionState):
		if next_state == TransmissionState.IDLE:
			self.current_scratchpad = None
			self.current_scratchpad_index = 0
		pass
class Logic:
	def __init__(self):
		self.version = "v1.0.0"
		self.mal_target = 0
		self.current_lru = None
		# list that stores the channels we are in, the LRU and the current state of the communications
		self.lrus= [LRUData(TEST_LRU())]	
		self.mcdu_rx_channel = ARINC_CARD_RX_CHNL
		self.data_recv = False
		self.data_aux = 0

	async def update(self):
		self.dev = self.devices[ARINC_CARD_NAME]
		if self.dev.is_ready:
			received_labels = []
			while True:
				try:
					label, timestamp = self.dev._rx_chnl[self.mcdu_rx_channel]._label_queue.popleft()
					received_labels.append((label, timestamp))
					
					p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
					decoded_label = ArincLabel.Base._reverse_label_number(label_id)
     
					print(oct(decoded_label), ssm, sdi, data)


					# p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
					# decoded_label = ArincLabel.Base._reverse_label_number(label_id)
		
					# if (decoded_label == 184) or (decoded_label == 255) or (decoded_label == 232):
					# 	pass
					# else:
					# 	print("Port 1", oct(decoded_label), ssm, hex(data), sdi)
     
					# label, timestamp = self.dev._rx_chnl[2]._label_queue.popleft()
					# p, ssm, data, sdi, label_id = ArincLabel.Base.unpack_dec(label)
					# decoded_label = ArincLabel.Base._reverse_label_number(label_id)
		
					# if (decoded_label == 184) or (decoded_label == 255) or (decoded_label == 232):
					# 	pass
					# else:
					# 	print("Port 2", oct(decoded_label), ssm, hex(data), sdi)
     
				except Exception as e:
						break

			if len(received_labels) > 0:
				self.data_recv = True
			for lru_data in self.lrus:
				channel = lru_data.lru.channel
				#send heartbeat
				if time.time() - lru_data.heartbeat_elapsed_time >= 0.9 and lru_data.state != TransmissionState.SEND_DATA:
				# if self.data_recv == True:
				# 	self.data_recv = False
     
					#print(self.data_aux)
					label = ArincLabel.Base._reverse_label_number(lru_data.lru.sal)
					# label |= self.data_aux<<8
     
					lru_identifier = ArincLabel.Base.pack_dec_no_sdi_no_ssm(122, label)
					self.dev.send_manual_single_fast(channel, lru_identifier)

					lru_data.heartbeat_elapsed_time = time.time()
					self.data_aux += 1

				lru_data.update(self, lru_data, received_labels)