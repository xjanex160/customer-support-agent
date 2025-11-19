import os
import sys
from datetime import datetime

# Add project root to sys.path for autodoc
sys.path.insert(0, os.path.abspath('..'))

project = 'Customer Support Agent'
author = 'Ebube Imoh'
copyright = f"{datetime.now().year}, {author}"

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
]

autosummary_generate = True
napoleon_google_docstring = True
napoleon_numpy_docstring = False

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'alabaster'
html_static_path = ['_static']