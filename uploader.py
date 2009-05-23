import sys, txtr, re, urllib, os, threading, time

try:
    import pygtk
    pygtk.require('2.0')
    import gtk,gtk.glade
    import gobject
    import gconf
except:
    HAVE_GTK = False
    print >>sys.stderr, "The GUI needs python-gtk (aka pygtk) version 2.12 or higher, python-gconf and python-gobject, please install"
    raise
else:
    HAVE_GTK = True

class _file_with_read_callback:
    def __init__(self, f, cb):
        self.f = f
        self.cb = cb
        self.size = os.fstat(self.fileno()).st_size
        self.aborted = False
    
    def read(self, blocksize):
        data = self.f.read(blocksize)
        self.cb(len(data))
        
        if self.aborted:
           return None 
        else:
            return data
    
    def fileno(self):  return self.f.fileno()
    def close(self):   return self.f.close()
    def __len__(self): return self.size
    
class Upload_Thread(object):
    def __init__(self, uri, parent, append_list=None):
        self.uri = uri
        self.parent = parent
        self.append_list = append_list
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
    def __init__(self, uri, parent, append_list=None):
        if not uri.lower().startswith("file:///"):
            raise ValueError, "Unsupported file uri format: %r" % uri
        self.file = urllib.unquote( uri[len("file://"):] ) # FIXME Handling encoding: UTF-8 to filesystem
        
        self.fd = file(self.file, "rb")
        self.file_name = os.path.basename(self.file)
        self.size = os.fstat(self.fd.fileno()).st_size
        self.bytes_done = 0
        self.percent_done = 0
        self.aborted = False
        self.finished = False
        self.result = None
        
        super(Upload_Thread_FILE, self).__init__(uri, parent, append_list)
    
    def do_upload(self):
        def update_gui(size):
            self.bytes_done = self.bytes_done + size
            self.percent_done = 100.0 * float(self.bytes_done) / float(self.size)
            gobject.idle_add(self.parent.upload_callback, self)
            
            if self.aborted:
                ## Warning: Kludge!
                ## Set a flag to make _file_with_read_callback not return anything from read(),
                ##    this will cause HTTPConnection to end sending data and return from request().
                ##    txtr.delivery_upload_document_file() will then see the flag on fp_with_callback
                ##    and partially close the TCP connection, which should signal an abort to the server
                self.fp_with_callback.aborted = True
            
            if self.harakiri:
                raise self.HarakiriException, "Get me out of here"
        
        self.fp_with_callback = _file_with_read_callback(self.fd, update_gui)
        result = self.parent.txtr.delivery_upload_document_file(
            fp = self.fp_with_callback,
            file_name = self.file_name,
            append_list = self.append_list)
        
        self.result = result
        self.finished = True
        gobject.idle_add(self.parent.upload_callback, self)
    
    def abort(self):
        self.aborted = True

class Upload_Thread_HTTP(Upload_Thread):
    def __init__(self, uri, parent, append_list=None):
        raise NotImplementedError, "HTTP uploads not implemented yet"
        
        super(Upload_Thread_HTTP, self).__init__(uri, parent, append_list)

class Upload_Thread_TEST(Upload_Thread):
    def __init__(self, uri, parent, append_list=None):
        self.size = 9000
        self.file_name = "Test file"
        self.bytes_done = 0
        self.percent_done = 0
        self.finished = False
        self.result = None
        super(Upload_Thread_TEST, self).__init__(uri, parent, append_list)
    
    def do_upload(self):
        for i in xrange(0, self.size, self.size/13 ):
            self.bytes_done = i
            self.percent_done = 100.0 * float(self.bytes_done) / float(self.size)
            gobject.idle_add(self.parent.upload_callback, self)
            
            time.sleep(1)
            
            if self.harakiri:
                raise self.HarakiriException, "Get me out of here"
        
        self.finished = True
        self.result = ("OK", "fubar")
        gobject.idle_add(self.parent.upload_callback, self)

class Document_Widget(gtk.Table, object):
    @classmethod
    def new_from_uri(cls, parent, uri, target=None):
        if target is None:
            append_list = None
            list_name = "No list"
        else:
            append_list = target[0]
            list_name = target[1]
        
        thread = None
        try:
            (scheme,) = uri.split(":",1)[:1]
            c = globals().get("Upload_Thread_%s" % scheme.upper(), None)
            if c is not None:
                thread = c(uri, None, append_list=append_list)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            print e
        
        r = cls(parent, upload_thread=thread, list_name=list_name)
        r.upload_callback(thread)
        return r
    
    @classmethod
    def new_from_document_id(cls, parent, document_id):
        return cls(parent, document_id=document_id)
    
    def __init__(self, parent, document_id = None, upload_thread = None, list_name = None):
        if (document_id is None and upload_thread is None) or \
            (document_id is not None and upload_thread is not None):
                raise TypeError, "Need EITHER document_id OR upload_thread argument"
        
        self._mode = None
        self._parent = parent
        
        gtk.Table.__init__(self, rows=3, columns=3)
        
        self._icon = gtk.image_new_from_stock("gtk-file", gtk.ICON_SIZE_DIALOG)
        self._buttonvbox = gtk.VBox()
        
        self._icon.set_property("xpad", 12)
        self._icon.set_property("ypad", 12)
        
        self.attach(self._icon, 0, 1, 0, 3, gtk.FILL, gtk.FILL)
        self.attach(self._buttonvbox, 2, 3, 0, 3, xoptions=gtk.FILL, yoptions=0)
        
        if upload_thread is not None:
            self._upload_thread = upload_thread
            self._list_name = list_name
            
            self._set_mode("upload")
            
            upload_thread.parent = self
        
        elif document_id is not None:
            self._document_id = document_id
            
            self._set_mode("document")
            
            self._load_document_data()
    
    def _init_upload_mode(self):
        if self._mode is not None: raise RuntimeError, "Can't init upload mode when different mode already active"
        
        self._progress_label = gtk.Label()
        self._progress_bar = gtk.ProgressBar()
        
        self._progress_label.set_property("xpad", 12)
        self._progress_label.set_property("xalign", 0)
        self._progress_bar.set_pulse_step(0.1)
        
        self.attach(self._progress_label, 1, 2, 0, 1, yoptions=0)
        self.attach(self._progress_bar, 1, 2, 1, 2, xpadding=12, yoptions=0)
        
        if hasattr(self._upload_thread, "abort"):
            self._stop_button = gtk.Button()
            self._stop_image = gtk.image_new_from_stock(gtk.STOCK_STOP, gtk.ICON_SIZE_MENU)
            
            self._buttonvbox.pack_start(self._stop_button)
            self._stop_button.set_image(self._stop_image)
            self._stop_button.connect("clicked", self._on_stop_button_clicked)
        
        self._mode = "upload"
    
    def _deinit_upload_mode(self):
        if self._mode != "upload": raise RuntimeError, "Can't deinit upload mode when not active"
        
        self._progress_label.destroy()
        self._progress_bar.destroy()
        
        del self._progress_label
        del self._progress_bar
        
        if hasattr(self._upload_thread, "abort"):
            self._stop_button.destroy()
            del self._stop_button
            del self._stop_image
        
        self._mode = None
    
    def _init_document_mode(self):
        if self._mode is not None: raise RuntimeError, "Can't init document mode when different mode already active"
        self._title_input = gtk.Entry()
        self._author_input = gtk.Entry()
        self._remove_button = gtk.Button()
        self._remove_image = gtk.image_new_from_stock(gtk.STOCK_REMOVE, gtk.ICON_SIZE_MENU)
        
        self._by_label = gtk.Label(str="by ")
        self._online_label = gtk.Label(str="Online: ")
        self._url_button = gtk.LinkButton(uri=self.txtr.DOCUMENT_BASE_URL + self._document_id)
        
        self._author_hbox = gtk.HBox()
        self._url_hbox = gtk.HBox()
        self._middle_vbox = gtk.VBox(spacing=1)
        
        self._title_input.connect("focus-out-event", 
            self._on_document_attribute_focus_out_event, txtr.ATTRIBUTES["title"])
        self._author_input.connect("focus-out-event", 
            self._on_document_attribute_focus_out_event, txtr.ATTRIBUTES["author"])
        self._title_input.connect("activate", 
            self._on_document_attribute_activate, txtr.ATTRIBUTES["title"])
        self._author_input.connect("activate", 
            self._on_document_attribute_activate, txtr.ATTRIBUTES["author"])
        self._url_button.set_property("xalign", 0)
        self._remove_button.set_image(self._remove_image)
        self._remove_button.connect("clicked", self._on_remove_button_clicked)
        
        self._author_hbox.pack_start(self._by_label, False)
        self._author_hbox.pack_start(self._author_input)
        
        self._url_hbox.pack_start(self._online_label, False)
        self._url_hbox.pack_start(self._url_button, True)
        
        self._buttonvbox.pack_start(self._remove_button)
        
        self._middle_vbox.pack_start(self._title_input)
        self._middle_vbox.pack_start(self._author_hbox)
        self._middle_vbox.pack_start(self._url_hbox)
        
        for t in self._title_input, self._author_input:
            t.set_has_frame(False)
            t.set_inner_border(None)
        
        if hasattr(self, "_file_name"):
            self._local_label = gtk.Label(str="Local: %s" % self._file_name)
            self._url_hbox.pack_start(self._local_label, False)
        
        self.attach(self._middle_vbox, 1, 2, 0, 3, yoptions=gtk.EXPAND)
        
        self._mode = "document"
    
    def _deinit_document_mode(self):
        if self._mode != "document": raise RuntimeError, "Can't deinit document mode when not active"
        
        if hasattr(self, "_file_name"):
            self._local_label.destroy()
            del self._local_label
        
        self._middle_vbox.destroy()
        self._remove_button.destroy()
        
        for i in  "_title_input", "_author_input", "_remove_button", "_remove_image", "_by_label", \
            "_online_label", "_url_button", "_author_hbox", "_url_hbox", "_middle_vbox":
                delattr(self, i)
        
        self._mode = None
    
    def _set_mode(self, new_mode):
        if self._mode is not None:
            getattr(self, "_deinit_%s_mode" % self._mode)()
        getattr(self, "_init_%s_mode" % new_mode)()
    
    def start(self):
        if self._mode == "upload":
            self._upload_thread.start()
    def stop(self):
        if self._mode == "upload":
            self._upload_thread.schedule_stop()

    def upload_callback(self, upload):
        "Called from Upload_Thread_* objects to notify about a change in state, update GUI"
        
        ## Update the text field
        if not upload.finished:
            self._progress_label.set_text("%s" % upload.file_name)
        else:
            if upload.result is not None:
                if upload.result[0] == "OK": 
                    additional_info = ", upload OK: %s" % upload.result[1]
                else:
                    additional_info = ", upload error: %s" % upload.result[0]
                    import pprint
                    pprint.pprint(upload.result)
            else:
                additional_info = ""
            self._progress_label.set_text("%s%s" % 
                (upload.file_name, additional_info))
        
        ## Update the progress bar
        if not upload.finished:
            self._progress_bar.set_text("%3.f%%, %i of %i bytes" % 
                (upload.percent_done, upload.bytes_done, upload.size))
            self._progress_bar.set_fraction(float(upload.percent_done) / 100.0)
        else:
            self._progress_bar.set_text("finished")
            self._progress_bar.set_fraction(1)
        
        
        if upload.finished:
            if upload.result[0] == "OK":
                ## Switch modes
                self._file_name = upload.file_name
                self._document_id = upload.result[1]
                self._set_mode("document")
                self.show_all()
                self._load_document_data()
            else:
                self._icon.set_from_stock("gtk-dialog-error", gtk.ICON_SIZE_DIALOG)
    
    def _load_document_data(self):
        self._document = txtr.WSDocMgmt.getDocument(self._parent.txtr.token, self._document_id)
        self._document_image = self._parent.txtr.delivery_download_image(self._document_id, size="SMALL")
        
        self._title_input.set_text(self._document["attributes"][txtr.ATTRIBUTES["title"]])
        self._author_input.set_text(self._document["attributes"][txtr.ATTRIBUTES["author"]])
        
        l = gtk.gdk.PixbufLoader()
        l.write(self._document_image)
        l.close()
        self._icon.set_from_pixbuf(l.get_pixbuf())
    
    def _change_document_attribute(self, attribute, value):
        self._parent.status("change_attribute", "Changing attribute ...")
        try:
            txtr.WSDocMgmt.changeDocumentAttributes(self._parent.txtr.token, [self._document_id],
                {attribute: value})
            self._parent.status("change_attribute", "Reloading document data ...")
            self._load_document_data()
            self._parent.status("change_attribute")
            self._parent.status_temporary(message="Attribute changed.")
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            print e
    
    def _on_stop_button_clicked(self, button):
        if self._upload_thread.finished and self._upload_thread.result[0] != "OK":
            # The Upload is already stopped, remove this document widget instead
            self._on_remove_button_clicked(button)
        elif hasattr(self._upload_thread, "abort"):
            self._upload_thread.abort()
            self._stop_button.set_property("sensitive", False)

    def _on_remove_button_clicked(self, button):
        self.destroy()
    
    def _on_document_attribute_focus_out_event(self, entry, event, attribute):
        value = entry.get_text()
        if self._document["attributes"][attribute] != value:
            self._change_document_attribute(attribute, value)

    def _on_document_attribute_activate(self, entry, attribute):
        value = entry.get_text()
        if self._document["attributes"][attribute] != value:
            self._change_document_attribute(attribute, value)

    txtr = property(lambda self: self._parent.txtr)


GLADE_FILE = "uploader.glade"
DRY_RUN = False
class Upload_GUI(object):
    _DRAG_INFO_URI = 1
    _DRAG_INFO_TEXT = 2
    GCONF_DIRECTORY = "/apps/txtr"
    
    class login_data_model_view(object):
        def __init__(self, parent, gconf_client, username_entry, password_entry):
            self.parent = parent
            self.gconf_client = gconf_client
            self.username_entry = username_entry
            self.password_entry = password_entry
            
            self.gconf_client.add_dir(self.parent.GCONF_DIRECTORY, gconf.CLIENT_PRELOAD_ONELEVEL)
            self.gconf_client.notify_add(self.parent.GCONF_DIRECTORY + "/username", self.gconf_changed_username)
            self.gconf_client.notify_add(self.parent.GCONF_DIRECTORY + "/password", self.gconf_changed_password)
            
            self.load()
        
        def gconf_changed_username(self, client, connection_id, value, *args):
            old = self.username_entry.get_text()
            new = value.value.to_string()
            if new != old:
                self.username_entry.set_text(new)
                self.parent.login_data_changed()
        
        def gconf_changed_password(self, client, connection_id, value, *args):
            old = self.password_entry.get_text()
            new = value.value.to_string()
            if new != old:
                self.password_entry.set_text(new)
                self.parent.login_data_changed()
        
        def save(self):
            changed = False
            u = self.username_entry.get_text()
            p = self.password_entry.get_text()
            if self.username != u:
                self.gconf_client.set_string(self.parent.GCONF_DIRECTORY + "/username", u)
                self.username = u
                changed = True
            if self.password != p:
                self.gconf_client.set_string(self.parent.GCONF_DIRECTORY + "/password", p)
                self.password = p
                changed = True
            if changed:
                self.parent.login_data_changed()
        
        def load(self):
            self.username = self.gconf_client.get_string(self.parent.GCONF_DIRECTORY + "/username")
            self.password = self.gconf_client.get_string(self.parent.GCONF_DIRECTORY + "/password")
            
            if self.username:
                self.username_entry.set_text(self.username)
            if self.password:
                self.password_entry.set_text(self.password)

    
    def __init__(self):
        self.main_window_xml = gtk.glade.XML(GLADE_FILE, "uploader_main")
        self.main_window = self.main_window_xml.get_widget("uploader_main")
        
        self.about_window_xml = gtk.glade.XML(GLADE_FILE, "uploader_about")
        self.about_window = self.about_window_xml.get_widget("uploader_about")
        self.about_window.set_transient_for(self.main_window)
        
        self.preferences_window_xml = gtk.glade.XML(GLADE_FILE, "uploader_preferences")
        self.preferences_window = self.preferences_window_xml.get_widget("uploader_preferences")
        self.preferences_window.set_transient_for(self.main_window)
        
        for i in "statusbar", "target", "documents_vbox", "documents_viewport":
            setattr(self, i, self.main_window_xml.get_widget(i))
        
        self.bg_pixbuf = gtk.gdk.pixbuf_new_from_file("bg_txtrSynchronizer.png")
        self.idle_image = gtk.image_new_from_pixbuf(self.bg_pixbuf)
        self.documents_vbox.pack_start(self.idle_image)
        self.idle_image.show()
        
        self.main_window_xml.signal_autoconnect(self)
        self.main_window.show()
        self.main_window.drag_dest_set(gtk.DEST_DEFAULT_ALL, [
                ("text/uri-list", 0, self._DRAG_INFO_URI),
                ("text/plain", 0, self._DRAG_INFO_TEXT),
            ], gtk.gdk.ACTION_COPY | gtk.gdk.ACTION_MOVE | gtk.gdk.ACTION_DEFAULT)
        
        gtk.quit_add(0, self.fast_shutdown)
        
        self.documents = []
        
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
        
        ## Prepare gconf, read config. Login if username/password available, otherwise display preferences
        self.gconf_client = gconf.client_get_default()
        self.login_data = self.login_data_model_view(self, self.gconf_client,
            self.preferences_window_xml.get_widget("username_input"),
            self.preferences_window_xml.get_widget("password_input"))
        
        self.txtr_dirty = False
        if not (self.login_data.username and self.login_data.password):
            self.on_preferences_activate(None)
        
        self.do_login()
    
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
    
    def on_preferences_activate(self, menuitem):
        result = self.preferences_window.run()
        self.preferences_window.hide()
        if result == gtk.RESPONSE_ACCEPT:
            self.login_data.save()
            if self.txtr_dirty:
                self.do_logout()
                self.do_login()
        else:
            self.login_data.load()
        self.txtr_dirty = False
    
    ## Indirectly called/utility methods
    def check_txtr(self):
        "Returns true when login to txtr was successful"
        if not hasattr(self, "txtr"):
            self.status_temporary("error", "Can't upload file without login data", timeout=5000)
            return False
        return True
    
    def add_upload(self, uri):
        "Add and start an upload"
        
        if not self.check_txtr(): return
        
        target_list = self.target.get_active()
        if target_list == -1:
            target = None
        else:
            target = self.available_lists[target_list]
        
        document = None
        try:
            document = Document_Widget.new_from_uri(self, uri, target)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            print e
        
        if document is not None:
            if len(self.documents) == 0:
                self.documents_vbox.remove(self.idle_image)
            self.documents.append(document)
            document.connect("destroy", self.remove_document)
            self.documents_vbox.pack_start(document, expand=False)
            document.show_all()
            document.start()
    
    def add_document(self, document_id):
        if not self.check_txtr(): return
        
        document = None
        try:
            document = Document_Widget.new_from_document_id(self, document_id)
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            print e
        
        if document is not None:
            self.documents.append(document)
            document.connect("destroy", self.remove_document)
            self.documents_vbox.remove(self.idle_image)
            self.documents_vbox.pack_start(document, expand=False)
            document.show_all()
    
    def remove_document(self, document):
        self.documents.remove(document)
        if len(self.documents) == 0:
            self.documents_vbox.pack_start(self.idle_image)
    
    def do_login(self):
        ## Set up API and log in
        if hasattr(self, "txtr"): return
        
        if not (self.login_data.username and self.login_data.password):
            self.status(message="Please set login data in preferences")
            return
        
        self.txtr = txtr.txtr(username=self.login_data.username, password=self.login_data.password)
        self.txtr_dirty = False
        if not DRY_RUN:
            self.status("login", "Login to txtr.com API ...")
            result = self.txtr.login()
            self.status("login")
            
            if not result:
                self.status(message="Login not ok, please check username and password")
                del self.txtr
                return
            
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
    
    def do_logout(self):
        if not hasattr(self, "txtr"): return
        
        self.status("login", "Logging out ...")
        self.txtr.logout()
        self.status("login")
        self.status(message="Logout ok")
        
        for i in range(len(self.available_lists)):
            self.target.remove_text(0)
        self.available_lists = []
        
        del self.txtr
    
    def login_data_changed(self):
        self.txtr_dirty = True
    
    def do_shutdown(self):
        for document in self.documents:
            document.stop()
        
        self.do_logout()
        
        self.main_window.destroy()
    
    def fast_shutdown(self): # Log out in any case upon termination of the main loop
        if not hasattr(self, "txtr"): return
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
    
    def status_temporary(self, context=None, message=None, timeout=5000):
        self.status(context, message, pump_events=False)
        gobject.timeout_add(timeout, lambda: self.status(context, message=None, pump_events=False) or False)
    
    def pump_events(self):
        "Process all pending GUI events, e.g. update the GUI."
        while gtk.events_pending():
            gtk.main_iteration()

if __name__ == "__main__":
    gtk.gdk.threads_init()
    
    g = Upload_GUI()
    if False:
        gobject.idle_add(lambda: g.add_upload("test://1") and None)
        gobject.timeout_add(5000, lambda: g.add_upload("test://2") and None )
        gobject.timeout_add(6000, lambda: g.add_upload("test://2") and None )
    if False:
        gobject.idle_add(lambda: g.add_document("ah8mg9") and None)
    gtk.main()
