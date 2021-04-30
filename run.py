#!/usr/bin/env python
# Simple startup script for Citation-Overlap

import pathlib
import sys

from citov import config, logs, medline_embase_scopus


def main():
	"""Start the graphical interface."""
	# set up logging including a log handler for uncaught exceptions
	logger = logs.setup_logger()
	logs.add_file_handler(
		logger, pathlib.Path(config.user_app_dirs.user_data_dir) / "out.log")
	sys.excepthook = logs.log_uncaught_exception
	
	# parse command-line args
	paths, outputFileName = medline_embase_scopus.parseArgs()
	if any(paths.values()):
		# run CLI if any database args given
		medline_embase_scopus.main(paths, outputFileName)
	else:
		# launch graphical interface
		from citov import gui
		gui.main()


if __name__ == "__main__":
	print("Starting Citation-Overlap run script...")
	main()
