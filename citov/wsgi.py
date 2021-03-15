#!/usr/bin/env python

import os
import io
import logging

from flask import Flask, request, jsonify
import pandas as pd

from citov import medline_embase_scopus

logging.basicConfig(filename='out.log',level=logging.INFO)
app = Flask(__name__)


def findOverlaps(data):
	dbExtractor = medline_embase_scopus.DbExtractor()
	dfs = {}
	for key, val in data.items():
		path = f'{key}.csv'
		df = pd.read_csv(
			io.StringIO(val), sep=',', index_col=False, dtype=str,
			na_filter=False)
		extractorPath = os.path.join(
			'citation-overlap', medline_embase_scopus.PATH_EXTRACTORS,
			f'{key}.yml')
		app.logger.info(path)
		app.logger.info(extractorPath)
		df, dbName = dbExtractor.extractDb(path, extractorPath, df)
		app.logger.info(dbName)
		app.logger.info(df.head())
		dfs[key] = df
	dfs['overlaps'] = dbExtractor.combineOverlaps()
	return dfs


@app.route('/', methods=['GET', 'POST'])
def main():
	if request.method == 'POST':
		jsonData = request.get_json()
		dfs = findOverlaps(jsonData)
		dfs = {k: v.to_json(orient='records') for k, v in dfs.items()}
		return jsonify(dfs)
	return 'Hello my friend!'


if __name__ == "__main__":
	main()

