import urllib, sys, sha, random

try:
    import simplejson
except ImportError:
    print >>sys.stderr, "Could not import simplejson, please install it"
    raise

try:
    import httplib2
except ImportError:
    pass

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
    DEBUG = 0
    
    def __init__(self, cookie = None):
        self.json_http_wrapper = _HTTP_Wrapper.new(cookie = cookie, baseurl = self.RPCURL)
    
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
        
        callurl = "%s?json=%s"% (self.RPCURL, urllib.quote(json))
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
    }
WSViewMgmt = _WSViewMgmt(_COOKIE)

class _WSListMgmt(_JSONBASE):
    BASENAME = "WSListMgmt"
    METHODS = {
        "getListListForUser": ["token", "userName"],
        "getList": ["token", "listID", "offset", "count"],
        "getSpecialList": ["token", "specialListType", "offset", "count"],
        "addDocumentsToList": ["token", "listID", "documentIDs", "addAt"],
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
    }
WSDocMgmt = _WSDocMgmt(_COOKIE)

class _WSUserMgmt(_JSONBASE):
    BASENAME = "WSUserMgmt"
    METHODS = {
        "getUserSettings": ["token"],
    }
WSUserMgmt = _WSUserMgmt(_COOKIE)

class txtr(object):
    DELIVERY_BASE_URL = "http://txtr.com/delivery/document/"
    
    def __init__(self, username=None, password=None, passhash=None, auth_from=None):
        self.user = None
        self.passh = None
        self._set_userdata(username, password, passhash, auth_from)
        
        self.token = None
        self.loginresponse = None
        
        self._cache = {}
    
    def __del__(self):
        if self.token is not None:
            self.logout()
    
    def _set_userdata(self, username=None, password=None, passhash=None, auth_from=None):
        if username is not None: self.user = username
        if passhash is not None: self.passh = passhash
        
        if password is not None:
            self.passh = sha.new(password).hexdigest()
        
        if auth_from is not None:
            try:
                u,p = file(auth_from, "r").read().strip().split(":",1)
            except:
                print >>sys.stderr, "Error: Need user:password in %s!\n\n" % auth_from
                raise
            self.user = u
            self.passh = sha.new(p).hexdigest()

    def login(self, username=None, password=None, passhash=None, auth_from=None):
        if username is not None or password is not None or passhash is not None or auth_from is not None:
            self._set_userdata(username, password, passhash, auth_from)
        
        self.loginresponse = WSAuth.authenticateUserByName(self.user, self.passh, False)
        self.token = self.loginresponse["token"]
    
    def logout(self):
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
        udid = WSDocMgmt.createDocumentFromWeb(self.token, url, display_name, categories, attributes, tags)
        
        if append_to is not None:
            self.add_documents_to_list([udid], append_to, append_position)
        
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
    
    def delivery_document_stream(self, document_id, version=None, format=None):
        url = self.DELIVERY_BASE_URL + document_id
        url = url + "?token=" + urllib.quote(self.token)
        if version is not None:
            url = url + "&v=" + urllib.quote(version)
        if format is not None:
            url = url + "&format=" + urllib.quote(format)
        
        fp = urllib.urlopen(url)
        return fp

    

