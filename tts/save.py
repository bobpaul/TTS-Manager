from .tts import *
from .url import Url
import tts
import zipfile
import json as JSON
import urllib.error
from enum import Enum

PAK_VER=2

class AssetType(Enum):
  MODEL = 'obj'
  IMAGE = 'ext'
  BUNDLE = 'unity3d'
  PDF = 'PDF'

def importPak(filesystem,filename):
  log=tts.logger()
  log.debug("About to import {} into {}.".format(filename,filesystem))
  if not os.path.isfile(filename):
    log.error("Unable to find mod pak {}".format(filename))
    return False
  if not zipfile.is_zipfile(filename):
    log.error("Mod pak {} format appears corrupt.".format(filename))
    return False
  try:
    with zipfile.ZipFile(filename,'r') as zf:
      bad_file=zf.testzip()
      if bad_file:
        log.error("At least one corrupt file found in {} - {}".format(filename,bad_file))
        return False
      if not zf.comment:
        # TODO: allow overrider
        log.error("Missing pak header comment in {}. Aborting import.".format(filename))
        return False
      metadata=JSON.loads(zf.comment.decode('utf-8'))
      if not tts.validate_metadata(metadata, PAK_VER):
        log.error(f"Invalid pak header '{metadata}' in {filename}. Aborting import.")
        return False
      log.info(f"Extracting {metadata['Type']} pak for id {metadata['Id']} (pak version {metadata['Ver']})")

      #select the thumbnail which matches the metadata id, else anything
      names = zf.namelist()
      thumbnails = [name for name in names if '/Thumbnails/' in name]
      thumbnail = None
      for thumbnail in thumbnails:
        if metadata['Id'] in os.path.basename(thumbnail):
          break

      outname=None
      for name in names:
        # Note that zips always use '/' as the seperator it seems.
        splitname = name.split('/')
        if len(splitname) > 2 and splitname[2] == 'Thumbnails':
          if name == thumbnail:
            #remove "Thumbnails" from the path
            outname='/'.join(splitname[0:2] + [os.path.extsep.join([metadata['Id'],'png'])])
          else:
            outname=None
            continue

        start=splitname[0]
        if start=='Saves':
          modpath=filesystem.basepath
        else:
          modpath=filesystem.modpath
        log.debug(f"Extracting {name} to {modpath}")
        zf.extract(name,modpath)
        if outname:
          log.debug(f"Renaming {name} to {outname}")
          os.rename(os.path.join(modpath,name), os.path.join(modpath,outname))
          try:
            outdir = os.path.dirname(os.path.join(modpath,name))
            os.rmdir(outdir)
          except OSError:
            log.debug(f"Can't remove dir {outdir}")

  except zipfile.BadZipFile as e:
    log.error("Mod pak {} format appears corrupt - {}.".format(filename,e))
  except zipfile.LargeZipFile as e:
    log.error("Mod pak {} requires large zip capability - {}.\nThis shouldn't happen - please raise a bug.".format(filename,e))
  log.info("Imported {} successfully.".format(filename))
  return True

def get_save_urls(savedata):
  '''
  Iterate over all the values in the json file, building a (key,value) set of
  all the values whose key ends in "URL"
  '''
  log=tts.logger()
  def parse_list(data):
    urls=set()
    for item in data:
      urls |= get_save_urls(item)
    return urls
  def parse_dict(data):
    urls=set()
    if not data:
      return urls
    for key in data:
      if type(data[key]) is not str or key=='PageURL' or key=='Rules':
        # If it isn't a string, it can't be an url.
        # Also don't save tablet state / rulebooks
        continue
      if key.endswith('URL') and data[key]!='':
        log.debug("Found {}:{}".format(key,data[key]))
        urls.add(data[key])
        continue
      protocols=data[key].split('://')
      if len(protocols)==1:
        # not an url
        continue
      if protocols[0] in ['http','https','ftp']:
        # belt + braces.
        urls.add(data[key])
        log.debug("Found {}:{}".format(key,data[key]))
        continue
    for item in data.values():
      urls |= get_save_urls(item)
    return urls

  if type(savedata) is list:
    return parse_list(savedata)
  if type(savedata) is dict:
    return parse_dict(savedata)
  return set()

class Mod:
  """ This represents the mod. Consumes json content or a json file and holds the list of URLs and relative file paths that make up the mod.

  File paths exclude the extension, as that can only be known by looking at the file (at least for images)
  Files have to be unique regardles of the extension anyway.

  self.images() -> [image_url, ]
  self.models() -> [models_url, ]
  self.pdfs() -> [pdf_url, ]
  self.bundles() -> [assetbundle_url, ]
  self.assetmap = {AssetType: {URL: path, }, }
  """
  def __init__(self, json, fname=None, thumbnail=None):
    """ Initialize a new Mod object.

      json - dict, str, Noneable
         if dict or None - the json content to intialize this object
         if string - the filename OR stringified json content to initialize this object

      fname - str, the filename of the json file. If None, name of json file is used if json is a file
      thumbnail - str, the filename of the thumbnail file

      fname and thumbnail are optional and may be used
    """
    log=tts.logger()
    self.modelpath = os.path.join('Mods', 'Models')
    self.imagespath = os.path.join('Mods', 'Images')
    self.workshoppath = os.path.join('Mods', 'Workshop')
    self.bundlespath = os.path.join('Mods', 'Assetbundles')
    self.pdfpath = os.path.join('Mods', 'PDF')

    self.assetmap = {}

    self.assetbundles = set()
    self.tableImages = set() #TableURL
    self.skyImages = set() #SkyURL
    self.customImages = set() #ImageURL, ImageSecondaryURL
    self.customUIImages = set() #URL
    self.customDeckImages = set() #BackURL, FaceURL
    self.customMeshModels = set() #ColliderURL, MeshURL
    self.customMeshImages = set() #DiffuseURL, NormalURL
    self.lightingModels = set() #LutURL; these might actually be bundles...
    self.customPdfs = set() #PDFUrl

    self.assetmap = {AssetType.MODEL: {},
                     AssetType.IMAGE: {},
                     AssetType.BUNDLE: {},
                     AssetType.PDF: {},
                     }

    if isinstance(json, dict):
      self._jsondata = jsondata
    elif type(json) == type(None):
      self._jsondata = {}
    elif isinstance(json, str) or isinstance(json, bytes):
      try:
        self._jsondata = JSON.loads(json)
      except JSON.JSONDecodeError:
        if os.path.isfile(json):
          with open(json, 'r') as jfile:
            self._jsondata = JSON.load(jfile)
        else:
          log.error('json was not a file nor json data')
          self._jsondata = {}

    if not fname and json and os.path.isfile(json):
      fname = os.path.basename(json)
    self.fname = os.path.join(self.workshoppath, fname) if fname else None
    self.thumbnail = os.path.join(self.workshoppath, os.path.basename(self.modthumbnail)) if thumbnail else None

    if 'SaveName' in self._jsondata.keys() and self._jsondata['SaveName']:
      self.name = self._jsondata['SaveName']
    else:
      self.name = None

    self.tableImages = set()
    if 'TableURL' in self._jsondata.keys():
      self.tableImages = [self._jsondata['TableURL']]

    self.skyImages = set()
    if 'SkyURL' in self._jsondata.keys():
      self.skyImages = [self._jsondata['SkyURL']]

    #TODO: this might be an asset bundle. Haven't yet found an example of a mod using this
    self.lightingModels = set()
    if 'Lighting' in self._jsondata.keys():
      if 'LutURL' in self._jsondata['Lighting'].keys():
        if self._jsondata['Lighting']['LutURL']:
          self.lightingModels.append(self._jsondata['Lighting']['LutURL'])

    #jq '. | select(.CustomUIAssets != null) | .CustomUIAssets[].URL
    self.customUIImages = []
    if 'CustomUIAssets' in self._jsondata.keys():
      for uiAsset in self._jsondata['CustomUIAssets']:
        if uiAsset['URL']:
          self.customUIImages.append(uiAsset['URL'])

    def _imagesBundlesPdfsMesh(jd):
      """
      populates assetbundles, customImages, customDeckImages,
          CustomMeshModels, and customPdfs based on the provided dictionary

      These objects are found at the same path in both
        jsondata['ObjectStates'] and jsondata['ObjectStates']['ContainedObjects']

      jd - json data to check
      returns - None, has side effects
      """
      for obj in jd:
        #jq '.ObjectStates[] | select(.CustomAssetbundle != null) | select(.CustomAssetbundle != null) | .CustomAssetbundle | .AssetbundleURL, .AssetbundleSecondaryURL'
        if 'CustomAssetbundle' in obj.keys():
          if obj['CustomAssetbundle']['AssetbundleURL']:
            self.assetbundles.add(obj['CustomAssetbundle']['AssetbundleURL'])
          if obj['CustomAssetbundle']['AssetbundleSecondaryURL']:
            self.assetbundles.add(obj['CustomAssetbundle']['AssetbundleSecondaryURL'])

        #jq '.ObjectStates[] | select(.CustomDeck != null) | .CustomDeck[] | .FaceURL, .BackURL'
        if 'CustomDeck' in obj.keys():
          for deckId in obj['CustomDeck'].keys():
            deck = obj['CustomDeck'][deckId]
            if deck['FaceURL']:
              self.customDeckImages.add(deck['FaceURL'])
            if deck['BackURL']:
              self.customDeckImages.add(deck['BackURL'].split('{Unique}')[0]) #Strip the {Unique} tag from come card backs

        #jq '.ObjectStates[] | select(.CustomImage != null) | .CustomImage | (.ImageURL, .ImageSecondaryURL)'
        if 'CustomImage' in obj.keys():
          if obj['CustomImage']['ImageURL']:
            self.customImages.add(obj['CustomImage']['ImageURL'])
          if obj['CustomImage']['ImageSecondaryURL']:
            self.customImages.add(obj['CustomImage']['ImageSecondaryURL'])

        #jq '.ObjectStates[] | select(.CustomMesh != null) | .CustomMesh | (.MeshURL, .DiffuseURL, .NormalURL, .ColliderURL)'
        if 'CustomMesh' in obj.keys():
          if obj['CustomMesh']['DiffuseURL']:
            self.customMeshImages.add(obj['CustomMesh']['DiffuseURL'])
          if obj['CustomMesh']['NormalURL']:
            self.customMeshImages.add(obj['CustomMesh']['NormalURL'])
          if obj['CustomMesh']['MeshURL']:
            self.customMeshModels.add(obj['CustomMesh']['MeshURL'])
          if obj['CustomMesh']['ColliderURL']:
            self.customMeshModels.add(obj['CustomMesh']['ColliderURL'])

        #jq '.ObjectStates[] | select(.CustomPDF != null) | .CustomPDF.PDFUrl'
        if 'CustomPDF' in obj.keys():
          if obj['CustomPDF']['PDFUrl']:
            self.customPdfs.add(obj['CustomPDF']['PDFUrl'])

        if 'CustomUIAssets' in obj.keys():
          for uiAsset in self.jsondata.keys['CustomUIAssets']:
            if uiAsset['URL']:
              self.customUIImages.add(uiAsset['URL'])

        if 'States' in obj.keys():
          _imagesBundlesPdfsMesh(obj['States'].values())
        if 'ContainedObjects' in obj.keys():
          _imagesBundlesPdfsMesh(obj['ContainedObjects'])

    self.assetbundles = set()
    self.customDeckImages = set()
    self.customImages = set()
    self.customMeshImages = set()
    self.customMeshModels = set()
    self.customPdfs = set()
    #jq '.ObjectStates[] | select(.States) |.States[] |select(.CustomAssetbundle != null) | select(.CustomAssetbundle != null) | .CustomAssetbundle | .AssetbundleURL, .AssetbundleSecondaryURL'
    if self._jsondata:
      _imagesBundlesPdfsMesh(self.jsondata['ObjectStates'])

    def _mapassets():
      """populates self.assetmap with a map of{URLs: (localPaths, AssetType), }

      Note that local paths are missing the extensions

      returns - none, but has side effects
      """
      for model in self.models():
        self.assetmap[AssetType.MODEL][model] = os.path.join(self.modelpath, tts.strip_filename(model))
      for image in self.images():
        self.assetmap[AssetType.IMAGE][image] = os.path.join(self.imagespath, tts.strip_filename(image))
      for bundle in self.bundles():
        self.assetmap[AssetType.BUNDLE][bundle] = os.path.join(self.bundlespath, tts.strip_filename(bundle))
      for pdf in self.pdfs():
        self.assetmap[AssetType.PDF][pdf] = os.path.join(self.pdfpath, tts.strip_filename(pdf))

    _mapassets()

  def images(self):
    """returns list of all image urls"""
    return list(self.tableImages) + list(self.skyImages) + list(self.customUIImages) + list(self.customImages) + list(self.customDeckImages) + list(self.customMeshImages)

  def models(self):
    """returns list of all model urls"""
    return list(self.customMeshModels) + list(self.lightingModels)

  def bundles(self):
    """returns list of all bundles"""
    return list(self.assetbundles)

  def pdfs(self):
    """returns list of all pdfs"""
    return list(self.customPdfs)

  @property
  def jsondata(self):
    return self._jsondata

  @jsondata.setter
  def jsondata(self, value):
    log=tts.logger()
    log.warn("Don't write to Mod.jsondata. Just make a new mod object")
    self._jsondata = value

  def verify_zip(self, zfile, loadjson=True) -> [str, ]:
    """
    Given a zipfile (str path or file-like object), verify the zip contains all the necesary
    files for the mod

    zfile - the zip file to check
    loadjson - if true, re-initializes with json data from archive
               if false, check this mode object against zip

    return -> list of missing URLs by type
    """
    log=tts.logger()
    everythingIsAModel = False

    zf = zipfile.ZipFile(zfile)
    header = {}
    try:
      header = JSON.loads(zf.comment)
      #version 1 paks put assetbundles and pdfs into mods
      if header["Ver"] <= 2: #TODO: just <... I'm the only person with version 2 packs
        log.warn('Version 1 pak file found; will search for pdfs and Assetbundles in Modules folder')
        everythingIsAModel = True
    except (JSON.decoder.JSONDecodeError,NameError,KeyError) as e:
      pass
    modfile = None
    if header:
      try:
        modfile = header['Id'] + '.json'
      except (JSON.decoder.JSONDecodeError,NameError,KeyError) as e:
        pass
    if loadjson:
      for asset in zf.filelist:
        if os.path.dirname(asset.filename) == 'Mods/Workshop' and asset.filename[-4:] == 'json':
          self.__init__( zf.read(asset), fname=modfile )
          break
        if os.path.dirname(asset.filename) == 'Mods/Workshop' and asset.filename[-3:] == 'cjc':
          log.warn("cjc file found. cjc based mods aren't supported. Open then Save in Tabletop Simulator to upgrade")
      if not asset.filename[-4:] == 'json':
        log.error("No JSON file found, unable to verify zip")
        return None
    #TODO: else: -> compare the json data is the same
    #  maybe https://pypi.org/project/jsoncomparison/
    return self.verify_list(zf.namelist(), everythingIsAModel)

  def verify_path(self, modsFolder, modJson=None, modThumb=None, everythingIsAModel=False) -> [str, ]:
    """Checks the folder contains all the necessary files for this mod

    modsFolder - path to the mods folder; this depends on Documents/GameData setting in TTS
    modJson - the json file or content to test. If not provided, check the current file

    """
    if modJson:
      self.__init__( modJson )
    models = ['Mods/Models/' + model for root,dirs,models in os.walk(os.path.join(modsFolder,'Models')) for model in models]
    images = ['Mods/Images/' + image for root,dirs,images in os.walk(os.path.join(modsFolder,'Images')) for image in images]
    bundle = ['Mods/Assetbundles/' + bundle for root,dirs,bundles in os.walk(os.path.join(modsFolder,'Assetbundles')) for bundle in bundles]
    pdfs = ['Mods/PDF/' + pdf for root,dirs,pdfs in os.walk(os.path.join(modsFolder,'PDF')) for pdf in pdfs]
    return self.verify_list(models+images+bundle+pdfs, everythingIsAModel)

  def verify_list(self, namelist, everythingIsAModel=False) -> [str, ]:
    """Given a relative list of file paths starting with 'Mods/', check to ensure all files
       referenced in the json exist in the list.

    namelist - list of names WITH UNIX PATH SEPARATOR starting with Mods/. Case sensitive
    everythingIsAModel - False for strict checking, True to look for Assetbundles and PDFs mislabeled as obj files.

    return -> List of urls (str) that are missing

    Ex: namelist = ['Mods/Workshop/12345678.json',
                    'Mods/Images/httpsimgurcomABCXYZ.jpg',
                    'Mods/PDF/httpsdrivegooglecomu0DOCSfubar.PDF',
                    'Mods/Models/abc123.obj',
                    'Mods/Assetbundles/httpscommunitysteamcomFOOBARBAZ.unity3d',
                   ]
    """
    missing = []
    log=tts.logger()
    found=0
    missing_images=[]
    namelist = [name.split('.')[0] for name in namelist]
    for url,image in self.assetmap[AssetType.IMAGE].items():
      if image.split('.')[0] not in namelist:
        missing_images.append(url)
        log.warn(f"Image: {url} is missing from archive")
      else:
        found += 1
        log.info(f"Image: {url} found")

    missing_models=[]
    for url,model in self.assetmap[AssetType.MODEL].items():
      if model.split('.')[0] not in namelist:
        missing_models.append(url)
        log.warn(f"Model: {url} is missing from archive")
      else:
        found += 1
        log.info(f"Model: {url} found")

    missing_pdfs=[]
    for url,pdf in self.assetmap[AssetType.PDF].items():
      if everythingIsAModel:
        pdf = os.path.join(self.modelpath, os.path.basename(pdf))
      if pdf.split('.')[0] not in namelist:
        missing_pdfs.append(url)
        log.warn(f"PDF: {url} is missing from archive")
      else:
        found += 1
        log.info(f"PDF: {url} found")

    missing_bundles=[]
    for url,bundle in self.assetmap[AssetType.BUNDLE].items():
      if everythingIsAModel:
        bundle = os.path.join(self.modelpath, os.path.basename(bundle))
      if bundle.split('.')[0] not in namelist:
        missing_bundles.append(url)
        log.warn(f"Assetbundle: {url} is missing from archive")
      else:
        found += 1
        log.info(f"Assetbundle: {url} found")

    total = len(self.images()) + len(self.models()) + len(self.bundles()) + len(self.pdfs())
    missing += missing_images + missing_models + missing_pdfs + missing_bundles
    if missing:
      log.warn(f"Missing: images\t{len(missing_images)}\tmodels\t{len(missing_models)}")
      log.warn(f"\t\tpdfs\t{len(missing_pdfs)}\tAssetbundles\t{len(missing_bundles)}")
      log.warn(f"{len(missing)} of {total} ({len(namelist)}) assets missing")
    else:
      log.info(f"All items found {found} of {total} ({len(namelist)})")
    return missing

class Save:
  def __init__(self,savedata,filename,ident,filesystem,save_type=SaveType.workshop):
    """ Initialize the save object
       savedata - the mod data; eg the contents of the json file
       filename - full path to the json file.
       ident - mod id; eg the file basename without the extension
       filesystem - "filesystem" object descring the mods dir
       save_type - Workshop, Mod, or Chest

     TODO: most of the required params are derivative. Only save_type, filesystem, and ident should be requied
     TODO: refactor to parse the json data in its own object so it can come equally from zip or from file on filesystem. The object should map relative paths to download URLs
    """
    log=tts.logger()
    self.data = savedata
    self.ident=ident
    if self.data['SaveName']:
      self.save_name=self.data['SaveName']
    else:
      self.save_name=self.ident
    self.save_type=save_type
    self.filesystem = filesystem
    self.filename=filename
    thumbnail = os.path.extsep.join(filename.split(os.path.extsep)[0:-1] + ['png']) #Known issue: this fails if filename doesn't contain an extsep
    if os.path.isfile(thumbnail):
        self.thumbnail = thumbnail
    else:
        self.thumbnail = None
    self.thumb=os.path.isfile(os.path.extsep.join([filename.split(os.path.extsep)[0],'png']))
    #strip the local part off.
    fileparts=self.filename.split(os.path.sep)
    while fileparts[0]!='Saves' and fileparts[0]!='Mods':
      fileparts=fileparts[1:]
    self.basename=os.path.join(*fileparts)
    log.debug("filename: {},save_name: {}, basename: {}".format(self.filename,self.save_name,self.basename))
    self.urls = [ Url(url,self.filesystem) for url in get_save_urls(savedata) ]
    self.missing = [ x for x in self.urls if not x.exists ]
    self.images=[ x for x in self.urls if x.exists and x.isImage ]
    self.models=[ x for x in self.urls if x.exists and not x.isImage ]
    log.debug("Urls found {}:{} missing, {} models, {} images".format(len(self.urls),len(self.missing),len(self.models),len(self.images)))

  def export(self,export_filename):
    log=tts.logger()
    log.info("About to export %s to %s" % (self.ident,export_filename))
    zfs = tts.filesystem.FileSystem(base_path="")
    zipComment = {
      "Ver":PAK_VER,
      "Id":self.ident,
      "Type":self.save_type.name
    }

    # TODO: error checking.
    with zipfile.ZipFile(export_filename,'w') as zf:
      zf.comment=JSON.dumps(zipComment).encode('utf-8')
      log.debug("Writing {} (base {}) to {}".format(self.filename,os.path.basename(self.filename),zfs.get_path_by_type(os.path.basename(self.filename),self.save_type)))
      zf.write(self.filename,zfs.get_path_by_type(os.path.basename(self.filename),self.save_type))
      if self.thumbnail:
        filepath=zfs.get_path_by_type(os.path.basename(self.thumbnail),self.save_type)
        arcname=os.path.join(os.path.dirname(filepath), 'Thumbnails', os.path.basename(filepath))
        zf.write(self.thumbnail,arcname=arcname)
        log.debug(f"Writing {self.thumbnail} to {arcname}")
      for url in self.models:
        log.debug("Writing {} to {}".format(url.location,zfs.get_model_path(os.path.basename(url.location))))
        zf.write(url.location,zfs.get_model_path(os.path.basename(url.location)))
      for url in self.images:
        log.debug("Writing {} to {}".format(url.location,zfs.get_model_path(os.path.basename(url.location))))
        zf.write(url.location,zfs.get_image_path(os.path.basename(url.location)))
    log.info("File exported.")

  @property
  def isInstalled(self):
    """Is every url referenced by this save installed?"""
    return len(self.missing)==0

  def download(self):
    log=tts.logger()
    log.warn("About to download files for %s" % self.save_name)
    if self.isInstalled==True:
      log.info("All files already downloaded.")
      return True

    successful=True
    url_counter=1
    for url in self.missing:
      log.warn("Downloading file {} of {} for {}".format(url_counter,len(self.missing),self.save_name))
      result = url.download()
      if not result:
        successful=False
      url_counter+=1

    #TODO:: remove items from missing list.
    return successful


    log.info("All files downloaded.")
    return True

  def __str__(self):
    result = "Save: %s\n" % self.data['SaveName']
    if len(self.missing)>0:
      result += "Missing:\n"
      for x in self.missing:
        result += str(x)+"\n"
    if len(self.images)>0:
      result += "Images:\n"
      for x in self.images:
        result += str(x)+"\n"
    if len(self.models)>0:
      result += "Models:\n"
      for x in self.models:
        result += str(x)+"\n"
    return result
__all__ = [ 'Save' ]
