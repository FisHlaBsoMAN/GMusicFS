

from .tools  import Tools
from .artist import Artist
from .album  import Album

import urllib

import tempfile

from eyed3.id3 import Tag, ID3_V2_4

import os


import pprint
pp  = pprint.PrettyPrinter(indent=2)  # For debug logging


from stat import S_IFDIR, S_IFREG

class Track(object):
    ID3V1_TRAILER_SIZE = 128

    # TODO: check:
    TRACK_REGEX = '(?P<disk>[0-9]+)-(?P<track>(?P<number>[0-9]+)) - (?P<trartist>.+?) - (?P<tralbum>.+?) - ((?P<title>.*)\.mp3)'
    TRACK_FORMAT = "{disk:02d}-{number:02d} - {artist_printable} - {album_printable} - {title_printable}.mp3"
    TRACK_TRACKS_FORMAT = "{disk:02d}-{number:02d} - {trartist} - {title}.mp3"

    TRACKS_REGEX = '^/tracks/' + TRACK_REGEX + '$'


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

        path = (
                "/artists/" +
                self.album_artist_printable + "/" +  # TODO: chech plz
                str(self.album) + "/" +
                str(self)
        )


        print(path)
        return str(path)

    def __init__ (self, library, data):
        self.__library = library
        self.__data = data

        self.__artists      = {}
        self.__albums       = {}
        self.__ppp          = {}
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
        self.__title_printable = Tools.strip_text(self.__title)

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
            self.__artist = Artist.NO_ARTIST_TITLE
            print("# track has no artist")

        # track_artist_printable
        self.__artist_printable = Tools.strip_text(self.__artist)

        # track_album
        if 'album' in data and data['album'].strip() != "":
            self.__album = data['album']
        else:
            self.__album = Album.NO_ALBUM_TITLE
            print("# track has no album")

        # track_artist_printable
        self.__album_printable = Tools.strip_text(self.__album)

        # album_artist
        if 'albumArtist' in data and data['albumArtist'].strip() != "":
            self.__album_artist = data['albumArtist']
        else:
            self.__album_artist = ""
            print("# track has no albumArtist")

        # track_artist_printable
        self.__album_artist_printable = Tools.strip_text(self.__album_artist)

        if 'year' in data:
            self.__year = data['year']
        else:
            self.__year = 0
            print("# track has no year")

    def add_album (self, album):  # TODO: check before insert? may be move outside check in class???? may be name conflicts
        self.__albums[album.title_printable] = album

    def add_artist (self, artist):  # TODO: check before insert? may be move outside check in class???? may be name conflicts
        self.__artists[artist.name_printable] = artist

    #see musiclibrary
    def add_path (self, path):
        self.__ppp[path] = 1
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



        #TODO: symlinking links
        if self.path == req_path: # path from
            linkink = 0
            print("\n\n########## paths coincide!\n\n")
        else:
            #see
            #return 0
            print("\n\n########## NOT paths coincide -> readlink!\n\n")
            linkink = S_IFLNK

        st = {'st_mode':    (linkink|S_IFREG|0o666), 'st_nlink': 1, 'st_ctime': 0, 'st_mtime': 0, 'st_atime': 0,
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
            try:
                self.__stream_url = urllib.request.FancyURLopener({}).open(self.__library.get_stream_url(self.id))
            except:
                return None
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
        return
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
        value2 = self.TRACK_FORMAT.format(
                disk             = int(self.disk),
                number           = int(self.number),
                artist_printable = self.artist_printable,
                album_printable  = self.album_printable,
                title_printable  = self.title_printable
        )
        return value2
