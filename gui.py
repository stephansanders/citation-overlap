#!/usr/bin/env python

import glob
import os

from PyQt5 import QtWidgets, QtCore
# adjust density for HiDPI screens
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
from traits.api import HasTraits, on_trait_change, Str, Button, \
	Array, push_exception_handler, File, List, Instance
from traitsui.api import View, Item, HGroup, VGroup, Tabbed, \
	HSplit, TabularEditor, FileEditor, CheckListEditor
from traitsui.tabular_adapter import TabularAdapter

import medline_embase_scopus


def main():
	# show complete stacktraces for debugging
	push_exception_handler(reraise_exceptions=True)
	gui = CiteOverlapGUI()
	gui.configure_traits()


class TraitsList(HasTraits):
	"""Generic Traits-enabled list."""
	selections = List([""])


class TableArrayAdapter(TabularAdapter):
	"""Table adapter for generic table output."""
	columns = []


class CiteOverlapGUI(HasTraits):
	"""GUI for Citation Overlap."""

	# Control panel controls
	_csvPath = File()
	_extractor = Str
	_extractorNames = Instance(TraitsList)
	_DEFAULT_EXTRACTOR = 'Auto'
	_importBtn = Button('Import file')
	_overlapBtn = Button('Find Overlaps')

	# Medline table
	_medlineAdapter = TableArrayAdapter()
	_medlineTable = TabularEditor(
		adapter=_medlineAdapter, editable=True, auto_resize_rows=True,
		stretch_last_section=False)
	_medline = Array

	# Embase table
	_embaseAdapter = TableArrayAdapter()
	_embaseTable = TabularEditor(
		adapter=_embaseAdapter, editable=True, auto_resize_rows=True,
		stretch_last_section=False)
	_embase = Array

	# SCOPUS table
	_scopusAdapter = TableArrayAdapter()
	_scopusTable = TabularEditor(
		adapter=_scopusAdapter, editable=True, auto_resize_rows=True,
		stretch_last_section=False)
	_scopus = Array

	# Overlaps output table
	_overlapsAdapter = TableArrayAdapter()
	_outputTable = TabularEditor(
		adapter=_overlapsAdapter, editable=True, auto_resize_rows=True,
		stretch_last_section=False)
	_overlaps = Array

	# controls panel
	_controlsPanel = VGroup(
		HGroup(
			Item(
				'_csvPath', label='File', style='simple',
				editor=FileEditor(allow_dir=False)),
		),
		HGroup(
			Item(
				"_extractor", label="Extractor",
				editor=CheckListEditor(
					name="object._extractorNames.selections")),
			Item('_importBtn', show_label=False),
		),
		Item('_overlapBtn', show_label=False),
	)

	# tabbed viewer of tables
	_tableView = Tabbed(
		Item('_medline', editor=_medlineTable, show_label=False, width=1200),
		Item('_embase', editor=_embaseTable, show_label=False),
		Item('_scopus', editor=_scopusTable, show_label=False),
		Item('_overlaps', editor=_outputTable, show_label=False),
	)

	# main view
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
		"""Initialize the GUI."""
		super().__init__()
		self._extractorNames = TraitsList()
		extractorNames = [self._DEFAULT_EXTRACTOR]
		extractorNames.extend(glob.glob(
			os.path.join(medline_embase_scopus.PATH_EXTRACTORS, "*")))
		self._extractorNames.selections = extractorNames

		self.dbExtractor = medline_embase_scopus.DbExtractor()

	@on_trait_change('_importBtn')
	def importFile(self):
		"""Import a database file."""
		extractorPath = self._extractor
		if extractorPath is self._DEFAULT_EXTRACTOR:
			extractorPath = None
		df, dbName = self.dbExtractor.extractDb(self._csvPath, extractorPath)
		if dbName == medline_embase_scopus.DbNames.MEDLINE.value:
			self._medlineAdapter.columns = df.columns.values.tolist()
			self._medline = df.to_numpy()
		elif dbName == medline_embase_scopus.DbNames.EMBASE.value:
			self._embaseAdapter.columns = df.columns.values.tolist()
			self._embase = df.to_numpy()
		elif dbName == medline_embase_scopus.DbNames.SCOPUS.value:
			self._scopusAdapter.columns = df.columns.values.tolist()
			self._scopus = df.to_numpy()

	@on_trait_change('_overlapBtn')
	def findOverlaps(self):
		"""Find overlaps."""
		df = self.dbExtractor.combineOverlaps()
		self._overlapsAdapter.columns = df.columns.values.tolist()
		self._overlaps = df.to_numpy()


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
