import sys, txtr, re, urllib, os, threading, time

try:
    import pygtk
    pygtk.require('2.0')
    import gtk,gtk.glade
    import gobject
except:
    HAVE_GTK = False
    print >>sys.stderr, "The GUI needs python-gtk (aka pygtk) version 2.12 or higher, and python-gobject, please install"
    raise
else:
    HAVE_GTK = True

class _file_with_read_callback:
    def __init__(self, f, cb):
        self.f = f
        self.cb = cb
        self.size = os.fstat(self.fileno()).st_size
    
    def read(self, blocksize):
        data = self.f.read(blocksize)
        self.cb(len(data))
        return data
    
    def fileno(self):
        return self.f.fileno()
    
    def __len__(self):
        return self.size
    
class Upload_Thread(object):
    def __init__(self, uri, parent):
        self.uri = uri
        self.parent = parent
        self.harakiri = False
        
        self.thread = threading.Thread(target=self.run)
    
    def start(self): self.thread.start()
    def schedule_stop(self): self.harakiri = True
    class HarakiriException(Exception): pass
    
    def run(self):
        try:
            self.do_upload()
        except self.HarakiriException:
            pass

class Upload_Thread_FILE(Upload_Thread):
    def __init__(self, uri, parent):
        if not uri.lower().startswith("file:///"):
            raise ValueError, "Unsupported file uri format: %r" % uri
        self.file = urllib.unquote( uri[len("file://"):] ) # FIXME Handling encoding: UTF-8 to filesystem
        
        self.fd = file(self.file, "rb")
        self.file_name = os.path.basename(self.file)
        self.size = os.fstat(self.fd.fileno()).st_size
        self.bytes_done = 0
        self.percent_done = 0
        self.finished = False
        
        super(Upload_Thread_FILE, self).__init__(uri, parent)
    
    def do_upload(self):
        def update_gui(size):
            self.bytes_done = self.bytes_done + size
            self.percent_done = 100.0 * float(self.bytes_done) / float(self.size)
            gobject.idle_add(self.parent.upload_callback, self)
            
            if self.harakiri:
                raise self.HarakiriException, "Get me out of here"
        
        connection = self.parent.txtr.delivery_upload_stream(fp=_file_with_read_callback(self.fd, update_gui),
            file_name = self.file_name)
        
        self.finished = True
        gobject.idle_add(self.parent.upload_callback, self)
        
        for i in xrange(51):
            time.sleep(0.1)
            gobject.idle_add(self.parent.upload_callback, self)
            if self.harakiri: break
        
        response = connection.getresponse()
        response_body = response.read()
        
        print connection, response, response_body
        
        connection.close()

class Upload_Thread_HTTP(Upload_Thread):
    def __init__(self, uri, parent):
        raise NotImplementedError, "HTTP uploads not implemented yet"
        
        super(Upload_Thread_HTTP, self).__init__(uri, parent)

class Upload_Thread_TEST(Upload_Thread):
    def __init__(self, uri, parent):
        self.size = 9000
        self.file_name = "Test file"
        self.bytes_done = 0
        self.percent_done = 0
        self.finished = False
        super(Upload_Thread_TEST, self).__init__(uri, parent)
    
    def do_upload(self):
        for i in xrange(0, self.size, self.size/13 ):
            self.bytes_done = i
            self.percent_done = 100.0 * float(self.bytes_done) / float(self.size)
            gobject.idle_add(self.parent.upload_callback, self)
            
            time.sleep(1)
            
            if self.harakiri:
                raise self.HarakiriException, "Get me out of here"
        
        self.finished = True
        gobject.idle_add(self.parent.upload_callback, self)
        
        for i in xrange(51):
            time.sleep(0.1)
            gobject.idle_add(self.parent.upload_callback, self)
            if self.harakiri: break

GLADE_FILE = "uploader.glade"
DRY_RUN = False
class Upload_GUI(object):
    _DRAG_INFO_URI = 1
    _DRAG_INFO_TEXT = 2
    def __init__(self):
        self.main_window_xml = gtk.glade.XML(GLADE_FILE, "uploader_main")
        self.main_window = self.main_window_xml.get_widget("uploader_main")
        
        self.about_window_xml = gtk.glade.XML(GLADE_FILE, "uploader_about")
        self.about_window = self.about_window_xml.get_widget("uploader_about")
        
        for i in "statusbar", "target", "upload_view":
            setattr(self, i, self.main_window_xml.get_widget(i))
        
        self.main_window_xml.signal_autoconnect(self)
        self.main_window.show()
        self.main_window.drag_dest_set(gtk.DEST_DEFAULT_ALL, [
                ("text/uri-list", 0, self._DRAG_INFO_URI),
                ("text/plain", 0, self._DRAG_INFO_TEXT),
            ], gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE | gtk.gdk.ACTION_DEFAULT)
        
        gtk.quit_add(0, self.fast_shutdown)
        
        ## Set up the upload treeview, model, etc.
        self.upload_store = gtk.ListStore(object)
        self.upload_view.set_model(self.upload_store)
        self.upload_column = gtk.TreeViewColumn('Uploads')
        self.upload_view.append_column(self.upload_column)
        
        self.upload_column_icon_cell = gtk.CellRendererPixbuf()
        self.upload_column_icon_cell.set_property("stock-size", gtk.ICON_SIZE_DIALOG)
        self.upload_column.pack_start(self.upload_column_icon_cell, False)
        self.upload_column.set_cell_data_func(self.upload_column_icon_cell, self.upload_callback_icon)
        
        self.upload_column_text_cell = gtk.CellRendererText()
        self.upload_column.pack_end(self.upload_column_text_cell, True)
        self.upload_column.set_cell_data_func(self.upload_column_text_cell, self.upload_callback_text)
        
        self.upload_column_progress_cell = gtk.CellRendererProgress()
        self.upload_column_progress_cell.set_property("width", 100)
        self.upload_column.pack_start(self.upload_column_progress_cell, False)
        self.upload_column.set_cell_data_func(self.upload_column_progress_cell, self.upload_callback_progress)
        
        ## Set up API and log in
        self.txtr = txtr.txtr(auth_from="auth.txt")
        if not DRY_RUN:
            self.status("login", "Login to txtr.com API ...")
            self.txtr.login()
            self.status("login")
            self.status(message="Login ok")
        
        ## Retrieve lists and set up drop-down menu
        self.status("lists", "Retrieving user's lists ...")
        self.available_lists = []
        if not DRY_RUN:
            lists = self.txtr.get_lists()
        else:
            lists = [{"ID":"foo", "name":"Foo"}]
        for l in lists:
            self.available_lists.append( (l["ID"], l["name"]) )
            self.target.append_text(l["name"])
        self.target.set_active(0)
        self.status("lists")
        
        ## Prepare file chooser filters
        patterns = (
            ("Adobe PDF files", "*.[pP][dD][fF]"),
            ("Microsoft PowerPoint presentations", "*.[pP][pP][tT]", "*.[pP][pP][tT][xX]"),
            ("Microsoft Word documents", "*.[dD][oO][cC]", "*.[dD][oO][cC][xX]"),
            ("Microsoft Excel sheets", "*.[xX][lL][sS]", "*.[xX][lL][sS][xX]"),
            ("All files", "*"),
        )
        self.uploader_chooser_filters = []
        for pattern in patterns:
            f = gtk.FileFilter()
            f.set_name(pattern[0])
            for p in pattern[1:]: f.add_pattern(p)
            self.uploader_chooser_filters.append(f)
    
    ## Autoconnected signal handlers ##
    def on_uploader_main_destroy(self, widget):
        gtk.main_quit()
    
    def on_exit_clicked(self, menuitem):                    self.do_shutdown()
    def on_uploader_main_delete_event(self, widget, event): self.do_shutdown()
    
    def on_upload_activate(self, menuitem):
        "Callback for activation of menu File -> Upload"
        c = gtk.FileChooserDialog("Select file to upload", parent=self.main_window,
                                  buttons=(gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                                    gtk.STOCK_OPEN, gtk.RESPONSE_ACCEPT) )
        for f in self.uploader_chooser_filters:
            c.add_filter(f)
        c.set_select_multiple(True)
        
        result = c.run()
        
        if result == gtk.RESPONSE_ACCEPT:
            for uri in c.get_uris():
                self.add_upload(uri)
            c.destroy()
        else:
            c.destroy()
    
    def on_uploader_main_drag_data_received(self, widget, drag_context, x, y, selection_data, info, time):
        "Callback for reception of dragged files or text"
        if info == self._DRAG_INFO_URI:
            for uri in selection_data.get_uris():
                self.add_upload(uri)
        elif info == self._DRAG_INFO_TEXT:
            for m in re.finditer(r'[a-zA-Z]{2,}://\S+', selection_data.get_text()):
                self.add_upload(m.group(0))
    
    def on_about_activate(self, menuitem):
        result = self.about_window.run()
        self.about_window.hide()
    
    ## Indirectly called/utility methods
    def add_upload(self, uri):
        "Add and start an upload"
        t = None
        try:
            (scheme,) = uri.split(":",1)[:1]
            c = globals().get("Upload_Thread_%s" % scheme.upper(), None)
            if c is not None:
                t = c(uri, self)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            print e
        
        if t is not None:
            self.upload_store.append( (t,) )
            t.start()
    
    def upload_callback(self, upload):
        "Called from Upload_Thread_* objects to notify about a change in state, update GUI"
        
        # Find ListStore row for this upload
        index = [i for i,e in enumerate(self.upload_store) if e[0] is upload][0] 
        
        self.upload_store.emit("row-changed", (index,), self.upload_store.get_iter((index,)))
    
    
    def upload_callback_icon(self, column, cell_renderer, tree_model, iter):
        "Called from the tree view when something in the tree model/store changes"
        upload = tree_model.get_value(iter, 0)
        if "." in upload.file_name: type = upload.file_name.split(".")[-1].lower()
        else: type = ".none"
        
        cell_renderer.set_property('stock-id', gtk.STOCK_FILE)
    
    def upload_callback_text(self, column, cell_renderer, tree_model, iter):
        "Called from the tree view when something in the tree model/store changes"
        upload = tree_model.get_value(iter, 0)
        if not upload.finished:
            cell_renderer.set_property('text', "%s: %i of %i bytes (%3.f%%)" % 
                (upload.file_name, upload.bytes_done, upload.size, upload.percent_done))
        else:
            cell_renderer.set_property('text', "%s: %i bytes uploaded" % 
                (upload.file_name, upload.bytes_done))
    
    def upload_callback_progress(self, column, cell_renderer, tree_model, iter):
        "Called from the tree view when something in the tree model/store changes"
        upload = tree_model.get_value(iter, 0)
        if not upload.finished:
            cell_renderer.set_property('pulse', -1)
            cell_renderer.set_property('value', upload.percent_done)
            cell_renderer.set_property('text', None)
        else:
            cell_renderer.set_property('value', 0)
            upload._i = getattr(upload, "_i", 0) + 1
            if upload._i > 50:
                cell_renderer.set_property('pulse', gobject.G_MAXINT)
                cell_renderer.set_property('text', "finished")
            else:
                cell_renderer.set_property('pulse', upload._i)
                cell_renderer.set_property('text', "processing")
    
    def do_shutdown(self):
        for u in self.upload_store:
            u[0].schedule_stop()
        
        self.status("login", "Logging out ...")
        self.txtr.logout()
        self.status("login")
        self.status(message="Logout ok")
        
        self.main_window.destroy()
    
    def fast_shutdown(self): # Log out in any case upon termination of the main loop
        self.txtr.logout()
        return 0
    
    def status(self, context=None, message=None, pump_events=True):
        "Push (or pop, when message is None) a message to the status bar. Also calls pump_events."
        if context is None:
            c = self.statusbar.get_context_id("_IDLE_")
        else:
            c = self.statusbar.get_context_id(context)
        
        if message is None:
            self.statusbar.pop(c)
        else:
            if context is None: # Do not stack messages in the default context
                self.statusbar.pop(c)
            self.statusbar.push(c, message)
        
        if pump_events:
            self.pump_events()
    
    def pump_events(self):
        "Process all pending GUI events, e.g. update the GUI."
        while gtk.events_pending():
            gtk.main_iteration()

if __name__ == "__main__":
    gtk.gdk.threads_init()
    
    g = Upload_GUI()
    gobject.idle_add(lambda: g.add_upload("test://1") and None)
    gobject.timeout_add(5000, lambda: g.add_upload("test://2") and None )
    gtk.main()
