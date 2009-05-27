import sys, sha
try:
    import SOAPpy
except ImportError:
    print >>sys.stderr, "Could not import SOAPpy, please install it, following the instructions on http://diveintopython.org/soap_web_services/install.html"
    raise
try:
    import pygtk
    pygtk.require('2.0')
    import gobject
except:
    HAVE_GTK = False
else:
    HAVE_GTK = True

auth_wsdl = "http://txtr.com/WSAuthService/WSAuth?wsdl"
auth_url = "http://txtr.com:80/WSAuthService/WSAuth"

try:
    user, password = file("auth.txt", "r").read().strip().split(":",1)
except:
    print >>sys.stderr, "Error: Need user:password in auth.txt!\n\n"
    raise

WSauth = SOAPpy.WSDL.Proxy(auth_wsdl).soapproxy
WSauth.config.dumpSOAPOut = 1
WSauth.config.dumpSOAPIn = 1

r = WSauth.authenticateUserByName(user, sha.new(password).hexdigest(), False)
