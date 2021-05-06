"""Utility functions for Citation-Overlap."""

import yaml


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
