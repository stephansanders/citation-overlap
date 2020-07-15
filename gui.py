#!/usr/bin/env python

from PyQt5 import QtWidgets, QtCore
# adjust density for HiDPI screens
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
from traits.api import HasTraits, on_trait_change, Button, \
	Array, push_exception_handler, File
from traitsui.api import View, Item, HGroup, VGroup, \
	HSplit, TabularEditor, FileEditor
from traitsui.tabular_adapter import TabularAdapter

import medline_embase_scopus


def main():
	# show complete stacktraces for debugging
	push_exception_handler(reraise_exceptions=True)
	gui = CiteOverlapGUI()
	gui.configure_traits()


class OverlapsArrayAdapter(TabularAdapter):
	"""Table adapter for main output."""
	columns = []


class CiteOverlapGUI(HasTraits):

	_csvPath = File()
	_overlapBtn = Button('Find Overlaps')

	_overlapsAdapter = OverlapsArrayAdapter()
	_outputTable = TabularEditor(
		adapter=_overlapsAdapter, editable=True, auto_resize_rows=True,
		stretch_last_section=False)
	_overlaps = Array

	_controlsPanel = VGroup(
		HGroup(
			Item(
				'_csvPath', label='File', style='simple',
				editor=FileEditor(allow_dir=False)),
		),
		Item('_overlapBtn', show_label=False),
	)

	_tableView = VGroup(
		Item('_overlaps', editor=_outputTable, show_label=False, width=1200),
	)

	view = View(
		HSplit(
			_controlsPanel,
			_tableView,
		),
		width=1500,
		height=800,
		title='Citation Overlap',
		resizable=True,
	)

	def __init__(self):
		super().__init__()
		self._csvPaths = []

	@on_trait_change('_csvPath')
	def _addCsvPath(self):
		print(f'Adding CSV path: {self._csvPath}')
		self._csvPaths.append(self._csvPath)

	@on_trait_change('_overlapBtn')
	def findOverlaps(self):
		df = medline_embase_scopus.main(self._csvPaths)
		self._overlapsAdapter.columns = df.columns.values.tolist()
		self._overlaps = df.to_numpy()


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
