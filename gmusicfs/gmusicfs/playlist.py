
from .track import Track
from .album import Album

import logging
logging.basicConfig(level=logging.ERROR)
log = logging.getLogger('gmusicfs')

class Playlist(object):
    """This class manages playlist information"""

    PLAYLIST_REGEX = '^/playlists/(?P<playlist>[^/]+)/' + Track.TRACK_REGEX + '$'

    def __init__ (self, library, data):
        self.__library = library
        self.__id      = data['id']
        self.__name    = data['name']
        self.__tracks  = {}

        for track in data['tracks']:

            # TODO: WTF IS THIS SHIT?
            track_id = track['trackId']
            # noinspection PyBroadException

            try:
                if 'track' in track:
                    library.addtrack(track['track'])
                    continue

                    # library.addtrack(track['track'])

                    album_id = track['track']['albumId']
                    if album_id not in self.__library.albums:
                        self.__library.albums[album_id] = Album(self.__library, track['track'])

                if track_id in self.__library.tracks:
                    tr = self.__library.tracks[track_id]
                else:
                    tr = Track(self.__library, track)


                self.__tracks[tr.title_printable] = tr
            except Exception:
                log.exception("error: {}".format(track))

        log.info("Playlist: {0.name}, {1} tracks".format(self, len(self.__tracks)))

    @property
    def id (self):
        return self.__id

    @property
    def name (self):
        return self.__name

    @property
    def tracks (self):
        return self.__tracks

    def __str__ (self):
        return "{0.name}".format(self)
