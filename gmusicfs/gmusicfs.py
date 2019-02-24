#!/usr/bin/env python3

import argparse
import configparser
import logging
# import inspect
import os
import pprint
import re
import tempfile
import traceback
import urllib
# import hashlib
import time, threading


import magic

mime = magic.Magic(mime=True)

from errno import ENOENT
from stat import S_IFDIR, S_IFREG

from eyed3.id3 import Tag, ID3_V2_4
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

# import gmusicapi.exceptions

from gmusicapi import Mobileclient as GoogleMusicAPI
from gmusicapi import Webclient    as GoogleMusicWebAPI # need for getting device id's

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
pp  = pprint.PrettyPrinter(indent=2)  # For debug logging



ALBUM_REGEX  = '(?P<album>[^/]+) \((?P<year>[0-9]{4})\)'
ALBUM_REGEX2 = '(?P<album>[^/]+) \((?P<year>[0-9]{4})\)/' # TODO: TEMPORARY, check bug of path's ending "/"

ALBUM_FORMAT = "{0.title_printable} ({0.year:04d})"

# TODO: check:
TRACK_REGEX         = '(?P<disk>[0-9]+)-(?P<track>(?P<number>[0-9]+)) - (?P<trartist>.+?) - (?P<tralbum>.+?) - ((?P<title>.*)\.mp3)'
TRACK_FORMAT        = "{disk:02d}-{number:02d} - {artist_printable} - {album_printable} - {title_printable}.mp3"
TRACK_TRACKS_FORMAT = "{disk:02d}-{number:02d} - {trartist} - {title}.mp3"

PLAYLIST_REGEX = '^/playlists/(?P<playlist>[^/]+)/' + TRACK_REGEX + '$'
TRACKS_REGEX   = '^/tracks/' + TRACK_REGEX + '$'

ID3V1_TRAILER_SIZE = 128

NO_ALBUM_TITLE  = "No Album"
NO_ARTIST_TITLE = "No Artist"


def strip_text (string_from):
    """Format a name to make it suitable to use as a filename"""
    return re.sub('[^\w0-9_\.!?#@$ ]+', '_', string_from.strip())


def getDeviceId (verbose=False):
    print("GO")
    cred_path = os.path.join(os.path.expanduser('~'), '.gmusicfs/gmusicfs') # TODO: move to library?
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
    username = config.get('credentials', 'username')
    password = config.get('credentials', 'password')
    if not username or not password:
        raise NoCredentialException(
                'No username/password could be read from config file'
                ': %s' % cred_path)

    api = GoogleMusicWebAPI(debug_logging=verbose)
    log.info('Logging in...')
    api.login(username, password)
    log.info('Login successful.')

    for device in api.get_registered_devices():
        if not 'name' in device or not device['name']:
            device['name'] = 'NoName'
        if device['id'][1] == 'x':
            pp.pprint(device)


    del api # not forget



class NoCredentialException(Exception):
    pass


class Artist(object):
    NO_ARTIST_TITLE = "No Artist"

    def __init__ (self, library, data, name=None):
        self.__library = library
        self.__albums = {}
        self.__tracks = {}
        self.__data = data

        # name
        if name is None and 'artist' in data and data['artist'].strip() != "":
            self.__name = data['artist']
        elif name is not None and name.strip() != "" and False:  # TODO: remove me. bypass
            self.__name = name
        else:
            self.__name = self.NO_ARTIST_TITLE

        # name_printable
        self.__name_printable = strip_text(self.__name)

        # artist_id
        if 'artistId' in data:
            self.__id = data['artistId']
        else:
            self.__id = self.__name

    @property
    def id (self):
        return self.__id

    @property
    def name (self):
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

    def add_album (self, album):
        if album.title_printable not in self.__albums:
            self.__albums[album.title_printable] = album

    def add_track (self, track):
        if str(track) not in self.__tracks:
            self.__tracks[str(track)] = track
        else:
            print("TRACK EXISTS")

    # TODO: check it
    def __str__ (self):
        return "{0.name_printable}".format(self)


class Album(object):

    def __init__(self, library, data):
        self.__library    = library
        self.__data       = data
        self.__tracks     = {}
        self.__artists    = {}
        self.__art        = bytes()
        self.__art_mime   = b'image/jpeg'
        self.__album_info = None

        # album_title
        if 'album' in data and data['album'].strip() != "":
            self.__album_title = data['album']
        else:
            self.__album_title = NO_ALBUM_TITLE

        # album_title_printable
        self.__album_title_printable = strip_text(self.__album_title)

        # album_artist ## self.__artist = self.__library.artists.get(data['artistId'][0], None)
        if 'albumArtist' in data and data['albumArtist'].strip() != "":
            self.__album_artist = data['albumArtist']
        elif 'artist' in data and data['artist'].strip() != "":
            self.__album_artist = data['artist']
        else:
            self.__album_artist = NO_ARTIST_TITLE

        # album_artist_printable
        self.__album_artist_printable = strip_text(self.__album_artist)

        # album_id
        if 'albumId' in data:
            self.__id = data['albumId']
        elif strip_text(self.__album_title) == strip_text(NO_ALBUM_TITLE):
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
    def id(self):
        return self.__id

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
        return self.__art_mime



    def add_track (self, track):
        self.__tracks[str(track)] = track
        if track.id not in self.__library.tracks:  # TODO: may be from playlists check it
            self.__library.tracks[track.id] = track

    def add_artist (self, artist):
        self.__artists[artist.name_printable] = artist

    def __get_year (self):
        # some tracks are not loaded from album_info, let's use them to get the album date release
        for track in self.__tracks.values():
            self.__year = track.year or self.__year

    # TODO: need check image type! some tracks has png cover
    def __load_art (self):
        if not self.__art_url:
            return
        log.info("loading art album: {0.title}".format(self))
        self.__art = bytes()

        art_path = os.path.join(os.path.expanduser('~'), '.gmusicfs', 'album_arts',   #TODO: make one var of path's
                                strip_text(self.id))  # without extension

        for ext in ['.jpg', '.png']:
            # noinspection PyBroadException
            try:
                local_art = open(art_path + ext, "rb")
                break
            except Exception:
                local_art = ""

        if local_art:
            print("# ART FROM FS")
            data = local_art.read()
            while data:
                self.__art += data
                data = local_art.read()
            local_art.close()
        else:
            print("# ART FROM URL")
            u = urllib.request.urlopen(self.__art_url)

            # TODO: do-while
            data = u.read()
            while data:
                self.__art += data
                data = u.read()
            u.close()

            self.__art_mime = mime.from_buffer(self.__art)

            if self.__art_mime == b'image/jpeg':
                file_extension = '.jpg'
            elif self.__art_mime == b'image/png':
                file_extension = '.png'
            else:  # todo: more variant?
                self.__art_mime = None
                self.__art = None
                return

            print("# ART WRITING TO DISK")
            local_art = open(art_path + file_extension, "wb")
            local_art.write(self.__art)
            local_art.close()

        print("loading art album: {0.title_printable} {0.art_mime}".format(self) + " done!")

    def __str__ (self):
        title2 = ALBUM_FORMAT.format(self)
        return title2


class Track(object):

    @property
    def id (self):
        return self.__id

    @property
    def title (self):
        return self.__title.strip()

    @property
    def stream_size (self):
        if not self.__stream_size and True:
            if 'length' in self.__data:
                self.__stream_size = int(self.__data['length'])
                print("#USING length")
            elif 'bytes' in self.__data:
                self.__stream_size = int(self.__data['bytes'])
                print("#USING BYTES")
            elif 'estimatedSize' in self.__data:
                self.__stream_size = int(self.__data['estimatedSize'])
                print("#USING estimatedSize")
            elif 'tagSize' in self.__data:
                self.__stream_size = int(self.__data['tagSize'])  # wtf?? #TODO: need fixing
                print("#USING tagSize")
            elif 'durationMillis' in self.__data:
                self.__stream_size = \
                    int(
                            (
                                    int(self.__data['durationMillis']) / 1000 + 1
                            ) * 320 / 8 * 1000
                    )
                print("#USING durationMillis")
            else:
                print("#USING fake size")
                self.__stream_size = 0
                self.__stream_size = 1 * 1024 * 1024

        return self.__stream_size + self.__tag_length

    @property
    def title_printable (self):
        return self.__title_printable

    @property
    def number (self):
        return self.__number

    @property
    def disk (self):
        return self.__disk

    @property
    def album (self):
        return self.__album

    @property
    def album_printable (self):
        return self.__album_printable

    @property
    def artist (self):
        return self.__artist

    @property
    def artist_printable (self):
        return self.__artist_printable

    @property
    def album_artist (self):
        return self.__album_artist

    @property
    def album_artist_printable (self):
        return self.__album_artist_printable

    @property
    def year (self):
        return self.__year

    @property
    def path (self):
        return self.__path

    def __init__ (self, library, data):
        self.__library = library
        self.__data = data

        self.__artists      = {}
        self.__albums       = {}
        self.__stream_url   = None
        self.__stream_cache = bytes()
        self.__rendered_tag = bytes()
        self.__tag          = ""
        self.__stream_size  = 0
        self.__tag_length   = 0
        self.__path         = None
        self.__num_of_open  = 0

        # TODO: its necessary to understand how it works
        # track_id
        if 'track' in data:
            self.__id = data['trackId']
            print("# track use trackId")
        elif 'id' in data:
            self.__id = data['id']
            print("# track use id")
        elif 'storeId' in data:
            self.__id = data['storeId']
            print("# track use storeId")
        else:
            self.__id = data['nid']
            print("# track use nid")

        # track_title
        if 'title' in data:
            self.__title = data['title']
        else:
            self.__title = "unknown_track_" + data['id']
            print("# track has no title")

        # track_title_printable
        self.__title_printable = strip_text(self.__title)

        # track_number
        if 'trackNumber' in data:
            self.__number = data['trackNumber']
        else:
            self.__number = 0
            print("# track has no track num")

        # track_disk
        if 'diskNumber' in data:
            self.__disk = data['diskNumber']
        else:
            self.__disk = 0
            print("# track has no diskNumber")

        # track_artist
        if 'artist' in data and data['artist'].strip() != "":
            self.__artist = data['artist']
        elif 'albumArtist' in data and data['albumArtist'].strip() != "":
            self.__artist = data['albumArtist']
            print("# track artist from albumArtist")  # TODO: needed??
        else:
            self.__artist = NO_ARTIST_TITLE
            print("# track has no artist")

        # track_artist_printable
        self.__artist_printable = strip_text(self.__artist)

        # track_album
        if 'album' in data and data['album'].strip() != "":
            self.__album = data['album']
        else:
            self.__album = NO_ALBUM_TITLE
            print("# track has no album")

        # track_artist_printable
        self.__album_printable = strip_text(self.__album)

        # album_artist
        if 'albumArtist' in data and data['albumArtist'].strip() != "":
            self.__album_artist = data['albumArtist']
        else:
            self.__album_artist = ""
            print("# track has no albumArtist")

        # track_artist_printable
        self.__album_artist_printable = strip_text(self.__album_artist)

        if 'year' in data:
            self.__year = data['year']
        else:
            self.__year = 0
            print("# track has no year")

    def add_album (self, album):  # TODO: check before insert? may be move outside check in class???? may be name conflicts
        self.__albums[album.title_printable] = album

    def add_artist (self, artist):  # TODO: check before insert? may be move outside check in class???? may be name conflicts
        self.__artists[artist.name_printable] = artist

    def add_path (self, path):
        if not self.__path:
            self.__path = path
        else:
            print("exist\n")

    def set_num_of_open (self, num):
        self.__num_of_open = num

    def __gen_tag (self):
        print("Creating tag idv3...")
        self.__tag = Tag()
        self.__tag.album = self.album
        self.__tag.artist = self.artist
        self.__tag.title = self.title
        self.__tag.disk_num = int(self.disk)
        self.__tag.track_num = int(self.number)

        if 'genre' in self.__data:
            self.__tag.genre = self.__data['genre']

        if self.album_artist != 'genre':
            self.__tag.album_artist = self.album_artist

        if int(self.year) != 0:
            self.__tag.recording_date = self.year

        if self.album_printable in self.__albums and self.__albums[self.album_printable].art:
            mime_type = self.__albums[self.album_printable].art_mime  # TODO: check mimetype
            '''
            print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
            print(self.__albums[self.album_printable].art)
            print("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
            '''
            # self.__tag.images.set(0x03, self.__albums[self.album_printable].art, 'image/png' )
            self.__tag.images.set(0x03, self.__albums[self.album_printable].art, mime_type, u'Front cover')

        else:
            print("# track has no art?")

        #  ###### pp.pprint(self.__tag.__dict__)

        # TODO: wtf??
        tmpfd, tmpfile = tempfile.mkstemp()
        os.close(tmpfd)

        self.__tag.save(tmpfile, ID3_V2_4)
        tmpfd = open(tmpfile, "rb")
        self.__rendered_tag = tmpfd.read()

        # TODO: NEED CHECKING
        # pp.pprint(self.__rendered_tag)

        tmpfd.close()
        os.unlink(tmpfile)
        return

    def get_attr (self, req_path):

        pp.pprint(req_path)
        #pp.pprint(self.__dict__)

        # st = {'st_mode': (S_IFREG | 0o777), 'st_nlink': 1, 'st_ctime': 0, 'st_mtime': 0, 'st_atime': 0, 'st_blksize': 512, 'st_blocks': (self.__data['playCount']*1954)}
        S_IFLNK = 0o120000 # LINK MASK

        print("LET'S GO!\n path1:")
        pp.pprint(self.path)
        print("vs\n reqed_path")
        pp.pprint(req_path)
        print("\n\n\n")




        if self.path == req_path: # path from
            linkink = 0
            print("\n\n########## paths coincide!\n\n")
        else:
            print("\n\n########## NOT paths coincide -> readlink!\n\n")
            linkink = S_IFLNK

        st = {'st_mode':    (linkink|S_IFREG|0o777), 'st_nlink': 1, 'st_ctime': 0, 'st_mtime': 0, 'st_atime': 0,
              'st_blksize': 512, 'st_blocks': 1}

        # todo: need validate data
        # print("#$#$#$#$#$")
        # pp.pprint(self.__dict__)
        # print("#$#$#$#$#$")

        if self.stream_size != 0:
            st['st_size'] = self.stream_size
            print("#STREAM SIZE: %d" % self.stream_size)
        else:
            st['st_size'] = 600 * 1024 * 1024  # 50MB
            print("ALERT! UNKNOWN SIZE")

        # TODO: caching filesize
        '''
        elif 'bytes' in self.__data:
            st['st_size'] = int(self.__data['bytes'])
        elif 'estimatedSize' in self.__data:
            st['st_size'] = int(self.stream_size)
        else:
            if 'tagSize' in self.__data:
                st['st_size'] = int(self.__data['tagSize'])  # wtf??
            else:
                print("####tagSize... wtf?")
                st['st_size'] = 0
                st['st_mode'] = (S_IFREG | 0o000)
        '''

        if 'creationTimestamp' in self.__data:
            st['st_ctime'] = st['st_mtime'] = int(self.__data['creationTimestamp']) / 1000000

        if 'recentTimestamp' in self.__data:
            st['st_atime'] = int(self.__data['recentTimestamp']) / 1000000

        return st

    def open (self):
        print("#######file openned!")
        # self.__num_of_open+=1
        # print(self.__data)
        pass
        # self.__stream_url = urllib.request.urlopen(self.__library.get_stream_url(self.id))
        # self.__stream_cache += self.__stream_url.read(64*1024) # Some caching


    # I XZ how it works!
    def read (self, read_offset, read_chunk_size):

        print("RUN READ: offset:" + str(read_offset) + "; size: " + str(read_chunk_size))

        if self.stream_size < 10:
            print("INVALID TRACK")
            return  # TODO: skip invalid tracks

        if not self.__tag:  # Crating tag only when needed WTAF
            print("#### # # CRATE TAG")
            self.__gen_tag()
            self.__stream_cache += bytes(self.__rendered_tag)

        # TODO: optimize it!
        tag_length = len(self.__rendered_tag)  # need?
        self.__tag_length = tag_length

        if read_offset == 0 and not self.__stream_url:
        #if not self.__stream_url:
            print('####### FIRST RUN TRACK')
            self.__stream_url = urllib.request.FancyURLopener({}).open(self.__library.get_stream_url(self.id))

            self.__stream_size = self.__stream_url.length
            self.__stream_cache += self.__stream_url.read(128 * 1024)  # 128kb?

        if not self.__stream_url:  # error while getting url
            # TODO:check it
            print("### Could't get stream url!")
            # print(self)
            print(self.id)
            print("offset " + str(read_offset))
            print("### END Could't get stream url!")
            return None

        # TODO: need test slow connection
        pos = (read_offset + read_chunk_size)
        # If we read the end of the file (the last 4 * 4k) and the track is not half loaded,
        # then we send to the hears of the one who reads
        if pos >= int(self.stream_size) - 10 * 4096 \
                and len(self.__stream_cache) - tag_length < (int(self.stream_size) / 2
        ):
            print("\033[032moffset:     \t%10.3fK\033[0m" % (read_offset / 1024))
            print("estSize:    \t%10.3fK" % (int(self.stream_size) / 1024))
            print("Read Consistently!")
            return None

        # Crutch

        print("\n############ debugPos")
        print("tag_length: \t%10.3fK" % (tag_length / 1024))
        print("#pos:       \t%10.3fK" % (pos / 1024))
        print("offset:     \t%10.3fK" % (read_offset / 1024))
        print("size:       \t%10.3fK" % (read_chunk_size / 1024))
        print("estSize:    \t%10.3fK" % (int(self.stream_size) / 1024))

        downloaded_stream_len = len(self.__stream_cache) - tag_length
        diff = downloaded_stream_len - tag_length - (read_offset + read_chunk_size)

        # TODO: move to while.... wtf is this???
        if downloaded_stream_len - read_chunk_size * 2 > read_offset + read_chunk_size:
            print("#from cache...")
        else:
            iter1 = 0
            try_no = 0
            while self.__stream_url:
                print("\033[031m\t\t\tDownloading.. %d chunk\033[0m" % iter1)
                iter1 += 1
                # TODO: check endless loop

                remain = (self.__stream_size - downloaded_stream_len)
                if remain <= 0:
                    print("Already downloaded")
                    break
                else:
                    print("remain..: %d" % remain)
                size_of_buffer = (read_chunk_size * 2) + (32 * 1024)

                if size_of_buffer > self.__stream_size - (len(self.__stream_cache) - tag_length):
                    print("TRIGGERED FAKING BUFER OVERFLOW@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
                    if (len(self.__stream_cache) - tag_length) < self.__stream_size:
                        print("last bytes: '%d' > 0 " % (self.__stream_size - len(self.__stream_cache) - tag_length))
                        if read_chunk_size > remain:
                            print("NEED TESTING (read_chunk_size > remain)!!!!")
                        size_of_buffer = remain
                    else:
                        print("downloaded size > stream size! breaking")
                        print("'%d' < 0" % (self.__stream_size - len(self.__stream_cache) - tag_length))
                        break
                chunk = self.__stream_url.read(size_of_buffer)

                self.__stream_cache += chunk  # simply offset?#read all now?
                downloaded_stream_len = len(self.__stream_cache) - tag_length

                print("##downloaded_stream_len: %d" % downloaded_stream_len)
                print("##tag_length:            %d" % tag_length)
                print("##read_offset:           %d" % read_offset)
                print("##read_chunk_size:       %d" % read_chunk_size)
                print("##size_of_buffer:        %d" % size_of_buffer)
                print("##ro+rcs:                %d" % (read_offset + read_chunk_size))

                print("chunk:                   %10.3fK" % (len(chunk) / 1000))

                if downloaded_stream_len >= (read_offset + read_chunk_size):
                    print("################# ALL ?")
                    break
                if len(chunk) == 0:
                    print("done?")
                    print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!len of chunk == 0")
                    print("downloaded length: %d" % downloaded_stream_len)
                    print("str_size in google %d" % self.__stream_size)
                    remain = (self.__stream_size - downloaded_stream_len)
                    print("remain:            %d" % remain)
                    if remain == 0:
                        print("STREAM DOWNLOADED")
                        break
                    else:  # TODO: need checking
                        print("STREAM IS NOT!!!! FULLY DOWNLOADED")
                        try_no += 1
                        print("try: %d" % try_no)
                        if try_no > 5:

                            self.__stream_url = None
                            print("break overload")
                            break
                        continue


            print("\033[031m\t\t\tDownloading..  OK! %d chunks\033[0m" % iter1)

        len_remain = (downloaded_stream_len + tag_length - read_offset - read_chunk_size)
        # Crutch
        print("#remain:     \t%10.3fK" % (len_remain / 1000))
        print("diff:        \t%10.3fK" % (diff / 1000))
        print("#downloaded: \t%10.3fK" % (downloaded_stream_len / 1000))
        print("#file_size:  \t%10.3fK" % (self.stream_size / 1000))
        print("#read_offset:\t%10.3fK" % (read_offset / 1000))
        print("#read_off+ch:\t%10.3fK" % (read_offset / 1000 + read_chunk_size / 1000))
        print("#tag_size:   \t%10.3fK" % (self.__tag_length / 1000))
        print("real_str_siz:\t%10.3fK" % (self.__stream_size / 1000))

        if len(self.__stream_cache) > self.stream_size:  # TODO: neeed??
            print( '### WHAT? DOWNLOADED SIZE > CALCULATED? {0:10d} > {1:10d}'.format(
                len(self.__stream_cache),
                self.stream_size))

            if read_offset + read_chunk_size > self.stream_size:
                print("## GIVE LAST PART OF FILE")
                return self.__stream_cache[read_offset:self.stream_size]
            else:
                print("#### GIVE SOME OF LAST PARTS OF FILE")
                return self.__stream_cache[read_offset:read_offset + read_chunk_size]
        if read_offset == 0:
            print(self.__stream_cache[read_offset:read_offset + 64])
        return self.__stream_cache[read_offset:read_offset + read_chunk_size]  # need len tas size????




    # TODO: transfer the close logic of closing files from the library
    def close (self):

        if self.__library.gfs.get_num_opens(self.path) < 1:
            print("i cleanup track")
            if self.__stream_url:
                print("#######################################################killing url")
                self.__stream_url.close()
                self.__stream_url = None
                self.__stream_cache = bytes()
                if self.__rendered_tag:
                    self.__stream_cache += bytearray(self.__rendered_tag)
        else:
            print("######################################track opened another")


    def __str__ (self):
        value2 = TRACK_FORMAT.format(
                disk             = int(self.disk),
                number           = int(self.number),
                artist_printable = self.artist_printable,
                album_printable  = self.album_printable,
                title_printable  = self.title_printable
        )
        return value2


class Playlist(object):
    """This class manages playlist information"""

    def __init__ (self, library, data):
        self.__library = library
        self.__id = data['id']
        self.__name = data['name']
        self.__tracks = {}

        for track in data['tracks']:

            # TODO: WTF IS THIS SHIT?
            track_id = track['trackId']
            # noinspection PyBroadException
            try:
                if 'track' in track:
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


class MusicLibrary(object):
    """This class reads information about your Google Play Music library"""

    def __init__ (self, username=None, password=None,  true_file_size=False, verbose=0, gfs=None):

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

            name = strip_text(pl['name'])

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


class GMusicFS(LoggingMixIn, Operations):
    """Google Music Filesystem"""

    def __init__ (self, path, username=None, password=None, true_file_size=False, verbose=0, lowercase=True): # TODO: lovercase

        self.library_path = path

        Operations.__init__(self)

        artist = '/artists/(?P<artist>[^/]+)'  # TODO: remove/move me

        self.artist_dir = re.compile('^{artist}$'.format(artist=artist))

        self.artist_album_dir = re.compile(
            '^{artist}/{album}$'.format(
                artist=artist, album=ALBUM_REGEX
            )
        )

        self.artist_album_dir2 = re.compile(
            '^{artist}/{album}$'.format(
                artist=artist, album=ALBUM_REGEX2
            )
        )
        self.artist_album_track = re.compile(
            '^{artist}/{album}/{track}$'.format(
                artist=artist, album=ALBUM_REGEX, track=TRACK_REGEX
            )
        )

        self.playlist_dir   = re.compile('^/playlists/(?P<playlist>[^/]+)$')
        print(PLAYLIST_REGEX)
        self.playlist_track = re.compile(PLAYLIST_REGEX)
        print(TRACKS_REGEX)
        self.tracks_track   = re.compile(TRACKS_REGEX)

        self.__opened_tracks = {}  # path -> urllib2_obj # TODO: короч отсюда танцувать или чо? я пока завис

        # Login to Google Play Music and parse the tracks:
        self.library = MusicLibrary(username, password, gfs=self, true_file_size=true_file_size, verbose=verbose)
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
            # print("path \"artist_dir_matches\"")
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
            title2 = TRACK_FORMAT.format(
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
            title2 = TRACK_FORMAT.format(
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
                pl_track = playlist.tracks[parts['title']]

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

            title2 = TRACK_FORMAT.format(
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

            title2 = TRACK_FORMAT.format(
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
            track = playlist.tracks[parts['title']]
            print("founded track in playlist " + str(playlist))
        else:
            print("##Error: track not found in any path's!")
            return None

        print("return track!\n\n")
        return track



    ## то что происходит при открытии файла
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


    ## то что происходит при закрытии файла
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
            print("трек открыт еще один раз")


        print("##openned tracks: ")
        pp.pprint(self.__opened_tracks)


    ## то что происходит при чтении файла
    def read (self, path, size, offset, fip):

        log.info("read: {} offset: {} size: {} ({})".format(path, offset, size, fip))
        track = self.gettrack(path)

        key = track.path
        track = self.__opened_tracks.get(key, None)
        if track is None:
            raise RuntimeError('unexpected path: %r' % path)

        return track[1].read(offset, size)

    ## то что происходит при чтении ссылки
    def readlink (self, path):
        print("My new path:" + path)
        track = self.gettrack(path)
        print("Me founded track: " + str(track))
        print("Track class name: " + track.__class__.__name__)



        if track is not None:  # TODO: count the number of slashes
            return "../../.." + track.path
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
    parser.add_argument('-l', '--lowercase', help='Convert all path elements to lowercase',
                        action='store_true', dest='lowercase')
    parser.add_argument('--deviceid', help='Get the device ids bounded to your account',
                        action='store_true', dest='deviceId')

    args = parser.parse_args()

    if args.deviceId:
        getDeviceId()
        return

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
    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, lowercase=args.lowercase)
    # quit()
    try:
        FUSE(fs, mountpoint, foreground=args.foreground, raw_fi=False, ro=True, nothreads=True, allow_other=args.allow_other, allow_root=args.allow_root, uid=args.uid,  gid=args.gid)
    finally:
        fs.cleanup()


if __name__ == '__main__':
    main()
