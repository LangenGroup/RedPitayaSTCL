# -*- coding: utf-8 -*-
"""
Created on Tue May 10 10:19:27 2022

@author: epultinevicius
"""
import selectors, struct, json, io, sys

class Message:
    def __init__(self, selector, sock, addr, action_dict = None, stop = True):
        self.sock = sock
        self.selector = selector
        self.addr = addr
        self.action_dict = action_dict
        self._recv_buffer = b""
        self._send_buffer = b""
        self._jsonheader_len = None
        self.jsonheader = None
        self.request = None
        self.response_created = False
        self.stop = stop # whether to stop after one message

    def _set_selector_events_mask(self, mode):
        """Set selector to listen for events: mode is 'r', 'w', or 'rw'."""
        if mode == "r":
            events = selectors.EVENT_READ
        elif mode == "w":
            events = selectors.EVENT_WRITE
        elif mode == "rw":
            events = selectors.EVENT_READ | selectors.EVENT_WRITE
        else:
            raise ValueError("Invalid events mask mode {}.".format(mode))
        self.selector.modify(self.sock, events, data=self)
    
    def _json_encode(self, obj, encoding):
        return json.dumps(obj, ensure_ascii=False).encode(encoding)

    def _json_decode(self, json_bytes, encoding):
        tiow = io.TextIOWrapper(
            io.BytesIO(json_bytes), encoding=encoding, newline=""
        )
        obj = json.load(tiow)
        tiow.close()
        return obj

    def _create_message(
        self, *, content_bytes, content_type, content_encoding
    ):
        jsonheader = {
            "byteorder": sys.byteorder,
            "content-type": content_type,
            "content-encoding": content_encoding,
            "content-length": len(content_bytes),
        }
        jsonheader_bytes = self._json_encode(jsonheader, "utf-8")
        message_hdr = struct.pack(">H", len(jsonheader_bytes))
        message = message_hdr + jsonheader_bytes + content_bytes
        return message

    def process_events(self, mask): #handles the socket event to either read or write
        if mask & selectors.EVENT_READ:
            
            self.read()
        if mask & selectors.EVENT_WRITE:
            
            self.write()
    
    def _read(self):
        try:
            # Should be ready to read
            data = self.sock.recv(4096)
        except BlockingIOError:
            print('Resource unavailable')
            # Resource temporarily unavailable (errno EWOULDBLOCK)
            pass
        else:
            if data:
                self._recv_buffer += data
            else:
                raise RuntimeError("Peer closed.")
    
    def read(self): 
        self._read()    #receive incoming message and store it in buffer
        # cases: what to process?
        
        if self._jsonheader_len is None:    #first: fixed length header --> retrieve jsonheader length
            self.process_protoheader()
        
        if self._jsonheader_len is not None:    #second: knowing the json header, retrieve the actual jsonheader
            if self.jsonheader is None:
                self.process_jsonheader()
        
        if self.jsonheader: #lastly, retrieve the actual message (server: process a  client request)
            if self.request is None:
                self.process_request()
        
        
    def write(self):
        if self.request:    #if there is a request, create a response first
            if not self.response_created:
                self.create_response()
        self._write()
        
    def process_protoheader(self):
        hdrlen = 2
        if len(self._recv_buffer) >= hdrlen:
            self._jsonheader_len = struct.unpack(   # read, decode and store length of jsonheader
                ">H", self._recv_buffer[:hdrlen]
            )[0]
            self._recv_buffer = self._recv_buffer[hdrlen:] #remove the read data from the buffer
            
    def process_jsonheader(self):
        hdrlen = self._jsonheader_len
        if len(self._recv_buffer) >= hdrlen:
            self.jsonheader = self._json_decode(
                self._recv_buffer[:hdrlen], "utf-8"
            )
            self._recv_buffer = self._recv_buffer[hdrlen:]
            for reqhdr in (
                "byteorder",
                "content-length",   # this one is important!
                "content-type",
                "content-encoding",
            ):
                if reqhdr not in self.jsonheader:
                    raise ValueError("Missing required header '{}'.".format(reqhdr))
                    print('1.3')
                
    def process_request(self):
        content_len = self.jsonheader["content-length"]
        
        if not len(self._recv_buffer) >= content_len:
            return
        
        data = self._recv_buffer[:content_len]
        self._recv_buffer = self._recv_buffer[content_len:]
        
        if self.jsonheader["content-type"] == "text/json":
            encoding = self.jsonheader["content-encoding"]
            self.request = self._json_decode(data, encoding)
        else:
            #Binary or unknown content-type
            self.request = data
        # Set selector to listen for write events, we're done reading.
        
        self._set_selector_events_mask("w")
    
    def _write(self):
        if self._send_buffer:
            #print("Sending to {}".format(self.addr))
            try:
                #Should be ready to write
                sent = self.sock.send(self._send_buffer)
            except BlockingIOError:
                #Resource temporarily unavailable (errno EWOULDBLOCK)
                pass
            else:
                self._send_buffer = self._send_buffer[sent:]
                #Close when the buffer is drained. The response had been sent.
                
                if sent and not self._send_buffer:
                    if self.stop:
                        self.close()
                    else: 
                        self._set_selector_events_mask("r")
                        # reset everything
                        self._recv_buffer = b""
                        self._send_buffer = b""
                        self._jsonheader_len = None
                        self.jsonheader = None
                        self.request = None
                        self.response_created = False
                    
    def close(self):
        #print("Closing connection to {}".format(self.addr))
        try:
            self.selector.unregister(self.sock)
        except Exception as e:
            print(
                "Error: selector.unregister() exception for {}: {}".format(self.addr, e)
            )
        #print("unregistered selector")
        try:
            self.sock.close()
        except OSError as e:
            print("Error: socket.close() exception for {}: {}".format(self.addr, e))
        finally:
            # Delete reference to socket object for garbage collection
            self.sock = None
        #print("reset socket to none")
            
    def create_response(self):
        if self.jsonheader["content-type"] == "text/json":
            response = self._create_response_json_content()     # This has to be defined depending on the application!
        else:
            # Binary or unknown content-type
            response = self._create_response_binary_content()
        message = self._create_message(**response)
        self.response_created = True
        self._send_buffer += message
 
        
    def _create_response_json_content(self):
        # here the action is carried out!
        action = self.request.get("action")
        query = self.request.get("value")
        if action in self.action_dict:                
            #try: 
            result = self.action_dict[action](query)
            #except Exception as e:
            #    result = "RP Error:"+str(e)
            content = {"result": result}
            #content = {"result": self.action_dict[action](query)}
        else:
            content = {"result": "Error: invalid action '{}'.".format(action)}
                
        content_encoding = "utf-8"
        response = {
            "content_bytes": self._json_encode(content, content_encoding),
            "content_type": "text/json",
            "content_encoding": content_encoding,
        }
        return response    

    def _create_response_binary_content(self):
        response = {
            "content_bytes": b"First 10 bytes of request: "
            + self.request[:10],
            "content_type": "binary/custom-server-binary-type",
            "content_encoding": "binary",
        }
        return response
    