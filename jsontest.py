import sys, sha, pprint
import txtr

if __name__ == "__main__":
    Txtr = txtr.txtr(auth_from="auth.txt")
    Txtr.login()
    token = Txtr.token
    
    #print txtr.WSViewMgmt.getViewSets(token, user)
    #print txtr.WSListMgmt.getListListForUser(token, None)
    
    #print txtr.WSDocMgmt.getAllDocumentIDs(token, False)
    #print txtr.WSDocMgmt.getUnlistedDocumentIDs(token)
    
    #print txtr.WSDocMgmt.suggestTitleImages(token, "akymg9")

    if False:
        new_id = txtr.WSDocMgmt.createDocumentFromWeb(token, 
            "http://docs.python.org/library/urllib.html", 
            None, None, None, None)
        print new_id
        
        inbox = txtr.WSListMgmt.getSpecialList(token, "INBOX", 0, -1)
        txtr.WSListMgmt.addDocumentsToList(token, inbox["ID"], [new_id], -1)
    
    #pprint.pprint(txtr.WSDocMgmt.getDocument(token, "amgcg9"))
    #pprint.pprint(txtr.WSDocMgmt.getPotentialDocumentAttributeCategories(token, "amgcg9"))
    #pprint.pprint(txtr.WSUserMgmt.getUserSettings(token))
    
    print txtr.WSListMgmt.getSpecialList(token, "INBOX", 0, 1)
    
    Txtr.logout()
