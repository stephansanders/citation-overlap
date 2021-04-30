#!/usr/bin/env python

import math
from collections import OrderedDict
from enum import Enum, auto
import glob
import os

from PyQt5 import QtWidgets, QtCore
# adjust density for HiDPI screens
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
from pyface.api import FileDialog, OK
from traits.api import HasTraits, on_trait_change, Int, Str, Button, \
	Array, push_exception_handler, File, List, Instance, Property
from traitsui.api import Handler, View, Item, HGroup, VGroup, Tabbed, \
	HSplit, TabularEditor, FileEditor, CheckListEditor
from traitsui.tabular_adapter import TabularAdapter

from citov import medline_embase_scopus


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
	#: tuple: Sub-group background colors.
	COLORS = (None, "gray", "darkBlue", "darkRed")
	#: list[tuple[str, Any]]: Columns as ``(name, ID)``.
	columns = []
	
	# group and sub-group column properties, which are required along with
	# corresponding functions when column IDs are given as strings rather than
	# indices, to access individual cells since the group/sub-group cannot
	# be accessed as attributes of the underlying data
	group_text = Property
	group_bg_color = Property
	subgrp_text = Property
	subgrp_bg_color = Property
	
	def _get_col(self, name):
		"""Get column index with the given column name.
		
		Args:
			name (str): Column name.
		
		Returns:
			int: Index of found column in :attr:`columns`.
		
		Raises:
			ValueError: if ``name`` was not found.
		
		"""
		for i, col in enumerate(self.columns):
			if col[0] == name:
				return i
		raise ValueError(f'Could not find column named: {name}')
	
	def _get_group_bg_color(self):
		"""Get background color to use for the current Group column row."""
		color = None
		try:
			group = self.item[self._get_col('Group')]
			if group == 'none':
				color = 'darkCyan'
			else:
				if int(group) % 2 == 0:
					# color all rows within each group that has an even group
					# number; assumes that all group numbers are represented
					# and sorted
					color = 'darkGreen'
		except ValueError:
			pass
		return color

	def _get_subgrp_bg_color(self):
		"""Get background color to use for the current Sub-group column row."""
		try:
			# cycle colors based on sub-group number
			group = self.item[self._get_col('Subgrp')]
			return self.COLORS[int(group) % len(self.COLORS)]
		except ValueError:
			pass
		return None

	def get_width(self, object, trait, column):
		"""Specify column widths."""
		# dict of col_id to width; cannot access public attributes for some
		# reason so set widths as private attribute
		return self._widths[column]
	def _get_group_text(self):
		"""Get Group column value."""
		return self.item[self._get_col('Group')]

	def _get_subgrp_text(self):
		"""Get Sub-group column value."""
		return self.item[self._get_col('Subgrp')]


class SheetTabs(Enum):
	MEDLINE = auto()
	EMBASE = auto()
	SCOPUS = auto()
	OVERLAPS = auto()


class CiteOverlapHandler(Handler):
	"""Custom handler for Citation Overlap GUI object events."""

	def init(self, info):
		"""Perform GUI initialization tasks."""
		# left-align table headers
		table_widgets = info.ui.control.findChildren(QtWidgets.QTableView)
		for table in table_widgets:
			table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft)

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
	#: OrderedDict[str, str]: Dictionary of separator descriptions to
	# separator characters.
	_EXPORT_SEPS = OrderedDict((
		('Tabs (.tsv)', '\t'),
		('Comma (.csv)', ','),
		('Bar (.csv)', '|'),
		('Semi-colon (.csv)', ';'),
	))

	# select the given tag based on SheetTabs enum value
	select_sheet_tab = Int(-1)

	# Control panel controls

	# input paths
	_medlinePath = File()
	_embasePath = File()
	_scopusPath = File()

	# extractor drop-down
	_extractor = Str
	_extractorNames = Instance(TraitsList)
	_DEFAULT_EXTRACTOR = 'Auto'

	# button to find overlaps
	_overlapBtn = Button('Find Overlaps')

	# table export
	_exportBtn = Button('Export Tables')
	_exportSep = Str
	_exportSepNames = Instance(TraitsList)
	_statusBarMsg = Str

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
				"_extractor", label="Extractor",
				editor=CheckListEditor(
					name="object._extractorNames.selections",
					format_func=lambda x: x)),
			Item(
				'_medlinePath', label='PubMed/MEDLINE file', style='simple',
				editor=FileEditor(allow_dir=False)),
			Item(
				'_embasePath', label='Embase file', style='simple',
				editor=FileEditor(allow_dir=False)),
			Item(
				'_scopusPath', label='Scopus file', style='simple',
				editor=FileEditor(allow_dir=False)),
		),
		Item('_overlapBtn', show_label=False),
		HGroup(
			Item('_exportBtn', show_label=False),
			Item(
				"_exportSep", label="Separator",
				editor=CheckListEditor(
					name="object._exportSepNames.selections")),
		),
	)

	# tabbed viewer of tables
	_tableView = Tabbed(
		Item('_medline', editor=_medlineTable, show_label=False, width=1000),
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
		width=1300,  # also influenced by _tableView width
		height=800,
		title='Citation Overlap',
		resizable=True,
		handler=CiteOverlapHandler(),
		statusbar="_statusBarMsg"
	)

	def __init__(self):
		"""Initialize the GUI."""
		super().__init__()

		# populate drop-down of available extractors from directory of
		# extractors, displaying only basename but keeping dict with full path
		self._extractorNames = TraitsList()
		extractorNames = [self._DEFAULT_EXTRACTOR]
		extractor_paths = glob.glob(
			str(medline_embase_scopus.PATH_EXTRACTORS / "*"))
		self._extractor_paths = {
			os.path.basename(f): f for f in extractor_paths}
		extractorNames.extend(self._extractor_paths.keys())
		self._extractorNames.selections = extractorNames
		self._extractor = self._extractorNames.selections[0]

		# populate drop-down of separators/delimiters
		self._exportSepNames = TraitsList()
		self._exportSepNames.selections = list(self._EXPORT_SEPS.keys())
		self._exportSep = self._exportSepNames.selections[0]

		# extractor instance
		self.dbExtractor = medline_embase_scopus.DbExtractor()
		
		# last opened directory
		self._save_dir = None

	@staticmethod
	def _df_to_cols(df):
		"""Convert a data frame to table columns with widths adjusted to
		fit the column width up to a given max amount.

		Args:
			df (:obj:`pd.DataFrame`): Data frame to enter into table.

		Returns:
			dict[int, int], list[(str, Any)], :obj:`np.ndarray`: Dictionary of
			column indices to width, list of column tuples given as
			``(col_name, col_ID)``, and data frame as a Numpy arry.

		"""
		colWidths = []
		colsIDs = []
		for i, col in enumerate(df.columns.values.tolist()):
			# get widths of all rows in column as well as header
			colWidth = df[col].astype(str).str.len().tolist()
			colWidth.append(len(col))
			colWidths.append(colWidth)
			
			# use index as ID except for group/sub-group, where using a string
			# allows the col along with row to be accessed for individual cells
			colID = col.lower() if col in ('Group', 'Subgrp') else i
			colsIDs.append((col, colID))
		
		# get max width for each col, taking log to slow the width increase
		# for wider strings and capping at a max width
		widths = {
			i: min((math.log1p(max(c)) * 40, TableArrayAdapter.MAX_WIDTH))
			for i, c in enumerate(colWidths)
		}
		
		return widths, colsIDs, df.to_numpy()

	@on_trait_change('_medlinePath')
	def importMedline(self):
		"""Import a Medline file and display in table."""
		df = self._importFile(
			self._medlinePath, medline_embase_scopus.DefaultExtractors.MEDLINE)
		if df is not None:
			self._medlineAdapter._widths, self._medlineAdapter.columns, \
				self._medline = self._df_to_cols(df)
			self.select_sheet_tab = SheetTabs.MEDLINE.value

	@on_trait_change('_embasePath')
	def importEmbase(self):
		"""Import an Embase file and display in table."""
		df = self._importFile(
			self._embasePath, medline_embase_scopus.DefaultExtractors.EMBASE)
		if df is not None:
			self._embaseAdapter._widths, self._embaseAdapter.columns, \
				self._embase = self._df_to_cols(df)
			self.select_sheet_tab = SheetTabs.EMBASE.value

	@on_trait_change('_scopusPath')
	def importScopus(self):
		"""Import a SCOPUS file and display in table."""
		df = self._importFile(
			self._scopusPath, medline_embase_scopus.DefaultExtractors.SCOPUS)
		if df is not None:
			self._scopusAdapter._widths, self._scopusAdapter.columns, \
				self._scopus = self._df_to_cols(df)
			self.select_sheet_tab = SheetTabs.SCOPUS.value

	def _importFile(self, path, extractor=None):
		"""Import a database file.

		Args:
			path (str): Path to database file to import.
			extractor (:obj:`medline_embase_scopus.DefaultExtractors`):
				Enum of default extractor for the given database. Ignored
				if :attr:`_extractor` is :const:`_DEFAULT_EXTRACTOR`.
				Defaults to None to determine by :meth:`dbExtractor.extractDb`.

		Returns:
			:obj:`pd.DataFrame`: Data frame of extracted file.

		"""
		if not os.path.exists(path):
			# file inaccessible, or manually edited, non-accessible path
			self._statusBarMsg = f'{path} could not be found, skipping'
			return None
		self._save_dir = os.path.dirname(path)

		extractorPath = self._extractor
		if extractorPath is self._DEFAULT_EXTRACTOR:
			# auto-select extractor based on given database, not on path
			if extractor:
				# use given extractor
				extractorPath = medline_embase_scopus.PATH_EXTRACTORS / \
					extractor.value
			else:
				# defer finding extractor to the extractor function
				extractorPath = None
		else:
			# get full path for selected extractor
			extractorPath = self._extractor_paths[extractorPath]

		try:
			# extract file
			df, dbName = self.dbExtractor.extractDb(path, extractorPath)
			self._statusBarMsg = f'Imported file from {path}'
			
			# reset extractor to auto
			self._extractor = self._DEFAULT_EXTRACTOR
			return df
		except (FileNotFoundError, SyntaxError) as e:
			self._statusBarMsg = str(e)
		return None

	@on_trait_change('_overlapBtn')
	def findOverlaps(self):
		"""Find overlaps."""
		try:
			df = self.dbExtractor.combineOverlaps()
			if df is None:
				return
			self._overlapsAdapter._widths, self._overlapsAdapter.columns, \
				self._overlaps = self._df_to_cols(df)
			self.select_sheet_tab = SheetTabs.OVERLAPS.value
			self._statusBarMsg = 'Found overlaps across databases'
		except TypeError as e:
			# TODO: catch additional errors that may occur with overlaps
			msg = 'An erorr occurred while finding overlaps across databases.' \
				' Please try again, or check the logs for more details.'
			self._statusBarMsg = msg
			print(msg)
			print(e)

	def _get_save_path(self, default_path):
		"""Get a save path from the user through a file dialog.

		Args:
			default_path (str): Default path to display in the dialog.

		Returns:
			str: Chosen path.

		Raises:
			FileNotFoundError: User canceled file selection.

		"""
		if self._save_dir:
			# use directory of last chosen import file
			default_path = os.path.join(self._save_dir, default_path)
		
		# open a PyFace file dialog in save mode
		save_dialog = FileDialog(action="save as", default_path=default_path)
		if save_dialog.open() == OK:
			# get user selected path
			return save_dialog.path
		else:
			# user canceled file selection
			raise FileNotFoundError("User canceled file selection")

	@on_trait_change('_exportBtn')
	def exportTables(self):
		"""Export tables to file."""
		self.dbExtractor.saveSep = self._EXPORT_SEPS[self._exportSep]
		try:
			save_path = self._get_save_path(
				self.dbExtractor.DEFAULT_OVERLAPS_PATH)
			self.dbExtractor.exportDataFrames(save_path)
			self._statusBarMsg = (
				f'Saved "{os.path.basename(save_path)}" and filtered tables to:'
				f' {os.path.dirname(save_path)}')
		except FileNotFoundError:
			print("Skipping file save")


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
