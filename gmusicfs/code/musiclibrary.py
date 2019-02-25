import os
import configparser
import traceback

import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')


from .tools    import Tools
from .track    import Track
from .album    import Album
from .artist   import Artist
from .playlist import Playlist

from gmusicapi import Mobileclient as GoogleMusicAPI


import pprint
pp  = pprint.PrettyPrinter(indent=2)  # For debug logging

class NoCredentialException(Exception):
    pass


class MusicLibrary(object):
    """This class reads information about your Google Play Music library"""

    def __init__ (self, username=None, password=None, verbose=0, gfs=None, true_file_size=False):

        self.verbose = bool(verbose)
        self.api     = GoogleMusicAPI(debug_logging=self.verbose)
        self.gfs     = gfs
        self.__login_and_setup(username, password)

        self.__artists         = {}
        self.__artists_by_name = {}
        self.__albums          = {}
        self.__tracks          = {}
        self.__tracks_by_title = {}
        self.__playlists       = {}
        self.__paths           = {}

        self.rescan()

    def __login_and_setup (self, username=None, password=None):
        # If credentials are not specified, get them from $HOME/.gmusicfs
        cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs/gmusicfs')  # TODO:  need to discuss
        if not username or not password:
            if not os.path.isfile(cred_path):
                raise NoCredentialException(
                        'No username/password was specified. No config file could '
                        'be found either. Try creating %s and specifying your '
                        'username/password there. Make sure to chmod 600.'
                        % cred_path)
            if not oct(os.stat(cred_path)[os.path.stat.ST_MODE]).endswith('00'):
                raise NoCredentialException(
                        'Config file is not protected. Please run: '
                        'chmod 600 %s' % cred_path)
            self.config = configparser.ConfigParser()
            self.config.read(cred_path)
            username = self.config.get('credentials', 'username')
            password = self.config.get('credentials', 'password')
            if not username or not password:
                raise NoCredentialException(
                        'No username/password could be read from config file'
                        ': %s' % cred_path)

        device_id = self.config.get('credentials', 'deviceId')
        if not username or not password:
            raise NoCredentialException(
                    'No username/password could be read from config file'
                    ': %s' % cred_path)
        if not device_id:
            raise NoCredentialException(
                    'No deviceId could be read from config file'
                    ': %s' % cred_path)
        if device_id.startswith("0x"):
            device_id = device_id[2:]

        print("Your device id:")
        print(device_id)

        log.info('Logging in...')
        self.api.login(username, password, device_id)
        log.info('Login successful.')

    @property
    def artists (self):
        return self.__artists

    @property
    def artists_by_name (self):
        return self.__artists_by_name

    @property
    def paths (self):
        return self.__paths

    @property
    def albums (self):
        return self.__albums

    @property
    def playlists (self):
        return self.__playlists

    @property
    def tracks (self):
        return self.__tracks

    @property
    def tracks_by_title (self):
        return self.__tracks_by_title

    # TODO: timer for rescan?
    def rescan (self):
        """Scan the Google Play Music library"""
        self.cleanup()
        self.__populate_library()

    # TODO: may be use webclient for download songs? manual creating meta needless!
    def get_stream_url (self, track_id):
        print("URL:")
        url = self.api.get_stream_url(track_id)
        print(url)
        return url

    def __populate_library (self):
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        errors = 0
        for track in tracks:
            try:
                # make track
                newtrack = Track(self, track)

                print("\n\n\n\n" + str(newtrack))

                if newtrack.id not in self.__tracks:
                    self.__tracks[newtrack.id] = newtrack
                else:
                    print("# ALERT! TRACK ALREADY EXISTS IN TRACK BASE? DUPES?")
                    newtrack = self.__tracks[newtrack.id]

                if str(newtrack) not in self.__tracks_by_title:
                    self.__tracks_by_title[str(newtrack)] = newtrack
                else:
                    print("# ALERT! TRACK_BY_NAME ALREADY EXISTS IN TRACK BASE? DUPES?")
                    newtrack = self.__tracks_by_title[str(newtrack)]

                # make album
                new_album = Album(self, track)
                if new_album.id not in self.__albums:
                    print("# new album in library: " + str(new_album))
                    self.__albums[new_album.id] = new_album
                else:
                    print("# old album from library: " + str(new_album))
                    new_album = self.__albums[new_album.id]



                # make artist
                new_artist = Artist(self, track)
                print("artist:" + new_artist.name_printable)



                # give Artist by name
                if new_artist.name_printable in self.__artists_by_name:
                    print("# artist from artist name printable: " + str(new_artist))
                    new_artist = self.__artists_by_name[new_artist.name_printable]

                # Give Artist by album artist name
                elif newtrack.album_artist_printable in self.__artists_by_name:
                    print("# artist from albumArtist: " + str(new_artist))
                    new_artist = self.__artists_by_name[newtrack.album_artist_printable]

                # adding new artist
                else:
                    print("# store new artist : " + str(new_artist))
                    if newtrack.album_artist_printable.strip() != "":
                        print("# new artist store from nTrack.album_artist_printable: " + newtrack.album_artist_printable)
                        self.__artists_by_name[newtrack.album_artist_printable] = new_artist

                    if new_artist.name_printable.strip() != "":

                        print("# new artist store from nArtist.name_printable: " + new_artist.name_printable)
                        self.__artists_by_name[new_artist.name_printable]  = new_artist


                # self.__paths[hashlib.sha224(nPath1.encode('ascii', 'ignore')).hexdigest()] = nTrack
                # self.__paths[hashlib.sha224(nPath2.encode('ascii', 'ignore')).hexdigest()] = nTrack
                # adding some file paths; #TODO: use artists and other class tree!
                if newtrack.album_artist_printable.strip() != "":
                    path = (
                        "/artists/" +
                        newtrack.album_artist_printable + "/" +
                        str(new_album) + "/" +
                        str(newtrack)
                    )
                    self.__paths[str(path)] = newtrack
                    newtrack.add_path(path)
                    print(newtrack.path)

                if new_artist.name_printable.strip() != "":  # TODO: strip needless?
                    path = (
                            "/artists/" +
                            new_artist.name_printable + "/" +
                            str(new_album) + "/" +
                            str(newtrack)
                    )
                    self.__paths[str(path)] = newtrack

                    newtrack.add_path(path)  # add main path
                    print(newtrack.path)

                if newtrack.path is None:
                    print("WTF!!!!????!!!???? track does not have artist or album_artist!!! or any invalid?")
                    newtrack.add_path("/dev/null")  # add main path


                newtrack.add_album(new_album)
                newtrack.add_artist(new_artist)

                new_album.add_track(newtrack)
                new_album.add_artist(new_artist)


                new_artist.add_album(new_album)
                new_artist.add_track(newtrack)

                '''
                print("\n\n\nTRACK:")
                pp.pprint(nTrack.__dict__)
                print("ALBUM:")
                pp.pprint(nAlbum.__dict__)
                print("ARTIST:")
                pp.pprint(nArtist.__dict__)
                '''

            except Exception:
                logging.error(traceback.format_exc())
                log.exception("Error loading track: {}" + str(pp.pprint(track)))
                errors += 1
                raise



        # refresh album arts
        # [albumObj.art for albumObj in self.albums.values()] #TODO: uncoment?

        # TODO: do not use path lists
        print("###all paths:")
        pp.pprint(self.__paths)

        # TODO: uncomment me
        # playlists = self.api.get_all_user_playlist_contents()

        playlists = ""
        for pl in playlists:

            name = Tools.strip_text(pl['name'])

            if name[len(name) - 1] == ".":
                name += "_"
            while name in self.__playlists:
                name += "_"

            if name:
                # noinspection PyBroadException
                try:
                    self.__playlists[name] = Playlist(self, pl)
                except Exception:
                    log.exception("Error loading playlist: {}".format(pl))
                    errors += 1

        print("Loaded {} tracks, {} albums, {} artists and {} playlists ({} errors).".format(len(self.__tracks),
                                                                                             len(self.__albums),
                                                                                             len( self.__artists_by_name),
                                                                                             len(self.__playlists),
                                                                                             errors))

    def cleanup (self):
        self.__artists         = {}
        self.__artists_by_name = {}
        self.__albums          = {}
        self.__tracks          = {}
        self.__tracks_by_title = {}
        self.__playlists       = {}
        self.__paths           = {}
        pass

