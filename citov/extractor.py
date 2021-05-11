"""Citation list extractor for the Citation-Overlap tool."""

import glob
import logging
import os
from collections import OrderedDict
from enum import Enum

import pandas as pd

from citov import config, overlapper, utils
from citov.utils import load_yaml

#: :class:`logging.Logger`: Logger for this module.
_logger = logging.getLogger().getChild(__name__)


class ExtractKeys(Enum):
	"""Database extraction output keys."""
	ROW = 'row'
	PMID = 'pmid'
	EMID = 'emid'
	AUTHOR_NAMES = 'authorNames'
	AUTHOR_KEY = 'authorKey'
	TITLE = 'title'
	TITLE_MIN = 'titleMin'
	YEAR = 'year'
	JOURNAL = 'journal'
	JOURNAL_KEY = 'journalKey'
	EXTRAS = 'extras'


class DbNames(Enum):
	"""Names of databases with extractors."""
	MEDLINE = 'Medline'
	EMBASE = 'Embase'
	SCOPUS = 'Scopus'


class JointKeyExtractor:
	"""Join metadata from different rows with custom separators.
	
	Allows specifying different keys and separators for each field. Can also
	prioritize certain keys over others, extracting the first key that is
	present.
	
	"""
	def __init__(self, key, start='', end=''):
		"""Initialize the extractor.

		Args:
			key (str, List[str]): Key or sequence of keys.
			start (str, List[str]): Start string or sequence of strings.
			end (str, List[str]): End string or sequence of strings
		"""
		self.key = key
		self.start = start
		self.end = end

	def __repr__(self):
		"""Get string representation."""
		return f'key={self.key}, start={self.start}, end={self.end}'

	@staticmethod
	def parseMods(row, mods, out):
		"""Recursively parse modifiers based on key presence.

		Args:
			row (dict[str, str]): Dictionary from a row.
			mods (List[:obj:`JointKeyExtractor]): Sequence of extractor
				objects or nested sequences. If a sequence, the first
				matching key will be used. If the key is a sequence,
				values will only be extracted if all keys are present.
			out (List[str]): Sequence of parsed values thus far.

		Returns:
			str: Parsed modifiers.

		"""
		mod = mods[0]
		if utils.is_seq(mod):
			# apply each modifier until successfully parsing
			for mod_sub in mod:
				parsed = JointKeyExtractor.parseMods(row, [mod_sub], [])
				if parsed:
					out.append(parsed)
					break
		elif utils.is_seq(mod.key):
			if all([k in row and row[k] for k in mod.key]):
				mod_sub = [
					JointKeyExtractor(k, s, e)
					for k, s, e in zip(mod.key, mod.start, mod.end)]
				JointKeyExtractor.parseMods(row, mod_sub, out)
		elif row.get(mod.key):
			out.append(''.join((mod.start, row[mod.key], mod.end)))
		if len(mods) <= 1:
			return ''.join(out)
		return JointKeyExtractor.parseMods(row, mods[1:], out)


class DbExtractor:
	"""Perform database extractions and store results for overlap detection.

	Attributes:
		saveSep (str): Separator/delimiter to use when exporting data frames;
			defaults to None to not export.
		globalPmidDict (dict): PubMed ID dict.
		globalAuthorKeyDict (dict): Author keys dict.
		globalTitleMinDict (dict): Short title dict.
		globalJournalKeyDict (dict): Journal key dict.
		dbsParsed (OrderedDict[str, dict]): Dictionary of database names to
			parsed database dictionaries; defaults to an empty dictionary.
		dfsParsed (OrderedDict): Dictionary of database names to
			parsed database data frames; defaults to an empty dictionary.
		dfOverlaps (:obj:`pd.DataFrame`): Data frame of databases processed
			for overlaps; defaults to None.

	"""
	#: str: Default overlaps file output filename.
	DEFAULT_OVERLAPS_PATH = 'medline_embase_scopus_combo'

	_YAML_MATCHER = {
		'ExtractKeys': ExtractKeys,
		'JointKeyExtractor': JointKeyExtractor,
	}

	def __init__(self, saveSep=None):
		self.saveSep = saveSep

		self.globalPmidDict = {}
		self.globalAuthorKeyDict = {}
		self.globalTitleMinDict = {}
		self.globalJournalKeyDict = {}
		self.dbsParsed = OrderedDict()
		self.dfsParsed = OrderedDict()
		self.dfOverlaps = None

		self._dbNamesLower = [e.value.lower() for e in DbNames]

	def _saveDataFrame(self, df, path, suffix=''):
		"""Save a data frame to file.

		Args:
			df (:obj:`pd.DataFrame`): Data frame to export.
			path (str): Base path for export.
			suffix (str): Path suffix; defaults to ''.

		Returns:
			str, pathOut: Output message and path.

		"""
		ext = 'tsv' if self.saveSep == '\t' else 'csv'
		pathOut = f'{os.path.splitext(path)[0]}{suffix}.{ext}'
		df.to_csv(pathOut, sep=self.saveSep, index=False)
		msg = f'Saved output file to: {pathOut}'
		print(msg)
		return msg, pathOut

	def extractDb(self, path, extractorPath=None, df=None):
		"""Extract a database file into a parsed format.

		Args:
			path (str): Path to database TSV file.
			extractorPath (str): Path to extractor specification YAML file;
				defaults to None to detect the appropriate extractor
				based on the corresponding name at the start of the filename
				in ``path``.
			df (:obj:`pd.DataFrame`): Data frame of database records to
				extract; defaults to None to read from ``path``.

		Returns:
			:obj:`pd.DataFrame`, str: The extracted database as a data frame
			and the name of database, or None for each if an appropriate
			extractor was not found.
		
		Raises:
			FileNotFound: If an appropriate extractor file was not found.

		"""
		if not extractorPath:
			# identify a YAML extractor for the given database based on first
			# part of the path filename
			pathDbSplit = os.path.basename(os.path.splitext(path)[0]).split('_')
			for extractor_dir in config.extractor_dirs:
				extractorPaths = glob.glob(
					str(extractor_dir / f'{pathDbSplit[0].lower()}.*'))
				for extrPath in extractorPaths:
					if os.path.splitext(extrPath.lower())[1] in (
							'.yml', '.yaml'):
						# case-insensitive match for YAML extension
						extractorPath = extrPath
						break

		if extractorPath and os.path.exists(extractorPath):
			# extract database file contents
			print(f'Loading extractor from "{extractorPath}" for "{path}"')
			extractor = load_yaml(extractorPath, self._YAML_MATCHER)[0]
			dbName = os.path.splitext(
				os.path.basename(extractorPath))[0].lower()
			dbEnum = None
			for name in self._dbNamesLower:
				if dbName.startswith(name):
					# format the database name according to the Enum value
					dbEnum = DbNames[name.upper()]
					dbName = dbEnum.value
					break
			headerMainId = 'Embase_ID' if dbEnum is DbNames.SCOPUS else None
			if df is None:
				try:
					if os.path.isdir(path):
						paths = glob.glob(os.path.join(path, "*"))
						df = utils.merge_csvs(paths)
					else:
						df = utils.read_csv(path)
				except SyntaxError as e:
					raise e
			self.dbsParsed[dbName], df_out = overlapper.processDatabase(
				df, dbName, extractor, self.globalPmidDict,
				self.globalAuthorKeyDict, self.globalTitleMinDict,
				self.globalJournalKeyDict, headerMainId)
			self.dfsParsed[dbName] = df_out
		else:
			raise FileNotFoundError(f'Could not find extrator for "{path}"')
		return df_out, dbName

	def combineOverlaps(self):
		"""Combine overlaps from extracted databases in :attr:`dbParsed`.

		Returns:
			:obj:`pd.DataFrame`: Data frame of overlaps, or None if
			:attr:`dbsParsed` is empty.

		"""
		if not self.dbsParsed:
			return None
		records = []

		print('\n#################################################################')
		print(' Looking for overlaps')
		print('#################################################################\n')

		# Look for overlaps between all the files
		matchGroupNew = {}
		idToGroup = {}
		idToSubgroup = {}
		subgroupToId = {'.': ''}
		idToDistance = {}
		globalmatchCount = 0

		for dbName, dbDict in self.dbsParsed.items():
			# find overlaps among parsed dicts
			globalmatchCount = overlapper.findOverlaps(
				records, dbDict, self.dbsParsed, self.globalPmidDict,
				self.globalAuthorKeyDict, self.globalTitleMinDict,
				dbName[:3].upper(), matchGroupNew, idToGroup,
				idToSubgroup, subgroupToId, idToDistance, globalmatchCount)

		# import records to data frame and sort with ungrouped rows at end,
		# filling NA after the sort
		df = pd.DataFrame.from_records(records)
		df = df.sort_values(['Group', 'Subgrp'])
		df = df.fillna('none')  # replace np.nan
		df['Group'] = df['Group'].astype(str).str.split('.', 1, expand=True)
		print(df)
		self.dfOverlaps = df
		return df

	def exportDataFrames(self, overlapsOutPath):
		"""Export parsed database and overlaps data frames to file.

		Args:
			overlapsOutPath (str): Path to overlaps files.

		Returns:
			List[str]: List of output messages.

		"""
		dirPath = os.path.dirname(overlapsOutPath)
		msgs = []
		for dbName, df in self.dfsParsed.items():
			msgs.append(self._saveDataFrame(
				df, os.path.join(dirPath, dbName), '_clean')[0])
		if self.dfOverlaps is not None:
			msgs.append(self._saveDataFrame(
				self.dfOverlaps, overlapsOutPath)[0])
		return msgs
