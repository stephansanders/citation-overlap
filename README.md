# citation-overlap
Citation-Overlap is a tool for literature reviews that matches citations across database lists to identify overlapping records for deduplication.

Systematic reviews and meta-analyses can use this tool to integrate bibliographic references from multiple databases into a unified list without repeats.

## Install

Citation-Overlap is available as a graphical application in two different flavors.

- Desktop application: [packages available for Windows, macOS, and Linux](https://github.com/stephansanders/citation-overlap/releases/latest)
- [Web app](https://script.google.com/macros/s/AKfycbwXJ0AeS1u7bY9koWhkODuP62b4gGiBCVX5mUboawBU62rfUsvAx-CFuWxbCr9CqKeMvw/exec) with Google Sheets

We recommend the desktop application for simplicity and speed. It can also be run as an automated command-line tool. The web app requires accepting Google permissions to save and show data in a Google Sheets spreadsheet and process data in a server running the Python code in this repo.

## Sample Data

- [Citation lists from MEDLINE, Embase, and Scopus for autism sequencing](https://github.com/stephansanders/citation-overlap/releases/download/v0.9.1/AutismSequencingCitations_2020-07-08.zip)
- [Citation lists from Web of Science and extractor definition file](https://github.com/stephansanders/citation-overlap/releases/download/v0.9.1/WebOfScience_2021-05-06.zip)
