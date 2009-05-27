#!/usr/bin/env python
import txtr
import sys, sha

HASH_FUNCTIONS = {"SHA1": sha.new}

def hash_document(Txtr, doc):
    document = txtr.WSDocMgmt.getDocument(Txtr.token, doc)
    version_hashes = {}
    add_list = []
    remove_list = []
    
    for tag in document["userTags"]:
        parts = tag.split(":")
        if len(parts) != 3: continue
        
        version, hash_scheme, hash_value = None, None, None
        
        try: version = str(int(parts[0], 10))
        except: continue
        if parts[0] != version: continue
        
        if not HASH_FUNCTIONS.has_key(parts[1]): continue
        else: hash_scheme = parts[1]
        
        hash_value = parts[2]
        
        version_hashes[ (version, hash_scheme) ] = hash_value
    
    for version in document["versions"].keys():
        need_hashes = []
        for hash_scheme in HASH_FUNCTIONS.keys():
            if not version_hashes.has_key( (version,hash_scheme) ):
                need_hashes.append(hash_scheme)
        
        if len(need_hashes) == 0: continue
        
        content_stream = Txtr.delivery_download_document_stream(doc, version)
        content = content_stream.read()
        content_stream.close()
        
        for hash_scheme in need_hashes:
            h = HASH_FUNCTIONS[hash_scheme]()
            h.update(content)
            hash_value = h.hexdigest()
            
            add_list.append( "%s:%s:%s" % (version, hash_scheme, hash_value) )
    
    for (version, hash_scheme), hash_value in version_hashes.items():
        if not document["versions"].has_key(version):
            remove_list.append( "%s:%s:%s" % (version, hash_scheme, hash_value) )
    
    if len(add_list) > 0 or len(remove_list) > 0:
        print "Document %s, add %r, remove %r" % (doc, add_list, remove_list)
        txtr.WSDocMgmt.changeDocumentTags(Txtr.token, [doc], add_list, remove_list)

if __name__ == "__main__":
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    
    try:
        doclist = txtr.WSDocMgmt.getAllDocumentIDs(Txtr.token, False)
        for doc in doclist:
            hash_document(Txtr, doc)
        
    finally:
        try:
            Txtr.logout()
        except:
            print >>sys.stderr, "Error during logout, the session token may not have been released"
