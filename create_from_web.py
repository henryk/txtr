#!/usr/bin/env python
import txtr
import sys, sha

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print >>sys.stderr, "Usage: %s URL" % sys.argv[0]
        sys.exit(1)
    
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    token = Txtr.token
    
    try:
        new_id = txtr.WSDocMgmt.createDocumentFromWeb(token, 
            sys.argv[1], 
            None, None, None, None)
        print "New document created: http://txtr.com/text/%s" % new_id
        
        try:
            inbox = txtr.WSListMgmt.getSpecialList(token, "INBOX", 0, -1)
            txtr.WSListMgmt.addDocumentsToList(token, inbox["ID"], [new_id], -1)
        except:
            print >>sys.stderr, "Error while appending document to INBOX.\nThe document has been uploaded but will not be visible\nuntil it is appended to a list with a view.\n\n"
            raise
    
    finally:
        try:
            Txtr.logout()
        except:
            print >>sys.stderr, "Error during logout, the session token may not have been released"
