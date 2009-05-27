#!/usr/bin/env python
import txtr
import sys, sha, codecs
from xml.dom import minidom

def update_node(Txtr, sony_card_basepath, node):
    path = node.getAttribute("path")
    if path == "": return
    
    content = None
    
    try:
        fp = file(sony_card_basepath + "/" + path, "r")
        try:
            content = fp.read()
        finally:
            fp.close()
    except IOError:
        return
    
    if content is not None:
        h = sha.new()
        h.update(content)
        hash = h.hexdigest()
    
    basename = path.split("/")[-1]
    # getAllDocumentsConstrained does not allow to search over tags
    #documents = txtr.WSDocMgmt.getAllDocumentsConstrained(Txtr.token, "(tag:%s)" % hash, 0, 2)
    documents = txtr.WSDocMgmt.getAllDocumentsConstrained(Txtr.token, "fileName:%s" % basename, 0, 10)
    
    document = None
    for d in documents:
        tags = d["userTags"]
        for t in tags:
            if "SHA1:%s" % hash in t:
                if document is not None: return # duplicate, abort
                else: document = d
    
    if document is None:
        return # no match found
    
    document = documents[0]
    author = document["attributes"].get("20514d7d-7591-49a4-a62d-f5c02a8f5edd", None)
    if author is not None:
        node.setAttribute("author", author)
        print "%s set author to %s" % (path, author)
    
    title = document["attributes"].get("65534960-94f7-4cb8-b473-d2ce34740f44", None)
    if title is not None:
        node.setAttribute("title", title)
        print "%s set title to %s" % (path, title)

if __name__ == "__main__":
    if len(sys.argv) not in (2,3):
        print >>sys.stderr, "Usage: %s sony_card_basepath [path_to_cache.xml]" % sys.argv[0]
        sys.exit(1)
    
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    
    try:
        sony_card_basepath = sys.argv[1]
        if len(sys.argv) < 3: path_to_cache = "Sony Reader/database/cache.xml"
        else: path_to_cache = sys.argv[2]
    
        t = minidom.parse(sony_card_basepath + "/" + path_to_cache)
        
        for node in t.getElementsByTagName("text"):
            update_node(Txtr, sony_card_basepath, node)
        
        t.writexml(codecs.open(sony_card_basepath + "/" + path_to_cache, 'w', encoding = 'utf-8'), encoding="UTF-8")
    finally:
        try:
            pass
            Txtr.logout()
        except:
            print >>sys.stderr, "Error during logout, the session token may not have been released"
