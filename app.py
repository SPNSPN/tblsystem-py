#! /usr/bin/env python3

import re
from TblSystem import *

class CmdlineProcess (BaseTblProcess):
	def __init__ (self, tx_queue):
		super().__init__(tx_queue)

		self.m_param = 1
		self.m_commands = {}

		self.regist_table(self.main_countup,	CmdlineProcess.MainHdl)
		self.regist_table(self.error_event,		CmdlineProcess.ErrorEventHdl)
		self.regist_table(self.reset,			CmdlineProcess.ResetHdl)
		self.regist_table(self.keyin_prompt,	CmdlineProcess.KeyinHdl)

	class MainHdl (BaseHdl):
		def __init__ (self, cycle_msec):
			super().__init__()
			self.i_cycle_msec = cycle_msec
			self.sleep_hdl = None
			self.keyin_hdl = None
			self.counter = 0

	def main_countup (self, hdl):
		hdl.counter += 1
		hdl.sleep_hdl = ClockProcess.SleepSecHdl(hdl.i_cycle_msec / 1000.0)
		self.Request(ClockProcess, hdl.sleep_hdl)
		return RC.OK(self.main_checkkeyin)
	def main_checkkeyin (self, hdl):
		if hdl.keyin_hdl is None:
			hdl.keyin_hdl = CmdlineProcess.KeyinHdl()
			self.Request(CmdlineProcess, hdl.keyin_hdl)
		if TblStatus.FIN == hdl.keyin_hdl.status:
			return RC.OK(self.main_parsecmd)
		return RC.OK(self.main_waitinterval)
	def main_parsecmd (self, hdl):
		keyin = hdl.keyin_hdl.o_str
		found = False
		for pat, cmd in self.m_commands.items():
			if pat.match(keyin):
				found = True
				cmd(keyin)
				break
		if not found:
			print("Unknown Command: {0}".format(keyin))
		self.keyin_hdl = None
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

	
	class KeyinHdl (BaseHdl):
		def __init__ (self):
			super().__init__()
			self.o_str = ""

	def keyin_prompt (self, hdl):
		print(">>> ", end = "")
		return RC.OK(self.keyin_readkeyin)

	def keyin_readkeyin (self, hdl):
		self.o_str = input()
		return RC.FIN()



def main ():
	tblsystem = TblSystem(4)

	tblsystem.regist_process(CmdlineProcess, 1, 500)

	tblsystem.establish()

	tblsystem.cyclic_call()

if __name__ == "__main__":
	main()
