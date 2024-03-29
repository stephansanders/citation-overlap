"""Utility functions for Citation-Overlap."""

import glob
import logging
import pathlib
import string

import pandas as pd
from pandas.errors import ParserError
import yaml

#: :class:`logging.Logger`: Logger for this module.
_logger = logging.getLogger().getChild(__name__)


def is_seq(val):
	"""Check if the value is a sequence.

	Args:
		val (Any): Value to check.

	Returns:
		bool: True if the value is a list or tuple.

	"""
	return isinstance(val, (tuple, list))


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
			if key in strToClass.keys():
				val = strToClass[key](*parse_enum_val(val[key]))
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


def get_file_sep(path):
	"""Get separator for the given file extension.
	
	Args:
		path (Union[str, :class:`Path`]): File path from which the separator
			will be determined.

	Returns:
		str: The file separator, which is `\t` if the extension of `path` is
		`.tsv` and `,` for `.csv`. 

	"""
	return '\t' if pathlib.Path(path).suffix.lower() == '.tsv' else ','


def read_csv(path):
	"""Read a CSV or TSV file.
	
	Args:
		path (Union[str, :class:`Path`]): Path to read. Delimiter is assumed
			to be either "," or "\t", determined from this path's extension.
			If the read fails, the other delimiter will be checked.

	Returns:
		:class:`pandas.DataFrame`: File imported to a data frame.
	
	Raises:
		SyntaxError: if `path` cannot be parsed.

	"""
	try:
		sep = get_file_sep(path)
		try:
			# identify separator based on extension since auto-detection
			# does not appear to work reliably for TSV files
			df = pd.read_csv(
				path, index_col=False, dtype=str, na_filter=False, sep=sep)
		except ParserError:
			# fall back to opposite common delimiter
			sep = ',' if sep == '\t' else '\t'
			df = pd.read_csv(
				path, index_col=False, dtype=str, na_filter=False, sep=sep)
		return df
	except ParserError as e:
		_logger.exception(e)
		raise SyntaxError(f'Could not parse "{path} during import')


def mergeCsvs(inPaths, outPath=None):
	"""Combine and export multiple CSV files to a single CSV file.

	Args:
		inPaths (Union[str, :class:`Path`, list[Union[str, :class:`Path`]]]):
			CSV/TSV file path(s) to import as data frames and concatenate.
			Can be a single directory, in which case the entire folder
			contents will be concatenated.
		outPath (Union[str, :obj:`pathlib.Path`]): Output path; defaults to
			None to not save the merged data frame.

	Returns:
		:class:`pandas.DataFrame`: Merged data frame.

	"""
	if not inPaths:
		return None
	paths = inPaths
	if not is_seq(paths):
		# get directory contents if paths given as a single directory path
		path = pathlib.Path(paths)
		if path.is_dir():
			paths = glob.glob(str(path / "*"))
	if is_seq(paths):
		# combine paths and fill NaNs in concatenated file with empty strings
		dfs = [read_csv(path) for path in paths]
		df = pd.concat(dfs).fillna('')
	else:
		# read single file
		df = read_csv(paths)
	
	if outPath is not None:
		# save to file if output path given
		_logger.info(f'Saving merged CSV/TSVs to "{outPath}"')
		df.to_csv(outPath, sep=get_file_sep(outPath))
	return df


def removePunctuation(val):
	"""Remove periods and replace spaces with underscores in strings.

	Args:
		val (str): String.

	Returns:
		str: ``val`` with punctuation removed.

	"""
	newName = val.translate(str.maketrans('', '', string.punctuation))
	newName = newName.replace(' ', '_')
	return newName
