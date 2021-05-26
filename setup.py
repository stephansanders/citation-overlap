# Citation-Overlap setup script

import setuptools

# installation configuration
config = {
	"name": "citation-overlap",
	"description": "Converge citations from scientific journal databases",
	"author": "Stephan Sanders Lab",
	"url": "https://github.com/stephansanders/citation-overlap",
	"author_email": "",
	"version": "0.9.4",
	"packages": setuptools.find_packages(),
	"scripts": [],
	"python_requires": ">=3.6",
	"install_requires": [
		"PyQt5",
		"traitsui",
		"jellyfish",
		"pandas",
		"pyyaml",
		"appdirs",
	],
}


if __name__ == "__main__":
	# perform setup
	setuptools.setup(**config)
