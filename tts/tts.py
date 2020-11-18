import os.path
import string
import json
import tts.logger
import tts.save
import codecs
from enum import Enum,IntEnum
from .filesystem import FileSystem,standard_basepath

class SaveType(IntEnum):
  workshop = 1
  save = 2
  chest = 3

class AssetType(Enum):
  MODEL = 'obj'
  IMAGE = 'various extensions'
  BUNDLE = 'unity3d'
  PDF = 'PDF'

def get_default_fs():
  return FileSystem(standard_basepath())

def strip_filename(filename):
  # Convert a filename to TTS format.
  valid_chars = "%s%s" % (string.ascii_letters, string.digits)
  return ''.join(c for c in filename if c in valid_chars)

def validate_metadata(metadata, maxver):
  # TODO: extract into new class
  if not metadata or not isinstance(metadata, dict):
    return False
  return ('Ver' in metadata and metadata['Ver'] <= maxver and
          'Id' in metadata and
          'Type' in metadata and metadata['Type'] in [x.name for x in SaveType])

def load_json_file(filename):
  log=tts.logger()
  if not filename:
    log.warn("load_json_file called without filename")
    return None
  if not os.path.isfile(filename):
    log.error("Unable to find requested file %s" % filename)
    return None
  log.info("loading json file %s" % filename)
  encodings = ['utf-8', 'windows-1250', 'windows-1252', 'ansi']
  data=None
  for encoding in encodings:
    try:
      data=codecs.open(filename,'r',encoding).read()
    except UnicodeDecodeError as e:
      log.debug("Unable to parse in encoding %s." % encoding)
    else:
      log.debug("loaded using encoding %s." % encoding)
      break
  if not data:
    log.error("Unable to find encoding for %s." % filename)
    return None
  j_data=json.loads(data)
  return j_data

def load_file_by_type(ident,filesystem,save_type):
  """load/parse the json file for a mod

  ident - id of the mod (eg: the filename, excluding the extension)
  save_type - the type of mod to load
  """
  assert isinstance(save_type, SaveType)
  assert isinstance(filesystem, FileSystem)
  filename=filesystem.get_json_filename_for_type(ident,save_type)
  return load_json_file(filename)

def describe_files_by_type(filesystem, save_type, sort_key=lambda mod: mod[0]):
  """ Describes all mods of a given save type. Ex: all Chests

      filesystem - a filesystem object; where to search for mods
      save_type - list only mods of type defined by SaveType enum
      sort_key - None or function for defining sort order. Defaults to sort by name

      return - List of (name, id)
  """
  assert isinstance(save_type, SaveType), "save_type must be a SaveType enum"
  output=[]
  for filename in filesystem.get_filenames_by_type(save_type):
    json=load_file_by_type(filename,filesystem,save_type)
    name=json['SaveName']
    output.append((name,filename))
    if sort_key:
      output = sorted(output, key=sort_key)
  return output

def download_file(filesystem,ident,save_type):
  """Attempt to download all files for a given savefile"""
  log=tts.logger()
  log.info("Downloading %s file %s (from %s)" % (save_type.name,ident,filesystem))

  save=tts.Save( ident=ident,
            save_type=save_type,
            filesystem=filesystem)

  if save.isInstalled:
    log.info("All files already downloaded.")
    return True

  successful = save.download()
  if successful:
    log.info("All files downloaded.")
  else:
    log.info("Some files failed to download.")
  return successful
