import inspect, sys, urllib, re

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
        
        while "_result" not in data and len(inst) > 0:
            mapping = inst.pop(0)
            url = mapping[0] % data
            content = urllib.urlopen(url).read()
            
            flags = len(mapping) < 2 and re.I or mapping[2]
            m = re.search(mapping[1], content, flags)
            if m is None: return None
            
            data.update(m.groupdict())
        
        if "_result" in data:
            return data["_result"]
        
        return None
    
    def load_bibtex(self):
        r = self.do_fetch(self.BIBTEX)
        if r is not None: return r.strip()
        return None

class IACR_ePrint_importer(base_importer):
    URLS = [
        r'http://eprint\.iacr\.org/(?P<year>[0-9]+)/(?P<report>[0-9]+)',
    ]
    
    BIBTEX = [
        ("http://eprint.iacr.org/cgi-bin/cite.pl?entry=%(year)s/%(report)s", "<PRE>(?P<_result>.*?)</PRE>", re.I | re.S)
    ]

class ACM_Portal_importer(base_importer):
    URLS = [
        r'http://portal.acm.org/citation.cfm\?id=(?P<doi>[0-9.]+)',
    ]
    
    BIBTEX = [
        ('http://portal.acm.org/citation.cfm?id=%(doi)s', "onClick=\"window.open\\('(?P<indirect>[^']+)'[^>]+>[^<]+BibTex<", re.I),
        ('http://portal.acm.org/%(indirect)s', "<PRE[^>]*>(?P<_result>.*?)</PRE>", re.I | re.S)
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
    print importer("http://eprint.iacr.org/2009/137").load_bibtex()
    print importer("http://portal.acm.org/citation.cfm?id=277650.277719").load_bibtex()
    print importer("http://portal.acm.org/citation.cfm?id=324550").load_bibtex()
