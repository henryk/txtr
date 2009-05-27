#!/usr/bin/env python

import sys, txtr, re, urllib, os, threading, time, locale, gettext
import pkg_resources

APP_NAME = "txtr_uploader"
LOCALE_DIR = "locale"
_ = gettext.gettext

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
    
    def fileno(self):      return self.f.fileno()
    def close(self):       return self.f.close()
    def __len__(self):     return self.size
    def __nonzero__(self): return 1
    
class Upload_Thread(object):
    def __init__(self, uri, parent, append_list=None):
        self.uri = uri
        self.parent = parent
        self.append_list = append_list
        self.started = False
        self.harakiri = False
        self.finished = False
        self.result = None
        
        self.thread = threading.Thread(target=self.run)
    
    def start(self): self.thread.start()
    def schedule_stop(self): self.harakiri = True
    class HarakiriException(Exception): pass
    
    def run(self):
        self.started = True
        try:
            try:
                self.do_upload()
            except self.HarakiriException:
                pass
            except Exception, e:
                if not self.finished:
                    self.finished = True
                    self.result = ("Exception", e)
                    gobject.idle_add(self.parent.upload_callback, self)
                raise
        finally:
            if not self.finished:
                self.finished = True
                self.result = ("Unexpected thread end")
                gobject.idle_add(self.parent.upload_callback, self)

class Upload_Thread_FILE(Upload_Thread):
    MOVE_HACK = False
    
    def __init__(self, uri, parent, append_list=None):
        if not uri.lower().startswith("file:///"):
            raise ValueError, "Unsupported file uri format: %r" % uri
        self.file = urllib.unquote( uri[len("file://"):] ) # FIXME: Handling encoding: UTF-8 to filesystem
        
        self.fd = file(self.file, "rb")
        self.source = os.path.basename(self.file) ## Human readable simplified source name
        self.size = os.fstat(self.fd.fileno()).st_size
        self.bytes_done = 0
        self.percent_done = 0
        self.aborted = False
        
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
        
        if self.aborted:
            self.result = ("Aborted",)
            self.finished = True
            gobject.idle_add(self.parent.upload_callback, self)
            return
        
        self.fp_with_callback = _file_with_read_callback(self.fd, update_gui)
        result = self.parent.txtr.delivery_upload_document_file(
            fp = self.fp_with_callback,
            file_name = self.source,
            append_list = (not self.MOVE_HACK) and self.append_list or None)
        
        if self.MOVE_HACK and result[0] == "OK":
            ## Append the document to its list after the upload is complete, preventing
            ## an exception due to the transactional nature of reaktor operations.
            ## Note: This means that documents will be appended to their lists in order
            ##  of upload completion, not in the order their uploads were started
            ## Warning: This leaves a window of opportunity where the document is not in
            ##  any list
            def delayed_work(): # Operate in a call-back to be synchronized with respect to the main loop
                self.parent.txtr.add_documents_to_list([result[1]], self.append_list)
            gobject.idle_add(delayed_work)
        
        self.result = result
        self.finished = True
        gobject.idle_add(self.parent.upload_callback, self)
    
    def abort(self):
        self.aborted = True
        if not self.started:
            self.result = ("Aborted",)
            self.finished = True
            gobject.idle_add(self.parent.upload_callback, self)

class Upload_Thread_HTTP(Upload_Thread):
    def __init__(self, uri, parent, append_list=None):
        self.size = None
        self.source = uri
        self.uri = uri
        self.bytes_done = None
        self.percent_done = None
        
        super(Upload_Thread_HTTP, self).__init__(uri, parent, append_list)
    
    def do_upload(self):
        def update_gui():
            ## Ping the GUI every once in a while, using the idle loop
            gobject.idle_add(self.parent.upload_callback, self)
            
            if self.finished and self.append_list is not None:
                if self.result[0] == "OK":
                    ## Do the list append here, synchronized within the main loop
                    self.parent.txtr.add_documents_to_list([self.result[1]], 
                        append_to=self.append_list)
            
            return not self.finished
        
        gobject.timeout_add(100, update_gui)
        
        ## Don't do the list append here
        document_id = self.parent.txtr.create_from_web(self.source, append_to=None)
        
        if document_id is not None:
            self.result = ("OK", document_id)
        else:
            self.result = ("Upload error")
        self.finished = True

class Upload_Thread_HTTPS(Upload_Thread_HTTP): pass

class Upload_Thread_TEST(Upload_Thread):
    def __init__(self, uri, parent, append_list=None):
        self.size = 9000
        self.source = "Test file"
        self.bytes_done = 0
        self.percent_done = 0
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
    MAXIMUM_ICON_SIZE_X = 48
    MAXIMUM_ICON_SIZE_Y = 72
    
    @classmethod
    def new_from_uri(cls, parent, uri, target_list=None, target_name=None):
        if target_list is None:
            append_list = None
            list_name = _("No list")
        else:
            append_list = target_list
            list_name = target_name
        
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
    def new_from_document_id(cls, parent, document_id, read_only=False, remove_button=True):
        return cls(parent, document_id=document_id, read_only=read_only, remove_button=remove_button)
    
    def __init__(self, parent, document_id = None, upload_thread = None, list_name = None, read_only=False, remove_button=True):
        if (document_id is None and upload_thread is None) or \
            (document_id is not None and upload_thread is not None):
                raise TypeError, "Need EITHER document_id OR upload_thread argument"
        
        self._mode = None
        self._parent = parent
        self._read_only = read_only
        self._show_remove_button = remove_button
        
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
        self._target_label = gtk.Label()
        self._progress_bar = gtk.ProgressBar()
        
        self._progress_label.set_property("xpad", 12)
        self._progress_label.set_property("xalign", 0)
        self._target_label.set_property("xpad", 12)
        self._target_label.set_property("xalign", 0)
        self._progress_bar.set_pulse_step(0.1)
        
        self._target_label.set_text(_("Target list: %(folder)s") % {
            "folder": self._list_name
        })
        
        self.attach(self._progress_label, 1, 2, 0, 1, yoptions=0)
        self.attach(self._target_label, 1, 2, 2, 3, yoptions=0)
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
        self._target_label.destroy()
        self._progress_bar.destroy()
        
        del self._progress_label
        del self._target_label
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
        
        if self._show_remove_button:
            self._buttonvbox.pack_start(self._remove_button)
        
        self._middle_vbox.pack_start(self._title_input)
        self._middle_vbox.pack_start(self._author_hbox)
        self._middle_vbox.pack_start(self._url_hbox)
        
        for t in self._title_input, self._author_input:
            t.set_has_frame(False)
            t.set_inner_border(None)
            if self._read_only:
                t.set_property("editable", False)
        
        if hasattr(self, "_source"):
            self._local_label = gtk.Label(str=_("Source: %s") % self._source)
            self._url_hbox.pack_start(self._local_label, False)
        
        self.attach(self._middle_vbox, 1, 2, 0, 3, yoptions=gtk.EXPAND)
        
        self._mode = "document"
    
    def _deinit_document_mode(self):
        if self._mode != "document": raise RuntimeError, "Can't deinit document mode when not active"
        
        if hasattr(self, "_source"):
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
            if not self._upload_thread.finished:
                self._upload_thread.start()
    def stop(self):
        if self._mode == "upload":
            self._upload_thread.schedule_stop()

    def upload_callback(self, upload):
        "Called from Upload_Thread_* objects to notify about a change in state, update GUI"
        
        ## Update the text field
        if not upload.finished:
            self._progress_label.set_text("%s" % upload.source)
        else:
            if upload.result is not None:
                if upload.result[0] == "OK": 
                    additional_info = _(", upload OK: %s") % upload.result[1]
                elif upload.result[0] == "Aborted":
                    additional_info = _(", upload aborted by user")
                else:
                    additional_info = _(", upload error: %s") % upload.result[0]
                    import pprint
                    pprint.pprint(upload.result)
            else:
                additional_info = ""
            self._progress_label.set_text("%s%s" % 
                (upload.source, additional_info))
        
        ## Update the progress bar
        if not upload.started:
            self._progress_bar.set_text(_("Waiting for other upload(s) to finish"))
            self._progress_bar.set_fraction(0)
        elif not upload.finished:
            if upload.size is not None:
                self._progress_bar.set_text(_("%(percent)3.f%%, %(done)i of %(size)i bytes") % { 
                    "percent": upload.percent_done, 
                    "done": upload.bytes_done, 
                    "size": upload.size})
                self._progress_bar.set_fraction(float(upload.percent_done) / 100.0)
            else:
                self._progress_bar.set_text(_("Upload in progress ..."))
                self._progress_bar.set_pulse_step(0.05)
                self._progress_bar.pulse()
        else:
            self._progress_bar.set_text(_("finished"))
            self._progress_bar.set_fraction(1)
        
        
        if upload.finished:
            if upload.result[0] == "OK":
                ## Switch modes
                self._source = upload.source
                self._document_id = upload.result[1]
                self._set_mode("document")
                self.show_all()
                self._load_document_data()
                gobject.idle_add(self._parent.upload_finished, self)
            elif upload.result[0] == "Aborted":
                self.destroy()
            else:
                self._icon.set_from_stock("gtk-dialog-error", gtk.ICON_SIZE_DIALOG)
                gobject.idle_add(self._parent.upload_finished, self)
    
    def is_finished(self):
        if self._mode != "upload": return True
        return self._upload_thread.finished
    
    def _load_document_data(self):
        self._document = txtr.WSDocMgmt.getDocument(self._parent.txtr.token, self._document_id)
        self._document_image = self._parent.txtr.delivery_download_image(self._document_id, size="SMALL")
        
        self._title_input.set_text(self._document["attributes"][txtr.ATTRIBUTES["title"]])
        self._author_input.set_text(self._document["attributes"][txtr.ATTRIBUTES["author"]])
        
        l = gtk.gdk.PixbufLoader()
        l.write(self._document_image)
        l.close()
        
        ## Scale
        pixbuf = l.get_pixbuf()
        scaled_h = float(pixbuf.get_height())
        scaled_w = float(pixbuf.get_width())
        scale = False
        
        if scaled_h > self.MAXIMUM_ICON_SIZE_Y:
            factor = scaled_h / float(self.MAXIMUM_ICON_SIZE_Y)
            scaled_h = scaled_h / factor
            scaled_w = scaled_w / factor
            scale = True
        if scaled_w > self.MAXIMUM_ICON_SIZE_X:
            factor = scaled_w / float(self.MAXIMUM_ICON_SIZE_X)
            scaled_h = scaled_h / factor
            scaled_w = scaled_w / factor
            scale = True
        if scale:
            pixbuf = pixbuf.scale_simple(int(scaled_w), int(scaled_h), gtk.gdk.INTERP_HYPER)
        
        xpad, ypad = self._icon.get_padding()
        self._icon.set_from_pixbuf(pixbuf)
        self._icon.set_size_request(self.MAXIMUM_ICON_SIZE_X + 2*xpad, self.MAXIMUM_ICON_SIZE_Y + 2*ypad)
    
    def _change_document_attribute(self, attribute, value):
        self._parent.status("change_attribute", _("Changing attribute ..."))
        try:
            txtr.WSDocMgmt.changeDocumentAttributes(self._parent.txtr.token, [self._document_id],
                {attribute: value})
            self._parent.status("change_attribute")
            self._parent.status("change_attribute", _("Reloading document data ..."))
            self._load_document_data()
            self._parent.status("change_attribute")
            self._parent.status_temporary(message=_("Attribute changed."))
        except (SystemExit, KeyboardInterrupt):
            raise
        except Exception, e:
            self._parent.status("change_attribute")
            self._parent.status(message=_("Error while trying to change attribute"))
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
        return False

    def _on_document_attribute_activate(self, entry, attribute):
        value = entry.get_text()
        if self._document["attributes"][attribute] != value:
            self._change_document_attribute(attribute, value)

    txtr = property(lambda self: self._parent.txtr)

class Lostfound_Dialog(object):
    def __init__(self, parent, gconf_client, parent_window=None):
        self.parent = parent
        self.gconf_client = gconf_client
        self.parent_window = parent_window
        self.unlisted_ids = []
    
    def run_conditionally(self):
        action = self.default_action
        if action == self.DEFAULT_ACTION_NOCHECK: 
            return
        
        if not hasattr(self.parent, "txtr"): return
        
        self.parent.status("lostfound", _("Retrieving lost texts ..."))
        try:
            self.unlisted_ids = txtr.WSDocMgmt.getUnlistedDocumentIDs(self.txtr.token)
        finally:
            self.parent.status("lostfound", pump_events=False)
        
        if len(self.unlisted_ids) == 0:
            self.parent.status_temporary("lostfound", _("No lost texts found"), timeout=1000)
            return
        
        self.parent.status("lostfound", _("Found %(count)i unlisted texts") % {
            "count": len(self.unlisted_ids),
        })
        
        try:
            if action == self.DEFAULT_ACTION_APPEND:
                self.do_append()
            else:
                self.run()
        finally:
            self.parent.status("lostfound")
        
    
    def do_append(self):
        self.parent.status("lostfound", _("Appending texts to the inbox ..."))
        try:
            try:
                self.txtr.add_documents_to_list(self.unlisted_ids, append_to="INBOX")
            finally:
                self.parent.status("lostfound")
        except:
            self.parent.status(_("Exception while trying to append to the inbox"))
        else:
            self.parent.status_temporary(message=_("Appended %(count)i texts to the inbox") % {
                "count": len(self.unlisted_ids),
            })
    
    def run(self):
        lostfound_dialog_xml = gtk.glade.XML(GLADE_FILE, "uploader_lostfound")
        lostfound_dialog = lostfound_dialog_xml.get_widget("uploader_lostfound")
        lostfound_documents = lostfound_dialog_xml.get_widget("lostfound_documents")
        lostfound_no_ask_again = lostfound_dialog_xml.get_widget("lostfound_no_ask_again")
        
        def delayed_add(): ## Add the documents in the idle loop to feign responsiveness
            for document_id in self.unlisted_ids:
                document = None
                try:
                    document = Document_Widget.new_from_document_id(self, document_id, 
                        read_only=True, remove_button=False)
                except (SystemExit, KeyboardInterrupt):
                    raise
                except Exception, e:
                    print e
                
                if document is not None:
                    lostfound_documents.pack_start(document, expand=False)
                    document.show_all()
                
                yield True
            
            yield False
        gobject.idle_add(delayed_add().next)
        
        if self.parent_window is not None:
            lostfound_dialog.set_transient_for(self.parent_window)
        response = lostfound_dialog.run()
        no_ask_again = lostfound_no_ask_again.get_active()
        lostfound_dialog.destroy()
        
        if response == gtk.RESPONSE_ACCEPT:
            if no_ask_again:
                self.default_action = self.DEFAULT_ACTION_APPEND
            self.do_append()
        elif response == gtk.RESPONSE_REJECT:
            if no_ask_again:
                self.default_action = self.DEFAULT_ACTION_NOCHECK
    
    DEFAULT_ACTION_UNSET = 0   ## 0 = unset (default to ASK)
    DEFAULT_ACTION_NOCHECK = 1 ## 1 = Don't check
    DEFAULT_ACTION_ASK = 2     ## 2 = Ask each time
    DEFAULT_ACTION_APPEND = 3  ## 3 = Append automatically
    default_action = property(
        lambda self: self.gconf_client.get_int(self.parent.GCONF_DIRECTORY + "/lostfound_action") or 2,
        lambda self, val: self.gconf_client.set_int(self.parent.GCONF_DIRECTORY + "/lostfound_action", val)
    )
    
    txtr = property(lambda self: self.parent.txtr)

class Preferences(object):
    class Preference_Setting(object):
        def __init__(self, name, type, field_name, default = None, gconf_name = None):
            """name is the attribute name this setting will be available in the parent Preferences as
            type is the type of the attribute and gconf entry, one of: str, int, bool
            field_name is either a Glade widget name that should be updated with changes from gconf
                and read from to update gconf (upon Dialog confirmation), or a callable which will
                be called with three arguments to get the value and with four arguments to set the value
                    for get: def callback(preference_setting, preferences, dialog_xml)
                    for set: def callback(preference_setting, preferences, dialog_xml, value)
            default is either the default value for the setting, or a callable that will be called
                with one argument to get the value if no value is set
            gconf_name is the key name in gconf, defaults to name"""
            
            if type not in (str, int, bool):
                raise ValueError, "type must be one of str, int, bool, and not %r" % type
            
            self.name = name
            self.type = type
            self.field_name = field_name
            self.default = default
            if gconf_name is None: self.gconf_name = name
            else: self.gconf_name = gconf_name
            
            self._notifications = {}
        
        def _get(self, parent):
            r = parent.gconf_client.get(parent.gconf_directory + "/" + self.gconf_name)
            if r is None:
                if hasattr(self.default, "__call__"):
                    return self.default(self)
                else:
                    return self.default
            
            if self.type == str:
                return r.get_string()
            elif self.type == int:
                return r.get_int()
            elif self.type == bool:
                return r.get_bool()
        
        def _set(self, parent, value):
            if self.type == str:
                parent.gconf_client.set_string(parent.gconf_directory + "/" + self.gconf_name, value)
            elif self.type == int:
                parent.gconf_client.set_int(parent.gconf_directory + "/" + self.gconf_name, value)
            elif self.type == bool:
                parent.gconf_client.set_bool(parent.gconf_directory + "/" + self.gconf_name, value)
        
        def _gconf_changed(self, client, connection_id, value, parent):
            parent.call_changed_cb(self)
        
        def _connect_signals(self, parent, dialog_xml):
            self._notifications[id(dialog_xml)] = \
                parent.gconf_client.notify_add(parent.gconf_directory + "/" + self.gconf_name,
                    self._gconf_changed_while_editing, (parent, dialog_xml))
            
            if not isinstance(self.field_name, basestring): return
            widget = dialog_xml.get_widget(self.field_name)
            
            if isinstance(widget, gtk.Entry):
                widget.connect("activate", self._on_entry_activate, parent, dialog_xml)
                widget.connect("focus-out-event", self._on_entry_focus_out_event, parent, dialog_xml)
        
        def _gconf_changed_while_editing(self, client, connection_id, value, args):
            parent, dialog_xml = args
            self._load_field(parent, dialog_xml)
        
        def _disconnect_signals(self, parent, dialog_xml):
            notification_id = self._notifications.get(id(dialog_xml), None)
            if notification_id is not None:
                parent.gconf_client.notify_remove(notification_id)
                del self._notifications[id(dialog_xml)]
            
            ## Widget signals are auto-disconnected when the dialog window is destroyed
        
        def _load_field(self, parent, dialog_xml):
            if hasattr(self.field_name, "__call__"):
                self.field_name(self, parent, dialog_xml)
                return
            
            if not isinstance(self.field_name, basestring): return
            widget = dialog_xml.get_widget(self.field_name)
            
            if hasattr(widget, "set_text"):
                widget.set_text(str(self._get(parent)))
        
        def _on_entry_activate(self, entry, parent, dialog_xml): 
            return self._entry_event(entry, parent, dialog_xml)
        def _on_entry_focus_out_event(self, widget, event, parent, dialog_xml): 
            return self._entry_event(widget, parent, dialog_xml)
        
        def _entry_event(self, entry, parent, dialog_xml):
            if self.type == str:
                self._set(parent, entry.get_text())
            elif self.type == int:
                self._set(parent, int(entry.get_text()))
            elif self.type == bool:
                self._set(parent, bool(entry.get_text()))
            return False
    
    PREFERENCES = [
        Preference_Setting("username", str, "username_input", ""),
        Preference_Setting("password", str, "password_input", ""),
    ]
    
    def __init__(self, parent, gconf_client):
        self.parent = parent
        self.gconf_client = gconf_client
        self.gconf_directory = self.parent.GCONF_DIRECTORY
        self.changed_cb = []
        self.dirty = None
        self.gconf_client.add_dir(self.gconf_directory, gconf.CLIENT_PRELOAD_ONELEVEL)
        
        for p in self.PREFERENCES:
            self.gconf_client.notify_add(self.gconf_directory + "/" + p.gconf_name, p._gconf_changed, self)
    
    def __getattr__(self, name):
        for p in self.PREFERENCES:
            if p.name == name: return p._get(self)
        return super(Preferences, self).__getattr__(name)

    def __setattr__(self, name, value):
        for p in self.PREFERENCES:
            if p.name == name: return p._set(self, value)
        return super(Preferences, self).__setattr__(name, value)
    
    def add_changed_listener(self, cb):
        self.changed_cb.append(cb)
    def del_changed_listener(self, cb):
        self.changed_cb.remove(cb)
    
    def call_changed_cb(self, *args, **kwargs):
        print "Something's changed %s %s" % (args, kwargs)
        if self.dirty is None: ## Change callbacks go out directly
            for cb in self.changed_cb:
                cb(self, *args, **kwargs)
        elif self.dirty == False: ## Changes are cumulated and whoever set dirty to False is responsible for them
            self.dirty = True
    
    def run(self, parent_window=None):
        dialog_xml = gtk.glade.XML(GLADE_FILE, "uploader_preferences")
        dialog = dialog_xml.get_widget("uploader_preferences")
        
        if parent_window is not None:
            dialog.set_transient_for(parent_window)
        
        self.dirty = self.dirty or False ## Set to False if it was None, True if it was True
        
        for p in self.PREFERENCES:
            p._connect_signals(self, dialog_xml)
            p._load_field(self, dialog_xml)
        
        response = dialog.run()
        
        for p in self.PREFERENCES:
            p._disconnect_signals(self, dialog_xml)
        
        dialog.destroy()
        
        if self.dirty:
            self.dirty = None
            self.call_changed_cb()
            return True
        else:
            self.dirty = None
            return False

GLADE_FILE = pkg_resources.resource_filename(__name__, "uploader.glade")
DRY_RUN = False
class Upload_GUI(object):
    _DRAG_INFO_URI = 1
    _DRAG_INFO_TEXT = 2
    GCONF_DIRECTORY = "/apps/txtr"
    
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
        self.current_upload = None
        self.available_lists = gtk.TreeStore(str, str)
        self.target.set_model(self.available_lists)
        
        ## Prepare file chooser filters
        patterns = (
            (_("Adobe PDF files"), "*.[pP][dD][fF]"),
            (_("Microsoft PowerPoint presentations"), "*.[pP][pP][tT]", "*.[pP][pP][tT][xX]"),
            (_("Microsoft Word documents"), "*.[dD][oO][cC]", "*.[dD][oO][cC][xX]"),
            (_("Microsoft Excel sheets"), "*.[xX][lL][sS]", "*.[xX][lL][sS][xX]"),
            (_("All files"), "*"),
        )
        self.uploader_chooser_filters = []
        for pattern in patterns:
            f = gtk.FileFilter()
            f.set_name(pattern[0])
            for p in pattern[1:]: f.add_pattern(p)
            self.uploader_chooser_filters.append(f)
        
        ## Prepare gconf, read config. Login if username/password available, otherwise display preferences
        self.gconf_client = gconf.client_get_default()
        self.preferences = Preferences(self, self.gconf_client)
        
        self.txtr_dirty = False
        self.preferences.add_changed_listener(self.login_data_changed)
        if not (self.preferences.username and self.preferences.password):
            self.on_preferences_activate(None)
        
        self.do_login()
    
    ## Autoconnected signal handlers ##
    def on_uploader_main_destroy(self, widget):
        gtk.main_quit()
    
    def on_exit_clicked(self, menuitem):                    self.do_shutdown()
    def on_uploader_main_delete_event(self, widget, event): self.do_shutdown()
    
    def on_upload_activate(self, menuitem):
        "Callback for activation of menu File -> Upload"
        c = gtk.FileChooserDialog(_("Select file to upload"), parent=self.main_window,
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
        result = self.preferences.run(self.main_window)
        if self.txtr_dirty: ## Changes were made
            self.do_logout()
            self.do_login()
        self.txtr_dirty = False
    
    ## Indirectly called/utility methods
    def check_txtr(self):
        "Returns true when login to txtr was successful"
        if not hasattr(self, "txtr"):
            self.status_temporary("error", _("Can't upload file without login data"), timeout=5000)
            return False
        return True
    
    def add_upload(self, uri):
        "Add and start an upload"
        
        if not self.check_txtr(): return
        
        target_list = self.target.get_active_iter()
        if target_list is None:
            target = None
        else:
            target = self.available_lists[target_list]
        
        document = None
        try:
            document = Document_Widget.new_from_uri(self, uri, target[1], target[0])
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
        
        self.start_next_document_to_upload()
    
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
    
    def upload_finished(self, document):
        "Called from Document_Widget.upload_callback()"
        if self.current_upload == document:
            self.current_upload = None
        self.start_next_document_to_upload()
    
    def start_next_document_to_upload(self):
        if self.current_upload is not None: return
        
        next_upload = None
        for document in self.documents_vbox.get_children():
            if not isinstance(document, Document_Widget): continue
            if not document.is_finished() and next_upload is None: next_upload = document
        
        if next_upload is not None:
            self.current_upload = next_upload
            next_upload.start()
    
    def do_login(self):
        ## Set up API and log in
        if hasattr(self, "txtr"): return
        
        if not (self.preferences.username and self.preferences.password):
            self.status(message=_("Please set login data in preferences"))
            return
        
        self.txtr = txtr.txtr(username=self.preferences.username, password=self.preferences.password)
        self.txtr_dirty = False
        if not DRY_RUN:
            self.status(message=None, pump_events=False) # Clear default context
            self.status("login", _("Login to txtr.com API ..."))
            result = self.txtr.login()
            self.status("login")
            
            if not result:
                self.status(message=_("Login not ok, please check username and password"))
                del self.txtr
                return
            
            self.status(message=_("Login ok"))
        
        ## Retrieve lists and set up drop-down menu
        self.status("lists", _("Retrieving user's lists ..."))
        if not DRY_RUN:
            lists, views = self.txtr.get_lists_and_views()
            inbox_id = self.txtr.get_special_list("INBOX").get("ID", None)
            trash_id = self.txtr.get_special_list("TRASH").get("ID", None)
        else:
            views = [{"name": "My Texts", "ID": "foo", "children_lists": ("bar",)}]
            lists = [{"name": "Private Texts", "ID": "bar"}, {"name": "INBOX", "ID":"baz"}]
            inbox_id = None
            trash_id = None
        
        inbox_iter = None
        for view in views:
            if view["name"] is None: continue
            
            if len(view["children_lists"]) > 0:
                last_view = self.available_lists.append(None, (view["name"], None) )
                # FIXME: Prevent the user from selecting these entries
            
            for child in view["children_lists"]:
                list = [l for l in lists if l["ID"] == child]
                if len(list) == 0: continue
                list = list[0]
                list["consumed"] = True
                
                if list["ID"] == inbox_id: list["name"] = _("Inbox")
                if list["ID"] == trash_id: list["name"] = _("Trash")
                
                if list["ID"] == inbox_id and inbox_iter is None:
                    inbox_iter = self.available_lists.prepend(last_view, (list["name"], list["ID"]) )
                else:
                    self.available_lists.append(last_view, (list["name"], list["ID"]) )
        
        for list in lists: # The remaining lists (not in any view set)
            if list.has_key("consumed") and list["consumed"]: continue
            
            if list["ID"] == inbox_id: list["name"] = _("Inbox")
            if list["ID"] == trash_id: list["name"] = _("Trash")
            
            if list["ID"] == inbox_id and inbox_iter is None:
                inbox_iter = self.available_lists.prepend(None, (list["name"], list["ID"]) )
            else:
                self.available_lists.append(None, (list["name"], list["ID"]) )
        
        if inbox_iter is not None:
            self.target.set_active_iter(inbox_iter)
        self.status("lists")
        
        lostfound = Lostfound_Dialog(parent=self, gconf_client=self.gconf_client, parent_window=self.main_window)
        if not DRY_RUN:
            lostfound.run_conditionally()
    
    def do_logout(self):
        if not hasattr(self, "txtr"): return
        
        self.status("login", _("Logging out ..."))
        self.txtr.logout()
        self.status("login")
        self.status(message=_("Logout ok"))
        
        self.available_lists.clear()
        
        del self.txtr
    
    def login_data_changed(self, *args, **kwargs):
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

def main():
    gtk.gdk.threads_init()
    
    for module in (gettext, gtk.glade):
        module.bindtextdomain(APP_NAME, LOCALE_DIR)
        module.textdomain(APP_NAME)
    
    g = Upload_GUI()
    if False:
        gobject.idle_add(lambda: g.add_upload("test://1") and None)
        gobject.timeout_add(5000, lambda: g.add_upload("test://2") and None )
        gobject.timeout_add(6000, lambda: g.add_upload("test://2") and None )
    if False:
        gobject.idle_add(lambda: g.add_document("ah8mg9") and None)
    gtk.main()

if __name__ == "__main__":
    main()
