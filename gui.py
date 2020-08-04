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
	#: int: max column width
	MAX_WIDTH = 200
	columns = []

	def get_width(self, object, trait, column):
		"""Specify column widths."""
		# cannot access public attributes for some reason
		return self._widths[column]


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

	@staticmethod
	def _df_to_cols(df):
		"""Convert a data frame to table columns with widths adjusted to
		fit the column width up to a given max amount.

		Args:
			df (:obj:`pd.DataFrame`): Data frame to enter into table.

		Returns:
			dict[int, int], List[str], :obj:`np.ndarray`: Dictionary of
			column indices to width, list of column strings, and data frame
			as a Numpy arry.

		"""
		cols = df.columns.values.tolist()
		widths = {
			i: min((
				max(df[c].astype(str).str.len()) * 15,
				TableArrayAdapter.MAX_WIDTH)) for i, c in enumerate(cols)
		}
		return widths, cols, df.to_numpy()

	@on_trait_change('_medlinePath')
	def importMedline(self):
		"""Import a Medline file and display in table."""
		df = self._importFile(
			self._medlinePath, medline_embase_scopus.DefaultExtractors.MEDLINE)
		self._medlineAdapter._widths, self._medlineAdapter.columns, \
			self._medline = self._df_to_cols(df)
		self.select_sheet_tab = SheetTabs.MEDLINE.value

	@on_trait_change('_embasePath')
	def importEmbase(self):
		"""Import an Embase file and display in table."""
		df = self._importFile(
			self._embasePath, medline_embase_scopus.DefaultExtractors.EMBASE)
		self._embaseAdapter._widths, self._embaseAdapter.columns, \
			self._embase = self._df_to_cols(df)
		self.select_sheet_tab = SheetTabs.EMBASE.value

	@on_trait_change('_scopusPath')
	def importScopus(self):
		"""Import a SCOPUS file and display in table."""
		df = self._importFile(
			self._scopusPath, medline_embase_scopus.DefaultExtractors.SCOPUS)
		self._scopusAdapter._widths, self._scopusAdapter.columns, \
			self._scopus = self._df_to_cols(df)
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
		self._overlapsAdapter._widths, self._overlapsAdapter.columns, \
			self._overlaps = self._df_to_cols(df)
		self.select_sheet_tab = SheetTabs.OVERLAPS.value


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
