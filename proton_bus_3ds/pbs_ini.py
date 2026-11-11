# SPDX-License-Identifier: GPL-2.0-or-later
"""Helpers to read Proton Bus Simulator INI / model text files."""

import os
import re
from collections import namedtuple

_MODELS_KEY = re.compile(r"^models\d*$", re.IGNORECASE)


def read_text(path):
    """Read a text file, tolerating BOMs and legacy Windows encodings."""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_ini(path):
    """Lenient INI parser.

    Returns a list of (section, key, value) tuples, in file order.
    Duplicate sections/keys are kept, keys are compared case-insensitively
    by callers. Lines starting with ';', '#' or '//' are comments.
    """
    entries = []
    section = ""
    for raw in read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#", "//")):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1:line.index("]")].strip()
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        entries.append((section, key.strip(), value.strip().strip('"')))
    return entries


def resolve(base, rel):
    """Join a path written in a PBS file (forward or back slashes) to base."""
    rel = rel.replace("\\", "/").strip()
    return os.path.normpath(os.path.join(base, *[p for p in rel.split("/") if p]))


def read_bus_ini(ini_path):
    """Return (base_dir, [model_txt_paths]) for a bus INI file."""
    ini_dir = os.path.dirname(os.path.abspath(ini_path))
    entries = parse_ini(ini_path)

    base_dir_value = ""
    model_files = []
    for section, key, value in entries:
        if section.lower() != "config" or not value:
            continue
        if key.lower() == "basedir":
            base_dir_value = value
        elif _MODELS_KEY.match(key):
            model_files.append(value)

    base_dir = resolve(ini_dir, base_dir_value) if base_dir_value else ini_dir
    return base_dir, [resolve(base_dir, m) for m in model_files]


def read_model_list(model_txt_path, base_dir):
    """Return the absolute paths of every .3ds file referenced in a model text file."""
    result = []
    for _section, _key, value in parse_ini(model_txt_path):
        if value.lower().endswith(".3ds"):
            result.append(resolve(base_dir, value))
    return result


def find_textures_dir(start_dir):
    """Walk up from start_dir and return the first '<ancestor>/textures' folder found."""
    current = os.path.abspath(start_dir)
    while True:
        try:
            for name in os.listdir(current):
                if name.lower() == "textures" and os.path.isdir(os.path.join(current, name)):
                    return os.path.join(current, name)
        except OSError:
            pass
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


MapInfo = namedtuple("MapInfo", "base_dir models_dir textures_rel")


def read_map_txt(map_path):
    """Read a map description file (<name>.map.txt).

    [map]
    baseDir=ageo        -> folder relative to the .map.txt file
    modelsDir=main      -> tiles are in <baseDir>/tiles/<modelsDir>
    textures=textures   -> textures folder relative to <baseDir>
    """
    map_dir = os.path.dirname(os.path.abspath(map_path))
    values = {}
    for section, key, value in parse_ini(map_path):
        if section.lower() == "map":
            values[key.lower()] = value

    base_dir = resolve(map_dir, values["basedir"]) if values.get("basedir") else map_dir
    tiles_dir = os.path.join(base_dir, "tiles")
    models_dir = resolve(tiles_dir, values["modelsdir"]) if values.get("modelsdir") else tiles_dir
    return MapInfo(base_dir, models_dir, values.get("textures") or "textures")


def map_name(map_path):
    """'ageo.map.txt' -> 'ageo'."""
    name = os.path.basename(map_path)
    if name.lower().endswith(".map.txt"):
        return name[:-len(".map.txt")]
    return os.path.splitext(name)[0]


def _natural_key(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", os.path.basename(path))]


def list_3ds(directory):
    """All .3ds files directly inside directory, in natural order."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    paths = [os.path.join(directory, n) for n in names
             if n.lower().endswith(".3ds") and not n.startswith("__pbs_tmp_")]
    return sorted((p for p in paths if os.path.isfile(p)), key=_natural_key)
