# Description: Process Embase and Pubmed search results and find matches
# Usage: python3 medline_embase_scopus.py -m pubmed_result.csv -e embase_noTitle.csv -s scopus_all.csv
# Author: Stephan Sanders

import csv # CSV files
import os # OS interfaces
import sys
import re # regex
import string # string manipulation
import argparse # arguments parser
import jellyfish # string comparison # pip3 install jellyfish
import hdbscan # pip3 install hdbscan

# How to perform the search

# Pubmed
# Need to use the old version as new one lacks the file download https://www.ncbi.nlm.nih.gov/pubmed/
# Perform search, e.g. (PDD OR ASD OR autism*) AND (biomarker* OR marker* OR endophenotype*)
# Click 'Send To', Select 'File', Select 'CSV'

# Embase; behind a paywall
# Emtree term - exploded: (biological marker OR endophenotype OR marker) AND (autism); 
# Language of article: english
# Records added to Embase (including end date): 01-01-1900 to 29-02-2020
# Select all records
# Click 'Export', for Choose a format: select 'CSV - Fields by Column', for Choose an output: select 'Full Record', do not tick 'Include search query in export'

# Scopus
# TITLE-ABS-KEY ( ( pdd  OR  asd  OR  autism* )  AND  ( biomarker*  OR  marker*  OR  endophenotype* ) )  AND  ( LIMIT-TO ( LANGUAGE ,  "English" ) )  AND  ( LIMIT-TO ( DOCTYPE ,  "ar" ) )  AND  ( LIMIT-TO ( SRCTYPE ,  "j" ) ) 
# Can only download 2000 at a time in CSV format. Use "Limit to" in the filters to the left to select groups of ≤2,000, e.g. by year
# Click arrow next to 'All' above the column headings and below 'Analyze search results'; click 'Select all'
# Click 'Export'
# Select 'CSV Export' 
# Add PubMed ID (you may want to add Abstract too)
# Click Export
# Combine the lists in a text editor or Google Sheet, not in Excel


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


def _parseYear(row, search):
	"""Get the year from a row.

	Args:
		row (dict[str, str]): Dictionary from a row.
		search (dict[str, Any]): Dictionary of ``row`` columns
			to regex search patterns to extract the year. Each pattern may
			be a sequence of patterns to try for the given column.

	Returns:
		str: Year.

	"""
	for key, val in search.items():
		shortDet = row.get(key)
		if shortDet is not None:
			if not isinstance(val, (tuple, list)):
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


def _parseID(row, key, search, warn=True, default='NoPMID'):
	"""Get the ID.

	Args:
		row (dict[str, str]): Dictionary from a row.
		key (str): Author names key in ``row``.
		search (str): Regex search pattern.
		warn (bool): True to warn if ID is not found; defaults to True.
		default (str): Default ID if ID is not found.

	Returns:
		str: ID.

	"""
	pmidField = row.get(key)
	if pmidField is not None:
		pmidMatch = re.search(search, pmidField)
		if pmidMatch:
			return pmidMatch.group(1)
	if warn:
		print('ERR: No ID found:' + pmidField)
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


def _rowToTabDelimStr(row):
	"""Convert a row to a tab-delimited string

	Args:
		row (dict[str, str]): Dictionary from a row.

	Returns:
		str: Tab-delimited string.

	"""
	rowOut = []
	rowLen = len(row)
	for i, field in enumerate(row):
		if i < rowLen - 1 or str(row[field]) == '["]':
			# skip last field if not brackets of empty quotes
			rowOut.append(str(row[field]))
	return '\t'.join(rowOut)


def medlineExtract(row):
	"""Extract key info from Medline.

	Args:
		row (dict[str, str]): Dictionary from a row.

	Returns:
		PubMed ID, author names, author key, title, title min, year, journal,
		journal key, full row.

	"""
	year = _parseYear(row, {'ShortDetails': (r'.\s+(\d{4})$', r'(\d{4})$')})
	authorNames, authorKey = _parseAuthorNames(row, 'Description', year)
	pmid = _parseID(row, 'Identifiers', r'PMID:(\d+)')
	title, titleMin = _parseTitle(row, 'Title')
	journal, journalKey = _parseJournal(row, 'Details')
	fullRow = _rowToTabDelimStr(row)

	return pmid, authorNames, authorKey, title, titleMin, year, journal, \
		journalKey, fullRow


def embaseExtract(row):
	"""Extract key info from Embase.

	Args:
		row (dict[str, str]): Dictionary from a row.

	Returns:
		PubMed ID, Embase ID author names, author key, title, title min,
		year, journal, journal key, full row.

	"""
	year = _parseYear(row, {
		'Date of Publication': r'(19\d{2}|20\d{2})',
		'Source': r'(19\d{2}|20\d{2})',
	})
	authorNames, authorKey = _parseAuthorNames(row, 'Author Names', year)
	pmid = _parseID(row, 'Medline PMID', r'(\d+)', warn=False)
	emid = _parseID(
		row, 'Embase Accession ID', r'(\d+)', warn=False, default='NoEMID')
	title, titleMin = _parseTitle(row, '\ufeff"Title"')
	journal, journalKey = _parseJournal(row, 'Source')
	fullRow = _rowToTabDelimStr(row)

	return pmid, emid, authorNames, authorKey, title, titleMin, year, \
		journal, journalKey, fullRow


def scopusExtract(row):
	"""Extract key info from Medline.

	Args:
		row (dict[str, str]): Dictionary from a row.

	Returns:
		PubMed ID, author names, author key, title, title min, year, journal,
		journal key, full row.

	"""
	year = _parseYear(row, {'Year': r'(19\d{2}|20\d{2})'})
	authorNames, authorKey = _parseAuthorNames(row, '\ufeffAuthors', year)
	pmid = _parseID(row, 'PubMed ID', r'(\d+)', warn=False)
	title, titleMin = _parseTitle(row, 'Title')
	key = 'Source title'
	_, journalKey = _parseJournal(row, key)

	# parses journal based on individual columns
	journal = f'{row[key]} {year};'
	if row['Volume']:
		journal = f'{journal}{row["Volume"]}'
	if row['Issue']:
		journal = f'{journal}({row["Issue"]})'
	if row['Art. No.']:
		journal = f'{journal}:{row["Art. No."]}'
	elif row['Page start'] and row["Page end"]:
		journal = f'{journal}:{row["Page start"]}-{row["Page end"]}'
	if row['DOI']:
		journal = f'{journal}. doi: {row["DOI"]}'

	fullRow = _rowToTabDelimStr(row)

	return pmid, authorNames, authorKey, title, titleMin, year, \
		journal, journalKey, fullRow


def fileNamer(inputFile):
	"""Get the clean version output file name.

	Args:
		inputFile (str): Input filename.

	Returns:
		str: Formatted filename.

	"""
	inputFileBits = inputFile.split('.')
	inputFileBits.pop() # remove extension
	inputFileBase = '.'.join(inputFileBits)
	cleaninputFileName = f'{inputFileBase}_clean.tsv'
	return cleaninputFileName


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
					basisDict['PMID'] = 5

	# Look for authorKey matches
	if authorKeyHere != '.':
		if ';' in authorKeyDict[authorKeyHere]:
			for theIdMatch in authorKeyDict[authorKeyHere].split(';'):
				matchKeyDict[theIdMatch] = 5
				if theId != theIdMatch:
					basisDict['authorKey'] = 5

	# Look for titleMin matches
	if titleMinHere != '.':
		if ';' in titleMinDict[titleMinHere]:
			for theIdMatch in titleMinDict[titleMinHere].split(';'):
				matchKeyDict[theIdMatch] = 5
				if theId != theIdMatch:
					basisDict['titleMin'] = 5

	return matchKeyDict, len(matchKeyDict), basisDict


def getDetails(extraId, medlineDict, embaseDict, scopusDict):
	"""Get PMID, authorKey and TitleMin for a given ID.

	Args:
		extraId (str): Extra ID.
		medlineDict (dict[str, dict[str, str]]): Medline dict.
		embaseDict (dict[str, dict[str, str]]): Embase dict.
		scopusDict (dict[str, dict[str, str]]): SCOPUS dict.

	Returns:
		PMID, authorKey and TitleMin.

	"""
	pmidExtraId = authorKeyExtraId = titleMinExtraId = '.'
	if extraId.startswith('MED'):
		pmidExtraId = medlineDict[extraId]['pmid']
		authorKeyExtraId = medlineDict[extraId]['authorKey']
		titleMinExtraId = medlineDict[extraId]['titleMin']
	elif extraId.startswith('EMB'):
		pmidExtraId = embaseDict[extraId]['pmid']
		authorKeyExtraId = embaseDict[extraId]['authorKey']
		titleMinExtraId = embaseDict[extraId]['titleMin']
	elif extraId.startswith('SCO'):
		pmidExtraId = scopusDict[extraId]['pmid']
		authorKeyExtraId = scopusDict[extraId]['authorKey']
		titleMinExtraId = scopusDict[extraId]['titleMin']

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
		basisOut = ';'.join(basisDict.keys())

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
					basis['PMID'] = 5

	# Look for authorKey matches
	if authorKeyHere != '.':
		if ';' in authorKeyDict[authorKeyHere]:
			for theIdMatch in authorKeyDict[authorKeyHere].split(';'):
				matchKey[theIdMatch] = 5
				if theId != theIdMatch:
					possibleMatch[theIdMatch] = 5
					basis['authorKey'] = 5

	# Look for titleMin matches
	if titleMinHere != '.':
		if ';' in titleMinDict[titleMinHere]:
			for theIdMatch in titleMinDict[titleMinHere].split(';'):
				matchKey[theIdMatch] = 5
				if theId != theIdMatch:
					possibleMatch[theIdMatch] = 5
					basis['titleMin'] = 5

	# Join matches
	match = basisOut = matchGroupOut = '.'
	if possibleMatch:
		
		match = ';'.join(possibleMatch.keys())
		basisOut = ';'.join(basis.keys())

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
		idList, medlineDict, embaseDict, scopusDict, matchGroupOut,
		idToGroup, idToSubgroup, subgroupToId, idToDistance):
	"""Try to work out subgroups based on Lichenstein distance.

	Args:
		idList (List[str]): List of IDs.
		medlineDict (dict[str, dict[str, str]]): Medline dict.
		embaseDict (dict[str, dict[str, str]]): Embase dict.
		scopusDict (dict[str, dict[str, str]]): SCOPUS dict.
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
		if idName.startswith('MED'):
			pDict[idName] = medlineDict[idName]['pmid']
			aDict[idName] = medlineDict[idName]['authorKey']
			tDict[idName] = medlineDict[idName]['titleMin']
			jDict[idName] = medlineDict[idName]['journalKey']
		elif idName.startswith('EMB'):
			pDict[idName] = embaseDict[idName]['pmid']
			aDict[idName] = embaseDict[idName]['authorKey']
			tDict[idName] = embaseDict[idName]['titleMin']
			jDict[idName] = embaseDict[idName]['journalKey']
		elif idName.startswith('SCO'):
			pDict[idName] = scopusDict[idName]['pmid']
			aDict[idName] = scopusDict[idName]['authorKey']
			tDict[idName] = scopusDict[idName]['titleMin']
			jDict[idName] = scopusDict[idName]['journalKey']

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
				elif pOne == 'NoPMID' or pTwo == 'NoPMID' :
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


def main():
	"""Parse arguments and find citation overlaps."""
	parser = argparse.ArgumentParser(
		description=
		'Find overlaps between articles downloaded from Medline, Embase, '
		'and Scopus')
	parser.add_argument('-m', '--medline', type=str, help='Medline CSV file')
	parser.add_argument('-e', '--embase', type=str, help='Embase CSV file')
	parser.add_argument('-s', '--scopus', type=str, help='Scopus CSV file')
	parser.add_argument('-f', '--first', type=str, help='Initial search CSV file')
	parser.add_argument(
		'-o', '--out', type=str, help='Name and location of the output file')
	parser.add_argument(
		'-d', '--debug', action='store_true', help='Debugging function')
	args = parser.parse_args()
	
	# Key variables and output file
	globalPmidDict = {}
	globalAuthorKeyDict = {}
	globalTitleMinDict = {}
	globalJournalKeyDict = {}
	globalmatchCount = 0
	outputFileName = 'medline_embase_scopus_combo.tsv'
	if args.out:
		outputFileName = args.out
	allOut = open(outputFileName, 'w')
	allOut.write(
		f'Paper_ID\tPMID\tAuthor_Names\tYear\tAuthor_Year_Key\tTitle'
		f'\tTitle_Key\t')
	allOut.write(
		f'Journal_Details\tJournal_Key\tSimilar_Records\tSimilarity\tGroup'
		f'\tPapers_In_Group\tMedline\tEmbase\tScopus\tFirst\tMainRecord\n')
	
	# Process medline file
	medlineDict = {}
	if args.medline:
	
		print('\n#############################################################')
		print(' Processing a Medline file')
		print('#############################################################\n')
	
		cleanFileName = fileNamer(args.medline)
		pubOut = open(cleanFileName, 'w')
	
		# Process the file
		pmidDict = {}
		authorKeyDict = {}
		titleMinDict = {}
		journalKeyDict = {}
		with open(args.medline, encoding="utf8") as csvfile:
	
			pubmedCsv = csv.DictReader(csvfile, delimiter=',', quotechar='"',)
			pubmedHeaders = list(pubmedCsv.fieldnames)
			pubmedColCount = len(pubmedHeaders)
			pubmedHeadersOut = '\t'.join(pubmedHeaders)
			pubOut.write(
				f'Medline_ID\tPMID\tAuthor_Names\tYear\tAuthor_Year_Key\tTitle'
				f'\tTitle_Key\t')
			pubOut.write(
				f'Journal_Details\tJournal_Key\tSimilar_Records\tSimilarity'
				f'\tSimilar_group\t{pubmedHeadersOut}\n')
	
			lineCount = 0
			for row in pubmedCsv:
				lineCount += 1
				medId = 'MED_'+'{:05d}'.format(lineCount)
				pmid, authorNames, authorKey, title, titleMin, year, journal, \
					journalKey, fullRow = medlineExtract(row)
				
				# Store the info
				medlineDict[medId] = {}
				medlineDict[medId]['row'] = fullRow
				medlineDict[medId]['pmid'] = pmid
				medlineDict[medId]['authorNames'] = authorNames
				medlineDict[medId]['authorKey'] = authorKey
				medlineDict[medId]['title'] = title
				medlineDict[medId]['titleMin'] = titleMin
				medlineDict[medId]['year'] = year
				medlineDict[medId]['journal'] = journal
				medlineDict[medId]['journalKey'] = journalKey
	
				# Record pmid matches
				if pmid in pmidDict:
					pmidDict[pmid] = f'{pmidDict[pmid]};{medId}'
				else:
					pmidDict[pmid] = medId
	
				# Record authorKey matches
				if authorKey in authorKeyDict:
					authorKeyDict[authorKey] = \
						f'{authorKeyDict[authorKey]};{medId}'
				else:
					authorKeyDict[authorKey] = medId
	
				# Record titleMin matches
				if titleMin in titleMinDict:
					titleMinDict[titleMin] = f'{titleMinDict[titleMin]};{medId}'
				else:
					titleMinDict[titleMin] = medId
	
				# Record journalKey matches
				if journalKey in journalKeyDict:
					journalKeyDict[journalKey] = \
						f'{journalKeyDict[journalKey]};{medId}'
				else:
					journalKeyDict[journalKey] = medId
	
				# Record global matches
				globalPmidDict, globalAuthorKeyDict, globalTitleMinDict, \
					globalJournalKeyDict = globalMatcher(
						medId, pmid, authorKey, titleMin, globalPmidDict,
						globalAuthorKeyDict, globalTitleMinDict,
						globalJournalKeyDict, journalKey)
	
		# Printout the file
		keyList = medlineDict.keys()
		matchCount = 0
		matchGroup = {}
		for medId in sorted (keyList):
			
			pmidHere = medlineDict[medId]['pmid']
			authorKeyHere = medlineDict[medId]['authorKey']
			titleMinHere = medlineDict[medId]['titleMin']
			match, basisOut, matchGroupOut, matchCount, matchGroup = \
				matchFinder(
					pmidHere, authorKeyHere, titleMinHere, pmidDict,
					authorKeyDict, titleMinDict, matchCount, medId, matchGroup)
	
			# Print out clean version
			pubOut.write(
				f'{medId}\t{pmidHere}\t{medlineDict[medId]["authorNames"]}'
				f'\t{medlineDict[medId]["year"]}\t')
			pubOut.write(
				f'{authorKeyHere}\t{medlineDict[medId]["title"]}'
				f'\t{titleMinHere}\t')
			pubOut.write(
				f'{medlineDict[medId]["journal"]}'
				f'\t{medlineDict[medId]["journalKey"]}\t')
			pubOut.write(
				f'{match}\t{basisOut}\t{matchGroupOut}'
				f'\t{medlineDict[medId]["row"]}\n')

	# Process embase file
	embaseDict = {}
	if args.embase:
	
		print('\n#############################################################')
		print(' Processing an Embase file')
		print('#############################################################\n')
	
		cleanFileName = fileNamer(args.embase)
		embOut = open(cleanFileName, 'w')
	
		# Process the file
		pmidDict = {}
		authorKeyDict = {}
		titleMinDict = {}
		journalKeyDict = {}
		with open(args.embase, encoding="utf8") as csvfile:
	
			embaseCsv = csv.DictReader(csvfile, delimiter=',', quotechar='"',)
			embaseHeaders = list(embaseCsv.fieldnames)
			embaseColCount = len(embaseHeaders)
			embaseHeadersOut = '\t'.join(embaseHeaders)
			embOut.write(
				f'Embase_ID\tPMID\tEMID\tAuthor_Names\tYear\tAuthor_Year_Key'
				f'\tTitle\tTitle_Key\t')
			embOut.write(
				f'Journal_Details\tJournal_Key\tSimilar_Records\tSimilarity'
				f'\tSimilar_group\t{embaseHeadersOut}\n')
	
			lineCount = 0
			for row in embaseCsv:
				lineCount += 1
				embId = 'EMB_'+'{:05d}'.format(lineCount)
				pmid, emid, authorNames, authorKey, title, titleMin, year, \
					journal, journalKey, fullRow = embaseExtract(row)
	
				# Store the info
				embaseDict[embId] = {}
				embaseDict[embId]['row'] = fullRow
				embaseDict[embId]['pmid'] = pmid
				embaseDict[embId]['emid'] = emid
				embaseDict[embId]['authorNames'] = authorNames
				embaseDict[embId]['authorKey'] = authorKey
				embaseDict[embId]['title'] = title
				embaseDict[embId]['titleMin'] = titleMin
				embaseDict[embId]['year'] = year
				embaseDict[embId]['journal'] = journal
				embaseDict[embId]['journalKey'] = journalKey
	
				# Record pmid matches
				if pmid in pmidDict:
					pmidDict[pmid] = f'{pmidDict[pmid]};{embId}'
				else:
					pmidDict[pmid] = embId
	
				# Record authorKey matches
				if authorKey in authorKeyDict:
					authorKeyDict[authorKey] = \
						f'{authorKeyDict[authorKey]};{embId}'
				else:
					authorKeyDict[authorKey] = embId
	
				# Record titleMin matches
				if titleMin in titleMinDict:
					titleMinDict[titleMin] = f'{titleMinDict[titleMin]};{embId}'
				else:
					titleMinDict[titleMin] = embId
	
				# Record journalKey matches
				if journalKey in journalKeyDict:
					journalKeyDict[journalKey] = \
						f'{journalKeyDict[journalKey]};{embId}'
				else:
					journalKeyDict[journalKey] = embId
	
				# Record global matches
				globalPmidDict, globalAuthorKeyDict, globalTitleMinDict, \
					globalJournalKeyDict = globalMatcher(
						embId, pmid, authorKey, titleMin, globalPmidDict,
						globalAuthorKeyDict, globalTitleMinDict,
						globalJournalKeyDict, journalKey)
	
		# Printout the file
		keyList = embaseDict.keys()
		matchCount = 0
		matchGroup = {}
		for embId in sorted (keyList):
	
			pmidHere = embaseDict[embId]['pmid']
			authorKeyHere = embaseDict[embId]['authorKey']
			titleMinHere = embaseDict[embId]['titleMin']
			match, basisOut, matchGroupOut, matchCount, matchGroup = \
				matchFinder(
					pmidHere, authorKeyHere, titleMinHere, pmidDict,
					authorKeyDict, titleMinDict, matchCount, embId, matchGroup)
			emidHere = embaseDict[embId]['emid']
	
			# Print out clean version
			embOut.write(
				f'{embId}\t{pmidHere}\t{emidHere}'
				f'\t{embaseDict[embId]["authorNames"]}'
				f'\t{embaseDict[embId]["year"]}\t')
			embOut.write(
				f'{authorKeyHere}\t{embaseDict[embId]["title"]}'
				f'\t{titleMinHere}\t')
			embOut.write(
				f'{embaseDict[embId]["journal"]}'
				f'\t{embaseDict[embId]["journalKey"]}\t')
			embOut.write(
				f'{match}\t{basisOut}\t{matchGroupOut}'
				f'\t{embaseDict[embId]["row"]}\n')
	
	# Process scopus file
	scopusDict = {}
	if args.scopus:
	
		print('\n#############################################################')
		print(' Processing a Scopus file')
		print('#############################################################\n')
	
		cleanFileName = fileNamer(args.scopus)
		scoOut = open(cleanFileName, 'w')
	
		# Process the file
		pmidDict = {}
		authorKeyDict = {}
		titleMinDict = {}
		journalKeyDict = {}
		with open(args.scopus, encoding="utf8") as csvfile:
	
			scopusCsv = csv.DictReader(csvfile, delimiter=',', quotechar='"',)
			scopusHeaders = list(scopusCsv.fieldnames)
			scopusColCount = len(scopusHeaders)
			scopusHeadersOut = '\t'.join(scopusHeaders)
			scoOut.write(
				f'Embase_ID\tPMID\tAuthor_Names\tYear\tAuthor_Year_Key'
				f'\tTitle\tTitle_Key\t')
			scoOut.write(
				f'Journal_Details\tJournal_Key\tSimilar_Records\tSimilarity'
				f'\tSimilar_group\t{scopusHeadersOut}\n')
	
			lineCount = 0
			for row in scopusCsv:
				lineCount += 1
				scoId = 'SCO_'+'{:05d}'.format(lineCount)
				pmid, authorNames, authorKey, title, titleMin, year, journal, \
					journalKey, fullRow = scopusExtract(row)
	
				# Store the info
				scopusDict[scoId] = {}
				scopusDict[scoId]['row'] = fullRow
				scopusDict[scoId]['pmid'] = pmid
				scopusDict[scoId]['authorNames'] = authorNames
				scopusDict[scoId]['authorKey'] = authorKey
				scopusDict[scoId]['title'] = title
				scopusDict[scoId]['titleMin'] = titleMin
				scopusDict[scoId]['year'] = year
				scopusDict[scoId]['journal'] = journal
				scopusDict[scoId]['journalKey'] = journalKey
	
				# Record pmid matches
				if pmid in pmidDict:
					pmidDict[pmid] = f'{pmidDict[pmid]};{scoId}'
				else:
					pmidDict[pmid] = scoId
	
				# Record authorKey matches
				if authorKey in authorKeyDict:
					authorKeyDict[authorKey] = \
						f'{authorKeyDict[authorKey]};{scoId}'
				else:
					authorKeyDict[authorKey] = scoId
	
				# Record titleMin matches
				if titleMin in titleMinDict:
					titleMinDict[titleMin] = \
						f'{titleMinDict[titleMin]};{scoId}'
				else:
					titleMinDict[titleMin] = scoId
	
				# Record journalKey matches
				if journalKey in journalKeyDict:
					journalKeyDict[journalKey] = \
						f'{journalKeyDict[journalKey]};{scoId}'
				else:
					journalKeyDict[journalKey] = scoId
	
				# Record global matches
				globalPmidDict, globalAuthorKeyDict, globalTitleMinDict, \
					globalJournalKeyDict = globalMatcher(
						scoId, pmid, authorKey, titleMin, globalPmidDict,
						globalAuthorKeyDict, globalTitleMinDict,
						globalJournalKeyDict, journalKey)
	
		# Printout the file
		keyList = scopusDict.keys()
		matchCount = 0
		matchGroup = {}
		for scoId in sorted (keyList):
	
			pmidHere = scopusDict[scoId]['pmid']
			authorKeyHere = scopusDict[scoId]['authorKey']
			titleMinHere = scopusDict[scoId]['titleMin']
			match, basisOut, matchGroupOut, matchCount, matchGroup = \
				matchFinder(
					pmidHere, authorKeyHere, titleMinHere, pmidDict,
					authorKeyDict, titleMinDict, matchCount, scoId, matchGroup)
			
			# Print out clean version
			scoOut.write(
				f'{scoId}\t{pmidHere}\t{scopusDict[scoId]["authorNames"]}'
				f'\t{scopusDict[scoId]["year"]}\t')
			scoOut.write(
				f'{authorKeyHere}\t{scopusDict[scoId]["title"]}'
				f'\t{titleMinHere}\t')
			scoOut.write(
				f'{scopusDict[scoId]["journal"]}'
				f'\t{scopusDict[scoId]["journalKey"]}\t')
			scoOut.write(
				f'{match}\t{basisOut}\t{matchGroupOut}'
				f'\t{scopusDict[scoId]["row"]}\n')

	print('\n#################################################################')
	print(' Looking for overlaps')
	print('#################################################################\n')
	
	matchGroupNew = {}
	matchCountHere = 0
	idToGroup = {}
	idToSubgroup = {}
	subgroupToId = {'.': ''}
	idToDistance = {}
	# Look for overlaps between all the files
	if args.medline:
		for medId in medlineDict:
			# if medId == 'MED_01933':
			# 	sys.exit('Found MED_01933')
	
			pmidHere = medlineDict[medId]['pmid']
			authorKeyHere = medlineDict[medId]['authorKey']
			titleMinHere = medlineDict[medId]['titleMin']
			journalKey = medlineDict[medId]['journalKey']
			
			if medId not in idToSubgroup:
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
							getDetails(
								extraId, medlineDict, embaseDict, scopusDict)
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
				matchDist = '.'
				if match != '.':
					idToGroup, idToSubgroup, subgroupToId, idToDistance = \
						subGroupV2(
							matchKeyDict, medlineDict, embaseDict, scopusDict,
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
			medStat = matchSub.count('MED') + 1
			embStat = matchSub.count('EMB')
			scoStat = matchSub.count('SCO')
			firStat = matchSub.count('ONE')
			papersInGroup = medStat+embStat+scoStat+firStat
	
			mainRecord = 'Y'
	
			# Print out clean version
			allOut.write(
				f'{medId}\t{pmidHere}\t{medlineDict[medId]["authorNames"]}'
				f'\t{medlineDict[medId]["year"]}\t')
			allOut.write(
				f'{authorKeyHere}\t{medlineDict[medId]["title"]}'
				f'\t{titleMinHere}\t{medlineDict[medId]["journal"]}\t{journalKey}\t')
			allOut.write(
				f'{match}\t{matchSub}\t{matchSubGroupOut}\t{papersInGroup}'
				f'\t{medStat}\t{embStat}\t{scoStat}\t{firStat}'
				f'\t{mainRecord}\n')
	
	if args.embase:
		for embId in embaseDict:
			pmidHere = embaseDict[embId]['pmid']
			authorKeyHere = embaseDict[embId]['authorKey']
			titleMinHere = embaseDict[embId]['titleMin']
			journalKey = embaseDict[embId]['journalKey']
			
			matchKeyDict = {}
			basisDict = {}
			matchKeyDict, matchKeyDictLenLast, basisDict = matchListMaker(
				pmidHere, authorKeyHere, titleMinHere, globalPmidDict,
				globalAuthorKeyDict, globalTitleMinDict, embId, matchKeyDict,
				basisDict)
			matchKeyDictLenNew = end = 0
			matchKeyList = '|'.join(matchKeyDict.keys())
	
			# Extend to all possible matches
			while end == 0:
				for extraId in matchKeyList.split('|'):
					pmidExtraId, authorKeyExtraId, titleMinExtraId = getDetails(
						extraId, medlineDict, embaseDict, scopusDict)
					if extraId != embId:
						matchKeyDict, matchKeyDictLenNew, basisDict = \
							matchListMaker(
								pmidExtraId, authorKeyExtraId, titleMinExtraId,
								globalPmidDict, globalAuthorKeyDict,
								globalTitleMinDict, extraId, matchKeyDict,
								basisDict)
				if matchKeyDictLenLast == matchKeyDictLenNew:
					end = 1
				else:
					matchKeyDictLenLast = matchKeyDictLenNew
					matchKeyList = '|'.join(matchKeyDict.keys())
			
			# Work out groups
			match, basisOut, matchGroupOut, globalmatchCount, matchGroupNew = \
				findGroups(
					embId, matchKeyDict, basisDict, globalmatchCount,
					matchGroupNew)
	
			# Work out subgroups
			matchDist = '.'
			if match != '.':
				idToGroup, idToSubgroup, subgroupToId, idToDistance = \
					subGroupV2(
						matchKeyDict, medlineDict, embaseDict, scopusDict,
						matchGroupOut, idToGroup, idToSubgroup,
						subgroupToId, idToDistance)
			else:
				idToSubgroup[embId] = '.'
				idToGroup[embId] = '.'
	
			# Assess subgroup status
			matchSubGroupOut = idToSubgroup[embId]
			matchSub = '.'
			for idName in subgroupToId[matchSubGroupOut].split(';'):
				if idName != embId and idName != '':
					if matchSub == '.':
						matchSub = f'{idName}({idToDistance[embId][idName]})'
					else:
						matchSub = \
							f'{matchSub};{idName}' \
							f'({idToDistance[embId][idName]})'
	
			# Assess group status
			match = '.'
			for idName in idToGroup[embId].split(';'):
				if idName != embId and idName != '.':
					if match == '.':
						match = f'{idName}({idToDistance[embId][idName]})'
					else:
						match = \
							f'{match};{idName}' \
							f'({idToDistance[embId][idName]})'
	
			# Assess contributors
			medStat = matchSub.count('MED')
			embStat = matchSub.count('EMB') + 1
			scoStat = matchSub.count('SCO')
			firStat = matchSub.count('ONE')
			papersInGroup = medStat+embStat+scoStat+firStat
	
			mainRecord = 'N'
			if 'MED' not in matchSub:
				mainRecord = 'Y'
	
			# Print out clean version
			allOut.write(
				f'{embId}\t{pmidHere}\t{embaseDict[embId]["authorNames"]}'
				f'\t{embaseDict[embId]["year"]}\t')
			allOut.write(
				f'{authorKeyHere}\t{embaseDict[embId]["title"]}\t{titleMinHere}'
				f'\t{embaseDict[embId]["journal"]}\t{journalKey}\t')
			allOut.write(
				f'{match}\t{matchSub}\t{matchSubGroupOut}\t{papersInGroup}'
				f'\t{medStat}\t{embStat}\t{scoStat}\t{firStat}\t{mainRecord}\n')
	
	if args.scopus:
		for scoId in scopusDict:
			pmidHere = scopusDict[scoId]['pmid']
			authorKeyHere = scopusDict[scoId]['authorKey']
			titleMinHere = scopusDict[scoId]['titleMin']
			journalKey = scopusDict[scoId]['journalKey']
			
			# Find matches
			matchKeyDict = {}
			basisDict = {}
			matchKeyDict, matchKeyDictLenLast, basisDict = matchListMaker(
				pmidHere, authorKeyHere, titleMinHere, globalPmidDict,
				globalAuthorKeyDict, globalTitleMinDict, scoId, matchKeyDict,
				basisDict)
			matchKeyDictLenNew = end = 0
			matchKeyList = '|'.join(matchKeyDict.keys())
	
			# Extend to all possible matches
			while end == 0:
				for extraId in matchKeyList.split('|'):
					pmidExtraId, authorKeyExtraId, titleMinExtraId = getDetails(
						extraId, medlineDict, embaseDict, scopusDict)
					if extraId != scoId:
						matchKeyDict, matchKeyDictLenNew, basisDict = \
							matchListMaker(
								pmidExtraId, authorKeyExtraId, titleMinExtraId,
								globalPmidDict, globalAuthorKeyDict,
								globalTitleMinDict, extraId, matchKeyDict,
								basisDict)
				if matchKeyDictLenLast == matchKeyDictLenNew:
					end = 1
				else:
					matchKeyDictLenLast = matchKeyDictLenNew
					matchKeyList = '|'.join(matchKeyDict.keys())
			
			# Work out groups
			match, basisOut, matchGroupOut, globalmatchCount, matchGroupNew = \
				findGroups(scoId, matchKeyDict, basisDict, globalmatchCount,
						   matchGroupNew)
	
			# Work out subgroups
			matchDist = '.'
			if match != '.':
				idToGroup, idToSubgroup, subgroupToId, idToDistance = \
					subGroupV2(
						matchKeyDict, medlineDict, embaseDict, scopusDict,
						matchGroupOut, idToGroup, idToSubgroup,
						subgroupToId, idToDistance)
			else:
				idToSubgroup[scoId] = '.'
				idToGroup[scoId] = '.'
	
			# Assess subgroup status
			matchSubGroupOut = idToSubgroup[scoId]
			matchSub = '.'
			for idName in subgroupToId[matchSubGroupOut].split(';'):
				if idName != scoId and idName != '':
					if matchSub == '.':
						matchSub = f'{idName}({idToDistance[scoId][idName]})'
					else:
						matchSub = \
							f'{matchSub};{idName}' \
							f'({idToDistance[scoId][idName]})'
	
			# Assess group status
			match = '.'
			for idName in idToGroup[scoId].split(';'):
				if idName != scoId and idName != '.':
					if match == '.':
						match = f'{idName}({idToDistance[scoId][idName]})'
					else:
						match = \
							f'{match};{idName}' \
							f'({idToDistance[scoId][idName]})'
	
			# Assess contributors
			medStat = matchSub.count('MED')
			embStat = matchSub.count('EMB')
			scoStat = matchSub.count('SCO') + 1
			firStat = matchSub.count('ONE')
			papersInGroup = medStat+embStat+scoStat+firStat
	
			mainRecord = 'N'
			if 'MED' not in matchSub and 'EMB' not in matchSub:
				mainRecord = 'Y'
	
			# Print out clean version
			allOut.write(
				f'{scoId}\t{pmidHere}\t{scopusDict[scoId]["authorNames"]}'
				f'\t{scopusDict[scoId]["year"]}\t')
			allOut.write(
				f'{authorKeyHere}\t{scopusDict[scoId]["title"]}\t{titleMinHere}'
				f'\t{scopusDict[scoId]["journal"]}\t{journalKey}\t')
			allOut.write(
				f'{match}\t{matchSub}\t{matchSubGroupOut}\t{papersInGroup}'
				f'\t{medStat}\t{embStat}\t{scoStat}\t{firStat}\t{mainRecord}\n')


if __name__ == "__main__":
	main()
