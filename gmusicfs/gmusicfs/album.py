

from .tools  import Tools
from .artist import Artist
from PIL import Image
import io
import os
import urllib
import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')



import magic

mime = magic.Magic(mime=True)

class Album(object):
    ALBUM_REGEX  = '(?P<album>[^/]+) \((?P<year>[0-9]{4})\)'
    ALBUM_REGEX2 = '(?P<album>[^/]+) \((?P<year>[0-9]{4})\)/' # TODO: TEMPORARY, check bug of path's ending "/"
    ALBUM_FORMAT = "{0.title_printable} ({0.year:04d})"
    NO_ALBUM_TITLE = "No Album"

    def __init__(self, library, data, custId = None):
        self.__library    = library
        self.__data       = data
        self.__tracks     = {}
        self.__artists    = {}
        self.__art        = bytes()
        self.__album_info = None

        # album_title
        if 'album' in data and data['album'].strip() != "":
            self.__album_title = data['album']
        else:
            self.__album_title = self.NO_ALBUM_TITLE

        # album_title_printable
        self.__album_title_printable = Tools.strip_text(self.__album_title)

        # album_artist ## self.__artist = self.__library.artists.get(data['artistId'][0], None)
        if 'albumArtist' in data and data['albumArtist'].strip() != "":
            self.__album_artist = data['albumArtist']
        elif 'artist' in data and data['artist'].strip() != "":
            self.__album_artist = data['artist']
        else:
            self.__album_artist = Artist.NO_ARTIST_TITLE

        # album_artist_printable
        self.__album_artist_printable = Tools.strip_text(self.__album_artist)

        # album_id

        if custId != None: #TODO: check dynamic album id creating
            self.__id = custId
        elif 'albumId' in data:
            self.__id = data['albumId']
        elif Tools.strip_text(self.__album_title) == Tools.strip_text(self.NO_ALBUM_TITLE):
            self.__id = self.__album_title + self.__album_artist  # TODO: check it
        else:
            self.__id = self.__album_title

        # year
        if 'year' in data:
            self.__year = data['year']
        else:
            self.__year = 0

        # url album art
        if 'albumArtRef' in data:
            self.__art_url = data['albumArtRef'][0]['url']
        else:
            self.__art_url = None

        # artist
        if 'artist' in data:
            self.__artist = data['artist']
        else:
            self.__artist = self.__album_artist

        # artist id
        # TODO: merge names by id
        if 'artistId' in data:
            self.__artistId = data['artistId']
        else:
            self.__artistId = self.__album_artist

    @property
    def id_db (self):
        return self.__id

    @property
    def id (self):
        return self.__album_artist_printable + self.title_printable #TODO: need debug track-album-title

    @property
    def tracks (self):
        return self.__tracks

    @property
    def title (self):
        return self.__album_title

    @property
    def title_printable (self):
        return self.__album_title_printable

    @property
    def year (self):
        if not self.__year:
            self.__get_year() # TODO: needed??
        return self.__year

    @property
    def album_artist (self):
        return self.__album_artist

    @property
    def album_artist_printable (self):
        return self.__album_artist_printable

    @property
    def art (self):
        if not self.__art:
            self.__load_art()
        return self.__art

    @property
    def art_mime (self):
        return 'image/jpeg'



    def add_track (self, track):
        self.__tracks[str(track)] = track
        if track.id not in self.__library.tracks:  # TODO: may be from playlists check it
            self.__library.tracks[track.id] = track

    def add_artist (self, artist):
        self.__artists[artist.name_printable] = artist

    def __get_year (self):
        # some tracks are not loaded from album_info, let's use them to get the album date release
        for track in self.__tracks.values():
            self.__year = track.year or self.__year # TODO: fking year 0000

    def __load_art (self):
        if not self.__art_url:
            return
        log.info("loading art album: {0.title}".format(self))
        self.__art = bytes()

        # TODO: make one var of path's (not sure that it's still actual)
        base_art_path = os.path.join(os.path.expanduser('~'), '.gmusicfs', 'album_arts')
        art_name = Tools.strip_text(self.id)
        art_path = os.path.join(base_art_path, art_name)  # without extension

        art_ext = ''
        if os.path.isdir(base_art_path):
            directory = os.scandir(base_art_path)
            for entry in directory:
                if entry.name.startswith(art_name):
                    art_ext = entry.name.replace(art_name + '.', '')
                    break  # assuming that there are no more saved arts
        else:
            os.mkdir(base_art_path)

        if art_ext:
            log.info('Taking art from filesystem')

            filepath = '%s.%s' % (art_path, art_ext)
            image = Image.open(filepath)

            if art_ext != 'jpg':
                log.info('Converting art from %s to jpg' % art_ext)
                image = image.convert('RGB')
                image.save(art_path + '.jpg')
                os.remove(filepath)

            self.__art = image.tobytes()
        else:
            log.info('Downloading art from Internet')

            try:
                u = urllib.request.urlopen(self.__art_url)
            except urllib.error.HTTPError:
                log.error("Cannot load art for album '%s'", self.title)
                return

            data = u.read()
            while data:
                self.__art += data
                data = u.read()
            u.close()

            log.info('Saving art to disk')
            art_mime = mime.from_buffer(self.__art)
            if art_mime.endswith('jpeg'):
                local_art = open(art_path + '.jpg', "wb")
                local_art.write(self.__art)
                local_art.close()
            else:  # need to convert this art to jpeg
                data_io = io.BytesIO(self.__art)
                image = Image.open(data_io).convert('RGB')
                image.save(art_path + '.jpg')

        print("loading art album: {0.title_printable} {0.art_mime}".format(self) + " done!")

    def __str__ (self):
        title2 = self.ALBUM_FORMAT.format(self)
        return title2
