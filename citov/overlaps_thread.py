# PyQt5 thread for running overlaps detection

from typing import TYPE_CHECKING, Callable

from PyQt5 import QtCore

if TYPE_CHECKING:
	from citov import extractor


class OverlapsThread(QtCore.QThread):
	"""Thread for setting up file import by extracting image metadata.

	Attributes:
		dbExtractor: Database extractor.
		fn_success: Function after finding overlaps.
		fn_prog: Function to update progress of finding overlaps.

	"""

	signal = QtCore.pyqtSignal(object)
	signal_prog = QtCore.pyqtSignal(object, object)

	def __init__(
			self, dbExtractor: "extractor.DbExtractor", fn_success,
			fn_prog: Callable[[int, str], None]):
		"""Initialize the overlap detection thread."""
		super().__init__()
		self.dbExtractor = dbExtractor
		self.signal.connect(fn_success)
		self.signal_prog.connect(fn_prog)

	def run(self):
		"""Find overlaps."""
		try:
			# find overlaps with progress tracking
			result = self.dbExtractor.combineOverlaps(
				lambda x, y: self.signal_prog.emit(x, y))
			
		except TypeError as e:
			# TODO: catch additional errors that may occur with overlaps
			result = \
				'An erorr occurred while finding overlaps across databases.' \
				' Please try again, or check the logs for more details.'
			print(result)
			print(e)
		self.signal.emit(result)

