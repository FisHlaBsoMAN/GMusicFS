
from .track import Track
from .album import Album
from .playlist import Playlist
from .musiclibrary import MusicLibrary, NoCredentialException

import configparser
import os
import re


from gmusicapi import Webclient    as GoogleMusicWebAPI
from gmusicapi import Mobileclient    as GoogleMusicMobileclient # need for getting device id's # TODO: mobile client need for getting devices. need dynamic change somes
from gmusicapi import Musicmanager    as GoogmeMusicManager
from oauth2client.client import OAuth2WebServerFlow
from gmusicapi.session import credentials_from_refresh_token, OAuthInfo

from errno import ENOENT
from stat import S_IFDIR

from fuse import FuseOSError, Operations, LoggingMixIn

import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')


import pprint
pp  = pprint.PrettyPrinter(indent=2)  # For debug logging

class GMusicFS(LoggingMixIn, Operations):
    """Google Music Filesystem"""

    def getDeviceId (self, api, verbose=False):

        api = self.login(api)

        for device in api.get_registered_devices():
            if not 'name' in device or not device['name']:
                device['name'] = 'NoName'
            if device['id'][1] == 'x':
                pp.pprint(device)
        #del api  # not forget
        return True

    def login (self, api, verbose=False):
        print("GO")
        cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs/gmusicfs')  # TODO: move to library?
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
        config = configparser.ConfigParser()

        config.read(cred_path)

        refresh_token = config.get('oauth', 'refresh_token')
        initial_code  = config.get('oauth', 'initial_code')
        device_id     = config.get('credentials', 'deviceid')

        #if not username or not password:
        #    raise NoCredentialException( 'No username/password could be read from config file'  ': %s' % cred_path)

        #api = GoogleMusicMobileclient(debug_logging=verbose)
        api._authtype = 'oauth'

        log.info("check authentification")
        if api.is_authenticated():
            log.info("Deauthentificate from api")
            api.logout()
        else:
            log.info("not authenticaticated")

        log.info("check device_id")
        if not device_id or device_id == "mac":
            device_id = GoogleMusicMobileclient.FROM_MAC_ADDRESS
            log.info(f"device_id generated from MAC ({device_id})")
        else:
            log.info(f"using loaded device_id ({device_id})")

        oauth_info = GoogleMusicMobileclient._session_class.oauth #TODO: need normal login mechanism

        log.info("checking refresh token")
        flow = OAuth2WebServerFlow(**oauth_info._asdict())

        if not initial_code:
            print(f"Need new initial code")
            print(f'Please provide the initial code from the following URL: \n{flow.step1_get_authorize_url()}', )
            print("And paste code in config\ninitial_code = bla\n")
            exit()


        if initial_code and not refresh_token:
            credentials = flow.step2_exchange(initial_code)
            refresh_token = credentials.refresh_token
            print(f"Please update your config to include the following refresh_token:\nrefresh_token = {refresh_token}")
            exit()

        authenticated = api.oauth_login(
            device_id,
            oauth_credentials=credentials_from_refresh_token(refresh_token, oauth_info))

        if authenticated:
            pp.pprint('Logged in to Google Music')
        else:
            pp.pprint(f'Failed to login to Google Music as "{device_id}"')
            pp.pprint('Failed to login to Google Music')

        return api



    def __init__ (self, path, username=None, password=None, true_file_size=False, verbose=0, lowercase=True, check=False): # TODO: lovercase

        self.library_path = path

        Operations.__init__(self)

        artist = '/artists/(?P<artist>[^/]+)'  # TODO: remove/move me

        self.artist_dir = re.compile('^{artist}$'.format(artist=artist))

        self.artist_album_dir = re.compile(
            '^{artist}/{album}$'.format(
                artist=artist, album=Album.ALBUM_REGEX
            )
        )

        self.artist_album_dir2 = re.compile(
            '^{artist}/{album}$'.format(
                artist=artist, album=Album.ALBUM_REGEX2
            )
        )
        self.artist_album_track = re.compile(
            '^{artist}/{album}/{track}$'.format(
                artist=artist, album=Album.ALBUM_REGEX, track=Track.TRACK_REGEX
            )
        )

        self.playlist_dir   = re.compile('^/playlists/(?P<playlist>[^/]+)$')
        #print(Playlist.PLAYLIST_REGEX)
        self.playlist_track = re.compile(Playlist.PLAYLIST_REGEX)
        #print(Track.TRACKS_REGEX)
        self.tracks_track   = re.compile(Track.TRACKS_REGEX)

        self.__opened_tracks = {}  # path -> urllib2_obj # TODO: make somth with it


        # Login to Google Play Music and parse the tracks:
        if(check):
            return
        self.library = MusicLibrary(username, password, gfs=self, true_file_size=true_file_size, verbose=verbose, GFS=self) #TODO: probably even make it out of initialization? and in the main do separately authorization and initialization of the library
        log.info("Filesystem ready : %s" % path)

    def cleanup (self):
        self.library.cleanup()

    def getattr(self, path, fh=None):
        print("getattr path:")
        print(path)
        print("end\n")

        """Get information about a file or directory"""
        artist_dir_matches         = self.artist_dir.match(path)
        artist_album_dir_matches   = self.artist_album_dir.match(path)
        artist_album_dir2_matches  = self.artist_album_dir2.match(path)

        '''
        print("regex:")
        print(self.artist_album_dir)
        print(self.artist_album_dir2)
        '''

        artist_album_track_matches = self.artist_album_track.match(path)
        playlist_dir_matches       = self.playlist_dir.match(path)
        playlist_track_matches     = self.playlist_track.match(path)
        tracks_track_matches       = self.tracks_track.match(path)


        # Default to a directory
        st = {
            'st_mode':  (S_IFDIR|0o755),
            'st_nlink': 1
        }
        date = 0  # Make the date really old, so that cp -u works correctly.
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date

        parts = ""
        if path == '/':
            print("path /")
            pass

        elif path == '/artists':
            print("path /artists/")
            pass

        elif path == '/playlists':
            print("path /playlists/")
            pass


        elif path == '/tracks':
            print("path /tracks/")
            pass

        elif artist_dir_matches:
            pass


        # TODO: cleanup

        elif artist_album_dir2_matches:

            print("path \"artist_album_dir2_matches\"")

            parts = artist_album_dir2_matches.groupdict()

            print("parts artist_album_dir2_matches:")

            print(parts)

            artist = self.library.artists_by_name[parts['artist']]

            print("==================")

            print(artist)

            print("==================")

            if parts['album'] not in artist.albums:

                raise FuseOSError(ENOENT)
                # return st

            album = artist.albums[parts['album']]

            st['st_size'] = len(artist.albums)

            print(album)

            print("==================")

            print("############### I ADD DIRECTORY SIZE ")


        elif artist_album_dir_matches:

            print("path \"artist_album_dir_matches\"")

            parts = artist_album_dir_matches.groupdict()
            print("parts artist_album_dir_matches:")
            print(parts)

            # TODO:  File "/home/fish/ProjecMy new pats/GMusicFS-19042018/gmusicfs/code/gmusicfs.py", line 203, in getattr
            # TODO:  artist th= self.library.artists_by_name[parts['artist']]
            # TODO:  KeyError: 'First Astronomical Velocity2'



            artist = self.library.artists_by_name[parts['artist']]
            print("==================")
            print(artist)
            print("==================")

            if parts['album'] not in artist.albums:
                raise FuseOSError(ENOENT)
                # return st

            album = artist.albums[parts['album']]
            st['st_size'] = len(artist.albums)

            print(album)
            print("==================")
            print("############### I ADD DIRECTORY SIZE ")

        elif artist_album_track_matches:

            print("path \"artist_album_track_m\"")

            parts = artist_album_track_matches.groupdict()
            print("parts artist_album_track_m:")
            print(parts)
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]

            print(parts)
            title2 = Track.TRACK_FORMAT.format(
                    disk             = int(parts['disk']),
                    number           = int(parts['number']),
                    artist_printable = parts['trartist'],
                    album_printable  = parts['tralbum'],
                    title_printable  = parts["title"]
            )
            track = album.tracks[title2]

            print("t==================")
            print(album)
            print(track)
            print("############### artist_album_track_m I RETURN TRACK ATTR!")
            return track.get_attr(path)

        elif tracks_track_matches:

            print("path \"tracks_track_m\"")
            parts = tracks_track_matches.groupdict()
            # print("parts tracks_track_m:")
            # print(parts)
            parts['disk'] = int(parts['disk'])  # TODO: verify this
            title2 = Track.TRACK_FORMAT.format(
                    disk             = int(parts['disk']),
                    number           = int(parts['number']),
                    artist_printable = parts['trartist'],
                    album_printable  = parts['tralbum'],
                    title_printable  = parts["title"]
            )

            if title2 not in self.library.tracks_by_title.keys():
                print("##Error: tracks_track_m -> title2 not found")
                raise FuseOSError(ENOENT)
                # return
            track = self.library.tracks_by_title[title2]
            print("OK, ADDING TRACK" + title2)
            print(track)
            print("############### artist_album_track_m I RETURN TRACK ATTR!")
            return track.get_attr(path)


        elif playlist_dir_matches:

            print("path \"playlist_dir_matches\"")

            pass
        elif playlist_track_matches:

            print("path \"playlist_track_matches\"")

            parts = playlist_track_matches.groupdict()
            print("parts playlist_track_matches:")
            print(parts)
            playlist = self.library.playlists[parts['playlist']]
            # TODO: revert checking
            # if parts['title'] in playlist.tracks:
            if parts['title']:
                print("############### playlist_track_matches I RETURN ATTR!")

                # pp.pprint(playlist.tracks)
                pl_track = playlist.tracks[parts['filename']]

                print(parts['title'])
                print("error in playlist")
                return pl_track.get_attr(pl_track.path)
            else:
                print("############### playlist_track_matches I RETURN XYU (st)")
                print(playlist.tracks)
                return st
        else:
            print("\n")
            print("##Error: Couldn't get attrs")
            print('"'+path+'"')
            print("\n")
            print(parts)
            print("\n")
            raise FuseOSError(ENOENT)

        return st



    def gettrack (self, path):

        artist_album_track_m = self.artist_album_track.match(path)
        playlist_track_m     = self.playlist_track.match(path)
        tracks_track_m       = self.tracks_track.match(path)

        # print("\nself dict :")
        # pp.pprint(self.__dict__)
        print("\n\n")
        print("gettrack path: "        + path)
        print("artist_album_track_m: " + str(artist_album_track_m))
        print("playlist_track_m: "     + str(playlist_track_m))
        print("tracks_track_m: "       + str(tracks_track_m))

        # open track from album
        if artist_album_track_m:
            parts  = artist_album_track_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album  = artist.albums[parts['album']]
            # TODO: TEST

            title2 = Track.TRACK_FORMAT.format(
                    disk             = int(parts['disk']),
                    number           = int(parts['number']),
                    artist_printable = parts['trartist'],
                    album_printable  = parts['tralbum'],
                    title_printable  = parts["title"]
            )
            track = album.tracks[title2]
            print("founded track in album: " + str(album))

        # Open track from tracks
        elif tracks_track_m:
            parts = tracks_track_m.groupdict()

            title2 = Track.TRACK_FORMAT.format(
                    disk             = int(parts['disk']),
                    number           = int(parts['number']),
                    artist_printable = parts['trartist'],
                    album_printable  = parts['tralbum'],
                    title_printable  = parts["title"]
            )
            track = self.library.tracks_by_title[title2]
            print("founded track in tracks")
        # Open track
        elif playlist_track_m:
            parts = playlist_track_m.groupdict()
            playlist = self.library.playlists[parts['playlist']]

            track = playlist.tracks[parts['filename']]

            print("founded track in playlist " + str(playlist))
        else:
            print("##Error: track not found in any path's!")
            return None

        print("return track!\n\n")
        return track



    def open (self, path, fip):
        log.info("open: {} ({})".format(path, fip))
        track = self.gettrack(path)
        track.open() #trigger function in track class
        if track is None:
            RuntimeError('unexpected opening of path: %r' % path)

        key = track.path
        if not key in self.__opened_tracks:
            self.__opened_tracks[key] = [0, track, fip]  # TODO: check this code. track does not using
        self.__opened_tracks[key][0] += 1

        pp.pprint(self.__opened_tracks)
        return fip



    def get_num_opens (self, path):
        if not path in self.__opened_tracks:
            return 0
        else:
            return self.__opened_tracks[path][0]


    def release (self, path, fip):
        log.info("release: {} ({})".format(path, fip))
        track = self.gettrack(path)

        key = track.path

        if not key in self.__opened_tracks:
            raise RuntimeError('unexpected path: %r' % path)

        self.__opened_tracks[key][0] -= 1
        track.set_num_of_open(self.__opened_tracks[key][0])
        if self.__opened_tracks[key][0] < 1:
           # time.sleep(2)
            self.__opened_tracks[key][1].close()
            #del self.__opened_tracks[key]
        else:
            print("the track is open one more time")


        print("##openned tracks: ")
        pp.pprint(self.__opened_tracks)


    def read (self, path, size, offset, fip):

        log.info("read: {} offset: {} size: {} ({})".format(path, offset, size, fip))
        track = self.gettrack(path)

        key = track.path
        track = self.__opened_tracks.get(key, None)
        if track is None:
            raise RuntimeError('unexpected path: %r' % path)

        return track[1].read(offset, size)

    ## see get_attr func in track
    def readlink (self, path):

        print("My new path:" + path)
        track = self.gettrack(path)
        print("Me founded track: " + str(track))
        print("Track class name: " + track.__class__.__name__)



        if track is not None:  # TODO: count the number of slashes


            if self.artist_album_track.match(path):
                return "../../.." + track.path
            if self.playlist_track.match(path):
                return "../.." + track.path
            if self.tracks_track.match(path):
                return ".." + track.path



            return "." + track.path



        else:
            print("##ERROR: link path" + track.path + " not avaliable")
            raise FuseOSError(ENOENT)
            # return "/dev/null"


    # TODO: add file sizes... maybe add radio?
    def readdir (self, path, fh):

        artist_dir_m       = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        playlist_dir_m     = self.playlist_dir.match(path)

        if path == '/':
            return ['.', '..', 'artists', 'playlists', 'tracks']

        elif path == '/artists':  # TODO: need filter bad characters?
            list_tmp = list(self.library.artists_by_name.keys())
            print(list_tmp)  # TODO: remove
            list_tmp = ['.', '..'] + list_tmp
            return list_tmp

        elif path == '/playlists':
            playlist_tmp = ['.', '..'] + list(self.library.playlists.keys())
            print(playlist_tmp)  # TODO: remove
            return playlist_tmp

        elif path == '/tracks':

            tmp_list = [(
                str(trackObj)
            ) for trackObj in self.library.tracks_by_title.values()]
            tmp_tracks = ['.', '..'] + tmp_list
            print("tracks::::")
            print(tmp_tracks)  # TODO: remove
            return tmp_tracks


        # TODO: cleanup or/and merge get trrack?
        elif artist_dir_m:
            print("artist_dir_m")
            # Artist directory -> lists albums.
            parts = artist_dir_m.groupdict()

            print("==========================parts")
            print(parts)

            artist = self.library.artists_by_name[parts['artist']]

            print("========================== artist")
            print(artist)

            print("========================== artist.albums")
            print(artist.albums)

            print("========================== artist.albums.values")
            values = artist.albums.values()
            print(values)
            tmp_list = [str(album) for album in artist.albums.values()]
            print(tmp_list)
            return ['.', '..'] + tmp_list

        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]
            return ['.', '..'] + [str(track) for track in album.tracks.values()]

        # print
        elif playlist_dir_m:
            # Playlists directory, lists tracks.
            parts = playlist_dir_m.groupdict()
            playlist = self.library.playlists[parts['playlist']]
            return ['.', '..'] + [str(track) for track in playlist.tracks.values()]
        else:
            print("####################################wtf?")
            print("self:")
            print(self)
            print("path:")
            print(path)
            print("fh:")
            print(fh)

        return ['.', '..']
