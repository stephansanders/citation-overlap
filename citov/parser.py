import logging
import re
import string
from enum import Enum

from citov import utils

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


def parseYear(row, key=None, search=None):
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


def parseAuthorNames(row, key, year):
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
			firstAuthor = utils.removePunctuation(authorsList[0])
		if lenAuthorsList >= 2:
			lastAuthor = utils.removePunctuation(authorsList[-1])
		if lenAuthorsList >= 3:
			secondAuthor = utils.removePunctuation(authorsList[1])

		authorKey = (
			f'{firstAuthor.lower()}|{secondAuthor.lower()}|'
			f'{lastAuthor.lower()}|{year}')

	return authorNames, authorKey


def parseID(row, key, search=None, default='NoPMID'):
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


def parseTitle(row, key):
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


def parseJournal(row, key):
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


def parseEntry(row, extractor):
	"""Extract salient metadata from a database entry.

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
		year = parseYear(row, search=year_arg)
	else:
		year = parseYear(row, year_arg)
	extraction[ExtractKeys.YEAR] = year

	# parse authors
	extraction[ExtractKeys.AUTHOR_NAMES], extraction[ExtractKeys.AUTHOR_KEY] \
		= parseAuthorNames(row, extractor[ExtractKeys.AUTHOR_KEY], year)

	# parse PubMed ID
	pmid_arg = extractor[ExtractKeys.PMID]
	if utils.is_seq(pmid_arg):
		pmid = parseID(row, *pmid_arg)
	else:
		pmid = parseID(row, pmid_arg)
	extraction[ExtractKeys.PMID] = pmid

	if ExtractKeys.EMID in extractor:
		# parse EMID
		extraction[ExtractKeys.EMID] = parseID(
			row, *extractor[ExtractKeys.EMID])

	# parse title
	extraction[ExtractKeys.TITLE], extraction[ExtractKeys.TITLE_MIN] \
		= parseTitle(row, extractor[ExtractKeys.TITLE])

	# parse journal
	extraction[ExtractKeys.JOURNAL], extraction[ExtractKeys.JOURNAL_KEY] \
		= parseJournal(row, extractor[ExtractKeys.JOURNAL])

	# store tab-delimited version of row
	extraction[ExtractKeys.ROW] = _rowToList(row)

	if ExtractKeys.EXTRAS in extractor:
		# apply additional extractors
		for extra in extractor[ExtractKeys.EXTRAS]:
			extraction[extra[0]] = JointKeyExtractor.parseMods(
				row, extra[1], [JointKeyExtractor.parseMods(
					extraction, extra[2], [])])

	return extraction
