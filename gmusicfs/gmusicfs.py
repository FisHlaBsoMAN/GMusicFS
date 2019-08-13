#!/usr/bin/env python3

import configparser
import logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('gmusicfs')
# import inspect
import os
import re
import argparse


from fuse import FUSE

import magic

mime = magic.Magic(mime=True)


# import gmusicapi.exceptions
#from gmusicapi import Webclient    as GoogleMusicWebAPI # need for getting device id's
#from gmusicapi import Mobileclient    as GoogleMusicWebAPI # need for getting device id's

from gmusicfs import Tools, GMusicFS, MusicLibrary, NoCredentialException, Track, Album, Artist, Playlist

from gmusicapi import Mobileclient    as GoogleMusicMobileclient # need for getting device id's # TODO: mobile client need for getting devices. need dynamic change somes
#from gmusicfs import *



def main():
    log.setLevel(logging.ERROR)
    logging.getLogger('gmusicapi').setLevel(logging.ERROR)
    logging.getLogger('fuse').setLevel(logging.ERROR)
    logging.getLogger('requests.packages.urllib3').setLevel(logging.ERROR)

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





    if args.deviceId: #TODO выделить отдельно иницаиализацию фс и медиатеки
        library = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, lowercase=args.lowercase, check=True)
        api = GoogleMusicMobileclient(debug_logging=logging.VERBOSE)
        library.getDeviceId(api)
        return
    fs = GMusicFS(mountpoint, true_file_size=args.true_file_size, verbose=verbosity, lowercase=args.lowercase,  check=False)

    # quit()
    try:
        os.system("fusermount -uz " + mountpoint)
        FUSE(fs, mountpoint, foreground=args.foreground, raw_fi=False, ro=True, nothreads=True, allow_other=args.allow_other, allow_root=args.allow_root, uid=args.uid,  gid=args.gid)
    finally:
        fs.cleanup()




if __name__ == '__main__':
    main()
