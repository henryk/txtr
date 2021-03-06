import urllib, urlparse, sys, random, httplib, socket, threading, time
from hashlib import sha1

try:
    import simplejson
except ImportError:
    print >>sys.stderr, "Could not import simplejson, please install it"
    raise

try:
    import httplib2
except ImportError:
    pass

__all__ = ["WSAuth", "WSViewMgmt", "WSListMgmt", "WSDocMgmt", "WSUserMgmt", "WSEventBus", "txtr"]

## Note: The following is a backport (read: copy) of the essential parts of the httplib module in Python 2.6
class _HTTPConnectionWithFileUpload(httplib.HTTPConnection):
    def send(self, str):
        """Send `str' to the server."""
        if self.sock is None:
            if self.auto_open:
                self.connect()
            else:
                raise NotConnected()

        # send the data to the server. if we get a broken pipe, then close
        # the socket. we want to reconnect when somebody tries to send again.
        #
        # NOTE: we DO propagate the error, though, because we cannot simply
        #       ignore the error... the caller will know if they can retry.
        if self.debuglevel > 0:
            print "send:", repr(str)
        try:
            blocksize=8192
            if hasattr(str,'read') :
                if self.debuglevel > 0: print "sendIng a read()able"
                data=str.read(blocksize)
                while data:
                    self.sock.sendall(data)
                    data=str.read(blocksize)
            else:
                self.sock.sendall(str)
        except socket.error, v:
            if v[0] == 32:      # Broken pipe
                self.close()
            raise
    
    def _send_request(self, method, url, body, headers):
        # honour explicitly requested Host: and Accept-Encoding headers
        header_names = dict.fromkeys([k.lower() for k in headers])
        skips = {}
        if 'host' in header_names:
            skips['skip_host'] = 1
        if 'accept-encoding' in header_names:
            skips['skip_accept_encoding'] = 1

        self.putrequest(method, url, **skips)

        if body and ('content-length' not in header_names):
            thelen=None
            try:
                thelen=str(len(body))
            except TypeError, te:
                # If this is a file-like object, try to
                # fstat its file descriptor
                import os
                try:
                    thelen = str(os.fstat(body.fileno()).st_size)
                except (AttributeError, OSError):
                    # Don't send a length if this failed
                    if self.debuglevel > 0: print "Cannot stat!!"

            if thelen is not None:
                self.putheader('Content-Length',thelen)
        for hdr, value in headers.iteritems():
            self.putheader(hdr, value)
        self.endheaders()

        if body:
            self.send(body)

if sys.hexversion >= 0x02060000:
    _HTTP_Connection_Class = httplib.HTTPConnection
else:
    _HTTP_Connection_Class = _HTTPConnectionWithFileUpload

class _HTTP_Wrapper(object):
    """A simple http wrapper object to try to use httplib2 if possible, and fall back to urllib otherwise.
    Try to handle Keep-Alive if possible. Try to handle singleton-ish behaviour, if possible."""
    _CACHE = {}
    
    @classmethod
    def new(clazz, cookie = None, baseurl = None, *args, **kwargs):
        """Get a _HTTP_Wrapper object. Will use (cookie, baseurl) as a cache key
        to try to return a previously created object iff both are not-None.
        The idea is to only have one Keep-Alive connection (if possible) per instantiation context
        (e.g. this module) and usage (e.g. JSON vs. delivery)."""
        
        def make_new(): return clazz(cookie=cookie, baseurl=baseurl, *args, **kwargs)
        
        if cookie is None or baseurl is None:
            return make_new()
            
        else:
            try:
                return clazz._CACHE[ (cookie, baseurl) ]
            except TypeError:
                return make_new()
            except KeyError:
                clazz._CACHE[ (cookie, baseurl) ] = v = make_new()
                return v
    
    def __init__(self, cookie, baseurl, timeout = None):
        
        if "httplib2" in sys.modules:
            self.httplib2 = httplib2.Http(timeout = timeout)
        else:
            self.httplib2 = None
    
    def request(self, uri, method = "GET", body = None, headers = None):
        if self.httplib2 is not None:
            response, body = self.httplib2.request(uri, method=method, body=body, headers=headers)
            return (response, body)
        else:
            if method != "GET" or headers is not None or body is not None:
                raise NotImplementedError, "Fallback for advanced HTTP operation is not yet implemented"
            
            fp = urllib.urlopen(uri)
            body = fp.read()
            fp.close()
            
            return (None, body)

class _JSONBASE(object):
    RPCURL = "http://txtr.com/json/rpc"
    RPCURL_SSL = "https://txtr.com/json/rpc"
    DEBUG = 0
    
    def __init__(self, cookie = None, baseurl = RPCURL):
        self.json_http_wrapper = _HTTP_Wrapper.new(cookie = cookie, baseurl = baseurl)
        self.baseurl = baseurl
    
    def __getattr__(self, fname):
        return lambda *args, **kwargs: self._docall(fname, *args, **kwargs)

    def _docall(self, fname, *args, **kwargs):
        id = str(random.random())
        method = "%s.%s" % (self.BASENAME, fname)
        if self.METHODS.has_key(fname):
            for e in kwargs.keys():
                if not e in self.METHODS[fname]:
                    print >>sys.stderr, "Warning: unmapped keyword argument %s for call to %s" % (e, method)
            
            params = []
            lastmapped = None
            for i, e in enumerate(self.METHODS[fname]):
                if kwargs.has_key(e):
                    params.append(kwargs[e])
                    lastmapped = i
                elif i < len(args):
                    params.append(args[i])
                    lastmapped = i
                else:
                    params.append(None)
            
##            if lastmapped is not None:
##                params = params[:(lastmapped+1)]
        else:
            print >>sys.stderr, "Warning: %s method not defined in %s, parameter mapping results are undefined" % (method, self.__class__)
            params = list(args) + kwargs.values()
        
        json = simplejson.dumps({
            "id": id,
            "method": method,
            "params": params,
        })
        
        callurl = "%s?json=%s"% (self.baseurl, urllib.quote(json))
        if self.DEBUG:
            print ">> ", urllib.unquote(callurl)
        
        _, r = self.json_http_wrapper.request(callurl)
        response = simplejson.loads(r)
        
        if self.DEBUG:
            print "<< ", response
        
        if response.has_key("error"):
            raise RuntimeError, "JSON-RPC call failed: %s" % response["error"]
        else:
            if response["id"] != id:
                raise RuntimeError, "JSON-RPC call failed, received id does not match sent id. This shouldn't happen"
            else:
                return response["result"]

_COOKIE = object()
class _WSAuth(_JSONBASE):
    BASENAME = "WSAuth"
    METHODS = {
        "authenticateUserByName": ["userName", "password", "stickyToken"],
        "deAuthenticate": ["token"],
    }
WSAuth = _WSAuth(_COOKIE)

class _WSViewMgmt(_JSONBASE):
    BASENAME = "WSViewMgmt"
    METHODS = {
        "getViewSets": ["token", "viewSetsOfUser"],
        "getViews": ["token", "viewSetID"],
    }
WSViewMgmt = _WSViewMgmt(_COOKIE)

class _WSListMgmt(_JSONBASE):
    BASENAME = "WSListMgmt"
    METHODS = {
        "getListListForUser": ["token", "userName"],
        "getList": ["token", "listID", "offset", "count"],
        "getSpecialList": ["token", "specialListType", "offset", "count"],
        "addDocumentsToList": ["token", "listID", "documentIDs", "addAt"],
        "getListsForUser": ["token", "userName"],
    }
WSListMgmt = _WSListMgmt(_COOKIE)

class _WSDocMgmt(_JSONBASE):
    BASENAME = "WSDocMgmt"
    METHODS = {
        "getAllDocumentIDs": ["token", "alsoRemoved"],
        "getUnlistedDocumentIDs": ["token"],
        "suggestTitleImages": ["token", "documentID"],
        "createDocumentFromWeb": ["token", "documentURL", "displayName", "categoryIDs", "attributes", "tags"],
        "getDocument": ["token", "documentID"],
        "getPotentialDocumentAttributeCategories": ["token", "documentID"],
        "addDocumentAttributeCategory": ["token", "documentIDs", "categoryID"],
        "removeDocumentAttributeCategory": ["token", "documentIDs", "categoryID"],
        "changeDocumentAttributes": ["token", "documentIDs", "attributes"],
        "changeDocumentTags": ["token", "documentIDs", "tagsToAdd", "tagsToRemove"],
        "getAllDocumentsConstrained": ["token", "search", "offset", "count"],
    }
WSDocMgmt = _WSDocMgmt(_COOKIE)

class _WSUserMgmt(_JSONBASE):
    BASENAME = "WSUserMgmt"
    METHODS = {
        "getUserSettings": ["token"],
    }
WSUserMgmt = _WSUserMgmt(_COOKIE)

class _WSEventBus(_JSONBASE):
    BASENAME = "WSEventBus"
    METHODS = {
        "subscribe": ["token", "eventType", "eventSubType"],
        "unsubscribe": ["token", "listenerID", "eventType", "eventSubType"],
        "getEvents": ["token", "eventType", "eventSubType"],
    }
WSEventBus = _WSEventBus(_COOKIE)

ATTRIBUTES = {
    "title":  "65534960-94f7-4cb8-b473-d2ce34740f44",
    "author": "20514d7d-7591-49a4-a62d-f5c02a8f5edd",
}

class txtr(object):
    DELIVERY_BASE_URL = "http://txtr.com/delivery/document/"
    IMAGE_BASE_URL = "http://txtr.com/delivery/img"
    DOCUMENT_BASE_URL = "http://txtr.com/text/"
    
    def __init__(self, username=None, password=None, passhash=None, auth_from=None):
        self.user = None
        self.passh = None
        self._set_userdata(username, password, passhash, auth_from)
        
        self.token = None
        self.loginresponse = None
        
        self._event_bus = None
        
        self._cache = {}
    
    def __del__(self):
        if self.token is not None:
            self.logout()
    
    def _set_userdata(self, username=None, password=None, passhash=None, auth_from=None):
        if username is not None: self.user = username
        if passhash is not None: self.passh = passhash
        
        if password is not None:
            self.passh = sha1(password).hexdigest()
        
        if auth_from is not None:
            try:
                u,p = file(auth_from, "r").read().strip().split(":",1)
            except:
                print >>sys.stderr, "Error: Need user:password in %s!\n\n" % auth_from
                raise
            self.user = u
            self.passh = sha1(p).hexdigest()

    def login(self, username=None, password=None, passhash=None, auth_from=None):
        if username is not None or password is not None or passhash is not None or auth_from is not None:
            self._set_userdata(username, password, passhash, auth_from)
        
        self.loginresponse = WSAuth.authenticateUserByName(self.user, self.passh, False)
        self.token = self.loginresponse["token"]
        
        if self.loginresponse["resultCode"]["name"] == "FAILURE":
            return False
        elif self.loginresponse["resultCode"]["name"] == "SUCCESS":
            return True
    
    def logout(self):
        if self.token is not None:
            WSAuth.deAuthenticate(self.token)
            self.token = None
    
    def _do_cache(self, cb, funcname, *args):
        cache_key = (funcname, args)
        try:
            return self._cache[cache_key]
        except KeyError:
            self._cache[cache_key] = value = cb()
            return value
        except TypeError: #uncacheable, e.g. mutable objects in cache_key
            return cb()
    
    SPECIAL_LIST_VALUES = ["INBOX", "CLIPBOARD", "TRASH"]
    def get_special_list(self, list_type):
        if list_type is None: return None
        if list_type not in self.SPECIAL_LIST_VALUES: return None
        if not isinstance(list_type, basestring): 
            raise TypeError, "list_type argument must be string, not %s" % type(list_type)
        
        return self._do_cache(lambda : WSListMgmt.getSpecialList(self.token, list_type, 0, 1), 
            "get_special_list", list_type)
    
    def create_from_web(self, url, display_name = None, categories = None, attributes = None, tags = None, append_to = "INBOX", append_position = -1):
        """Creates a new document from a WWW URL and optionally appends it to a given list.
        
        Note on mixing this call with other calls: Since all (except for the delivery)
        operations on this txtr object (try) to use the same HTTP connection they should not be
        run concurrently. Since it is likely that you want to execute other operations besides
        this create call, a special contract is followed: If you don't use the append_to argument
        (that is: specify append_to=None) then this method will open up a separate HTTP connection
        for the createDocumentFromWeb call. You can then perform the append at a later time yourself,
        in a synchronized manner.""" 
        
        if append_to is not None:
            udid = WSDocMgmt.createDocumentFromWeb(self.token, url, display_name, categories, attributes, tags)
            self.add_documents_to_list([udid], append_to, append_position)
        else:
            doc_mgr = _WSDocMgmt(None) ## Create a custom WSDocMgmt, in order to force a separate HTTP connection
            udid = doc_mgr.createDocumentFromWeb(self.token, url, display_name, categories, attributes, tags)
            del doc_mgr
        
        return udid
    
    def add_documents_to_list(self, documents, append_to="INBOX", append_position=-1):
        list_id = None
        if append_to is not None:
            special = self.get_special_list(append_to)
            if special is not None:
                list_id = special["ID"]
            else:
                list_id = append_to
        
        if list_id is not None:
            WSListMgmt.addDocumentsToList(self.token, list_id, documents, append_position)
    
    def delivery_download_document_stream(self, document_id, version=None, format=None):
        """Returns a file-like object to read a downloaded document from.
        Note: Remember to close() the returned object when done."""
        url = self.DELIVERY_BASE_URL + document_id
        url = url + "?token=" + urllib.quote(self.token)
        if version is not None:
            url = url + "&v=" + urllib.quote(version)
        if format is not None:
            url = url + "&format=" + urllib.quote(format)
        
        fp = urllib.urlopen(url)
        return fp
    
    def delivery_download_image(self, document_id, size=None):
        url = self.IMAGE_BASE_URL + "?token=" + urllib.quote(self.token)
        url = url + "&type=DOCUMENTIMAGE"
        url = url + "&documentID=" + document_id
        if size is not None:
            url = url + "&size=" + urllib.quote(size)
        
        fp = urllib.urlopen(url)
        data = fp.read()
        fp.close()
        
        return data
    
    def delivery_upload_document_file(self, fp, file_name, document_id=None, append_list=None):
        """Upload a document from a file-like object (fp).
        Returns a tuple (status, new document-id). Status should be "OK".
        A note on the append_list parameter: All operations on the reaktor are transactional,
        so if you perform two concurrent uploads, both targeting the same list, the second
        upload will fail with an exception after the document has been transferred since the 
        append_list list has been changed since starting the upload. To be on the safe side,
        don't use append_list, but instead append the document manually, after the upload is
        complete."""
        url = self.DELIVERY_BASE_URL
        if document_id is not None:
            url = url + document_id + "/upload/version"
            raise NotImplementedError, "Version upload not implemented"
        else:
            url = url + "upload"
        url = url + "?token=" + urllib.quote(self.token)
        url = url + "&fileName=" + urllib.quote(file_name)
        if append_list is not None:
            url = url + "&addToList=" + urllib.quote(append_list)
        
        parsed_url = urlparse.urlparse(url)
        assert parsed_url.scheme.lower() == "http"
        
        connection = _HTTP_Connection_Class(parsed_url.netloc)
        r = connection.request("POST", parsed_url.path + "?" + parsed_url.query, body=fp)
        fp.close()
        
        if fp.aborted:
            ## Warning: Kludge! The upload has been externally aborted, the HTTP connection is currently
            ##     in a bad state: The server was expecting content-length bytes, but we won't send anymore
            ##     Instead we'll half-close the TCP connection to signal an end to the server
            connection.sock.shutdown(socket.SHUT_WR)
        
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        
        if response.status != 200:
            return ("HTTP error", response, response_body)
        else:
            result = response_body.split()
            if result[0].strip().upper() == "OK":
                return ("OK", result[1].strip())
            else:
                return ("reaktor error", response_body)

    def get_lists(self, username=None):
        return WSListMgmt.getListsForUser(self.token, username)
    
    def get_lists_and_views(self, username=None):
        lists = WSListMgmt.getListsForUser(self.token, username)
        viewsets = WSViewMgmt.getViewSets(self.token, username)
        for viewset in viewsets:
            viewset["name"] = viewset["properties"].get("name", None)
            views = WSViewMgmt.getViews(self.token, viewset["ID"])
            viewset["children_lists"] = [v["listID"] for v in views]
        return lists, viewsets
    
    def get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = self.Event_Bus(self)
            self._event_bus.start()
        return self._event_bus
    event_bus = property(get_event_bus)

    class Event_Bus(threading.Thread):
        POLL_TIME = 5 # in seconds
        
        def __init__(self, parent):
            threading.Thread.__init__(self)
            self.parent = parent
            self.subscriptions = {}
            self.stop = False
            self.last_run = 0
        
        def subscribe(self, callback, event_type=None, event_sub_type=None, *args, **kwargs):
            """Register a callback to be called with optional user defined data whenever
            an event with the given type and subtype is detected. The callback will be given
            the event as its first argument."""
            id = WSEventBus.subscribe(self.parent.token, event_type, event_sub_type)
            self.subscriptions[id] = (callback, args, kwargs) ## FIXME: Locking?
            return id
        
        def unsubscribe(self, id):
            WSEventBus.unsubscribe(self.parent.token, id, None, None)
            del self.subscriptions[id]
        
        def run(self):
            while not self.stop:
                ## This loop runs once per second to check whether to end the thread
                ## However, actual event bus polling is only performed every POLL_TIME runs
                
                if self.last_run > self.POLL_TIME:
                    self.last_run = 0
                    
                    events = WSEventBus.getEvents(self.parent.token, None, None)
                    for event in events:
                        for id in event["subscriptionIDs"]:
                            if self.subscriptions.has_key(id):
                                x = self.subscriptions[id]
                                x[0](event, *x[1], **x[2])
                
                self.last_run = self.last_run + 1
                time.sleep(1)
