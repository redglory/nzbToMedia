import sys
import urllib
import os
import shutil
import ConfigParser
import datetime
import time
import json
import logging

import Transcoder
from nzbToMediaEnv import *
from nzbToMediaSceneExceptions import process_all_exceptions

Logger = logging.getLogger()

def get_imdb(nzbName, dirName):
 
    imdbid = ""    

    a = nzbName.find('.cp(') + 4 #search for .cptt( in nzbName
    b = nzbName[a:].find(')') + a
    if a > 3: # a == 3 if not exist
        imdbid = nzbName[a:b]
    
    if imdbid:
        Logger.info("Found movie id %s in name", imdbid) 
        return imdbid
    
    a = dirName.find('.cp(') + 4 #search for .cptt( in dirname
    b = dirName[a:].find(')') + a
    if a > 3: # a == 3 if not exist
        imdbid = dirName[a:b]
    
    if imdbid:
        Logger.info("Found movie id %s in directory", imdbid) 
        return imdbid

    else:
        Logger.warning("Could not find an imdb id in directory or name")
        Logger.info("Postprocessing will continue, but the movie may not be identified correctly by CouchPotato")
        return ""

def get_movie_info(baseURL, imdbid, download_id):
    
    if not imdbid and not download_id:
        return ""
    url = baseURL + "movie.list/?status=active"

    Logger.debug("Opening URL: %s", url)

    try:
        urlObj = urllib.urlopen(url)
    except:
        Logger.exception("Unable to open URL")
        return ""

    movie_id = ""
    releaselist = []
    try:
        result = json.load(urlObj)
        movieid = [item["id"] for item in result["movies"]]
        library = [item["library"]["identifier"] for item in result["movies"]]
    except:
        Logger.exception("Unable to parse json data for movies")
        return ""

    for index in range(len(movieid)):
        if not imdbid:
            url = baseURL + "movie.get/?id=" + str(movieid[index])
            Logger.debug("Opening URL: %s", url)
            try:
                urlObj = urllib.urlopen(url)
            except:
                Logger.exception("Unable to open URL")
                return ""
            try:
                result = json.load(urlObj)
                releaselist = [item["info"]["download_id"] for item in result["movie"]["releases"] if "download_id" in item["info"] and item["info"]["download_id"].lower() == download_id.lower()]  
            except:
                Logger.exception("Unable to parse json data for releases")
                return ""

            if len(releaselist) > 0:
                movie_id = str(movieid[index])
                Logger.info("Found movie id %s in database via download_id %s", movie_id, download_id)
                break
            else:
                continue

        if library[index] == imdbid:
            movie_id = str(movieid[index])
            Logger.info("Found movie id %s in CPS database for movie %s", movie_id, imdbid)
            break

    if not movie_id:
        Logger.exception("Could not parse database results to determine imdbid or movie id")

    return movie_id

def get_status(baseURL, movie_id, clientAgent, download_id):
    
    if not movie_id:
        return "", clientAgent, "none", "none"
    url = baseURL + "movie.get/?id=" + str(movie_id)
    Logger.debug("Looking for status of movie: %s - with release sent to clientAgent: %s and download_id: %s", movie_id, clientAgent, download_id)
    Logger.debug("Opening URL: %s", url)

    try:
        urlObj = urllib.urlopen(url)
    except:
        Logger.exception("Unable to open URL")
        return "", clientAgent, "none", "none"
    result = json.load(urlObj)
    try:
        movie_status = result["movie"]["status"]["identifier"]
        Logger.debug("This movie is marked as status %s in CouchPotatoServer", movie_status)
    except: # index out of range/doesn't exist?
        Logger.exception("Could not find a status for this movie")
        movie_status = ""
    try:
        release_status = "none"
        if download_id != "" and download_id != "none": # we have the download id from the downloader. Let's see if it's valid.
            release_statuslist = [item["status"]["identifier"] for item in result["movie"]["releases"] if "download_id" in item["info"] and item["info"]["download_id"].lower() == download_id.lower()]
            clientAgentlist = [item["info"]["download_downloader"] for item in result["movie"]["releases"] if "download_id" in item["info"] and item["info"]["download_id"].lower() == download_id.lower()]
            if len(release_statuslist) == 1: # we have found a release by this id. :)
                release_status = release_statuslist[0]
                clientAgent = clientAgentlist[0]
                Logger.debug("Found a single release with download_id: %s for clientAgent: %s. Release status is: %s", download_id, clientAgent, release_status)
                return movie_status, clientAgent, download_id, release_status
            elif len(release_statuslist) > 1: # we have found many releases by this id. Check for snatched status
                clients = [item for item in clientAgentlist if item.lower() == clientAgent.lower()]
                clientAgent = clients[0]
                if len(clients) == 1: # ok.. a unique entry for download_id and clientAgent ;)
                    release_status = [item["status"]["identifier"] for item in result["movie"]["releases"] if "download_id" in item["info"] and item["info"]["download_id"].lower() == download_id.lower() and item["info"]["download_downloader"] == clientAgent][0]
                    Logger.debug("Found a single release for download_id: %s and clientAgent: %s. Release status is: %s", download_id, clientAgent, release_status)
                else: # doesn't matter. only really used as secondary confirmation of movie status change. Let's continue.                
                    Logger.debug("Found several releases for download_id: %s and clientAgent: %s. Cannot determine the release status", download_id, clientAgent)
                return movie_status, clientAgent, download_id, release_status
            else: # clearly the id we were passed doesn't match the database. Reset it and search all snatched releases.... hence the next if (not elif ;) )
                download_id = "" 
        if download_id == "none": # if we couldn't find this initially, there is no need to check next time around.
            return movie_status, clientAgent, download_id, release_status
        elif download_id == "": # in case we didn't get this from the downloader.
            download_idlist = [item["info"]["download_id"] for item in result["movie"]["releases"] if item["status"]["identifier"] == "snatched"]
            clientAgentlist = [item["info"]["download_downloader"] for item in result["movie"]["releases"] if item["status"]["identifier"] == "snatched"]
            if len(clientAgentlist) == 1:
                if clientAgent == "manual":
                    clientAgent = clientAgentlist[0]
                    download_id = download_idlist[0]
                    release_status = "snatched"
                elif clientAgent.lower() == clientAgentlist[0].lower():
                    download_id = download_idlist[0]
                    clientAgent = clientAgentlist[0]
                    release_status = "snatched"
                Logger.debug("Found a single download_id: %s and clientAgent: %s. Release status is: %s", download_id, clientAgent, release_status) 
            elif clientAgent == "manual":
                download_id = "none"
                release_status = "none"
            else:
                index = [index for index in range(len(clientAgentlist)) if clientAgentlist[index].lower() == clientAgent.lower()]            
                if len(index) == 1:
                    download_id = download_idlist[index[0]]
                    clientAgent = clientAgentlist[index[0]]
                    release_status = "snatched"
                    Logger.debug("Found download_id: %s for clientAgent: %s. Release status is: %s", download_id, clientAgent, release_status)
                else:
                    Logger.info("Found a total of %s releases snatched for clientAgent: %s. Cannot determine download_id. Will perform a renamenr scan to try and process.", len(index), clientAgent)                
                    download_id = "none"
                    release_status = "none"
        else: #something went wrong here.... we should never get to this.
            Logger.info("Could not find a download_id in the database for this movie")
            release_status = "none"
    except: # index out of range/doesn't exist?
        Logger.exception("Could not find a download_id for this movie")
        download_id = "none"
    return movie_status, clientAgent, download_id, release_status

def process(dirName, nzbName=None, status=0, clientAgent = "manual", download_id = ""):

    status = int(status)
    config = ConfigParser.ConfigParser()
    configFilename = os.path.join(os.path.dirname(sys.argv[0]), "autoProcessMedia.cfg")
    Logger.info("Loading config from %s", configFilename)

    if not os.path.isfile(configFilename):
        Logger.error("You need an autoProcessMedia.cfg file - did you rename and edit the .sample?")
        return 1 # failure

    config.read(configFilename)

    host = config.get("CouchPotato", "host")
    port = config.get("CouchPotato", "port")
    apikey = config.get("CouchPotato", "apikey")
    delay = float(config.get("CouchPotato", "delay"))
    method = config.get("CouchPotato", "method")
    delete_failed = int(config.get("CouchPotato", "delete_failed"))
    wait_for = int(config.get("CouchPotato", "wait_for"))

    try:
        ssl = int(config.get("CouchPotato", "ssl"))
    except (ConfigParser.NoOptionError, ValueError):
        ssl = 0

    try:
        web_root = config.get("CouchPotato", "web_root")
    except ConfigParser.NoOptionError:
        web_root = ""
        
    try:    
        transcode = int(config.get("Transcoder", "transcode"))
    except (ConfigParser.NoOptionError, ValueError):
        transcode = 0

    try:
        remoteCPS = int(config.get("CouchPotato", "remoteCPS"))
    except (ConfigParser.NoOptionError, ValueError):
        remoteCPS = 0

    nzbName = str(nzbName) # make sure it is a string
    
    imdbid = get_imdb(nzbName, dirName)

    if ssl:
        protocol = "https://"
    else:
        protocol = "http://"
    # don't delay when we are calling this script manually.
    if nzbName == "Manual Run":
        delay = 0

    baseURL = protocol + host + ":" + port + web_root + "/api/" + apikey + "/"
    
    movie_id = get_movie_info(baseURL, imdbid, download_id) # get the CPS database movie id this movie.
   
    initial_status, clientAgent, download_id, initial_release_status = get_status(baseURL, movie_id, clientAgent, download_id)
    
    process_all_exceptions(nzbName.lower(), dirName)

    if status == 0:
        if transcode == 1:
            result = Transcoder.Transcode_directory(dirName)
            if result == 0:
                Logger.debug("Transcoding succeeded for files in %s", dirName)
            else:
                Logger.warning("Transcoding failed for files in %s", dirName)

        if method == "manage":
            command = "manage.update"
        else:
            command = "renamer.scan"
            if clientAgent != "manual" and download_id != "none":
                if remoteCPS == 1:
                    command = command + "/?downloader=" + clientAgent + "&download_id=" + download_id
                else:
                    command = command + "/?movie_folder=" + dirName + "&downloader=" + clientAgent + "&download_id=" + download_id

        url = baseURL + command

        Logger.info("Waiting for %s seconds to allow CPS to process newly extracted files", str(delay))

        time.sleep(delay)

        Logger.debug("Opening URL: %s", url)

        try:
            urlObj = urllib.urlopen(url)
        except:
            Logger.exception("Unable to open URL")
            return 1 # failure

        result = json.load(urlObj)
        Logger.info("CouchPotatoServer returned %s", result)
        if result['success']:
            Logger.info("%s scan started on CouchPotatoServer for %s", method, nzbName)
        else:
            Logger.error("%s scan has NOT started on CouchPotatoServer for %s. Exiting", method, nzbName)
            return 1 # failure

    else:
        Logger.info("Download of %s has failed.", nzbName)
        Logger.info("Trying to re-cue the next highest ranked release")
        
        if not movie_id:
            Logger.warning("Cound not find a movie in the database for release %s", nzbName)
            Logger.warning("Please manually ignore this release and refresh the wanted movie")
            Logger.error("Exiting autoProcessMovie script")
            return 1 # failure

        url = baseURL + "movie.searcher.try_next/?id=" + movie_id

        Logger.debug("Opening URL: %s", url)

        try:
            urlObj = urllib.urlopen(url)
        except:
            Logger.exception("Unable to open URL")
            return 1 # failure

        result = urlObj.readlines()
        for line in result:
            Logger.info("%s", line)

        Logger.info("Movie %s set to try the next best release on CouchPotatoServer", movie_id)
        if delete_failed and not dirName in ['sys.argv[0]','/','']:
            Logger.info("Deleting failed files and folder %s", dirName)
            try:
                shutil.rmtree(dirName)
            except:
                Logger.exception("Unable to delete folder %s", dirName)
        return 0 # success
    
    if nzbName == "Manual Run":
        return 0 # success

    # we will now check to see if CPS has finished renaming before returning to TorrentToMedia and unpausing.
    start = datetime.datetime.now()  # set time for timeout
    pause_for = wait_for * 10 # keep this so we only ever have 6 complete loops.
    while (datetime.datetime.now() - start) < datetime.timedelta(minutes=wait_for):  # only wait 2 (default) minutes, then return.
        movie_status, clientAgent, download_id, release_status = get_status(baseURL, movie_id, clientAgent, download_id) # get the current status fo this movie.
        if movie_status != initial_status:  # Something has changed. CPS must have processed this movie.
            Logger.info("SUCCESS: This movie is now marked as status %s in CouchPotatoServer", movie_status)
            return 0 # success
        time.sleep(pause_for) # Just stop this looping infinitely and hogging resources for 2 minutes ;)
    else:
        if release_status != initial_release_status and release_status != "none":  # Something has changed. CPS must have processed this movie.
            Logger.info("SUCCESS: This release is now marked as status %s in CouchPotatoServer", release_status)
            return 0 # success
        else: # The status hasn't changed. we have waited 2 minutes which is more than enough. uTorrent can resule seeding now. 
            Logger.warning("The movie does not appear to have changed status after %s minutes. Please check CouchPotato Logs", wait_for)
            return 1 # failure

def get_xbmc_json_obj():
    
    config = ConfigParser.ConfigParser()
    configFilename = os.path.join(os.path.dirname(sys.argv[0]), "autoProcessMedia.cfg")
    
    if not os.path.isfile(configFilename):
        Logger.error("You need an autoProcessMedia.cfg file - did you rename and edit the .sample?")
        return 1 # failure

    config.read(configFilename)

    #setings for xbmc part of script
    host = config.get("XBMC", "host")
    port = config.get("XBMC", "port")
    username = config.get("XBMC", "username")
    password = config.get("XBMC", "password")
    http_address = 'http://%s:%s/jsonrpc' % (host, port)
    
    try:
         import json
    except ImportError:
         import simplejson as json
    import urllib2, base64

    class XBMCJSON:

         def __init__(self, server):
              self.server = server
              self.version = '2.0'

         def __call__(self, **kwargs):
              method = '.'.join(map(str, self.n))
              self.n = []
              return XBMCJSON.__dict__['Request'](self, method, kwargs)

         def __getattr__(self,name):
              if not self.__dict__.has_key('n'):
                    self.n=[]
              self.n.append(name)
              return self

         def Request(self, method, kwargs):
              data = [{}]
              data[0]['method'] = method
              data[0]['params'] = kwargs
              data[0]['jsonrpc'] = self.version
              data[0]['id'] = 1

              data = json.JSONEncoder().encode(data)
              content_length = len(data)

              content = {
                    'Content-Type': 'application/json',
                    'Content-Length': content_length,
              }
      
              request = urllib2.Request(self.server, data, content)
              base64string = base64.encodestring('%s:%s' % (username, password)).replace('\n', '')
              request.add_header("Authorization", "Basic %s" % base64string)

              f = urllib2.urlopen(request)
              response = f.read()
              f.close()
              response = json.JSONDecoder().decode(response)

              try:
                    return response[0]['result']                
              except:
                    return response[0]['error']
                    
    xbmc = XBMCJSON(http_address)
    Logger.info('- XBMC JSON Object successfully created!')
    return xbmc
 
def update_videolibrary(xbmc):

    ## Command to update XBMC Video library
    xbmc.VideoLibrary.Scan()
    Logger.info('- XBMC: Updating Video Library.' )

#### END ### 

def runCmd(cmd):
    Logger.info(str(shlex.split(cmd)))
    proc = subprocess.Popen(shlex.split(cmd), 
                 stdout=subprocess.PIPE, 
                 stderr=subprocess.PIPE, 
                 stdin=subprocess.PIPE)
    out, err = proc.communicate()
    ret = proc.returncode
    proc.wait()
    return (ret, out, err, proc)
    
def run_ember():

    ###########################################
    #### Ember Media Manager Auto Scraping ####
    ###########################################
    ### Command lines
    ### -------------
    ### -fullask
    ### -fullauto
    ### -missask
    ### -missauto
    ### -newask
    ### -newauto
    ### -markask
    ### -markauto
    ### -file
    ### -folder
    ### -export
    ### -template
    ### -resize
    ### -all
    ### -nfo
    ### -posters
    ### -fanart
    ### -extra
    ### -nowindow
    ### -run
    ###########################################

    config = ConfigParser.ConfigParser()
    configFilename = os.path.join(os.path.dirname(sys.argv[0]), "autoProcessMedia.cfg")
    
    if not os.path.isfile(configFilename):
        Logger.error("You need an autoProcessMedia.cfg file - did you rename and edit the .sample?")
        return 1 # failure

    config.read(configFilename)

    #setings for Ember Media Manager part of script
    emberMM_path   = config.get("EmberMM", "path")
    emberMM_params = config.get("EmberMM", "params")
    cmd_line = emberMM_path + emberMM_params
    Logger.info(cmd_line)

    # Lauch Ember Media Manager and store PID for future kill
    startTime = datetime.datetime.now()
    returnCode, stdOut, stdErr, sp = runCmd(cmd_line) 
    Logger.info('- Ember Media Manager: running on PID: (' + str(sp.pid) + ')' + ' started at: ' + str(startTime))
    endTime = datetime.datetime.now()
    # Kill Lauch Media Manager's PID
    subprocess.call("taskkill /F /T /PID %i"%sp.pid)    
    Logger.info('- Ember Media Manager ran for ' + str((endTime - startTime)))    
    Logger.info('- Killed Ember Media Manager on PID: (' + str(sp.pid) + ')' )    
    # Return Ember processing code
    return returnCode    

def run_artdownloader(movie, xbmc):
    #####################################################################################################################
    ###                  $$$ Art types $$$               ######      $$$ Mediatypes $$$  ######   $$$ Medianames $$$  ###
    #####################################################################################################################
    #                          Movies                      ##         mediatype=movie       #                           #
    #------------------------------------------------------##        mediatype=tvshow       # dbid=$INFO[ListItem.DBID] #                             #
    # poster | fanart | extrafanart | extrathumbs | thumb  ##      mediatype=musicvideo     #                           #
    # clearlogo | clearart | discart | banner              ##                               #                           #
    #####################################################################################################################
    #                          TV Shows                    ##
    #------------------------------------------------------##
    # poster | clearlogo | fanart | extrafanart | banner   ##
    # seasonposter | extrathumbs | clearart | tvthumb      ##
    # seasonthumb | seasonbanner | characterart            ##
    #########################################################
    #                        Musicvideos                   ##
    #------------------------------------------------------##
    # poster | fanart | extrafanart | clearart | discart   ##
    # clearlogo | extrathumbs                              ##
    #####################################################################################################################
    #                                           $$$ RunScript Command examples $$$                                      #
    #-------------------------------------------------------------------------------------------------------------------#
    #       XBMC.runscript(script.artwork.downloader, mode=custom, mediatype=movie, silent=true, extrafanart)           #
    #####################################################################################################################
    a=1

def get_url(http_address, mode, output, apikey):
    if mode == "qstatus":
        url = http_address + "/api?mode=" + mode + '&output=xml&apikey=' + apikey
    elif mode == "history":
        url = http_address + "/api?mode=" + mode + '&start=0&limit=4&output=' + output + '&apikey=' + apikey
    return url    

def check_sabnzbd():

    ### Read SABnzbd config settings
    config = ConfigParser.ConfigParser()
    configFilename = os.path.join(os.path.dirname(sys.argv[0]), "autoProcessMedia.cfg")
    
    if not os.path.isfile(configFilename):
        Logger.error("You need an autoProcessMedia.cfg file - did you rename and edit the .sample?")
        return 1 # failure

    config.read(configFilename)

# setings for xbmc part of script
    apikey = config.get("SABnzbd", "apikey")
    host = config.get("SABnzbd", "host")
    port = config.get("SABnzbd", "port")
    username = config.get("SABnzbd", "username")
    password = config.get("SABnzbd", "password")
    http_address = 'http://%s:%s/sabnzbd' % (host, port)

    ### Wait for SABnzbd to finish all downloads

    # Get URL for Queue Status
    url = get_url(http_address, 'qstatus', 'xml', apikey)
    
    # Load the queue:
    queue = urllib2.urlopen(url)
    queuedata = queue.read()
    queue.close()
    ## ACTIVE DOWNLOAD ?##
    # Script checks for active download it will loop here until download is complete
    while True:
        complete = queuedata.count("<noofslots>0</noofslots>")
        if complete != 1:
            Logger.info('- SABnzbd: Downloading...')
            time.sleep(300)
            
            # reload queue or loop will be stuck with old data from first read
            queue = urllib2.urlopen(url)
            queuedata = queue.read()
            queue.close()
            
        # triger to continue    
        if complete == 1:
            Logger.info('- SABnzbd: No active downloads. ')
            break
            
    ## HISTORY - POSTPROCESSING ACTIVE ?##
    
    # Get URL for Post-Processing Status
    url = get_url(http_address, 'history', 'json', apikey)
        
    while True:
        history = urllib2.Request(url)
        response = urllib2.urlopen(history)
        historydata = response.read()
        
        ##looking for stuff we need in history
        Postprocesing = historydata.count('Repairing') or historydata.count('Unpacking') or historydata.count('Verifying')
        Repairing = historydata.count('Repairing')
        Unpacking = historydata.count('Unpacking')
        Verifying = historydata.count('Verifying')
        
        ##logging 
        if Repairing >= 1 or Unpacking >= 1 or Verifying >= 1 or Postprocesing  >= 1:
        #    Logger.info('- SABnzbd: Repairing files...')
        #elif Unpacking >= 1:
        #    Logger.info('- SABnzbd: Unpacking files...')
        #elif Verifying >= 1:
        #    Logger.info('- SABnzbd: Verifying files...')
        #if Postprocesing  >= 1:
            Logger.info('- SABnzbd is post-processing...')
            ## loop script while sab is doing something with files
            # time.sleep(120)
            return 2            
        else: 
            Logger.info('- SABnzbd: Finished all jobs.')
            return 0 