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

    #pprint.pprint(txtr.WSDocMgmt.getDocument(token, "amgcg9"))
    #pprint.pprint(txtr.WSDocMgmt.getPotentialDocumentAttributeCategories(token, "amgcg9"))
    #pprint.pprint(txtr.WSUserMgmt.getUserSettings(token))
    
    #print txtr.WSListMgmt.getSpecialList(token, "INBOX", 0, 1)
    
    if False:
        alldocs = {}
        
        l = txtr.WSDocMgmt.getAllDocumentIDs(token, False)
        for e in l:
            alldocs[e] = txtr.WSDocMgmt.getDocument(token, e)
        
        pprint.pprint(alldocs)
    
    Txtr.logout()
