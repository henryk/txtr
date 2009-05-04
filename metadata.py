import inspect, sys, urllib, re, htmlentitydefs

NEED_BIBTEX = 0

try:
    import _bibtex
except:
    if NEED_BIBTEX:
        print >>sys.stderr, "Couldn't load _bibtex module, please install python-bibtex"
        raise


HTML_ENTITY_REPLACEMENTS = dict(htmlentitydefs.entitydefs)
HTML_ENTITY_REPLACEMENTS.update( {
    "nbsp": " ",
})

def clean_html(string):
    string = re.sub('<br[^>]*>', "\n", string)
    string = re.sub('&([a-z]+);', lambda m: HTML_ENTITY_REPLACEMENTS.get(m.group(1),"&%s;" % m.group(0)), string)
    # FIXME Numeric references (e.g. &#937;)
    return string


class base_importer(object):
    def __init__(self, url, match = None):
        if match is None:
            for urlscheme in self.URLS:
                m = re.match(urlscheme, url)
                if m is not None:
                    match = m
                    break
        
        if match is None:
            raise ValueError, "URL doesn't match any url scheme this importer understands"
        
        self.url = url
        self.data = match.groupdict()
    
    def do_fetch(self, instructions):
        data = dict(self.data)
        inst = list(instructions)
        
        while len(inst) > 0:
            mapping = inst.pop(0)
            url = mapping[0] % data
            content = urllib.urlopen(url).read()
            
            flags = len(mapping) < 2 and re.I or mapping[2]
            m = re.search(mapping[1], content, flags)
            if m is None: return None
            
            data.update(m.groupdict())
        
        return data
    
    def load_bibtex(self):
        r = self.do_fetch(self.BIBTEX)
        
        if r is None: return None
        
        if "_bibtex" in r: return r["_bibtex"].strip()
        
        if "_bibtex_in_html" in r:
            return clean_html(r['_bibtex_in_html']).strip()
        
        return None

class IACR_ePrint_importer(base_importer):
    URLS = [
        r'http://eprint\.iacr\.org/(?P<year>[0-9]+)/(?P<report>[0-9]+)',
    ]
    
    BIBTEX = [
        ("http://eprint.iacr.org/cgi-bin/cite.pl?entry=%(year)s/%(report)s", "<PRE>(?P<_bibtex>.*?)</PRE>", re.I | re.S)
    ]
    
    DOCUMENT_URL = "http://eprint.iacr.org/%(year)s/%(report)s.pdf"

class ACM_Portal_importer(base_importer):
    URLS = [
        r'http://portal.acm.org/citation.cfm\?id=(?P<doi>[0-9.]+)',
    ]
    
    BIBTEX = [
        ('http://portal.acm.org/citation.cfm?id=%(doi)s', "onClick=\"window.open\\('(?P<indirect>[^']+)'[^>]+>[^<]+BibTex<", re.I),
        ('http://portal.acm.org/%(indirect)s', "<PRE[^>]*>(?P<_bibtex>.*?)</PRE>", re.I | re.S)
    ]

class CiteSeerX_importer(base_importer):
    URLS = [
        r'http://citeseerx.ist.psu.edu/viewdoc/summary\?doi=(?P<doi>[^&]+)',
    ]
    
    BIBTEX = [
        ('http://citeseerx.ist.psu.edu/viewdoc/summary?doi=%(doi)s', "<h2>BibTeX.*?<div[^>]+>(?P<_bibtex_in_html>.*?)</div", re.I | re.S)
    ]

def importer(url):
    for clazz in globals().values():
        if not (inspect.isclass(clazz) and issubclass(clazz, base_importer) and hasattr(clazz, "URLS")): continue
        for urlscheme in clazz.URLS:
            m = re.match(urlscheme, url)
            if m is not None:
                return clazz(url, m)
    
    raise ValueError, "No importer found for url '%s'" % url

if __name__ == "__main__":
    if False:
        print importer("http://portal.acm.org/citation.cfm?id=277650.277719").load_bibtex()
        print importer("http://portal.acm.org/citation.cfm?id=324550").load_bibtex()
        print importer("http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.23.414").load_bibtex()
        print importer("http://eprint.iacr.org/2009/137").load_bibtex()
    else:
        test = """@misc{cryptoeprint:2009:137,
    author = {Nicolas T. Courtois},
    title = {The Dark Side of Security by Obscurity and Cloning MiFare Classic Rail and Building Passes Anywhere, Anytime},
    howpublished = {Cryptology ePrint Archive, Report 2009/137},
    year = {2009},
    note = {\url{http://eprint.iacr.org/}},
}"""

    
    if "_bibtex" in sys.modules:
        b = _bibtex.open_string("foo", test, True)
        print b
        
        _bibtex.first(b)
        i = _bibtex.next(b)
        while i:
            print i
            i = _bibtex.next(b)
    
