#!  /usr/bin/env python3
#! -*- coding: utf-8 -*-

import sys
import time
import threading
from enum import Enum

def find_if (pred, collection):
	return next(filter(pred, collection), None)

class ProcessInfo:
	def __init__ (self, cls, thread_id, cycle_msec):
		self.cls = cls
		self.thread_id = thread_id
		self.cycle_msec = cycle_msec

class ProcessingInfo:
	def __init__ (self, prc, hdl, stp):
		self.prc = prc
		self.hdl = hdl
		self.stp = stp

class RequestInfo:
	def __init__ (self, cls, hdl):
		self.cls = cls
		self.hdl = hdl

def nop (hdl):
	return RC.FIN()

class RC:
	class _tag (Enum):
		ERROR = -1
		OK = 0
		FEED = 1
		FIN = 2

	def __init__ (self, tag, eid, next_step):
		self.tag = tag
		self.eid = eid
		self.next = next_step

	def ERORR (eid):
		return RC(RC._tag.ERROR, eid, nop)

	def OK (next_step):
		return RC(RC._tag.OK, 0, next_step)

	def FEED ():
		return RC(RC._tag.FEED, 0, nop)

	def FIN ():
		return RC(RC._tag.FIN, 0, nop)

def cyclic_caller (task, cyclic_sec):
	prev = time.time()
	while True:
		task()
		now = time.time()
		time.sleep(max(cyclic_sec - (now - prev), 0))
		prev = now

class TblSystemTh:
	SEC = 0.001
	def __init__ (self, tx_queue, rx_queue, interceptor):
		self.processing_stack = Queue()
		self.IF = tx_queue
		self.request = rx_queue
		self.interceptor = interceptor
		self.processes = {}

	def regist_process (self, tblsystem, cls):
		if cls in self.processes:
			raise RuntimeError("{0} has registered with a TblSystemTh".format(cls))
		self.processes[cls] = cls(self.IF)

	def establish (self, tblsystem):
		self.err_interceptor = tblsystem.interceptor(ErrorProcess)
		def _seterr (eid, msg):
			if self.err_interceptor.is_full():
				raise RuntimeError("TblSystemTh insert Error, but ErrorQueue is full")
			else:
			 	self.err_interceptor.enqueue(ErrorProcess.SetErrorHdl(eid, msg))
		self.SetError = _seterr

		for _, prc in self.processes.items():
			prc.establish(tblsystem)


	def cyclic_call (self):
		cyclic_caller(self.step, TblSystemTh.SEC)

	def step (self):
		# Request要求処理
		req = self.request.seek()
		if req:
			self.request.dequeue()
			prc = self.processes[req.cls]
			self.processing_stack.push(ProcessingInfo(prc, req.hdl, prc.tables[type(req.hdl)]))
		mgr = ProcessingInfo(None, None, None)
		while True:
			# Interrupt要求処理
			interrupt = self.interceptor.seek()
			if interrupt:
				self.interceptor.dequeue()
				# 実行中の処理を退避
				self.processing_stack.push(ProcessingInfo(mgr))
				# 割り込み処理を開始
				prc = self.processes[interrupt.cls]
				mgr = ProcessingInfo(prc, interrupt.hdl, prc.tables[type(interrupt.hdl)])
			if mgr.prc is None:
				stk = self.processing_stack.seek()
				if stk:
					# 退避していた処理を復帰
					self.processing_stack.pop()
					mgr = stk
					mgr.hdl.status = TblStatus.RUN
				else:
					# 残りの処理がなければ終了
					break

			# 1ステップ実行
			rc = mgr.stp(mgr.hdl)

			if RC._tag.ERROR == rc.tag:
				self.SetError(ErrorProcess.ID.RC_ERROR, "{0}がRC_ERROR({1})を返した".format(mgr.stp, rc.eid))
				mgr.hdl.status = TblStatus.ERROR
				mgr.prc = None
			elif RC._tag.OK == rc.tag:
				mgr.stp = rc.next
			elif RC._tag.FEED == rc.tag:
				self.IF.enqueue(RequestInfo(type(mgr.prc), mgr.hdl))
				mgr.prc = None
			elif RC._tag.FIN == rc.tag:
				mgr.hdl.status = TblStatus.FIN
				mgr.prc = None


class TblSystem:
	def __init__ (self, num_threads):
		if num_threads < 1:
			raise RuntimeError("Thread size is less than zero: {0}".format(num_threads))
		self.threads = []
		self.tthreads = []
		self.tx_queues = []
		self.rx_queues = []
		self.interceptors = []
		self.processes = []
		self.transport = {}

		for pidx in range(0, num_threads):
			self.tx_queues.append(Queue())
			self.rx_queues.append(Queue())
			self.interceptors.append(Queue())

		for pidx in range(0, num_threads):
			# スレッドを生成
			self.threads.append(TblSystemTh(self.tx_queues[pidx], self.rx_queues[pidx], self.interceptors[pidx]))

		# 標準機能
		self.regist_process(ErrorProcess, 0, 1)
		self.regist_process(ClockProcess, 0, 1)
		self.regist_process(FileIOProcess, 0, 100)
		self.regist_process(LogProcess, 0, 100)

	def regist_process (self, process_cls, thread_id, cycle_msec):
		if find_if(lambda e: e.cls is process_cls, self.processes):
			raise RuntimeError("Duplicate Resistoration. Process({0})".format(process_cls))
		if not issubclass(process_cls, BaseTblProcess):
			raise RuntimeError("Registered Process({0}) doesn't inherit {1}".format(process_cls, BaseTblProcess))
		if thread_id >= len(self.threads):
			raise RuntimeError("Registered ThreadId({0}) is more than thread size({1})".format(thread_id, len(self.threads)))

		self.processes.append(ProcessInfo(process_cls, thread_id, cycle_msec))
		self.transport[process_cls] = thread_id

	def establish (self):
		for pidx in range(0, len(self.threads)):
			assignments = [pinfo for pinfo in self.processes if pinfo.thread_id == pidx]
			# スレッドにProcessクラスを割当て
			for pmgr in assignments:
				self.threads[pidx].regist_process(self, pmgr.cls)

			self.threads[pidx].establish(self)

			# MainHdl要求をキューに追加
			for pmgr in assignments:
				if self.rx_queues[pidx].is_full():
					raise  RuntimeError("cannot insert MainHdl. RequestQueue is full.")
				else:
					self.rx_queues[pidx].enqueue(RequestInfo(pmgr.cls, pmgr.cls.MainHdl(pmgr.cycle_msec)))

			if 0 != pidx:
				# id0以外の処理は別スレッドで実行
				th = threading.Thread(target = self.threads[pidx].cyclic_call)
				th.start()
				self.tthreads.append(th)

	def interceptor (self, cls):
		pmgr = find_if(lambda pmgr: pmgr.cls == cls, self.processes)
		if not pmgr:
			raise RuntimeError("{0} is not registered.".format(cls))

		return self.interceptors[pmgr.thread_id]

	def step (self):
		# tx_queuesに入ってくるrequestをrx_queuesに振り分ける
		for txq in self.tx_queues:
			while True:
				req = txq.seek()
				if req:
					txq.dequeue()
					self.rx_queues[self.transport[req.cls]].enqueue(req)
				else:
					break
		# thread_id0の処理はここで行う
		self.threads[0].step()

	def cyclic_call (self):
		cyclic_caller(self.step, TblSystemTh.SEC)

class Queue:
	SIZE = 1024
	def __init__ (self):
		self.buffer = [None] * Queue.SIZE
		self.head = 0
		self.tail = 0

	def __str__ (self):
		if self.tail < self.head:
			return "<Queue {0}>".format(self.buffer[self.head:] + self.buffer[:self.tail])
		else:
			return "<Queue {0}>".format(self.buffer[self.head: self.tail])
			

	def is_full (self):
		return (self.head - self.tail) % Queue.SIZE == 1

	def is_empty (self):
		return self.head == self.tail

	def enqueue (self, data):
		self.buffer[self.tail] = data
		self.tail = (self.tail + 1) % Queue.SIZE

	def dequeue (self):
		self.buffer[self.head] = None
		self.head = (self.head + 1) % Queue.SIZE

	def push (self, data):
		self.head = (self.head - 1) if self.head > 0 else Queue.SIZE - 1
		self.buffer[self.head] = data

	def pop (self):
		self.dequeue()

	def seek (self):
		return self.buffer[self.head]

class MutexQueue (Queue):
	def __init__ (self):
		super().__init__()
		self.head_lock = threading.Lock()
		self.tail_lock = threading.Lock()

	def is_full (self):
		self.head_lock.acquire()
		self.tail_lock.acquire()
		ans = super().is_full()
		self.tail_lock.release()
		self.head_lock.release()
		return ans

	def is_empty (self):
		self.head_lock.acquire()
		self.tail_lock.acquire()
		ans = super().is_empty()
		self.tail_lock.release()
		self.head_lock.release()
		return ans

	def enqueue (self, data):
		self.tail_lock.acquire()
		super().enqueue(data)
		self.tail_lock.release()

	def dequeue (self):
		self.head_lock.acquire()
		super().dequeue()
		self.head_lock.release()

	def push (self, data):
		self.head_lock.acquire()
		super().push(data)
		self.head_lock.release()

	def seek (self):
		self.head_lock.acquire()
		res = super().seek()
		self.head_lock.release()
		return res

class TblStatus (Enum):
	ERROR = -1
	INIT = 0
	RUN = 1
	FIN = 2

class BaseHdl:
	def __init__ (self):
		self.status = TblStatus.INIT


class BaseTblProcess:
	def __init__ (self, tx_queue):
		# メッセージIF
		self.IF = tx_queue
		self.tables = {}

	def establish (self, tblsystem):
		# SetErrorは割り込みで実行する
		self.err_interceptor = tblsystem.interceptor(ErrorProcess)
		def _seterr (eid, msg):
			if self.err_interceptor.is_full():
				raise RuntimeError("{0} insert Error, but ErrorQueue is full".format(type(self)))
			else:
				self.err_interceptor.enqueue(\
						RequestInfo(ErrorProcess\
							, ErrorProcess.SetErrorHdl(eid, msg)))
		self.SetError = _seterr

		# よく使う関数を登録
		self.Request = lambda cls, hdl: self.IF.enqueue(RequestInfo(cls, hdl))
		self.WriteLog = lambda msg:\
						self.Request(LogProcess, LogProcess.WriteLogHdl(msg))


	def regist_table (self, tbltop, hdl_cls):
		if not hasattr(self, tbltop.__name__):
			raise RuntimeError("{0} is not defined Tbl in {1}".format(tbltop.__name__, type(self)))
		self.tables[hdl_cls] = tbltop

class ErrorProcess (BaseTblProcess):
	class LEVEL (Enum):
		NONE = 0
		CYCLE = 1
		FATAL = 2

	class ID (Enum):
		NONE = 0
		RC_ERROR = 1
		UNDEFINED_ERR = 2

	def __init__ (self, tx_queue):
		super().__init__(tx_queue)

		self.m_errors = []
		self.m_interceptors = []

		self.regist_table(self.main_countup,	ErrorProcess.MainHdl)
		self.regist_table(self.error_event,		ErrorProcess.ErrorEventHdl)
		self.regist_table(self.reset,			ErrorProcess.ResetHdl)
		self.regist_table(self.seterror_set,	ErrorProcess.SetErrorHdl)
		self.regist_table(self.reseterror_reset, ErrorProcess.ResetErrorHdl)

	def establish (self, tblsystem):
		super().establish(tblsystem)
		# 自身以外全てのクラスに対する割り込みキュー
		self.m_interceptors = [(pinfo.cls, tblsystem.interceptor(pinfo.cls)) for pinfo in tblsystem.processes if pinfo.cls != ErrorProcess]

	class MainHdl (BaseHdl):
		def __init__ (self, cycle_msec):
			super().__init__()
			self.i_cycle_msec = cycle_msec
			self.sleep_hdl = None
			self.counter = 0

	def main_countup (self, hdl):
		hdl.counter += 1
		hdl.sleep_hdl = ClockProcess.SleepSecHdl(hdl.i_cycle_msec / 1000.0)
		self.Request(ClockProcess, hdl.sleep_hdl)
		return RC.OK(self.main_waitinterval)
	def main_waitinterval (self, hdl):
		if TblStatus.FIN != hdl.sleep_hdl.status:
			return RC.FEED()
		return RC.OK(self.main_recur)
	def main_recur (self, hdl):
		self.Request(ErrorProcess, hdl)
		return RC.FIN()

	
	class ErrorEventHdl (BaseHdl):
		def __init__ (self, level):
			super().__init__()
			self.i_level = level
			
	def error_event (self, hdl):
		return RC.FIN()


	class ResetHdl (BaseHdl):
		def __init__ (self):
			super().__init__()

	def reset (self, hdl):
		return RC.FIN()


	class SetErrorHdl (BaseHdl):
		def __init__ (self, level, eid, msg):
			super().__init__()
			self.i_level = 0
			self.i_eid = eid
			self.i_msg = msg
			self.hdls = []

	def seterror_set (self, hdl):
		self.m_errors.append(hdl)
		if hdl.i_level > self.m_level:
			# 異常レベルが上がった場合、各クラスの異常イベントを起動する
			self.m_level = hdl.i_level
			for cls, interceptor in self.m_interceptors:
				hdl.hdls.append(cls.ErrorEventHdl(self.m_level))
				interceptor.enqueue(cls, hdl.hdls[-1])
		return RC.OK(self.seterror_waitset)
	def seterror_waitset (self, hdl):
		if all(map(lambda hdl: TblStatus.FIN == hdl.status, hdl.hdls)):
			# 全クラスの異常イベントが完了したら終了
			return RC.FIN()
		return RC.FEED()


	class ResetErrorHdl (BaseHdl):
		def __init__ (self):
			super().__init__()

	def reseterror_reset (self, hdl):
		self.m_errors = []
		for cls, interceptor in self.m_interceptors:
			hdl.hdls.append(cls.ResetHdl())
			self.Request(cls, hdl.hdls[-1])
		return RC.OK(self.reseterror_waitreset)
	def reseterror_waitreset (self, hdl):
		if all(map(lambda hdl: TblStatus.FIN == hdl.status, hdl.hdls)):
			# 全クラスのリセットが完了したら終了
			return RC.FIN()
		return RC.FEED()


class ClockProcess (BaseTblProcess):
	def __init__ (self, tx_queue):
		super().__init__(tx_queue)

		self.regist_table(self.main_countup,		ClockProcess.MainHdl)
		self.regist_table(self.error_event,			ClockProcess.ErrorEventHdl)
		self.regist_table(self.reset,				ClockProcess.ResetHdl)
		self.regist_table(self.getclock_getclock,	ClockProcess.GetClockHdl)
		self.regist_table(self.gettime_gettime,		ClockProcess.GetTimeHdl)
		self.regist_table(self.sleepsec_gettime, ClockProcess.SleepSecHdl)

	class MainHdl (BaseHdl):
		def __init__ (self, cycle_msec):
			super().__init__()
			self.i_cycle_msec = cycle_msec
			self.sleep_hdl = None
			self.counter = 0

	def main_countup (self, hdl):
		hdl.counter += 1
		hdl.sleep_hdl = ClockProcess.SleepSecHdl(hdl.i_cycle_msec / 1000.0)
		self.Request(ClockProcess, hdl.sleep_hdl)
		return RC.OK(self.main_waitinterval)
	def main_waitinterval (self, hdl):
		if TblStatus.FIN != hdl.sleep_hdl.status:
			return RC.FEED()
		return RC.OK(self.main_recur)
	def main_recur (self, hdl):
		self.Request(ErrorProcess, hdl)
		return RC.FIN()

	
	class ErrorEventHdl (BaseHdl):
		def __init__ (self, level):
			super().__init__()
			self.i_level = level
			
	def error_event (self, hdl):
		return RC.FIN()


	class ResetHdl (BaseHdl):
		def __init__ (self):
			super().__init__()

	def reset (self, hdl):
		return RC.FIN()


	class GetClockHdl (BaseHdl):
		def __init__ (self):
			super().__init__()
			self.o_clock = 0.0

	def getclock_getclock (self, hdl):
		hdl.o_clock = time.clock()
		return RC.FIN()


	class GetTimeHdl (BaseHdl):
		def __init__ (self):
			super().__init__()
			self.o_time = 0.0

	def gettime_gettime (self, hdl):
		hdl.o_time = time.time()
		return RC.FIN()


	class SleepSecHdl (BaseHdl):
		def __init__ (self, secs):
			super().__init__()
			self.i_secs = secs
			self.begin = None

	def sleepsec_gettime (self, hdl):
		hdl.begin = time.time()
		return RC.OK(self.sleepsec_checkpast)
	def sleepsec_checkpast (self, hdl):
		now = time.time()
		if now - hdl.begin < hdl.i_secs:
			return RC.FEED()

		return RC.FIN()

class FileIOProcess (BaseTblProcess):
	def __init__ (self, tx_queue):
		super().__init__(tx_queue)

		self.m_files = {}

		self.regist_table(self.main_countup,	FileIOProcess.MainHdl)
		self.regist_table(self.error_event,		FileIOProcess.ErrorEventHdl)
		self.regist_table(self.reset,			FileIOProcess.ResetHdl)
		self.regist_table(self.open_isopen,		FileIOProcess.OpenHdl)
		self.regist_table(self.close_isclose,	FileIOProcess.CloseHdl)

	class MainHdl (BaseHdl):
		def __init__ (self, cycle_msec):
			super().__init__()
			self.i_cycle_msec = cycle_msec
			self.sleep_hdl = None
			self.counter = 0

	def main_countup (self, hdl):
		hdl.counter += 1
		hdl.sleep_hdl = ClockProcess.SleepSecHdl(hdl.i_cycle_msec / 1000.0)
		self.Request(ClockProcess, hdl.sleep_hdl)
		return RC.OK(self.main_waitinterval)
	def main_waitinterval (self, hdl):
		if TblStatus.FIN != hdl.sleep_hdl.status:
			return RC.FEED()
		return RC.OK(self.main_recur)
	def main_recur (self, hdl):
		self.Request(ErrorProcess, hdl)
		return RC.FIN()


	class ErrorEventHdl (BaseHdl):
		def __init__ (self, level):
			super().__init__()
			self.i_level = level
			
	def error_event (self, hdl):
		return RC.FIN()


	class ResetHdl (BaseHdl):
		def __init__ (self):
			super().__init__()

	def reset (self, hdl):
		return RC.FIN()

	class OpenHdl (BaseHdl):
		def __init__ (self, filepath):
			self.i_filepath = filepath
			self.o_fp = None
			self.o_success = False

	def open_isopen (self, hdl):
		if hdl.i_filepath in self.m_files:
			hdl.o_fp = self.m_files[hdl.i_filepath]
			hdl.o_success = True
			return RC.FIN()
		return RC.OK(self.open_open)
	def open_open (self, hdl):
		try:
			fp = open(hdl.i_filepath)
			hdl.o_fp = fp
			self.m_files[hdl.i_filepath] = fp
			hdl.o_success = True
		except FileNotFoundError as e:
			hdl.o_fp = None
			hdl.o_success = False
		return RC.FIN()

	
	class CloseHdl (BaseHdl):
		def __init__ (self, filepath):
			self.i_filepath = filepath
			self.o_success = False
			
	def close_isclose (self, hdl):
		if hdl.i_filepath in self.m_files:
			return RC.OK(self.close_close)
		hdl.o_success = True
		return RC.FIN()
	def close_close (self, hdl):
		fp = self.m_files.pop(hdl.i_filepath)
		close(fp)
		hdl.o_success = True
		return RC.FIN()


class LogProcess (BaseTblProcess):
	class LEVEL (Enum):
		DEBUG = -1
		MESSAGE = 0
		WARNING = 1
		ERROR = 2

	def __init__ (self, tx_queue):
		super().__init__(tx_queue)

		self.m_loglevel = LogProcess.LEVEL.MESSAGE
		self.m_filepath = "log/{0}.log".format(time.time())

		self.regist_table(self.main_countup,		LogProcess.MainHdl)
		self.regist_table(self.error_event,			LogProcess.ErrorEventHdl)
		self.regist_table(self.reset,				LogProcess.ResetHdl)
		self.regist_table(self.writelog_checklevel, LogProcess.WriteLogHdl)
		self.regist_table(self.loglevel_loglevel,	LogProcess.LogLevelHdl)

	class MainHdl (BaseHdl):
		def __init__ (self, cycle_msec):
			super().__init__()
			self.i_cycle_msec = cycle_msec
			self.sleep_hdl = None
			self.counter = 0

	def main_countup (self, hdl):
		hdl.counter += 1
		hdl.sleep_hdl = ClockProcess.SleepSecHdl(hdl.i_cycle_msec / 1000.0)
		self.Request(ClockProcess, hdl.sleep_hdl)
		return RC.OK(self.main_waitinterval)
	def main_waitinterval (self, hdl):
		if TblStatus.FIN != hdl.sleep_hdl.status:
			return RC.FEED()
		return RC.OK(self.main_recur)
	def main_recur (self, hdl):
		self.Request(ErrorProcess, hdl)
		return RC.FIN()


	class ErrorEventHdl (BaseHdl):
		def __init__ (self, level):
			super().__init__()
			self.i_level = level
			
	def error_event (self, hdl):
		return RC.FIN()


	class ResetHdl (BaseHdl):
		def __init__ (self):
			super().__init__()

	def reset (self, hdl):
		return RC.FIN()


	class WriteLogHdl (BaseHdl):
		def __init__ (self, level, msg):
			self.i_level = level
			self.i_msg = msg
			self.fileopen_hdl = None
			self.fileclose_hdl = None

	def writelog_checklevel (self, hdl):
		if hdl.i_level < self.m_level:
			return RC.FIN()
		return RC.OK(self.writelog_openfile)
	def writelog_openfile (self, hdl):
		hdl.fileopen_hdl = FileIOProcess.OpenHdl(self.m_filepath)
		self.Request(FileIOProcess, hdl.fileopen_hdl)
		return RC.OK(self.writelog_waitopenfile)
	def writelog_waitopenfile (self, hdl):
		if TblStatus.FIN == hdl.fileopen_hdl.status:
			return RC.OK(self.writelog_write)
		return RC.FEED()
	def writelog_write (self, hdl):
		hdl.fileopen_hdl.o_fp.write(hdl.i_msg)
		return RC.OK(self.writelog_closefile)
	def writelog_closefile (self, hdl):
		hdl.fileclose_hdl = FileIOProcess.CloseHdl(self.m_filepath)
		self.Request(FileIOProcess, hdl.fileclose_hdl)
		return RC.OK(self.writelog_waitclosefile)
	def writelog_waitclosefile (self, hdl):
		if TblStatus.FIN == hdl.fileclose_hdl.status:
			return RC.FIN()
		return RC.FEED()

	class LogLevelHdl (BaseHdl):
		def __init__ (self, level):
			self.i_level = level

	def loglevel_loglevel (self, hdl):
		self.m_loglevel = hdl.i_level
		return RC.FIN()
