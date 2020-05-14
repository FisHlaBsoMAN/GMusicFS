

from .tools import Tools

class Artist(object):
    NO_ARTIST_TITLE = "No Artist"
    def __init__ (self, library, data, name=None):
        self.__library = library
        self.__albums  = {}
        self.__tracks  = {}
        self.__data    = data

        # name
        if name is None and 'artist' in data and data['artist'].strip() != "":
            self.__name = data['artist']
        elif name is not None and name.strip() != "" and False: # TODO: remove me. bypass
            self.__name = name
        else:
            self.__name = self.NO_ARTIST_TITLE

        # name_printable
        self.__name_printable = Tools.strip_text(self.__name)

        # artist_id
        if 'artistId' in data:
            self.__id = data['artistId']
        else:
            self.__id = self.__name

    @property
    def id(self):
        return self.__id

    @property
    def name(self):
        return self.__name

    @property
    def name_printable (self):
        return self.__name_printable

    @property
    def albums (self):
        return self.__albums

    @property
    def tracks (self):
        return self.__tracks

    def add_album (self, album, track=None):
        if album.title_printable not in self.__albums:
            self.__albums[album.title_printable] = album
        else:
            two = self.__albums[album.title_printable]
            print(str(album), " already exists")
            if album.id != two.id:
                print("album id is differs\n")

    def add_track (self, track):
        if str(track) not in self.__tracks:
            self.__tracks[str(track)] = track
        else:
            print("TRACK EXISTS")

    # TODO: check it
    def __str__ (self):
        return "{0.name_printable}".format(self)
 
