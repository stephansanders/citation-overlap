# Citation-Overlap configuration
"""Configuration settings for Citation-Overlap."""

import pathlib

from appdirs import AppDirs

#: str: Application name.
APP_NAME = "Citation-Overlap"

#: :class:`pathlib.Path`: Application directory.
app_dir = pathlib.Path(__file__).resolve().parent.parent
#: str: Accessor to application-related user directories.
user_app_dirs = AppDirs(APP_NAME, False)
#: list[:class:`pathlib.Path`]: List of extractor directories, defaulting
# to the `extractors` folder in the app directory.
extractor_dirs = [app_dir / 'extractors']
