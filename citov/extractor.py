"""Citation list extractor for the Citation-Overlap tool."""

from collections import OrderedDict
from enum import Enum
import glob
import logging
import os
import re
import string

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
			self.dbsParsed[dbName], df_out = processDatabase(
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


def _parseYear(row, key=None, search=None):
	"""Get the year from a row.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Column name; defaults to None. If given, ``search`` will
			be ignored.
		search (dict[str, Any]): Dictionary of ``row`` columns in which to
			search with the given regex patterns to extract the year. Each
			pattern may be a sequence of patterns to try for the given column.
			The first match will be returned.

	Returns:
		str: Year, or "NoYear" if no year is found.

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
				if not utils.is_seq(val):
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


def _parseID(row, key, search=None, default='NoPMID'):
	"""Get the ID.

	Args:
		row (dict[str, str]): A row as a dictionary.
		key (str): Key in ``row`` for the ID.
		search (str): Regex search pattern to extract the ID; defaults to None.
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
	_logger.debug('No ID found: %s', pmidField)
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
	if utils.is_seq(pmid_arg):
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
		df, dbName, extractor, globalPmidDict, globalAuthorKeyDict,
		globalTitleMinDict, globalJournalKeyDict, headerMainId=None):
	"""Process a database records.

	Args:
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
