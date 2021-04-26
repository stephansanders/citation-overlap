#!/usr/bin/env python
# Description: Process Embase and Pubmed search results and find matches
# Usage: python3 medline_embase_scopus.py -m pubmed_result.csv \
#   -e embase_noTitle.csv -s scopus_all.csv
# Author: Stephan Sanders

from enum import Enum
from collections import OrderedDict
import glob
import os
import re # regex
import string # string manipulation
import argparse # arguments parser
import jellyfish # string comparison # pip3 install jellyfish
#import hdbscan # pip3 install hdbscan
import pandas as pd
from pandas.errors import ParserError
import yaml

from citov import config

# How to perform the search

# Pubmed
# Perform search, e.g. (PDD OR ASD OR autism*) AND
# (biomarker* OR marker* OR endophenotype*)
# Click 'Save', open 'Format', Select 'CSV'

# Embase; behind a paywall
# Emtree term - exploded: (biological marker OR endophenotype OR marker)
# AND (autism);
# Language of article: english
# Records added to Embase (including end date): 01-01-1900 to 29-02-2020
# Select all records
# Click 'Export', for Choose a format: select 'CSV - Fields by Column',
# for Choose an output: select 'Full Record', do not tick 'Include search
# query in export'

# Scopus
# TITLE-ABS-KEY ( ( pdd  OR  asd  OR  autism* )  AND
# ( biomarker*  OR  marker*  OR  endophenotype* ) )  AND
# ( LIMIT-TO ( LANGUAGE ,  "English" ) )  AND  ( LIMIT-TO ( DOCTYPE ,  "ar" ) )
# AND  ( LIMIT-TO ( SRCTYPE ,  "j" ) )
# Can only download 2000 at a time in CSV format. Use "Limit to" in the
# filters to the left to select groups of ≤2,000, e.g. by year
# Click arrow next to 'All' above the column headings and below
# 'Analyze search results'; click 'Select all'
# Click 'Export'
# Select 'CSV Export'
# Add PubMed ID (you may want to add Abstract too)
# Click Export
# Combine the lists in a text editor or Google Sheet, not in Excel


#: str: Path to extractor specification folder.
PATH_EXTRACTORS = config.app_dir / 'extractors'


class DefaultExtractors(Enum):
	"""Default extractor filenames Enumeration."""
	MEDLINE = 'medline.yml'
	EMBASE = 'embase.yml'
	SCOPUS = 'scopus.yml'


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
	def __init__(self, key, start='', end=''):
		"""Extract values based on presence of keys or combinations of keys.

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
		if is_seq(mod):
			for mod_sub in mod:
				parsed = JointKeyExtractor.parseMods(row, [mod_sub], [])
				if parsed:
					out.append(parsed)
					break
		elif is_seq(mod.key):
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
			extractorPaths = glob.glob(
				str(PATH_EXTRACTORS / f'{pathDbSplit[0].lower()}.*'))
			for extrPath in extractorPaths:
				if os.path.splitext(extrPath.lower())[1] in ('.yml', '.yaml'):
					# case-insensitive match for YAML extension
					extractorPath = extrPath
					break

		if extractorPath and os.path.exists(extractorPath):
			# extract database file contents
			print(f'Loading extractor from "{extractorPath}" for "{path}"')
			extractor = load_yaml(extractorPath, _YAML_MATCHER)[0]
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
					df = pd.read_csv(
						path, index_col=False, dtype=str, na_filter=False)
				except ParserError:
					raise SyntaxError(f'Could not parse "{path} during import')
			self.dbsParsed[dbName], df_out = processDatabase(
				path, df, dbName, extractor, self.globalPmidDict,
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
			globalmatchCount = findOverlaps(
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


_YAML_MATCHER = {
	'ExtractKeys': ExtractKeys,
	'JointKeyExtractor': JointKeyExtractor,
}


def load_yaml(path, strToClass=None):
	"""Load a YAML file with support for multiple documents and Enums.

	Args:
		path (str): Path to YAML file.
		strToClass (dict): Dictionary mapping strings to classes; defaults
			to None. If a key or value in the YAML file matches a class
			followed by a period, the corresponding Enum will be used.
			If the first key in a dictionary matches a class, this dictionary
			will be replaced with an instance of this class with the value
			passed as arguments to the constructor.

	Returns:
		List[dict]: Sequence of parsed dictionaries for each document within
		a YAML file.

	"""
	def parse_enum_val(val):
		if isinstance(val, dict):
			key = tuple(val.keys())[0]
			if key in _YAML_MATCHER.keys():
				val = _YAML_MATCHER[key](*parse_enum_val(val[key]))
			else:
				val = parse_enum(val)
		elif is_seq(val):
			val = [parse_enum_val(v) for v in val]
		elif isinstance(val, str):
			val_split = val.split(".")
			if len(val_split) > 1 and val_split[0] in strToClass:
				# replace with the corresponding Enum class
				val = strToClass[val_split[0]][val_split[1]]
		return val

	def parse_enum(d):
		# recursively parse Enum keys and values within nested dictionaries
		out = {}
		for key, val in d.items():
			if isinstance(val, dict):
				# parse nested dictionaries
				val = parse_enum(val)
			elif is_seq(val):
				val = [parse_enum_val(v) for v in val]
			else:
				val = parse_enum_val(val)
			key = parse_enum_val(key)
			out[key] = val
		return out

	with open(path) as yaml_file:
		# load all documents into a generator
		docs = yaml.load_all(yaml_file, Loader=yaml.FullLoader)
		data = []
		for doc in docs:
			if strToClass:
				doc = parse_enum(doc)
			data.append(doc)
	return data


def authorNameProcess(name):
	"""Remove periods and replace spaces with underscores in author names.

	Args:
		name (str): Name string.

	Returns:
		str: Formatted name.

	"""
	# remove punctuation
	newName = name.translate(str.maketrans('', '', string.punctuation))
	newName = newName.replace(' ', '_')
	# newName = newName.replace('.', '')
	# newName = newName.replace('-', '')
	return newName


def printv(x):
	"""Quick way of printing variable name and variable, useful when debugging.

	Args:
		x (Any): Variable to look up.

	Returns:
		str: Variable info.

	"""
	import inspect
	frame = inspect.currentframe().f_back
	s = inspect.getframeinfo(frame).code_context[0]
	r = re.search(r"\((.*)\)", s).group(1)
	print("{} = {}".format(r, x))


def is_seq(val):
	"""Check if the value is a sequence.

	Args:
		val (Any): Value to check.

	Returns:
		bool: True if the value is a list or tuple.

	"""
	return isinstance(val, (tuple, list))


def _parseYear(row, key=None, search=None):
	"""Get the year from a row.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Column name; defaults to None. If given, ``search`` will
			be ignored.
		search (dict[str, Any]): Dictionary of ``row`` columns
			to regex search patterns to extract the year. Each pattern may
			be a sequence of patterns to try for the given column.

	Returns:
		str: Year.

	"""
	if key:
		# extract by simple key
		year = row.get(key)
		if year is not None:
			return year
	else:
		for col, val in search.items():
			# check for search pattern within column
			shortDet = row.get(col)
			if shortDet is not None:
				if not is_seq(val):
					val = [val]
				for pttn in val:
					yearMatch = re.search(pttn, shortDet)
					if yearMatch:
						return yearMatch.group(1)
	return 'NoYear'


def _parseAuthorNames(row, key, year):
	"""Get the author names and key.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Author names key in ``row``.
		year (str): Year to include in author key.

	Returns:
		List[str], str: Author names list, author key string. Both are None
		if ``key`` is not found in ``row``.

	"""
	authorKey = authorNames = '.'
	names = row.get(key)
	if names:
		authorNames = names
		authorsList = authorNames.split(', ')
		authorsList = list(filter(None, authorsList))
		firstAuthor = secondAuthor = lastAuthor = 'None'
		lenAuthorsList = len(authorsList)
		if lenAuthorsList >= 1:
			firstAuthor = authorNameProcess(authorsList[0])
		if lenAuthorsList >= 2:
			lastAuthor = authorNameProcess(authorsList[-1])
		if lenAuthorsList >= 3:
			secondAuthor = authorNameProcess(authorsList[1])

		authorKey = (
			f'{firstAuthor.lower()}|{secondAuthor.lower()}|'
			f'{lastAuthor.lower()}|{year}')

	return authorNames, authorKey


def _parseID(row, key, search=None, warn=True, default='NoPMID'):
	"""Get the ID.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Author names key in ``row``.
		search (str): Regex search pattern; defaults to None.
		warn (bool): True to warn if ID is not found; defaults to True.
		default (str): Default ID if ID is not found.

	Returns:
		str: ID.

	"""
	pmidField = row.get(key)
	if pmidField is not None:
		if search:
			# search for regex
			pmidMatch = re.search(search, pmidField)
			if pmidMatch:
				return pmidMatch.group(1)
		else:
			return pmidField
	if warn:
		print(f'ERR: No ID found: {pmidField}')
	return default


def _parseTitle(row, key):
	"""Get titles

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Author names key in ``row``.

	Returns:
		str, str: Title and shortest unique title.

	"""
	title = 'noTitle'
	titleMin = '.'
	titleName = row.get(key)
	if titleName:
		title = titleName
		titleField = titleName.lower()
		titleFieldClean = titleField.translate(str.maketrans(
			'', '', string.punctuation))  # remove punctuation
		titleList = titleFieldClean.split()
		titleMin = '_'.join(titleList[:7])
	return title, titleMin


def _parseJournal(row, key):
	"""Get the journal details.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Author names key in ``row``.

	Returns:
		str, str: Journal and journal key.

	"""
	journal = row.get(key)
	journalKey = None
	if journal:
		journalName = re.split(r'\d+', journal)
		journalNameLower = journalName[0].lower()
		journalNameLowerClean = journalNameLower.translate(str.maketrans(
			'', '', string.punctuation))  # remove punctuation
		journalKey = ''
		for word in journalNameLowerClean.split():
			threeLetter = word[:3]
			threeLetter.replace('jou', 'j')
			journalKey = f'{journalKey}{threeLetter}'
	return journal, journalKey


def _rowToList(row):
	"""Convert a row to a list, skipping the last field unless it contains
	brackets of empty single quotes.

	Args:
		row (dict[str, str]): Dictionary from a row.

	Returns:
		List[str]: Row without last element unless it meets the above criteria.

	"""
	rowOut = []
	rowLen = len(row)
	for i, field in enumerate(row):
		if i < rowLen - 1 or str(row[field]) == '["]':
			# skip last field if not brackets of empty quotes
			rowOut.append(str(row[field]))
	return rowOut


def dbExtract(row, extractor):
	"""Extract key info from a database row.

	The ``extractor`` specifies the arguments to the corresponding parsers
	for the given key. The :obj:`ExtractKeys.EXTRAS` key specifies a
	sequence of further modifications to the given key values. Each
	modification is a squence of the key to modify, a sequence of
	`JointKeyExtractors` that will be parsed from the given database row,
	and another sequence of extractors that will be parsed from the current
	extraction output.

	Args:
		row (dict[str, str]): Dictionary from a row.
		extractor (dict[:obj:`ExtractKeys`, Any): Extractor specification
			dict.

	Returns:
		dict[:obj:`ExtractKeys`, str]: Dictionary of extracted elements,
		with values defaulting to None if not found.

	"""
	extraction = dict.fromkeys(ExtractKeys, None)

	# parse year
	year_arg = extractor[ExtractKeys.YEAR]
	if isinstance(year_arg, dict):
		year = _parseYear(row, search=year_arg)
	else:
		year = _parseYear(row, year_arg)
	extraction[ExtractKeys.YEAR] = year

	# parse authors
	extraction[ExtractKeys.AUTHOR_NAMES], extraction[ExtractKeys.AUTHOR_KEY] \
		= _parseAuthorNames(row, extractor[ExtractKeys.AUTHOR_KEY], year)

	# parse PubMed ID
	pmid_arg = extractor[ExtractKeys.PMID]
	if is_seq(pmid_arg):
		pmid = _parseID(row, *pmid_arg)
	else:
		pmid = _parseID(row, pmid_arg)
	extraction[ExtractKeys.PMID] = pmid

	if ExtractKeys.EMID in extractor:
		# parse EMID
		extraction[ExtractKeys.EMID] = _parseID(
			row, *extractor[ExtractKeys.EMID])

	# parse title
	extraction[ExtractKeys.TITLE], extraction[ExtractKeys.TITLE_MIN] \
		= _parseTitle(row, extractor[ExtractKeys.TITLE])

	# parse journal
	extraction[ExtractKeys.JOURNAL], extraction[ExtractKeys.JOURNAL_KEY] \
		= _parseJournal(row, extractor[ExtractKeys.JOURNAL])

	# store tab-delimited version of row
	extraction[ExtractKeys.ROW] = _rowToList(row)

	if ExtractKeys.EXTRAS in extractor:
		# apply additional extractors
		for extra in extractor[ExtractKeys.EXTRAS]:
			extraction[extra[0]] = JointKeyExtractor.parseMods(
				row, extra[1], [JointKeyExtractor.parseMods(
					extraction, extra[2], [])])

	return extraction


def matchListMaker(
		pmidHere, authorKeyHere, titleMinHere, pmidDict,
		authorKeyDict, titleMinDict, theId, matchKeyDict, basisDict):
	"""Get a list of possible matches

	Args:
		pmidHere (str): PubMed ID.
		authorKeyHere (str): Author key.
		titleMinHere (str): Title min.
		pmidDict (dict[str, str]): PubMed dictionary.
		authorKeyDict (dict[str, str]): Author dictionary.
		titleMinDict (dict[str, str]): Title min dictionary.
		theId: ID.
		matchKeyDict (dict[str, int]): Match dictionary.
		basisDict (dict[str, int]): Basis dictionary.

	Returns:
		match dict, length of this dict, and basis dict.

	"""
	# Look for PMID matches
	if pmidHere != 'NoPMID' and pmidHere != '.':
		if ';' in pmidDict[pmidHere]:
			for theIdMatch in pmidDict[pmidHere].split(';'):
				matchKeyDict[theIdMatch] = 5
				if theId != theIdMatch:
					basisDict[ExtractKeys.PMID] = 5

	# Look for authorKey matches
	if authorKeyHere != '.':
		if ';' in authorKeyDict[authorKeyHere]:
			for theIdMatch in authorKeyDict[authorKeyHere].split(';'):
				matchKeyDict[theIdMatch] = 5
				if theId != theIdMatch:
					basisDict[ExtractKeys.AUTHOR_KEY] = 5

	# Look for titleMin matches
	if titleMinHere != '.':
		if ';' in titleMinDict[titleMinHere]:
			for theIdMatch in titleMinDict[titleMinHere].split(';'):
				matchKeyDict[theIdMatch] = 5
				if theId != theIdMatch:
					basisDict[ExtractKeys.TITLE_MIN] = 5

	return matchKeyDict, len(matchKeyDict), basisDict


def getDetails(extraId, dbDicts):
	"""Get PMID, authorKey and TitleMin for a given ID.

	Args:
		extraId (str): Extra ID.
		dbDicts (List[dict[str, dict[str, str]]]): Sequence of database dicts.

	Returns:
		PMID, authorKey and TitleMin.

	"""
	pmidExtraId = authorKeyExtraId = titleMinExtraId = '.'
	for dbDict in dbDicts:
		if extraId in dbDict:
			pmidExtraId = dbDict[extraId][ExtractKeys.PMID]
			authorKeyExtraId = dbDict[extraId][ExtractKeys.AUTHOR_KEY]
			titleMinExtraId = dbDict[extraId][ExtractKeys.TITLE_MIN]
			break

	return pmidExtraId, authorKeyExtraId, titleMinExtraId


def findGroups(theId, matchKeyDict, basisDict, matchCountHere, matchGroup):
	"""Find and label groups of matching papers.

	Args:
		theId (str): ID.
		matchKeyDict (dict[str, int]): Match dictionary.
		basisDict (dict[str, int]): Basis dictionary.
		matchCountHere (int): Match count.
		matchGroup (dict[str, int]): Match group dict.

	Returns:
		match, basis out, match group out, match count, match group.

	"""
	match = basisOut = matchGroupOut = '.'
	if len(matchKeyDict) > 1:
		possibleMatch = []
		for otherId in matchKeyDict:
			if otherId != theId:
				possibleMatch.append(otherId)
		
		match = ';'.join(possibleMatch)
		basisOut = ';'.join([k.value for k in basisDict.keys()])

		matchKeysAll = sorted(matchKeyDict.keys())
		matchKeyJoinAll = ';'.join(matchKeysAll)

		if matchKeyJoinAll in matchGroup:
			matchGroupOut = matchGroup[matchKeyJoinAll]
		else:
			matchCountHere += 1
			matchGroup[matchKeyJoinAll] = matchCountHere
			matchGroupOut = matchGroup[matchKeyJoinAll]

	return match, basisOut, matchGroupOut, matchCountHere, matchGroup


def matchFinder(
		pmidHere, authorKeyHere, titleMinHere, pmidDict, authorKeyDict,
		titleMinDict, matchCountHere, theId, matchGroup):
	"""Find matches within a single source.

	Args:
		pmidHere (str): PubMed ID.
		authorKeyHere (str): Author key.
		titleMinHere (str): Title min.
		pmidDict (dict[str, str]): PubMed dictionary.
		authorKeyDict (dict[str, str]): Author dictionary.
		titleMinDict (dict[str, str]): Title min dictionary.
		matchCountHere (int): Match count.
		theId: ID.
		matchGroup (dict[str, int]): Match group dict.

	Returns:
		match, basis out, match group out, match count, and match group.

	"""
	possibleMatch = {}
	basis = {}
	matchKey = {}
	
	# Look for PMID matches
	if pmidHere != 'NoPMID':
		if ';' in pmidDict[pmidHere]:
			for theIdMatch in pmidDict[pmidHere].split(';'):
				matchKey[theIdMatch] = 5
				if theId != theIdMatch:
					possibleMatch[theIdMatch] = 5
					basis[ExtractKeys.PMID] = 5

	# Look for authorKey matches
	if authorKeyHere != '.':
		if ';' in authorKeyDict[authorKeyHere]:
			for theIdMatch in authorKeyDict[authorKeyHere].split(';'):
				matchKey[theIdMatch] = 5
				if theId != theIdMatch:
					possibleMatch[theIdMatch] = 5
					basis[ExtractKeys.AUTHOR_KEY] = 5

	# Look for titleMin matches
	if titleMinHere != '.':
		if ';' in titleMinDict[titleMinHere]:
			for theIdMatch in titleMinDict[titleMinHere].split(';'):
				matchKey[theIdMatch] = 5
				if theId != theIdMatch:
					possibleMatch[theIdMatch] = 5
					basis[ExtractKeys.TITLE_MIN] = 5

	# Join matches
	match = basisOut = matchGroupOut = '.'
	if possibleMatch:
		
		match = ';'.join(possibleMatch.keys())
		basisOut = ';'.join([k.value for k in basis.keys()])

		matchKey[theId] = 5
		matchKeysAll = sorted(matchKey.keys())
		matchKeyJoinAll = ';'.join(matchKeysAll)
		if matchKeyJoinAll in matchGroup:
			matchGroupOut = matchGroup[matchKeyJoinAll]
		else:
			matchCountHere += 1
			matchGroup[matchKeyJoinAll] = matchCountHere
			matchGroupOut = matchGroup[matchKeyJoinAll]

	return match, basisOut, matchGroupOut, matchCountHere, matchGroup


# Try to work out subgroups based on Lichenstein distance
def subGroup(
		thisId, idList, medlineDict, embaseDict, scopusDict, firstDict,
		matchGroupOut, existingGroup, geneToSubgroup):
	"""

	Args:
		thisId (str): ID.
		idList (List[str]): List of IDs.
		medlineDict (dict[str, dict[str, str]]): Medline dict.
		embaseDict (dict[str, dict[str, str]]): Embase dict.
		scopusDict (dict[str, dict[str, str]]): SCOPUS dict.
		firstDict (dict[str, dict[str, str]]): First dict.
		matchGroupOut (str): Match group for output.
		existingGroup (List[str]): Existing groups.
		geneToSubgroup:

	Returns:
		ID dict.

	"""
	# Get a unique groupId
	groupNum = 1
	nextGroup = f'{matchGroupOut}.{groupNum}'
	while nextGroup in existingGroup:
		groupNum += 1
		nextGroup = f'{matchGroupOut}.{groupNum}'

	# Get identifiers for Id of interest
	pmidHere = authorKeyHere = titleMinHere = '.'
	if thisId.startswith('MED'):
		pmidHere = medlineDict[thisId]['pmid']
		authorKeyHere = medlineDict[thisId]['authorKey']
		titleMinHere = medlineDict[thisId]['titleMin']
	elif thisId.startswith('EMB'):
		pmidHere = embaseDict[thisId]['pmid']
		authorKeyHere = embaseDict[thisId]['authorKey']
		titleMinHere = embaseDict[thisId]['titleMin']
	elif thisId.startswith('SCO'):
		pmidHere = scopusDict[thisId]['pmid']
		authorKeyHere = scopusDict[thisId]['authorKey']
		titleMinHere = scopusDict[thisId]['titleMin']
	elif thisId.startswith('ONE'):
		pmidHere = firstDict[thisId]['pmid']
		authorKeyHere = firstDict[thisId]['authorKey']
		titleMinHere = firstDict[thisId]['titleMin']

	# Get identifiers for each matching Id
	idDist = '.'
	goodMatch = []
	badMatch = []
	for thatId in idList:
		if thatId != thisId:

			pmidMatch = authorKeyMatch = titleMinMatch = '.'
			if thatId.startswith('MED'):
				pmidMatch = medlineDict[thatId]['pmid']
				authorKeyMatch = medlineDict[thatId]['authorKey']
				titleMinMatch = medlineDict[thatId]['titleMin']
			elif thatId.startswith('EMB'):
				pmidMatch = embaseDict[thatId]['pmid']
				authorKeyMatch = embaseDict[thatId]['authorKey']
				titleMinMatch = embaseDict[thatId]['titleMin']
			elif thatId.startswith('SCO'):
				pmidMatch = scopusDict[thatId]['pmid']
				authorKeyMatch = scopusDict[thatId]['authorKey']
				titleMinMatch = scopusDict[thatId]['titleMin']
			elif thatId.startswith('ONE'):
				pmidMatch = firstDict[thatId]['pmid']
				authorKeyMatch = firstDict[thatId]['authorKey']
				titleMinMatch = firstDict[thatId]['titleMin']

			# Get the PMID distance, 0 to 100, with 0 the worst and 100 the
			# best; 9999 is unknown
			distanceOut = 9999
			if pmidHere == pmidMatch and pmidHere != 'NoPMID':
				distanceOut = 100
			elif pmidHere == 'NoPMID' or pmidMatch == 'NoPMID' :
				distanceOut = 9999
			else:
				distanceOut = 0

			# If no useful PMID matching
			if distanceOut == 9999:
				
				# 0 to 100, with 0 the worst and 100 the best
				authorKeyActualDiff = jellyfish.damerau_levenshtein_distance(
					authorKeyHere, authorKeyMatch)
				titleMinActualDiff = jellyfish.damerau_levenshtein_distance(
					titleMinHere, titleMinMatch)

				authorKeyDiff = 100 - min(authorKeyActualDiff, 100)
				titleMinDiff = 100 - min(titleMinActualDiff, 100)

				authorKeyDiffWeight = 100 - int(authorKeyActualDiff / (
						len(authorKeyHere) + len(authorKeyMatch)) * 100)
				titleMinDiffWeight = 100 - int(titleMinActualDiff / (
						len(titleMinHere) + len(titleMinMatch)) * 100)

				distance = min(authorKeyDiff, titleMinDiff)
				distanceWeight = min(authorKeyDiffWeight, titleMinDiffWeight)
				distanceOut = f'{distance}/{distanceWeight}'

			if idDist == '.':
				idDist = f'{thatId}({distanceOut})'
			else:
				idDist = f'{idDist};{thatId}({distanceOut})'

			# Find subgroups
			if distanceOut >= 100:
				# Same subgroup
				goodMatch.append(thatId) 
			if distanceOut <= 10:
				badMatch.append(thatId) 

	return idDist


def getSubgroupNum(matchGroupOut, groupNum):
	"""Get subgroup number

	Args:
		matchGroupOut (str): Matching group output.
		groupNum (int): Group number.

	Returns:
		Next group string, next group number.

	"""
	nextGroup = f'{matchGroupOut}.{groupNum}'
	groupNum += 1

	return nextGroup, groupNum


def subGroupV2(
		idList, dbDicts, matchGroupOut,
		idToGroup, idToSubgroup, subgroupToId, idToDistance):
	"""Try to work out subgroups based on Lichenstein distance.

	Args:
		idList (List[str]): List of IDs.
		dbDicts (List[dict[str, dict[str, str]]]): Sequence of database dicts.
		matchGroupOut (str): Match group for output.
		idToGroup (dict[str, str]): Dictionary group info.
		idToSubgroup (dict[str, str]): Dictionary mapping IDs to subgroups
		subgroupToId (dict[str, str]): Dictionary mapping subgroups to IDs.
		idToDistance (dict[str, str]): Dictionary mapping IDs to distance.

	Returns:
		``idToGroup``, ``idToSubgroup``, ``subgroupToId``, and ``idToDistance``.

	"""
	groupNum = 0
	idGroup = ';'.join(idList.keys())

	# Simplify data structure
	pDict = {}
	aDict = {}
	tDict = {}
	jDict = {}
	for idName in idList:
		idToGroup[idName] = idGroup
		for dbDict in dbDicts:
			if idName in dbDict:
				pDict[idName] = dbDict[idName][ExtractKeys.PMID]
				aDict[idName] = dbDict[idName][ExtractKeys.AUTHOR_KEY]
				tDict[idName] = dbDict[idName][ExtractKeys.TITLE_MIN]
				jDict[idName] = dbDict[idName][ExtractKeys.JOURNAL_KEY]
				break

	# Initialize the dictionary
	for idName in idList:
		idToDistance[idName] = {}

	# Find the distances
	for idNameOne in idList:
		pOne = pDict[idNameOne]
		aOne = aDict[idNameOne]
		tOne = tDict[idNameOne]
		jOne = jDict[idNameOne]

		for idNameTwo in idList:
			pTwo = pDict[idNameTwo]
			aTwo = aDict[idNameTwo]
			tTwo = tDict[idNameTwo]
			jTwo = jDict[idNameTwo]

			if (idNameTwo not in idToDistance[idNameOne]
					and idNameOne != idNameTwo):
				# Pmid distance
				distanceOut = 9999
				if pOne == pTwo and pOne != 'NoPMID':
					distanceOut = 100
				elif pOne == 'NoPMID' or pTwo == 'NoPMID':
					distanceOut = 9999
				else:
					distanceOut = 0

				# If no useful PMID matching
				if distanceOut == 9999:
					# print(f'{idNameOne} vs {idNameTwo}')

					# Find the title distance
					titleMinActualDiff = jellyfish.damerau_levenshtein_distance(
						tOne, tTwo)
					titleMinDiffWeight = 30 - int(titleMinActualDiff / (
							len(tOne) + len(tTwo)) * 30)

					# Find the journal distance
					journalKeyActualDiff = \
						jellyfish.damerau_levenshtein_distance(jOne, jTwo)
					journalKeyDiffWeight = 20 - int(journalKeyActualDiff / (
							len(jOne) + len(jTwo)) * 20)

					# Find the year distance
					aOneList = aOne.split('|')
					aOneYear = aOneList.pop()

					aTwoList = aTwo.split('|')
					aTwoYear = aTwoList.pop()

					yearDist = 0
					if aOneYear == aTwoYear:
						yearDist = 20
					elif aOneYear == 'NoYear' or aTwoYear == 'NoYear' \
							or aOneYear == '.' or aTwoYear == '.':
						yearDist = 0
					elif int(aOneYear) - 1 == int(aTwoYear) or \
							int(aOneYear) + 1 == int(aTwoYear):
						yearDist = 16
					elif int(aOneYear) - 2 == int(aTwoYear) or \
							int(aOneYear) + 2 == int(aTwoYear):
						yearDist = 12

					# Find the author distance
					authorDist = 0
					authorActualDiff = jellyfish.damerau_levenshtein_distance(
						''.join(aOneList), ''.join(aTwoList))
					# printv(authorActualDiff)
					if authorActualDiff <= 5:
						# If it's a close match use the combined distance
						authorDist = 30 - authorActualDiff
					else:
						# If not, split by the authors
						# printv(aOneList)
						authorUsed = {}
						factor = 30
						if len(aOneList) >= 2:
							factor = 30 / len(aOneList)
						for authorOne in aOneList:
							highestScore = 0
							authorMatch = ''
							for authorTwo in aTwoList:
								# print(f'{authorOne} vs {authorTwo}')
								
								# if authorTwo not in authorUsed:
								authorActualDiff = \
									jellyfish.damerau_levenshtein_distance(
										authorOne, authorTwo)
								authorKeyDiffWeight = factor - int(
									authorActualDiff /
									(len(authorOne) + len(authorTwo)) * factor)
								if authorKeyDiffWeight > highestScore:
									highestScore = authorKeyDiffWeight
									authorMatch = authorTwo

							authorUsed[authorMatch] = 5
							authorUsed[authorOne] = 5
							authorDist += highestScore
							# printv(highestScore)

					distanceOut = (
							titleMinDiffWeight + journalKeyDiffWeight
							+ yearDist + authorDist)
					
					# printv(titleMinDiffWeight)
					# printv(journalKeyDiffWeight)
					# printv(yearDist)
					# printv(authorDist)
					# printv(distanceOut)

				idToDistance[idNameOne][idNameTwo] = distanceOut
				idToDistance[idNameTwo][idNameOne] = distanceOut

	# Find the groups
	for idNameOne in idList:
		for idNameTwo in idList:
			# print(f'{idNameOne} vs {idNameTwo}')
			# printv(idToDistance[idNameOne][idNameTwo])
			if idNameOne == idNameTwo:
				# Same id
				next
			elif idNameOne in idToSubgroup and idNameTwo in idToSubgroup:
				# Already assigned
				next
			elif idToDistance[idNameOne][idNameTwo] >= 90:
				# Match
				if idNameOne in idToSubgroup:
					idToSubgroup[idNameTwo] = idToSubgroup[idNameOne]
					subgroupToId[nextGroup] = \
						f'{subgroupToId[nextGroup]};{idNameTwo}'
				elif idNameTwo in idToSubgroup:
					idToSubgroup[idNameOne] = idToSubgroup[idNameTwo]
					subgroupToId[nextGroup] = \
						f'{subgroupToId[nextGroup]};{idNameOne}'
				else:
					nextGroup, groupNum = getSubgroupNum(
						matchGroupOut, groupNum)
					# printv(groupNum)
					# printv(nextGroup)
					subgroupToId[nextGroup] = f'{idNameOne};{idNameTwo}'
					idToSubgroup[idNameOne] = nextGroup
					idToSubgroup[idNameTwo] = nextGroup
	
	# Assign remaing Ids to their own groups and get the output
	for idNameOne in idList:
		if idNameOne not in idToSubgroup:
			nextGroup, groupNum = getSubgroupNum(matchGroupOut, groupNum)
			idToSubgroup[idNameOne] = nextGroup
			subgroupToId[nextGroup] = f'{idNameOne}'

	return idToGroup, idToSubgroup, subgroupToId, idToDistance


def globalMatcher(
		idHere, pmid, authorKey, titleMin, globalPmidDict, globalauthorKeyDict,
		globaltitleMinDict, globalJournalKeyDict, journalKey):
	"""Find matches across all input files.

	Args:
		idHere (str): ID.
		pmid (str): PubMed ID.
		authorKey (str): Author key.
		titleMin (str): Title min.
		globalPmidDict (dict[str, str]): Pubmed ID dict.
		globalauthorKeyDict (dict[str, str]): Author key dict.
		globaltitleMinDict (dict[str, str]): Title min dict.
		globalJournalKeyDict (dict[str, str]): Journal key dict.
		journalKey (str): Journal key.

	Returns:
		``globalPmidDict``, ``globalauthorKeyDict``, ``globaltitleMinDict``,
		and ``globalJournalKeyDict``.

	"""
	# Record pmid matches
	if pmid in globalPmidDict:
		globalPmidDict[pmid] = f'{globalPmidDict[pmid]};{idHere}'
	else:
		globalPmidDict[pmid] = idHere

	# Record authorKey matches
	if authorKey in globalauthorKeyDict:
		globalauthorKeyDict[authorKey] = \
			f'{globalauthorKeyDict[authorKey]};{idHere}'
	else:
		globalauthorKeyDict[authorKey] = idHere

	# Record titleMin matches
	if titleMin in globaltitleMinDict:
		globaltitleMinDict[titleMin] = \
			f'{globaltitleMinDict[titleMin]};{idHere}'
	else:
		globaltitleMinDict[titleMin] = idHere

	# Record journalKey matches
	if journalKey in globalJournalKeyDict:
		globalJournalKeyDict[journalKey] = \
			f'{globalJournalKeyDict[journalKey]};{idHere}'
	else:
		globalJournalKeyDict[journalKey] = idHere

	return globalPmidDict, globalauthorKeyDict, globaltitleMinDict,\
		globalJournalKeyDict


def processDatabase(
		path, df, dbName, extractor, globalPmidDict, globalAuthorKeyDict,
		globalTitleMinDict, globalJournalKeyDict, headerMainId=None):
	"""Process a database records.

	Args:
		path (str): Path from which to construct the output path.
		df (:obj:`pd.DataFrame`): Data frame to process.
		dbName (str): Database name.
		extractor (func): Extractor specification dict.
		globalPmidDict (dict): Global dictionary of PubMed IDs.
		globalAuthorKeyDict (dict): Global dictionary of author keys.
		globalTitleMinDict (dict): Global dictionary of short titles.
		globalJournalKeyDict (dict): Global dictionary of journal keys.
		headerMainId (str): String for the main ID in the header; defaults
			to None, in which case the header will be constructed from
			``dbName``.

	Returns:
		dict[str, dict[:obj:`ExtractKeys`, str]], :obj:`pd.DataFrame`:
		Dictionary of processed database entries, where keys are database
		IDs, and values are dictionarys of extraction keys to processed
		strings. Data Frame of the processed file.

	"""
	print('\n#############################################################')
	print(f' Processing a {dbName} file')
	print('#############################################################\n')

	if not headerMainId:
		headerMainId = f'{dbName}_ID'

	procDict = {}

	# Process the file
	pmidDict = {}
	authorKeyDict = {}
	titleMinDict = {}
	journalKeyDict = {}
	for lineCount, row in enumerate(df.to_dict(orient="records")):
		# shift line count by 1 for 1-based indexing
		dbId = f'{dbName[:3].upper()}_{lineCount+1:05d}'
		extraction = dbExtract(row, extractor)

		# Store the info
		procDict[dbId] = extraction
		pmid = extraction[ExtractKeys.PMID]
		authorKey = extraction[ExtractKeys.AUTHOR_KEY]
		titleMin = extraction[ExtractKeys.TITLE_MIN]
		journalKey = extraction[ExtractKeys.JOURNAL_KEY]

		# Record pmid matches
		if pmid in pmidDict:
			pmidDict[pmid] = f'{pmidDict[pmid]};{dbId}'
		else:
			pmidDict[pmid] = dbId

		# Record authorKey matches
		if authorKey in authorKeyDict:
			authorKeyDict[authorKey] = \
				f'{authorKeyDict[authorKey]};{dbId}'
		else:
			authorKeyDict[authorKey] = dbId

		# Record titleMin matches
		if titleMin in titleMinDict:
			titleMinDict[titleMin] = f'{titleMinDict[titleMin]};{dbId}'
		else:
			titleMinDict[titleMin] = dbId

		# Record journalKey matches
		if journalKey in journalKeyDict:
			journalKeyDict[journalKey] = \
				f'{journalKeyDict[journalKey]};{dbId}'
		else:
			journalKeyDict[journalKey] = dbId

		# Record global matches
		globalPmidDict, globalAuthorKeyDict, globalTitleMinDict, \
			globalJournalKeyDict = globalMatcher(
				dbId, pmid, authorKey, titleMin, globalPmidDict,
				globalAuthorKeyDict, globalTitleMinDict,
				globalJournalKeyDict, journalKey)

	# Printout the file
	keyList = procDict.keys()
	matchCount = 0
	matchGroup = {}
	headerIds = None
	pubmedHeaders = None
	records = []
	for dbId in sorted(keyList):

		pmidHere = procDict[dbId][ExtractKeys.PMID]
		authorKeyHere = procDict[dbId][ExtractKeys.AUTHOR_KEY]
		titleMinHere = procDict[dbId][ExtractKeys.TITLE_MIN]
		match, basisOut, matchGroupOut, matchCount, matchGroup = \
			matchFinder(
				pmidHere, authorKeyHere, titleMinHere, pmidDict,
				authorKeyDict, titleMinDict, matchCount, dbId, matchGroup)

		# concatenate available IDs
		ids = (dbId, pmidHere, procDict[dbId][ExtractKeys.EMID])
		idsStr = [i for i in ids if i is not None]
		if headerIds is None:
			# construct headers based on available IDs
			pubmedHeaders = list(df.columns.values)
			headerIdKeys = [
				f'{headerMainId}', ExtractKeys.PMID.value.upper(),
				ExtractKeys.EMID.value.upper()]
			headerIds = [h for h, i in zip(headerIdKeys, ids) if i is not None]

		# add clean record
		record = OrderedDict()
		for header, idStr in zip(headerIds, idsStr):
			record[header] = idStr
		record['Author_Names'] = procDict[dbId][ExtractKeys.AUTHOR_NAMES]
		record['Year'] = procDict[dbId][ExtractKeys.YEAR]
		record['Author_Year_Key'] = authorKeyHere
		record['Title'] = procDict[dbId][ExtractKeys.TITLE]
		record['Title_Key'] = titleMinHere
		record['Journal_Details'] = procDict[dbId][ExtractKeys.JOURNAL]
		record['Journal_Key'] = procDict[dbId][ExtractKeys.JOURNAL_KEY]
		record['Similar_Records'] = match
		record['Similarity'] = basisOut
		record['Similar_group'] = matchGroupOut
		if pubmedHeaders:
			for header, val in zip(
					pubmedHeaders, procDict[dbId][ExtractKeys.ROW]):
				if header in record:
					header = f'{header}_orig'
				record[header] = val
		records.append(record)

	df_out = pd.DataFrame.from_records(records)
	return procDict, df_out


def findOverlaps(
		records, procDict, dbDicts, globalPmidDict, globalAuthorKeyDict,
		globalTitleMinDict, dbAbbr, matchGroupNew, idToGroup, idToSubgroup,
		subgroupToId, idToDistance, globalmatchCount):
	"""Find overlaps between processed database entries.

	Args:
		records (List[dict]): List of records, to which records from
			``procDict`` will be added.
		procDict (dict[str, dict[:obj:`ExtractKeys`, str]]): Processed
			database dict.
		dbDicts (dict[str, [dict[str, dict[str, str]]]]): Dictionary of
			database dicts.
		globalPmidDict:
		globalAuthorKeyDict:
		globalTitleMinDict:
		dbAbbr (str): Database string.
		matchGroupNew:
		idToGroup:
		idToSubgroup:
		subgroupToId:
		idToDistance:
		globalmatchCount (int): Global match count.

	Returns:
		int: Updated global match count.

	"""
	# set up counts per database
	dbAbbrs = [f'{tuple(d.keys())[0][:3]}' for d in dbDicts.values() if d]
	# TODO: temporarily include for comparison with prior output
	dbAbbrs.append('ONE')

	for medId in procDict:

		pmidHere = procDict[medId][ExtractKeys.PMID]
		authorKeyHere = procDict[medId][ExtractKeys.AUTHOR_KEY]
		titleMinHere = procDict[medId][ExtractKeys.TITLE_MIN]
		journalKey = procDict[medId][ExtractKeys.JOURNAL_KEY]

		if dbAbbr != 'MED' or medId not in idToSubgroup:
			matchKeyDict = {}
			basisDict = {}
			matchKeyDict, matchKeyDictLenLast, basisDict = \
				matchListMaker(
					pmidHere, authorKeyHere, titleMinHere, globalPmidDict,
					globalAuthorKeyDict, globalTitleMinDict, medId,
					matchKeyDict, basisDict)
			matchKeyDictLenNew = end = 0
			matchKeyList = '|'.join(matchKeyDict.keys())

			# Extend to all possible matches
			while end == 0:
				for extraId in matchKeyList.split('|'):
					# printv(extraId)
					pmidExtraId, authorKeyExtraId, titleMinExtraId = \
						getDetails(extraId, dbDicts.values())
					if extraId != medId:
						matchKeyDict, matchKeyDictLenNew, basisDict = \
							matchListMaker(
								pmidExtraId, authorKeyExtraId,
								titleMinExtraId, globalPmidDict,
								globalAuthorKeyDict, globalTitleMinDict,
								extraId, matchKeyDict, basisDict)
				if matchKeyDictLenLast == matchKeyDictLenNew:
					end = 1
				else:
					matchKeyDictLenLast = matchKeyDictLenNew
					matchKeyList = '|'.join(matchKeyDict.keys())

			# Work out groups
			match, basisOut, matchGroupOut, globalmatchCount, \
				matchGroupNew = findGroups(
					medId, matchKeyDict, basisDict, globalmatchCount,
					matchGroupNew)

			# Work out subgroups
			if match != '.':
				idToGroup, idToSubgroup, subgroupToId, idToDistance = \
					subGroupV2(
						matchKeyDict, dbDicts.values(),
						matchGroupOut, idToGroup,
						idToSubgroup, subgroupToId, idToDistance)
			else:
				idToSubgroup[medId] = '.'
				idToGroup[medId] = '.'

		# Assess subgroup status
		matchSubGroupOut = idToSubgroup[medId]
		matchSub = '.'
		for idName in subgroupToId[matchSubGroupOut].split(';'):
			if idName != medId and idName != '':
				if matchSub == '.':
					matchSub = f'{idName}({idToDistance[medId][idName]})'
				else:
					matchSub = \
						f'{matchSub};{idName}' \
						f'({idToDistance[medId][idName]})'

		# convert x.y (group.subgroup) to separate fields, defaulting to a
		# zero string for subgrounp
		group, sub = matchSubGroupOut.split('.')
		group = int(group) if group else None
		if not sub:
			sub = '0'

		# Assess group status
		match = '.'
		for idName in idToGroup[medId].split(';'):
			if idName != medId and idName != '.':
				if match == '.':
					match = f'{idName}({idToDistance[medId][idName]})'
				else:
					match = \
						f'{match};{idName}' \
						f'({idToDistance[medId][idName]})'

		# Assess contributors
		stats = OrderedDict.fromkeys(dbAbbrs, 0)
		papersInGroup = 0
		for key in stats.keys():
			# count occurrences of DB entry
			stats[key] = matchSub.count(key)
			if key == dbAbbr:
				# add one for the given database
				stats[key] += 1
			papersInGroup += stats[key]

		# record is "main" if the sub-group matches do not include records
		# from any previously processed databases
		mainRecord = 'Y'
		for key in dbAbbrs:
			if key == dbAbbr:
				break
			if key in matchSub:
				mainRecord = 'N'

		# add clean record
		record = OrderedDict((
			('Paper_ID', medId),
			('PMID', pmidHere),
			('Group', group),
			('Subgrp', sub),
			('Grp_Size', papersInGroup),
			('Author_Names', procDict[medId][ExtractKeys.AUTHOR_NAMES]),
			('Year', procDict[medId][ExtractKeys.YEAR]),
			('Author_Year_Key', authorKeyHere),
			('Title', procDict[medId][ExtractKeys.TITLE]),
			('Title_Key', titleMinHere),
			('Journal_Details', procDict[medId][ExtractKeys.JOURNAL]),
			('Journal_Key', journalKey),
			('Similar_Records', match),
			('Similarity', matchSub),
		))
		dbDictsNames = list(dbDicts.keys())
		dbDictsNames.append('First')
		for name, val in zip(dbDictsNames, stats.values()):
			record[name] = str(val)
		record['MainRecord'] = mainRecord
		records.append(record)
	return globalmatchCount


def parseArgs():
	"""Parse arguments."""
	parser = argparse.ArgumentParser(
		description=
		'Find overlaps between articles downloaded from Medline, Embase, '
		'and Scopus')
	parser.add_argument('-m', '--medline', type=str, help='Medline CSV file')
	parser.add_argument('-e', '--embase', type=str, help='Embase CSV file')
	parser.add_argument('-s', '--scopus', type=str, help='Scopus CSV file')
	parser.add_argument(
		'-f', '--first', type=str, help='Initial search CSV file')
	parser.add_argument(
		'-o', '--out', type=str, help='Name and location of the output file')
	parser.add_argument(
		'-d', '--debug', action='store_true', help='Debugging function')
	args = parser.parse_args()
	paths = []
	outputFileName = None
	if args.medline:
		paths.append(args.medline)
	if args.embase:
		paths.append(args.embase)
	if args.scopus:
		paths.append(args.scopus)
	if args.out:
		outputFileName = args.out
	return paths, outputFileName


def main(paths, outputFileName=None):
	"""Extract database TSV files into dicts and find citation overlaps.

	Args:
		paths (List[str]): Input file paths.
		outputFileName (str): Name of output file; defaults to None to use
			a default name.

	Returns:
		:obj:`pd.DataFrame`: Combined citations with overlaps as a data frame.

	"""
	# assume that paths are ordered by arg parser
	dbExtractor = DbExtractor('\t')
	for path in paths:
		try:
			dbExtractor.extractDb(path)
		except (FileNotFoundError, SyntaxError) as e:
			print(e)
	dbExtractor.combineOverlaps()
	dbExtractor.exportDataFrames(
		outputFileName if outputFileName else dbExtractor.DEFAULT_OVERLAPS_PATH)


if __name__ == "__main__":
	main(*parseArgs())
