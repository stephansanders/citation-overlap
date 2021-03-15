# -*- mode: python ; coding: utf-8 -*-
# Setup specification file for Pyinstaller
"""Pyinstaller specification for freezing Citation-Overlap and its environment.

Originally auto-generated by Pyinstaller, modified here to include
modules and packages not detected but required for Citation-Overlap.

"""

import os
import pathlib

import pkg_resources
import importlib_resources

import setup as citov_setup

block_cipher = None


def get_pkg_egg(name):
	"""Get package egg-info path.

	Args:
		name (str): Package name.

	Returns:
		str, str: The egg-info path and output path for the given package.

	"""
	egg_info = pkg_resources.get_distribution(name).egg_info
	return egg_info, os.path.basename(egg_info)


def get_pkg_path(name):
	"""Get path to the installed package.

	Args:
		name (str): Package name.

	Returns:
		str, str: The package path and output path for the given package.

	"""
	pkg_dir = name
	for entry in importlib_resources.files(name).iterdir():
		pkg_dir = os.path.dirname(entry)
		break
	return pkg_dir, os.path.basename(pkg_dir)


# WORKAROUND: PyQt5 as of v5.15.4 gives a segmentation fault when the "Qt5"
# folder is not present; even an empty folder bypasses this error, but a stub
# must be added here for Pyinstaller to include the file
path_qt5 = pathlib.Path("build") / "Qt5"
path_qt5.mkdir(parents=True, exist_ok=True)
(path_qt5 / "stub").touch(exist_ok=True)

a = Analysis(
	["../run.py"],
	pathex=[],
	binaries=[],
	datas=[
		# add full package folders since they contain many modules that
		# are dynamically discovered or otherwise not found by Pyinstaller
		*[get_pkg_path(p) for p in (
			"pyface",
			"traitsui",
		)],
		# add egg-info folders required for these packages' entry points
		*[get_pkg_egg(p) for p in (
			"pyface",
			"traitsui",
		)],
		# workaround for error when folder is missing
		(path_qt5.resolve(), pathlib.Path("Pyqt5") / "Qt5"),
	],
	hiddenimports=[],
	hookspath=[],
	runtime_hooks=[],
	excludes=[],
	win_no_prefer_redirects=False,
	win_private_assemblies=False,
	cipher=block_cipher,
	noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name=citov_setup.config["name"],
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=True,
	console=False)
coll = COLLECT(
	exe,
	a.binaries,
	a.zipfiles,
	a.datas,
	strip=False,
	upx=True,
	upx_exclude=[],
	name="run")
app = BUNDLE(
	coll,
	name="{}.app".format(citov_setup.config["name"].title()),
	icon=None,
	bundle_identifier=None,
	info_plist={
		"NSRequiresAquaSystemAppearance": False,
	})
