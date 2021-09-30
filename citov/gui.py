#!/usr/bin/env python
from typing import Union

import math
from collections import OrderedDict
from enum import Enum, auto
import glob
import os

import pandas as pd
import sys

import numpy as np
from PyQt5 import QtWidgets, QtCore
# adjust density for HiDPI screens
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
from pyface.api import FileDialog, OK
from traits.api import HasTraits, on_trait_change, Int, Str, Button, \
	Array, push_exception_handler, File, HTML, List, Instance, Property
from traitsui.api import Handler, View, Item, Group, HGroup, VGroup, Tabbed, \
	HSplit, HTMLEditor, TabularEditor, FileEditor, CheckListEditor, \
	ProgressEditor
from traitsui.tabular_adapter import TabularAdapter

from citov import config, extractor, overlaps_thread


def main():
	# show complete stacktraces for debugging
	push_exception_handler(reraise_exceptions=True)
	gui = CiteOverlapGUI()
	gui.configure_traits()


def _displayExtractor(path):
	"""Convert an extractor filename for display.
	
	Args:
		path (str): Path.

	Returns:
		str: ``path`` without extension.

	"""
	return os.path.splitext(path)[0]


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


class CiteOverlapHandler(Handler):
	"""Custom handler for Citation Overlap GUI object events."""
	
	TAB_OVERLAPS = "Overlaps"

	def init(self, info):
		"""Perform GUI initialization tasks."""
		# left-align table headers
		table_widgets = info.ui.control.findChildren(QtWidgets.QTableView)
		for table in table_widgets:
			table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft)
		
		views = list(info.object.importViews)
		views.append(None)
		for i, view in enumerate(views):
			# rename tabs in all tabbed panes since the CiteImport triggered
			# names appear to be overridden, with one extra iteration to
			# change the last ("Overlaps") tab in the largest Tabbed group
			info.object.renameSheetTab = i
			# any string to trigger change if view is None
			info.object.renameSheetName = (
				'change' if view is None else _displayExtractor(view.extractor))
			self.object_renameSheetName_changed(info)
		
		# trigger renaming the overlaps tab in the largest tabbed pane
		info.object.renameSheetTab = len(info.object.importViews)
		info.object.renameSheetName = ''
		
		for ed in info.ui._editors:
			if ed.name == "_helpHtml":
				# enable opening links in an external browser in help doc
				# editor, assumed to be a QTextBrowser
				ed.control.setOpenExternalLinks(True)
	
	@staticmethod
	def getSheetsTabWidget(info):
		tabWidgets = info.ui.control.findChildren(QtWidgets.QTabWidget)
		if len(tabWidgets) < 1:
			return []
		return tabWidgets[:-1]
	
	def object_selectSheetTab_changed(self, info):
		"""Select the given tab specified by
		:attr:`CiteOverlapGUI.selectSheetTab`.

		Args:
			info (UIInfo): TraitsUI UI info.

		"""
		# find the tab widget QTabWidget and select the given tab
		tabWidgets = self.getSheetsTabWidget(info)
		for tabWidget in tabWidgets:
			tabWidget.setCurrentIndex(info.object.selectSheetTab)
	
	def object_renameSheetName_changed(self, info):
		"""Handler to rename sheets.
		
		Args:
			info (UIInfo): TraitsUI UI info.

		"""
		if not info.object.renameSheetName:
			# skip name resets
			return
		
		# find all tabbed panes, which contain different numbers of "other" tabs
		tabWidgets = self.getSheetsTabWidget(info)
		for tabWidget in tabWidgets:
			# rename tab from name trait unless the last tab, assumed to be
			# the overlaps tab
			tabCount = tabWidget.count()
			tabi = info.object.renameSheetTab
			name = (
				info.object.renameSheetName if tabi < tabCount - 1
				else self.TAB_OVERLAPS)
			tabWidget.setTabText(tabi, name)
		
		# reset name to allow other dropdowns set to the same extractor name
		# as the last chosen extractor to trigger a name change
		info.object.renameSheetName = ''


class CiteSheet(HasTraits):
	"""Spreadsheet for citation array."""
	adapter = TableArrayAdapter  # adapter for TabularAdapter
	data = Array  # citation array


class CiteImport(HasTraits):
	"""Citation list file importer.
	
	Provides a view to select the extractor definition file and citation
	file to import.
	
	Attributes:
		sheet (:class:`CiteSheet`): Spreadsheet displaying the imported data.
		dbName (str): Name of imported database.
	
	"""
	extractor = Str()  # extractor filename in extractorNames
	extractorNames = Instance(TraitsList)  # list of extractor filenames
	path = File()  # citation list path
	sheet = Instance(CiteSheet)  # associated sheet
	clearBtn = Button('Clear')  # button to clear data
	
	# TraitsUI default view
	traits_view = View(
		VGroup(
			HGroup(
				Item(
					"extractor", label='File source', springy=True,
					# convert extractor filename for display
					editor=CheckListEditor(
						name="object.extractorNames.selections",
						format_func=_displayExtractor)),
			),
			HGroup(
				Item(
					'path', show_label=False, style='simple', springy=True,
					editor=FileEditor(allow_dir=True)),
				Item('clearBtn', show_label=False),
			),
		),
	)
	
	def __init__(self, sheet):
		"""Initialize import view."""
		super().__init__()
		self.sheet = sheet
		self.dbName = None


class CiteOverlapGUI(HasTraits):
	"""GUI for Citation Overlap."""
	
	#: str: Default extractor option to prompt user to select an extractor.
	_DEFAULT_EXTRACTOR = "Select..."
	
	#: int: Default number of import views.
	_DEFAULT_NUM_IMPORTS = 3
	
	#: OrderedDict[str, str]: Dictionary of separator descriptions to
	# separator characters.
	_EXPORT_SEPS = OrderedDict((
		('Tabs (.tsv)', '\t'),
		('Comma (.csv)', ','),
		('Bar (.csv)', '|'),
		('Semi-colon (.csv)', ';'),
	))

	# handler triggers
	selectSheetTab = Int(-1)  # tab index to select
	renameSheetTab = Int(-1)  # tab index to rename
	renameSheetName = Str  # new tab name

	# CONTROL PANEL TRAITS

	# citation list import views
	importMedline = Instance(CiteImport)
	importEmbase = Instance(CiteImport)
	importScopus = Instance(CiteImport)
	importOther1 = Instance(CiteImport)
	importOther2 = Instance(CiteImport)
	importOther3 = Instance(CiteImport)
	importOther4 = Instance(CiteImport)
	_importAddBtn = Button('Add Sheet')

	# extractor drop-downs
	_extractorNames = Instance(TraitsList)
	_extractorAddBtn = Button('Add Extractor')

	# button to find overlaps and progress bar
	_overlapBtn = Button('Find Overlaps')
	_progBarPct = Int(0)
	_progBarMsg = Str('Awaiting overlaps')

	# table export
	_exportBtn = Button('Export Tables')
	_exportSep = Str
	_exportSepNames = Instance(TraitsList)
	_statusBarMsg = Str
	
	# HELP PANEL TRAITS
	
	pkgDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	docsDir = os.path.join(pkgDir, "docs")
	if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
		# detect frozen env using the PyInstaller-specific attributes
		# (currently works even without this setting through symlinks)
		docsDir = os.path.realpath(os.path.join(sys._MEIPASS, "docs"))
	with open(os.path.join(docsDir, "sidebar.html"), mode="r") as help_file:
		helpMsg = "".join(help_file.readlines())
	
	_helpHtml = HTML(helpMsg)
	
	# SHEETS TRAITS
	
	# counter for number of "other citation" sheets
	_numCitOther = Int(0)
	_tabularArgs = {
		'editable': True, 'auto_resize_rows': True,
		'stretch_last_section': False}
	
	# Import view groups, which need an adapter set here to avoid sharing
	# the adapter across view instances
	
	# MEDLINE table
	_medlineAdapter = TableArrayAdapter()
	_medlineTable = TabularEditor(adapter=_medlineAdapter, **_tabularArgs)
	_medline = CiteSheet(adapter=_medlineAdapter)

	# Embase table
	_embaseAdapter = TableArrayAdapter()
	_embaseTable = TabularEditor(adapter=_embaseAdapter, **_tabularArgs)
	_embase = CiteSheet(adapter=_embaseAdapter)

	# Scopus table
	_scopusAdapter = TableArrayAdapter()
	_scopusTable = TabularEditor(adapter=_scopusAdapter, **_tabularArgs)
	_scopus = CiteSheet(adapter=_scopusAdapter)

	# Other 1 table
	_citOther1Adapter = TableArrayAdapter()
	_citOther1Table = TabularEditor(adapter=_citOther1Adapter, **_tabularArgs)
	_citOther1 = CiteSheet(adapter=_citOther1Adapter)

	# Other 2 table
	_citOther2Adapter = TableArrayAdapter()
	_citOther2Table = TabularEditor(adapter=_citOther2Adapter, **_tabularArgs)
	_citOther2 = CiteSheet(adapter=_citOther2Adapter)

	# Other 3 table
	_citOther3Adapter = TableArrayAdapter()
	_citOther3Table = TabularEditor(adapter=_citOther3Adapter, **_tabularArgs)
	_citOther3 = CiteSheet(adapter=_citOther3Adapter)

	# Other 4 table
	_citOther4Adapter = TableArrayAdapter()
	_citOther4Table = TabularEditor(adapter=_citOther4Adapter, **_tabularArgs)
	_citOther4 = CiteSheet(adapter=_citOther4Adapter)

	# Overlaps output table
	_overlapsAdapter = TableArrayAdapter()
	_outputTable = TabularEditor(adapter=_overlapsAdapter, **_tabularArgs)
	_overlaps = CiteSheet(adapter=_overlapsAdapter)
	
	# TRAITUI WIDGETS
	
	# controls panel
	_controlsPanel = VGroup(
		VGroup(
			Item('importMedline', show_label=False, style='custom'),
			Item('importEmbase', show_label=False, style='custom'),
			Item('importScopus', show_label=False, style='custom'),
			Item(
				'importOther1', show_label=False, style='custom',
				visible_when='_numCitOther >= 1'
			),
			Item(
				'importOther2', show_label=False, style='custom',
				visible_when='_numCitOther >= 2'
			),
			Item(
				'importOther3', show_label=False, style='custom',
				visible_when='_numCitOther >= 3'
			),
			Item(
				'importOther4', show_label=False, style='custom',
				visible_when='_numCitOther >= 4'
			),
			HGroup(
				Item(
					'_importAddBtn', show_label=False, springy=True,
					enabled_when='_numCitOther <= object._DEFAULT_NUM_IMPORTS'),
				Item('_extractorAddBtn', show_label=False, springy=True),
			),
			label='Load Citation Files',
		),
		VGroup(
			HGroup(
				Item('_overlapBtn', show_label=False, springy=True),
			),
			Item('_progBarPct', show_label=False, editor=ProgressEditor(
				min=0, max=100, message_name='_progBarMsg')),
			HGroup(
				Item('_exportBtn', show_label=False, springy=True),
				Item(
					"_exportSep", label="Separator",
					editor=CheckListEditor(
						name="object._exportSepNames.selections")),
			),
			label='Detect Overlapping Citations',
		),
		label="Import",
	)
	
	# help panel
	_helpPanel = VGroup(
		Item("_helpHtml", editor=HTMLEditor(format_text=True), show_label=False),
		label="Help",
	)
	
	# tabbed panel for sidebar
	_sidebarTabs = Tabbed(
		_controlsPanel,
		_helpPanel,
	)

	# Tabbed viewers of tables
	
	# WORKAROUND: Because of an apparent limitation in adding tabs dynamically
	# in TraitsUI (https://github.com/enthought/traitsui/pull/1456), separate
	# views are created and toggled depending on the number of "other" sheets,
	# toggled by the "visible_when" flag
	
	# default tabbed viewer
	_tableView1 = Tabbed(
		Item(
			'object._medline.data', editor=_medlineTable, show_label=False,
			width=1000),
		Item('object._embase.data', editor=_embaseTable, show_label=False),
		Item('object._scopus.data', editor=_scopusTable, show_label=False),
		Item('object._overlaps.data', editor=_outputTable, show_label=False),
		visible_when='_numCitOther == 0',
	)

	# tabbed viewer of tables with one "other" sheet
	_tableView2 = Tabbed(
		Item(
			'object._medline.data', editor=_medlineTable, show_label=False,
			width=1000),
		Item('object._embase.data', editor=_embaseTable, show_label=False),
		Item('object._scopus.data', editor=_scopusTable, show_label=False),
		Item('object._citOther1.data', editor=_citOther1Table, show_label=False),
		Item('object._overlaps.data', editor=_outputTable, show_label=False),
		visible_when='_numCitOther == 1',
	)

	# tabbed viewer of tables with two "other" sheets
	_tableView3 = Tabbed(
		Item(
			'object._medline.data', editor=_medlineTable, show_label=False,
			width=1000),
		Item('object._embase.data', editor=_embaseTable, show_label=False),
		Item('object._scopus.data', editor=_scopusTable, show_label=False),
		Item('object._citOther1.data', editor=_citOther1Table, show_label=False),
		Item('object._citOther2.data', editor=_citOther2Table, show_label=False),
		Item('object._overlaps.data', editor=_outputTable, show_label=False),
		visible_when='_numCitOther == 2',
	)

	# tabbed viewer of tables with three "other" sheets
	_tableView4 = Tabbed(
		Item(
			'object._medline.data', editor=_medlineTable, show_label=False,
			width=1000),
		Item('object._embase.data', editor=_embaseTable, show_label=False),
		Item('object._scopus.data', editor=_scopusTable, show_label=False),
		Item('object._citOther1.data', editor=_citOther1Table, show_label=False),
		Item('object._citOther2.data', editor=_citOther2Table, show_label=False),
		Item('object._citOther3.data', editor=_citOther2Table, show_label=False),
		Item('object._overlaps.data', editor=_outputTable, show_label=False),
		visible_when='_numCitOther == 3',
	)

	# tabbed viewer of tables with four "other" sheets
	_tableView5 = Tabbed(
		Item(
			'object._medline.data', editor=_medlineTable, show_label=False,
			width=1000),
		Item('object._embase.data', editor=_embaseTable, show_label=False),
		Item('object._scopus.data', editor=_scopusTable, show_label=False),
		Item('object._citOther1.data', editor=_citOther1Table, show_label=False),
		Item('object._citOther2.data', editor=_citOther2Table, show_label=False),
		Item('object._citOther3.data', editor=_citOther2Table, show_label=False),
		Item('object._citOther4.data', editor=_citOther2Table, show_label=False),
		Item('object._overlaps.data', editor=_outputTable, show_label=False),
		visible_when='_numCitOther == 4',
	)

	# main view
	view = View(
		HSplit(
			_sidebarTabs,
			# only one table view should be displayed at a time
			Group(
				_tableView1,
				_tableView2,
				_tableView3,
				_tableView4,
				_tableView5,
			),
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
		
		# set up import views
		self.importMedline = CiteImport(sheet=self._medline)
		self.importEmbase = CiteImport(sheet=self._embase)
		self.importScopus = CiteImport(sheet=self._scopus)
		self.importOther1 = CiteImport(sheet=self._citOther1)
		self.importOther2 = CiteImport(sheet=self._citOther2)
		self.importOther3 = CiteImport(sheet=self._citOther3)
		self.importOther4 = CiteImport(sheet=self._citOther4)
		self.importViews = (
			self.importMedline,
			self.importEmbase,
			self.importScopus,
			self.importOther1,
			self.importOther2,
			self.importOther3,
			self.importOther4,
		)

		# populate drop-down of available extractors from directory of
		# extractors, displaying only basename but keeping dict with full path
		extractor_paths = []
		for extractor_dir in config.extractor_dirs:
			extractor_paths.extend(glob.glob(str(extractor_dir / "*")))
		self._extractor_paths = {
			os.path.basename(f): f for f in extractor_paths}
		self._updateExtractorNames(True)
		for importer in self.importViews:
			importer.observe(self.renameTabEvent, "extractor")
			importer.observe(self.importFile, "path")
			importer.observe(self.clearSheet, "clearBtn")

		# populate drop-down of separators/delimiters
		self._exportSepNames = TraitsList()
		self._exportSepNames.selections = list(self._EXPORT_SEPS.keys())
		self._exportSep = self._exportSepNames.selections[0]

		# extractor and overlaps thread instances
		self.dbExtractor = extractor.DbExtractor()
		self._overlapsThread = None
		
		# last opened directory
		self._save_dir = None
	
	def _updateExtractorNames(self, reset=False):
		"""Update the list of extractor names shown in the combo boxes.
		
		Args:
			reset (bool): True to reset to default selections; defaults to
				False.
		
		"""
		if reset:
			# pick default selections for each extractor
			selections = [e.value for e in extractor.DefaultExtractors]
			numExtra = len(self.importViews) - len(selections)
			if numExtra > 0:
				selections.extend([self._DEFAULT_EXTRACTOR] * numExtra)
		else:
			# keep current selections
			selections = [v.extractor for v in self.importViews]
		# update combo box from extractor path keys
		self._extractorNames = TraitsList()
		extractorNames = [self._DEFAULT_EXTRACTOR]
		extractorNames.extend(self._extractor_paths.keys())
		self._extractorNames.selections = extractorNames
		
		# assign default extractor selections
		for view, selection in zip(self.importViews, selections):
			view.extractorNames = self._extractorNames
			view.extractor = selection
	
	def renameTabEvent(self, event):
		"""Handler to rename a spreadsheet tab.
		
		Args:
			event (:class:`traits.observation.events.TraitChangeEvent`): Event.

		"""
		self.renameSheetTab = self.importViews.index(event.object)
		self.renameSheetName = _displayExtractor(event.object.extractor)

	def clearSheet(self, event):
		"""Clear the sheet associated with an import view.
		
		Args:
			event (:class:`traits.observation.events.TraitChangeEvent`): Event.

		"""
		event.object.sheet.data = np.empty((0, 0))
		del self.dbExtractor.dbsParsed[event.object.dbName]
		event.object.path = ''
	
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

	@on_trait_change('_importAddBtn')
	def addImport(self):
		"""Add import fields and a new sheet."""
		if self._numCitOther < len(
				self.importViews) - self._DEFAULT_NUM_IMPORTS:
			# trigger additional import view and tab with new sheet
			self._numCitOther += 1

	@on_trait_change('_extractorAddBtn')
	def addExtractor(self):
		"""Add an extractor to the combo box."""
		try:
			# get path to extractor from file dialog
			path = self._getFileDialogPath()
		except FileNotFoundError:
			return
		
		# update combo box
		pathName = os.path.basename(path)
		self._extractor_paths[pathName] = path
		self._updateExtractorNames()
	
	def importFile(self, event):
		"""Import a database file.

		Args:
			event (:class:`traits.observation.events.TraitChangeEvent`): Event.

		Returns:
			:obj:`pd.DataFrame`: Data frame of extracted file.

		"""
		path = event.object.path
		if not os.path.exists(path):
			if path:
				# file inaccessible, or manually edited, non-accessible path
				self._statusBarMsg = f'{path} could not be found, skipping'
			return None
		self._save_dir = os.path.dirname(path)

		try:
			# extract file
			extractorPath = self._extractor_paths[event.object.extractor]
			df, dbName = self.dbExtractor.extractDb(path, extractorPath)
			event.object.dbName = dbName
			self._statusBarMsg = f'Imported file from {path}'
			sheet = event.object.sheet
			if df is not None and sheet is not None:
				# output data frame to associated table
				sheet.adapter._widths, sheet.adapter.columns, sheet.data = \
					self._df_to_cols(df)
				self.selectSheetTab = self.importViews.index(event.object)
			return df
		except (FileNotFoundError, SyntaxError) as e:
			self._statusBarMsg = str(e)
		return None

	def _updateProgBar(self, pct: int, msg: str):
		""""Update progress bar.
		
		Args:
			pct: Percentage complete, from 0-100.
			msg: Message to display.

		"""
		self._progBarPct = pct
		self._progBarMsg = msg

	def _overlapsHandler(self, result: Union[pd.DataFrame, str]):
		"""Handle result from finding overlaps.
		
		Args:
			result: Data frame of overlaps or message.
		
		"""
		if isinstance(result, pd.DataFrame):
			self._progBarPct = 100
			if result is None:
				# clear any existing data in sheet if no citation lists
				self._overlaps.data = np.empty((0, 0))
				self._statusBarMsg = 'No citation lists found'
				return
			
			# populate overlaps sheet
			self._overlaps.adapter._widths, self._overlaps.adapter.columns, \
				self._overlaps.data = self._df_to_cols(result)
			self.selectSheetTab = self._DEFAULT_NUM_IMPORTS + self._numCitOther
			self._statusBarMsg = 'Found overlaps across databases'
		elif isinstance(result, str):
			# show message
			self._statusBarMsg = result

	@on_trait_change('_overlapBtn')
	def findOverlaps(self):
		"""Find overlaps in a thread."""
		self._progBarPct = 0
		self._overlapsThread = overlaps_thread.OverlapsThread(
			self.dbExtractor, self._overlapsHandler, self._updateProgBar)
		self._overlapsThread.start()

	def _getFileDialogPath(self, default_path='', mode='open'):
		"""Get a path from the user through a file dialog.

		Args:
			default_path (str): Initial path to display in the dialog; defaults
				to an emptry string. If :attr:`_save_dir` is set,
				``default_path`` will be joined to the save directory.
			mode (str): "open" for an open dialog, or "save as" for a save
				dialog.

		Returns:
			str: Chosen path.

		Raises:
			FileNotFoundError: User canceled file selection.

		"""
		if self._save_dir:
			# use directory of last chosen import file
			default_path = os.path.join(self._save_dir, default_path)
		
		# open a PyFace file dialog in save mode
		save_dialog = FileDialog(action=mode, default_path=default_path)
		if save_dialog.open() == OK:
			# get user selected path
			return save_dialog.path
		else:
			# user canceled file selection
			raise FileNotFoundError("User canceled file selection")

	@on_trait_change('_exportBtn')
	def exportTables(self):
		"""Export tables to a files."""
		self.dbExtractor.saveSep = self._EXPORT_SEPS[self._exportSep]
		try:
			# prompt user to select an output file path for the combined list;
			# save along with filtered folders in a separate dir there
			save_path = self._getFileDialogPath(
				self.dbExtractor.DEFAULT_OVERLAPS_PATH, "save as")
			self.dbExtractor.exportDataFrames(save_path)
			self._statusBarMsg = (
				f'Saved combined table to "{save_path}" and filtered tables '
				f'alongside in "{self.dbExtractor.DEFAULT_CLEANED_DIR_PATH}"')
		except FileNotFoundError:
			print("Skipping file save")


if __name__ == "__main__":
	print('Initializing Citation Overlap GUI')
	main()
