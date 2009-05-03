#!/usr/bin/env python
import txtr
import sys

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print >>sys.stderr, "Usage: %s URL" % sys.argv[0]
        sys.exit(1)
    
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    
    try:
        
        try:
            new_id = Txtr.create_from_web(sys.argv[1], append_to="INBOX")
            print "New document created: http://txtr.com/text/%s" % new_id
        except:
            print >>sys.stderr, "Exception during document creation, the document may have been created but not appended."
            raise
    
    finally:
        try:
            Txtr.logout()
        except:
            print >>sys.stderr, "Error during logout, the session token may not have been released"
