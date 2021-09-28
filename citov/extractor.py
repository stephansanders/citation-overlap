"""Citation list extractor for the Citation-Overlap tool."""

import argparse
from collections import OrderedDict
from enum import Enum
import glob
import logging
import os
import pathlib
from typing import List

import sys

import pandas as pd

from citov import config, logs, overlapper, utils
from citov.parser import ExtractKeys, JointKeyExtractor, parseEntry

#: :class:`logging.Logger`: Logger for this module.
_logger = logging.getLogger().getChild(__name__)


class DbNames(Enum):
	"""Names of databases with extractors."""
	MEDLINE = 'Medline'
	EMBASE = 'Embase'
	SCOPUS = 'Scopus'


class DefaultExtractors(Enum):
	"""Default extractor filenames Enumeration."""
	MEDLINE = 'MEDLINE.yml'
	EMBASE = 'Embase.yml'
	SCOPUS = 'Scopus.yml'


class DbExtractor(overlapper.DbMatcher):
	"""Perform database extractions and store results for overlap detection.

	Attributes:
		saveSep (str): Separator/delimiter to use when exporting data frames;
			defaults to None to not export.
		dfsParsed (OrderedDict): Dictionary of database names to
			parsed database data frames; defaults to an empty dictionary.
		dfOverlaps (:obj:`pd.DataFrame`): Data frame of databases processed
			for overlaps; defaults to None.

	"""
	#: Default overlaps file output filename.
	DEFAULT_OVERLAPS_PATH: str = 'overlapped'
	#: Default folder name for cleaned citation lists.
	DEFAULT_CLEANED_DIR_PATH: str = 'cleaned'

	_YAML_MATCHER = {
		'ExtractKeys': ExtractKeys,
		'JointKeyExtractor': JointKeyExtractor,
	}

	def __init__(self, saveSep=None):
		super().__init__()
		self.saveSep = saveSep

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
			pmidHere: (pmidDict, ('NoPMID',), ExtractKeys.PMID),
			authorKeyHere: (authorKeyDict, ('.',), ExtractKeys.AUTHOR_KEY),
			titleMinHere: (titleMinDict, ('.',), ExtractKeys.TITLE_MIN),
		}

		DbExtractor.makeMatches(dbDicts, theId, matchKey, basis, possibleMatch)

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
			# part of the path filename, case-insensitive
			pathDbSplit = os.path.splitext(os.path.basename(
				path))[0].lower().split('_')
			for extractor_dir in config.extractor_dirs:
				# get all files in the given extractor directory
				extractorPaths = glob.glob(str(extractor_dir / '*'))
				for extrPath in extractorPaths:
					# search for case-insensitive match between YAML filenames
					# and citation files
					extrBase, extrExt = os.path.splitext(os.path.basename(
						extrPath).lower())
					if pathDbSplit[0] == extrBase and extrExt in (
							'.yml', '.yaml'):
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
					df = utils.mergeCsvs(path)
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

		dbOverlapper = overlapper.DbOverlapper(self.dbsParsed)
		for dbName, dbDict in self.dbsParsed.items():
			# find overlaps among parsed dicts
			globalmatchCount = dbOverlapper.findOverlaps(
				records, dbDict, dbName[:3].upper(), matchGroupNew, idToGroup,
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

	def exportDataFrames(self, overlapsOutPath: str) -> List[str]:
		"""Export parsed database and overlaps data frames to a directory.

		Args:
			overlapsOutPath: Path to export file. Parents directories which
				will be created if necessary.

		Returns:
			List of output messages.

		"""
		outDirCleaned = os.path.join(
			os.path.dirname(overlapsOutPath), self.DEFAULT_CLEANED_DIR_PATH)
		os.makedirs(outDirCleaned, exist_ok=True)
		msgs = []
		for dbName, df in self.dfsParsed.items():
			msgs.append(self._saveDataFrame(
				df, os.path.join(outDirCleaned, dbName), '_clean')[0])
		if self.dfOverlaps is not None:
			msgs.append(self._saveDataFrame(
				self.dfOverlaps, overlapsOutPath)[0])
		return msgs


def _combine_spreadsheets(paths, outputFileName=None):
	"""Combine spreadsheet files into a single, merged file.
	
	Args:
		paths (list[str]): List of paths to combine.
		outputFileName (str): Path to output combined file; defaults to None
			to use a location based on the first path in ``paths``.

	Returns:
		:class:`pandas.DataFrame`: The combined data frame.

	"""
	nPaths = len(paths)
	if nPaths < 1:
		# no paths to combine
		return
	
	out_path = outputFileName
	if not out_path:
		# make default path
		out_path = pathlib.Path(paths[0])
		out_path = out_path.parent / \
			f'{out_path.stem}_combined{out_path.suffix}'
	
	if nPaths == 1:
		# extract single path if only one given
		paths = paths[0]
	
	# merge files
	return utils.mergeCsvs(paths, out_path)


def parseArgs():
	"""Parse arguments."""
	parser = argparse.ArgumentParser(
		description=
		'Find overlaps between articles downloaded from Medline, Embase, '
		'and Scopus')
	parser.add_argument(
		'cit_lists', nargs="*", help='Citation lists auto-detected by filename')
	parser.add_argument(
		'-m', '--medline', nargs="*", type=str, help='Medline CSV/TSV file')
	parser.add_argument(
		'-e', '--embase', nargs="*", type=str, help='Embase CSV/TSV file')
	parser.add_argument(
		'-s', '--scopus', nargs="*", type=str, help='Scopus CSV/TSV file')
	parser.add_argument(
		'-o', '--out', type=str, help='Name and location of the output file')
	parser.add_argument(
		'-x', '--extractors', nargs="*",
		help='Folder path(s) of additional extractors')
	parser.add_argument(
		'-c', '--combine', nargs="*",
		help=(
			'CSV/TSV file path(s) to combine. Can be given as a single '
			'folder, in which case its entire contents will be combined.'))
	parser.add_argument(
		'-v', '--verbose', action='store_true', help='Verbose logging')
	args, args_unknown = parser.parse_known_args()
	
	if args.verbose:
		# turn on verbose mode
		logs.update_log_level(logging.getLogger(), logging.DEBUG)
		_logger.debug('Turned on verbose mode with debug logging')
	
	# parse input paths to the appropriate database extractor
	paths = dict.fromkeys(DefaultExtractors, None)
	outputFileName = None
	if args.cit_lists:
		# paths given without a parameter are auto-detected
		paths['auto'] = args.cit_lists
		_logger.info(
			f'Set citation lists for auto-detection by filename: '
			f'{args.cit_lists}')
	if args.medline:
		paths[DefaultExtractors.MEDLINE] = args.medline
		_logger.info(f'Set Medline citation lists: {args.medline}')
	if args.embase:
		paths[DefaultExtractors.EMBASE] = args.embase
		_logger.info(f'Set Embase citation lists: {args.embase}')
	if args.scopus:
		paths[DefaultExtractors.SCOPUS] = args.scopus
		_logger.info(f'Set Scopus citation lists: {args.scopus}')

	if args.extractors:
		# add additional extractor directories
		config.extractor_dirs.extend([pathlib.Path(p) for p in args.extractors])

	if args.out:
		# parse output file path
		outputFileName = args.out
		_logger.info(f'Set output path: {outputFileName}')

	if args.combine:
		# combine files along rows
		_logger.info(f'Combining citation lists and exiting: {args.combine}')
		_combine_spreadsheets(args.combine, outputFileName)
		sys.exit()
	
	# notify user of full args list, including unrecognized args
	_logger.debug(f"All command-line arguments: {sys.argv}")
	if args_unknown:
		_logger.info(
			f"The following command-line arguments were unrecognized and "
			f"ignored: {args_unknown}")
	
	return paths, outputFileName


def main(paths, outputFileName=None):
	"""Extract database TSV files into dicts and find citation overlaps.

	Args:
		paths (dict[Any, str]): Dictionary of extractor Enums from
			:class:`DefaultExtractors` to input file paths. Any key not
			in this Enum class is treated as paths for auto-detection.
		outputFileName (str): Name of output file; defaults to None to use
			a default name.

	Returns:
		:class:`pandas.DataFrame`: Combined citations with overlaps as a data
		frame.

	"""
	# assume that paths are ordered by arg parser
	dbExtractor = DbExtractor('\t')
	for extract, paths in paths.items():
		if paths is None:
			continue
		extractorPath = None  # auto-detect extractor
		if extract in DefaultExtractors:
			# use extractor specified by key
			extractorPath = config.extractor_dirs[0] / extract.value
		for path in paths:
			try:
				# extract citation list with the given extractor
				dbExtractor.extractDb(path, extractorPath)
			except (FileNotFoundError, SyntaxError) as e:
				print(e)
	
	# find overlaps and export merged and filtered tables
	dbExtractor.combineOverlaps()
	dbExtractor.exportDataFrames(
		outputFileName if outputFileName else dbExtractor.DEFAULT_OVERLAPS_PATH)


if __name__ == "__main__":
	main(*parseArgs())
