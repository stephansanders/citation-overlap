#!/usr/bin/env python
# Simple startup script for Citation-Overlap

import pathlib
import sys

from citov import config, gui, logs


def main():
	"""Start the graphical interface."""
	# set up logging including a log handler for uncaught exceptions
	logger = logs.setup_logger()
	logs.add_file_handler(
		logger, pathlib.Path(config.user_app_dirs.user_data_dir) / "out.log")
	sys.excepthook = logs.log_uncaught_exception
	
	# lauch graphical interface
	gui.main()


if __name__ == "__main__":
	print("Starting Citation-Overlap run script...")
	main()
