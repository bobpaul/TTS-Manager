import urllib.request
import urllib.error
import http.client
import imghdr
import tts
from socket import error as SocketError


# fix jpeg detection
def test_jpg(h,f):
  """binary jpg"""
  if h[:3]==b'\xff\xd8\xff':
    return 'jpg'

imghdr.tests.append(test_jpg)

class Url:
  def __init__(self, url, filesystem, assettype=None):
    self.url = url
    self.stripped_url=tts.strip_filename(url)
    self.filesystem = filesystem
    self._jsonassettype = assettype
    self._assettype = assettype
    self._looked_for_location=False
    self._location=None

  def examine_filesystem(self):
    if not self._looked_for_location:
      self._location,self.assettype=self.filesystem.find_details(self.url)
      self._looked_for_location=True

  def download(self):
    log=tts.logger()
    if self.exists:
      return True
    url=self.url
    protocols=url.split('://')
    if len(protocols)==1:
      log.warn("Missing protocol for {}. Assuming http://.".format(url))
      url = "http://" + url
    log.info("Downloading data for %s." % url)
    user_agent = 'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)'
    headers = { 'User-Agent' : user_agent }
    request=urllib.request.Request(url,headers=headers)
    try:
      response=urllib.request.urlopen(request)
    except (urllib.error.URLError,SocketError) as e:
      log.error("Error downloading %s (%s)" % (url,e))
      return False
    try:
      data=response.read()
    except http.client.IncompleteRead as e:
      #This error is the http server did not return the whole file
      log.error("Error downloading %s (%s)" % (url,e))
      return False
    imagetype=imghdr.what('',data)
    filename=None
    if self._jsonassettype != tts.AssetType.IMAGE:
      filename=self.filesystem.get_asset_path(self.stripped_url + '.' + self._jsonassettype.value, self._jsonassettype)
      log.debug(f"File is {self._jsonassettype}, {filename}")
    else:
      if imagetype=='jpeg':
        imagetype='jpg'
      filename=self.filesystem.get_asset_path(self.stripped_url + '.' + imagetype, self._jsonassettype)
      log.debug(f"File is {imagetype}, {filename}")
    try:
      with open(filename,'wb') as fh:
        fh.write(data)
    except IOError as e:
      log.error("Error writing file %s (%s)" % (filename,e))
      return False
    self._looked_for_location=False
    return True

  @property
  def exists(self):
    """Does the url exist on disk already?"""
    return self.location != None

  @property
  def assettype(self):
    """What type of asset is this URL?
    """
    self.examine_filesystem()
    return self._assettype

  @assettype.setter
  def assettype(self, value):
    """What type of asset is this URL?
    """
    log=tts.logger()
    if value != self._assettype:
        log.warn(f"assettype changing since reading json {self._assettype.name} -> {value}")
    self._assettype = value

  @property
  def location(self):
    """Return the location of the file on disk for this url, if it exists."""
    self.examine_filesystem()
    return self._location

  def __repr__(self):
    if self.exists:
      return f"{self._assettype.VALUE}: {self.url} ({self.location})"
    else:
      return f"{self.url} (Not Found)"

  def __str__(self):
    if self.exists:
      return f"{self._assettype}: {self.url}"
    else:
      return "%s (Not Found)" % self.url
