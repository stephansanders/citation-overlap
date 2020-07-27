#!/usr/bin/env python

from enum import Enum, auto
import glob
import os

from PyQt5 import QtWidgets, QtCore
# adjust density for HiDPI screens
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
from traits.api import HasTraits, on_trait_change, Int, Str, Button, \
	Array, push_exception_handler, File, List, Instance
from traitsui.api import Handler, View, Item, HGroup, VGroup, Tabbed, \
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


class SheetTabs(Enum):
	MEDLINE = auto()
	EMBASE = auto()
	SCOPUS = auto()
	OVERLAPS = auto()


class CiteOverlapHandler(Handler):
	"""Custom handler for Citation Overlap GUI object events."""

	def object_select_sheet_tab_changed(self, info):
		"""Select the given tab specified by
		:attr:`CiteOverlapGUI.select_controls_tab`.

		Args:
			info (UIInfo): TraitsUI UI info.

		"""
		# find the tab widget QTabWidget and subtract one from Enum-based
		# index (1-based)
		tab_widgets = info.ui.control.findChildren(QtWidgets.QTabWidget)
		tab_widgets[0].setCurrentIndex(info.object.select_sheet_tab - 1)


class CiteOverlapGUI(HasTraits):
	"""GUI for Citation Overlap."""

	# select the given tag based on SheetTabs enum value
	select_sheet_tab = Int(-1)

	# Control panel controls
	_medlinePath = File()
	_embasePath = File()
	_scopusPath = File()
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
		VGroup(
			Item(
				'_medlinePath', label='Pubmed/Medline file', style='simple',
				editor=FileEditor(allow_dir=False)),
			Item(
				'_embasePath', label='Embase file', style='simple',
				editor=FileEditor(allow_dir=False)),
			Item(
				'_scopusPath', label='SCOPUS file', style='simple',
				editor=FileEditor(allow_dir=False)),
			Item(
				"_extractor", label="Extractor",
				editor=CheckListEditor(
					name="object._extractorNames.selections")),
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
		handler=CiteOverlapHandler(),
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

	@on_trait_change('_medlinePath')
	def importMedline(self):
		"""Import a Medline file and display in table."""
		df = self._importFile(
			self._medlinePath, medline_embase_scopus.DefaultExtractors.MEDLINE)
		self._medlineAdapter.columns = df.columns.values.tolist()
		self._medline = df.to_numpy()
		self.select_sheet_tab = SheetTabs.MEDLINE.value

	@on_trait_change('_embasePath')
	def importEmbase(self):
		"""Import an Embase file and display in table."""
		df = self._importFile(
			self._embasePath, medline_embase_scopus.DefaultExtractors.EMBASE)
		self._embaseAdapter.columns = df.columns.values.tolist()
		self._embase = df.to_numpy()
		self.select_sheet_tab = SheetTabs.EMBASE.value

	@on_trait_change('_scopusPath')
	def importScopus(self):
		"""Import a SCOPUS file and display in table."""
		df = self._importFile(
			self._scopusPath, medline_embase_scopus.DefaultExtractors.SCOPUS)
		self._scopusAdapter.columns = df.columns.values.tolist()
		self._scopus = df.to_numpy()
		self.select_sheet_tab = SheetTabs.SCOPUS.value

	def _importFile(self, path, extractor):
		"""Import a database file."""
		extractorPath = self._extractor
		if extractorPath is self._DEFAULT_EXTRACTOR:
			if extractor:
				extractorPath = os.path.join(
					medline_embase_scopus.PATH_EXTRACTORS,
					extractor.value)
			else:
				extractorPath = None
		df, dbName = self.dbExtractor.extractDb(path, extractorPath)
		return df

	@on_trait_change('_overlapBtn')
	def findOverlaps(self):
		"""Find overlaps."""
		df = self.dbExtractor.combineOverlaps()
		if df is None:
			return
		self._overlapsAdapter.columns = df.columns.values.tolist()
		self._overlaps = df.to_numpy()
		self.select_sheet_tab = SheetTabs.OVERLAPS.value


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
