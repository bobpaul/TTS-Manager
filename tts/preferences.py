import tkinter as Tk
import tkinter.ttk as ttk
import tkinter.simpledialog as simpledialog
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
import tts
import platform
import os
from enum import Enum

class ModSaveLocation(Enum):
    Documents = 0
    GameData = 1
    Auto = 2

if platform.system() == 'Windows':
  import winreg
else:
  import xdgappdirs
  import configparser

class Preferences(object):
  def __new__(cls):
    """Select the correct platform class."""
    if platform.system() == 'Windows':
      new_cls = PreferencesWin
    else:
      new_cls = PreferencesLinux
    instance = super(Preferences, new_cls).__new__(new_cls)
    if not issubclass(new_cls, cls) and new_cls != cls:
      instance.__init__(n)
    return instance

  def __init__(self):
    self.changed=False
    self._modSavePref=ModSaveLocation.Auto
    self._TTSLocation = ''
    self._firstRun = True
    #child class must initialize these properly (load from disk or assign defaults)

  @property
  def locationIsUser(self):
    """Returns True if the data location is the user's Documents\My Games folder

    if the configuration is set to auto, this checks the TTS setting
    """
    tts.logger().warn('Reading from locationIsUser is deprecated')
    return self.modSaveLocation() == ModSaveLocation.Documents

  @locationIsUser.setter
  def locationIsUser(self, value):
    tts.logger().warn('Writing to locationIsUser is deprecated')
    if isinstance(value, int) or isinstance(value, str) or isinstance(value, ModSaveLocation):
      self.modSavePref = value
    elif isinstance(value, bool):
      self.modSavePref = 'Documents' if value else 'Auto'

  def modSaveLocation(self) -> ModSaveLocation:
    """Returns the mod location. If the preference is set to auto
       this returns the setting found in the TTS game preferences"""
    if self.modSavePref == ModSaveLocation.Auto:
      return tts.get_modlocation_linux()
    else:
      return self.modSavePref

  @property
  def modSavePref(self) -> ModSaveLocation:
    return self._modSavePref

  @modSavePref.setter
  def modSavePref(self, value):
    modSetting = self._modSavePref
    if isinstance(value, str):
      modSetting = ModSaveLocation[value]
    elif isinstance(value,int):
      modSetting = ModSaveLocation(value)
    elif isinstance(value, ModSaveLocation):
      modSetting = value
    else:
      tts.logger().error(f'Invalid modSavePref: {value}')
    if modSetting != self._modSavePref:
      self.changed=True
      self._modSavePref = modSetting
    assert(isinstance(self._modSavePref, ModSaveLocation))

  @property
  def TTSLocation(self):
    return self._TTSLocation

  @TTSLocation.setter
  def TTSLocation(self,value):
    value = os.path.normpath(value)
    if self._TTSLocation==value:
      return
    self._TTSLocation=value
    self.changed=True

  @property
  def firstRun(self):
    return self._firstRun

  @firstRun.setter
  def firstRun(self,value):
    if self._firstRun==bool(value):
      return
    self._firstRun=bool(value)
    self.changed=True

  def reset(self):
    self.modSavePref=ModSaveLocation.Auto
    self.firstRun=1
    self.TTSLocation=""
    #child class must delete values from disk storage

  def save(self):
    # No longer first run.
    self.firstRun=0
    #Child class must save all 4 values to disk storage

  def validate(self):
    return self.get_filesystem().check_dirs()

  def get_filesystem(self):
    if self.modSaveLocation().name == 'Documents':
      return tts.get_default_fs()
    if not os.path.isdir(self.TTSLocation):
      tts.logger().error(f'Mods are in GameData but TTS Install Location is invalid: "{self.TTSLocation}"')
    return tts.filesystem.FileSystem(tts_install_path=self.TTSLocation)

  def __str__(self):
    return f"""Preferences:
modSavePref: {self.modSavePref.name}
TTSLocation: {self.TTSLocation}
firstRun: {self.firstRun}""".format()


class PreferencesWin(Preferences):

  def __init__(self):
    super().__init__()
    self._connection=winreg.ConnectRegistry(None,winreg.HKEY_CURRENT_USER)
    self._registry=winreg.CreateKeyEx( self._connection, "Software\TTS Manager",0,winreg.KEY_ALL_ACCESS )
    try:
      self.modSavePref = ModSaveLocation[ winreg.QueryValueEx(self._registry,"modSavePref")[0] ]
    except:
      try:
        self.modSavePref = ModSaveLocation.Documents if "True"==winreg.QueryValueEx(self._registry,"locationIsUser")[0] else ModSaveLocation.Auto
      except:
        pass
    try:
      self._TTSLocation=os.path.normpath( winreg.QueryValueEx(self._registry,"TTSLocation")[0] )
    except:
      pass
    try:
      self._firstRun="True"==winreg.QueryValueEx(self._registry,"firstRun")[0]
    except:
      pass

  def reset(self):
    super().reset()
    winreg.DeleteValue(self._registry,"modSavePref")
    winreg.DeleteValue(self._registry,"TTSLocation")
    winreg.DeleteValue(self._registry,"firstRun")
    try:
      winreg.DeleteValue(key, 'locationIsUser')
    except:
      pass

  def save(self):
    super().save()
    # Make sure all values have been createds
    winreg.SetValueEx(self._registry,"modSavePref",0,winreg.REG_SZ,str(self.modSavePref.name))
    winreg.SetValueEx(self._registry,"TTSLocation",0,winreg.REG_SZ,str(self.TTSLocation))
    winreg.SetValueEx(self._registry,"firstRun",0,winreg.REG_SZ,str(self.firstRun))
    #remove deprecated keys
    try:
      winreg.DeleteValue(self._registry, 'locationIsUser')
    except:
      pass
    try:
      winreg.DeleteValue(self._registry,"defaultSaveLocation")
    except:
      pass


class PreferencesLinux(Preferences):

  def __init__(self):
    super().__init__()
    self._conffile = os.path.join(xdgappdirs.user_config_dir(),'tts_manager.ini')
    self._config = configparser.ConfigParser(allow_no_value=True)
    self._config['main'] = {'modSavePref': ModSaveLocation.Auto.name,
                         'TTSLocation': '',
                         'firstRun': 'yes'}
    self._config.read(self._conffile, encoding='utf-8')

    validModSaveLocations = [e.name for e in ModSaveLocation]
    location = self._config['main']['modSavePref']
    self.modSavePref = location if location in validModSaveLocations else ModSaveLocation.Auto
    self._TTSLocation = self._config['main']['TTSLocation']
    self._firstRun = self._config['main'].getboolean('load_firstRun')

  def reset(self):
    super().reset()
    try:
      os.unlink(self._conffile)
    except FileNotFoundError:
      pass
    self.__init__()

  def save(self):
    super().save()
    # Make sure all values have been createds
    self._config['main']['modSavePref'] = self.modSavePref.name
    self._config['main']['TTSLocation'] = self._TTSLocation
    self._config['main']['firstRun'] = 'yes' if self._firstRun else 'no'
    with open(self._conffile, 'w') as configfile:
      self._config.write(configfile)


class PreferencesDialog(simpledialog.Dialog):
  def applyModSavePref(*args):
    args[0].preferences.modSavePref=args[0].modPrefInt.get()

  def body(self,master):
    self.master=master
    self.preferences=Preferences()
    ttk.Label(master,text="Mod Save Location:").grid(row=0)
    self.modPrefInt=Tk.IntVar()
    self.modPrefInt.set(self.preferences.modSavePref.value)
    print(f'modpref is {self.preferences.modSavePref.name}, int is {self.modPrefInt.get()}')
    for option in ModSaveLocation:
      ttk.Radiobutton(master,
                      text=option.name,
                      variable=self.modPrefInt,
                      value=int(option.value)
                     ).grid(row=0,column=option.value+1)
    self.modPrefInt.trace("w",self.applyModSavePref)
    ttk.Label(master,text="TTS Install location:").grid(row=1,columnspan=3)
    self.ttsLocationEntry=ttk.Entry(master)
    self.ttsLocationEntry.insert(0,self.preferences.TTSLocation)
    self.ttsLocationEntry.grid(row=2,sticky=Tk.E+Tk.W,columnspan=2)
    ttk.Button(master,text="Browse",command=self.pickTTSDir).grid(row=2,column=2)
    ttk.Label(master,text="If you have installed via Steam, this will be something like:\n \"C:\\Program Files (x86)\\Steam\\steamapps\\common\\Tabletop Simulator\"").grid(row=5,columnspan=2)
    ttk.Button(master,text="Validate",command=self.validate).grid(row=3,columnspan=3)

  def pickTTSDir(self):
    self.preferences.TTSLocation=filedialog.askdirectory(
            parent=self.master,
            mustexist=True
        )
    self.ttsLocationEntry.delete(0,Tk.END)
    self.ttsLocationEntry.insert(0,self.preferences.TTSLocation)

  def validate(self):
    self.preferences.TTSLocation=self.ttsLocationEntry.get()
    if not self.preferences.validate():
      messagebox.showwarning("Missing directories","Unable to find some directories - please check your settings.")
      return False
    messagebox.showinfo("TTS Manager","Preferences validated OK.")
    return True

  def apply(self):
    self.preferences.TTSLocation=self.ttsLocationEntry.get()
    self.preferences.save()
