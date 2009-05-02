import urllib, sys, sha, random
try:
    import simplejson
except ImportError:
    print >>sys.stderr, "Could not import simplejson, please install it"
    raise

class _JSONBASE(object):
    RPCURL = "http://txtr.com/json/rpc"
    DEBUG = 0
    
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
        
        r = urllib.urlopen(callurl).read()
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

class _WSAuth(_JSONBASE):
    BASENAME = "WSAuth"
    METHODS = {
        "authenticateUserByName": ["userName", "password", "stickyToken"],
        "deAuthenticate": ["token"],
    }
WSAuth = _WSAuth()

class _WSViewMgmt(_JSONBASE):
    BASENAME = "WSViewMgmt"
    METHODS = {
        "getViewSets": ["token", "viewSetsOfUser"],
    }
WSViewMgmt = _WSViewMgmt()

class _WSListMgmt(_JSONBASE):
    BASENAME = "WSListMgmt"
    METHODS = {
        "getListListForUser": ["token", "userName"],
        "getList": ["token", "listID", "offset", "count"],
        "getSpecialList": ["token", "specialListType", "offset", "count"],
        "addDocumentsToList": ["token", "listID", "documentIDs", "addAt"],
    }
WSListMgmt = _WSListMgmt()

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
        "changeDocumentAttributes": ["token", "documentIDs", "attributes"]
    }
WSDocMgmt = _WSDocMgmt()

class _WSUserMgmt(_JSONBASE):
    BASENAME = "WSUserMgmt"
    METHODS = {
        "getUserSettings": ["token"],
    }
WSUserMgmt = _WSUserMgmt()

class txtr(object):
    def __init__(self, username=None, password=None, passhash=None, auth_from=None):
        self.user = None
        self.passh = None
        self._set_userdata(username, password, passhash, auth_from)
        
        self.token = None
        self.loginresponse = None
    
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
    
