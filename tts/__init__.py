from .url import Url
from .save import Save
from .tts import *
from .filesystem import *
from .logger import *
from .preferences import Preferences, ModSaveLocation

import platform
if platform.system() == 'Windows':
    import regex
else:
    import xdgappdirs
if platform.system() == 'Linux':
    import base64
    import xml.etree.ElementTree as ET

def get_modlocation_linux():
    confdir = xdgappdirs.user_config_dir()
    prefsfile = os.path.join(confdir, 'unity3d/Berserk Games/Tabletop Simulator/prefs')

    xmlroot = ET.parse(prefsfile).getroot()
    prefs = xmlroot.findall('pref')
    for pref in prefs:
        if 'name' in pref.keys() and pref.attrib['name'] == 'ConfigGame':
            preferences = json.loads(base64.b64decode(pref.text))
            break
    return ModSaveLocation(preferences['ConfigMods']['Location'])
