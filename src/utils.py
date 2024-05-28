# CONSTANT for settings

MAX_HOP = None
ONLY_DEF = False

ENABLE_DOCSTRING = True
LAST_K_LINES = 1

import os
DS_BASE_DIR = os.path.abspath("../ReccEval")
DS_REPO_DIR = os.path.join(DS_BASE_DIR, "Source_Code")
DS_FILE = os.path.join(DS_BASE_DIR, "metadata.jsonl")
DS_GRAPH_DIR = os.path.join(DS_BASE_DIR, "Graph")