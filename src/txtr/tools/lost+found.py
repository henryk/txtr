#!/usr/bin/env python
import txtr
import sys

if __name__ == "__main__":
    
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    token = Txtr.token
    
    try:
        
        lost_ids = txtr.WSDocMgmt.getUnlistedDocumentIDs(token)
        if len(lost_ids) > 0:
            print "The following document IDs are not in any list, appending to INBOX:"
            print "\t" + ("\t\n".join(lost_ids))
            Txtr.add_documents_to_list(lost_ids, append_to="INBOX")
        else:
            print "No lost documents found"
    
    finally:
        try:
            Txtr.logout()
        except:
            print >>sys.stderr, "Error during logout, the session token may not have been released"
