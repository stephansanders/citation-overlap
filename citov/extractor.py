"""Citation list extractor for the Citation-Overlap tool."""

from collections import OrderedDict
from enum import Enum
import glob
import logging
import os

import pandas as pd

from citov import config, overlapper, utils
from citov.parser import ExtractKeys, JointKeyExtractor, parseEntry

#: :class:`logging.Logger`: Logger for this module.
_logger = logging.getLogger().getChild(__name__)


class DbNames(Enum):
	"""Names of databases with extractors."""
	MEDLINE = 'Medline'
	EMBASE = 'Embase'
	SCOPUS = 'Scopus'


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
	
	@staticmethod
	def _matchFinder(
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
			match, basis out, match group out, and match count.

		"""
		possibleMatch = {}
		basis = {}
		matchKey = {}

		dbDicts = {
			pmidHere: (pmidDict, 'NoPMID', ExtractKeys.PMID),
			authorKeyHere: (authorKeyDict, '.', ExtractKeys.AUTHOR_KEY),
			titleMinHere: (titleMinDict, '.', ExtractKeys.TITLE_MIN),
		}

		for key, val in dbDicts.items():
			# identify matches for the given metadata
			if key != val[1]:
				dbDict = val[0]
				if ';' in dbDict[key]:
					for theIdMatch in dbDict[key].split(';'):
						matchKey[theIdMatch] = 5
						if theId != theIdMatch:
							possibleMatch[theIdMatch] = 5
							basis[val[2]] = 5

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

		return match, basisOut, matchGroupOut, matchCountHere

	def processDatabase(self, df, dbName, extractor, headerMainId=None):
		"""Process a database records.

		Args:
			df (:obj:`pd.DataFrame`): Data frame to process.
			dbName (str): Database name.
			extractor (func): Extractor specification dict.
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
			dbId = f'{dbName[:3].upper()}_{lineCount + 1:05d}'
			extraction = parseEntry(row, extractor)

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
			dbDicts = {
				pmid: self.globalPmidDict,
				authorKey: self.globalAuthorKeyDict,
				titleMin: self.globalTitleMinDict,
				journalKey: self.globalJournalKeyDict
			}
			for key, dbDict in dbDicts.items():
				dbDict[key] = f'{dbDict[key]};{dbId}' if key in dbDict else dbId

		# Print out the file
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
			match, basisOut, matchGroupOut, matchCount = self._matchFinder(
				pmidHere, authorKeyHere, titleMinHere, pmidDict, authorKeyDict,
				titleMinDict, matchCount, dbId, matchGroup)

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
			extractor = utils.load_yaml(extractorPath, self._YAML_MATCHER)[0]
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
			self.dbsParsed[dbName], df_out = self.processDatabase(
				df, dbName, extractor, headerMainId)
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
