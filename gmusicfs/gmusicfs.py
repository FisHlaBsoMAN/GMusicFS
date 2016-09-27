#!/usr/bin/env python2

import os
import re
import sys
import urllib2
import ConfigParser
from errno import ENOENT
from stat import S_IFDIR, S_IFREG
import argparse
import tempfile
import logging
import pprint

from eyed3.id3 import Tag, ID3_V2_4
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn#, fuse_get_context
#import gmusicapi.exceptions
from gmusicapi import Mobileclient as GoogleMusicAPI
#from gmusicapi import Webclient as GoogleMusicWebAPI

reload(sys)  # Reload does the trick
sys.setdefaultencoding('UTF-8')

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
pp = pprint.PrettyPrinter(indent=4)  # For debug logging

ALBUM_REGEX = '(?P<album>[^/]+) \((?P<year>[0-9]{4})\)'
ALBUM_FORMAT = u'{name} ({year:04d})'

TRACK_REGEX = '(?P<track>(?P<number>[0-9]+) - (?P<title>.*)\.mp3)'
TRACK_FORMAT = '{number:02d} - {name}.mp3'

ID3V1_TRAILER_SIZE = 128

def formatNames(string_from):
    """Format a name to make it suitable to use as a filename"""
    return re.sub('/', '-', string_from)


class NoCredentialException(Exception):
    pass
        
        
class Artist(object):
    
    def __init__(self, library, data):
        self.__library = library
        self.__id = data['artistId'][0]
        self.__name = data['artist']
        self.__albums = {}
        
    @property
    def id(self):
        return self.__id

    @property
    def name(self):
        return self.__name
    
    @property
    def albums(self):
        return self.__albums
    
    def add_album(self, album):
        self.__albums[album.title] = album
    
    def __str__(self):
        return "{0.name}".format(self)
    
class Album(object):
    
    def __init__(self, library, data):
        self.__library = library
        self.__id = data['albumId']
        self.__artist = self.__library.artists[data['artistId'][0]]
        self.__title = data['album']
        self.__tracks = {}
        self.__year = 2005
        
    @property
    def id(self):
        return self.__id
        
    @property
    def tracks(self):
        return self.__tracks

    @property
    def title(self):
        return self.__title

    @property
    def year(self):
        return self.__year

    @property
    def artist(self):
        return self.__artist
        
    def add_track(self, track):
        self.__tracks[track.title] = track

    def __str__(self):
        return "{0.title} ({0.year:04d})".format(self)

class Track(object):
    
    def __init__(self, library, data):
        self.__library = library
        if 'track' in data: # Playlists manage tracks in a different way
            self.__id = data['trackId']
            data = data['track']
        else:
            self.__id = data['id']
            
        self.__data = data
        self.__title = data['title']
        self.__number = int(data['trackNumber'])
        self.__album = self.__library.albums.get(data['albumId'], None)
        self.__url = None
        self.__gen_tag()
        self.__stream_cache = str(self.get_rendered_tag())
        
    def __gen_tag(self):
        self.__tag = Tag()
        self.__tag.album = self.__data['album']
        self.__tag.artist = self.__data['artist']
        self.__rendered_tag = None
        
    def get_rendered_tag(self):
        if not self.__rendered_tag:
            tmpfd, tmpfile = tempfile.mkstemp()
            os.close(tmpfd)
            self.__tag.save(tmpfile, ID3_V2_4)
            tmpfd = open(tmpfile, "r")
            self.__rendered_tag = tmpfd.read()
            tmpfd.close()
            os.unlink(tmpfile)
        return self.__rendered_tag
        
    @property
    def id(self):
        return self.__id
        
    @property
    def number(self):
        return self.__number
    
    @property
    def title(self):
        return self.__title
        
    @property
    def album(self):
        return self.__album
    
    def get_attr(self):
        st = {}
        st['st_mode'] = (S_IFREG | 0o444)
        st['st_nlink'] = 1
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = 0
        
        if 'bytes' in self.__data:
            st['st_size'] = int(self.__data['bytes'])
        elif 'estimatedSize' in self.__data:
            st['st_size'] = int(self.__data['estimatedSize'])
        else:
            st['st_size'] = int(self.__data['tagSize'])
        
        if 'creationTimestamp' in self.__data:
            st['st_ctime'] = st['st_mtime'] = int(self.__data['creationTimestamp']) / 1000000
        if 'recentTimestamp' in self.__data:
            st['st_atime'] = int(self.__data['recentTimestamp']) / 1000000
        return st
        
    def _open(self):
        """Return the track stream URL"""
        if not self.__url:
            self.__url = urllib2.urlopen(self.__library.get_stream_url(self.id))
    
    def read(self, offset, size):
        # TODO: cleanup shitty code
        if self.__url:
            if offset > len(self.__stream_cache) or offset + size > len(self.__stream_cache):
                return '' # Not enough data
        elif offset == 0: # Trying to filter OS open request
            self._open()
        
        if self.__url:
            self.__stream_cache += self.__url.read() # Cache all available data
        if offset > len(self.__stream_cache) or offset + size > len(self.__stream_cache):
            return '' # Not enough data
        return self.__stream_cache[offset:offset + size]
    
    def close(self):
        if self.__url:
            self.__stream_cache = str(self.get_rendered_tag())
            self.__url.close()
            self.__url = None
    
    def __str__(self):
        return "{0.number:02d} - {0.title}.mp3".format(self)

class Playlist(object):
    """This class manages playlist information"""

    def __init__(self, library, data):
        self.__library = library
        self.__id = data['id']
        self.__name = data['name']
        self.__tracks = {}
        for track in data['tracks']:
            trackId = track['trackId']
            try:
                if trackId in self.__library.tracks:
                    tr = self.__library.tracks[trackId]
                else:
                    tr = Track(self.__library, track)
                self.__tracks[tr.title] = tr
            except:
                log.exception("error: {}".format(track))
        
        log.info("Playlist: {0.name}, {1} tracks".format(self, len(self.__tracks)))
    
    @property
    def id(self):
        return self.__id
        
    @property
    def name(self):
        return self.__name
        
    @property
    def tracks(self):
        return self.__tracks

    def __str__(self):
        return "{0.name}".format(self)

class MusicLibrary(object):
    """This class reads information about your Google Play Music library"""
    def __init__(self, username=None, password=None,
                 true_file_size=False, scan=True, verbose=0):
        
        self.verbose = bool(verbose)
        self.api = GoogleMusicAPI(debug_logging=self.verbose)
        self.__login_and_setup(username, password)
        
        if scan:
            self.rescan()
    
    def __login_and_setup(self, username=None, password=None):
        # If credentials are not specified, get them from $HOME/.gmusicfs
        if not username or not password:
            cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs')
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
            self.config = ConfigParser.ConfigParser()
            self.config.read(cred_path)
            username = self.config.get('credentials', 'username')
            password = self.config.get('credentials', 'password')
            if not username or not password:
                raise NoCredentialException(
                    'No username/password could be read from config file'
                    ': %s' % cred_path)

        log.info('Logging in...')
        self.api.login(username, password, GoogleMusicAPI.FROM_MAC_ADDRESS)
        log.info('Login successful.')

    @property
    def artists(self):
        return self.__artists
    
    @property
    def artists_by_name(self):
        return self.__artists_by_name
    
    @property
    def albums(self):
        return self.__albums
    
    @property
    def playlists(self):
        return self.__playlists
        
    @property
    def tracks(self):
        return self.__tracks
    
    def rescan(self):
        """Scan the Google Play Music library"""
        self.__artists = {}
        self.__artists_by_name = {}
        self.__albums = {}
        self.__tracks = {}
        self.__playlists = {}
        self.__populate_library()

    def get_stream_url(self, trackId):
        url = self.api.get_stream_url(trackId)
        return url
        
    def __populate_library(self):
        log.info('Gathering track information...')
        tracks = self.api.get_all_songs()
        errors = 0
        for track in tracks:
            try:
                log.debug('track = %s' % pp.pformat(track))
                
                trackId = track['id']
                if trackId in self.__tracks:
                    continue
                
                artistId = track['artistId'][0]
                if artistId not in self.__artists:
                    self.__artists[artistId] = Artist(self, track)
                    self.__artists_by_name[str(self.__artists[artistId])] = self.__artists[artistId]
                artist = self.__artists[artistId]
                
                albumId = track['albumId']
                if albumId not in self.__albums:
                    self.__albums[albumId] = Album(self, track)
                    artist.add_album(self.__albums[albumId])
                album = self.__albums[albumId]
                
                self.__tracks[trackId] = Track(self, track)
                album.add_track(self.__tracks[trackId])
            except:
                log.exception("Error loading track: {}".format(track))
                errors += 1
                
        playlists = self.api.get_all_user_playlist_contents()
        for pl in playlists:
            if pl['name']:
                try:
                    self.__playlists[pl['name']] = Playlist(self, pl)
                except:
                    log.exception("Error loading playlist: {}".format(pl))
                    errors += 1
                    
        log.info("Loaded {} tracks, {} albums, {} artists and {} playlists ({} errors).".format(len(self.__tracks), len(self.__albums), len(self.__artists), len(self.__playlists), errors))
    
    def cleanup(self):
        pass

class GMusicFS(LoggingMixIn, Operations):
    """Google Music Filesystem"""

    def __init__(self, path, username=None, password=None,
                 true_file_size=False, verbose=0, scan_library=True,
                 lowercase=True):
        Operations.__init__(self)

        artist = '/artists/(?P<artist>[^/]+)'

        self.artist_dir = re.compile('^{artist}$'.format(
            artist=artist))
        self.artist_album_dir = re.compile('^{artist}/{album}$'.format(
            artist=artist, album=ALBUM_REGEX))
        self.artist_album_track = re.compile('^{artist}/{album}/{track}$'.format(
            artist=artist, album=ALBUM_REGEX, track=TRACK_REGEX))

        self.playlist_dir = re.compile('^/playlists/(?P<playlist>[^/]+)$')
        #self.playlist_track = re.compile('^/playlists/(?P<playlist>[^/]+)/(?P<track>[^/]+\.mp3)$')
        self.playlist_track = re.compile('^/playlists/(?P<playlist>[^/]+)/(?P<track>(?P<number>[0-9]+) - (?P<title>.*)\.mp3)$')

        self.__opened_tracks = {}  # path -> urllib2_obj
        
        # Login to Google Play Music and parse the tracks:
        self.library = MusicLibrary(username, password,
                                    true_file_size=true_file_size, verbose=verbose, scan=scan_library)
        log.info("Filesystem ready : %s" % path)

    def cleanup(self):
        self.library.cleanup()

    def getattr(self, path, fh=None):
        """Get information about a file or directory"""
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        artist_album_track_m = self.artist_album_track.match(path)
        playlist_dir_m = self.playlist_dir.match(path)
        playlist_track_m = self.playlist_track.match(path)

        # Default to a directory
        st = {
            'st_mode': (S_IFDIR | 0o755),
            'st_nlink': 2}
        date = 0  # Make the date really old, so that cp -u works correctly.
        st['st_ctime'] = st['st_mtime'] = st['st_atime'] = date

        if path == '/':
            pass
        elif path == '/artists':
            pass
        elif path == '/playlists':
            pass
        elif artist_dir_m:
            pass
        elif artist_album_dir_m:
            parts = artist_album_dir_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]
            st['st_size'] = len(artist.albums)
            
        elif artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]
            track = album.tracks[parts['title']]
            return track.get_attr()
            
        elif playlist_dir_m:
            pass
            
        elif playlist_track_m:
            parts = playlist_track_m.groupdict()
            playlist = self.library.playlists[parts['playlist']]
            track = playlist.tracks[parts['title']]
            return track.get_attr()
        else:
            raise FuseOSError(ENOENT)
            
        return st

    def open(self, path, fh):
        artist_album_track_m = self.artist_album_track.match(path)
        playlist_track_m = self.playlist_track.match(path)
        
        if artist_album_track_m:
            parts = artist_album_track_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]
            track = album.tracks[parts['title']]
        elif playlist_track_m:
            parts = playlist_track_m.groupdict()
            playlist = self.library.playlists[parts['playlist']]
            track = playlist.tracks[parts['title']]
        else:
            RuntimeError('unexpected opening of path: %r' % path)

        self.__opened_tracks[fh] = track
            
        return fh

    def release(self, path, fh):
        log.info("release: {} ({})".format(path, fh))
        if fh not in self.__opened_tracks:
            raise RuntimeError('unexpected path: %r' % path)
        track = self.__opened_tracks.pop(fh)
        if track not in self.__opened_tracks.values():
            track.close()

    def read(self, path, size, offset, fh):
        track = self.__opened_tracks.get(fh, None)
        if track is None:
            raise RuntimeError('unexpected path: %r' % path)
        log.info("read: {} offset: {} size: {} ({})".format(path, offset, size, fh))
        return track.read(offset, size)

    def readdir(self, path, fh):
        artist_dir_m = self.artist_dir.match(path)
        artist_album_dir_m = self.artist_album_dir.match(path)
        playlist_dir_m = self.playlist_dir.match(path)
        
        if path == '/':
            return ['.', '..', 'artists', 'playlists']
            
        elif path == '/artists':
            return ['.', '..'] + self.library.artists_by_name.keys()
            
        elif path == '/playlists':
            return ['.', '..'] + self.library.playlists.keys()
            
        elif artist_dir_m:
            # Artist directory, lists albums.
            parts = artist_dir_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            return ['.', '..'] + [str(album) for album in artist.albums.values()]
            
        elif artist_album_dir_m:
            # Album directory, lists tracks.
            parts = artist_album_dir_m.groupdict()
            artist = self.library.artists_by_name[parts['artist']]
            album = artist.albums[parts['album']]
            return ['.', '..'] + [str(track) for track in album.tracks.values()]
            
        elif playlist_dir_m:
            # Playlists directory, lists tracks.
            parts = playlist_dir_m.groupdict()
            playlist = self.library.playlists[parts['playlist']]
            return ['.', '..'] + [str(track) for track in playlist.tracks.values()]
            
        return ['.', '..']


def main():
    log.setLevel(logging.WARNING)
    logging.getLogger('gmusicapi').setLevel(logging.WARNING)
    logging.getLogger('fuse').setLevel(logging.WARNING)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description='GMusicFS')
    parser.add_argument('mountpoint', help='The location to mount to')
    parser.add_argument('-f', '--foreground', dest='foreground',
                        action="store_true",
                        help='Don\'t daemonize, run in the foreground.')
    parser.add_argument('-v', '--verbose', help='Be a little verbose',
                        action='store_true', dest='verbose')
    parser.add_argument('-vv', '--veryverbose', help='Be very verbose',
                        action='store_true', dest='veryverbose')
    parser.add_argument('-t', '--truefilesize', help='Report true filesizes'
                        ' (slower directory reads)',
                        action='store_true', dest='true_file_size')
    parser.add_argument('--allow_other', help='Allow all system users access to files'
                        ' (Requires user_allow_other set in /etc/fuse.conf)',
                        action='store_true', dest='allow_other')
    parser.add_argument('--allow_root', help='Allow root access to files',
                        action='store_true', dest='allow_root')
    parser.add_argument('--uid', help='Set filesystem uid (numeric)', default=os.getuid(),
                        action='store', dest='uid')
    parser.add_argument('--gid', help='Set filesystem gid (numeric)', default=os.getgid(),
                        action='store', dest='gid')
    parser.add_argument('--nolibrary', help='Don\'t scan the library at launch',
                        action='store_true', dest='nolibrary')
    parser.add_argument('-l', '--lowercase', help='Convert all path elements to lowercase',
                        action='store_true', dest='lowercase')

    args = parser.parse_args()

    mountpoint = os.path.abspath(args.mountpoint)

    # Set verbosity:
    if args.veryverbose:
        log.setLevel(logging.DEBUG)
        logging.getLogger('gmusicapi').setLevel(logging.DEBUG)
        logging.getLogger('fuse').setLevel(logging.DEBUG)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 10
    elif args.verbose:
        log.setLevel(logging.INFO)
        logging.getLogger('gmusicapi').setLevel(logging.INFO)
        logging.getLogger('fuse').setLevel(logging.INFO)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 1
    else:
        log.setLevel(logging.WARNING)
        logging.getLogger('gmusicapi').setLevel(logging.WARNING)
        logging.getLogger('fuse').setLevel(logging.WARNING)
        logging.getLogger('requests.packages.urllib3').setLevel(logging.WARNING)
        verbosity = 0

    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, scan_library=not args.nolibrary, lowercase=args.lowercase)
    try:
        FUSE(fs, mountpoint, foreground=args.foreground,
                    ro=True, nothreads=True, allow_other=args.allow_other, allow_root=args.allow_root, uid=args.uid, gid=args.gid)
    finally:
        fs.cleanup()

if __name__ == '__main__':
    main()
