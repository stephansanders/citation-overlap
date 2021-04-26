# Logger for Citation-Overlap
"""Citation-Overlap logging."""

import pathlib

import logging
from logging import handlers


def setup_logger(level=logging.INFO):
	"""Set up a basic root logger with a stream handler.

	Returns:
		:class:`logging.Logger`: Root logger for the application.

	"""
	logger = logging.getLogger()
	logger.setLevel(level)

	# set up handler for console
	handler_stream = logging.StreamHandler()
	handler_stream.setLevel(logging.INFO)
	handler_stream.setFormatter(logging.Formatter(
		'%(name)s - %(levelname)s - %(message)s'))
	logger.addHandler(handler_stream)

	return logger


def add_file_handler(logger, path, backups=5):
	"""Add a rotating log file handler with a new log file.

	Args:
		logger (:class:`logging.Logger`): Logger to update.
		path (Union[str, :class:`pathlib.Path`]): Path to log.
		backups (int): Number of backups to maintain; defaults to 5.

	Returns:
		:class:`logging.Logger`: The logger for chained calls.

	"""
	# check if log file already exists
	pathl = pathlib.Path(path)
	roll = pathl.is_file()

	# create a rotations file handler to manage number of backups while
	# manually managing rollover based on file presence rather than size
	pathl.parent.mkdir(parents=True, exist_ok=True)
	handler_file = handlers.RotatingFileHandler(path, backupCount=backups)
	handler_file.setLevel(logger.level)
	handler_file.setFormatter(logging.Formatter(
		'%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
	logger.addHandler(handler_file)

	if roll:
		# create a new log file if exists, backing up the old one
		handler_file.doRollover()
	return logger


def log_uncaught_exception(exc_type, exc, trace):
	"""Handle uncaught exceptions globally with logging.

	Args:
		exc_type: Exception class. 
		exc: Exception instance.
		trace: Traceback object.

	Returns:

	"""
	logger = logging.getLogger()
	# log the exception
	logger.critical(
		'Unhandled exception', exc_info=(exc_type, exc, trace))
