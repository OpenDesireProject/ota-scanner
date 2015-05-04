#!/usr/bin/python
# File scanner for CyanogenMod OTA download server.
# Copyright (C) 2015  Niko Hyrynsalmi (Mustaavalkosta)
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

from __future__ import print_function
from fakesechead import FakeSecHead
import ConfigParser
import MySQLdb as mdb
import hashlib
import os
import sys
import time
import zipfile

DEBUG = 0

# Retrieve MD5 sum for a zip
def get_md5(file):
    md5string = ''
    # Check if .md5sum file exists, otherwise calculate directly from zip file
    if os.path.isfile(file + '.md5sum'):
        md5string = open(file + '.md5sum').read().split('  ')[0]
    else:
        md5string = hashlib.md5(open(file, 'rb').read()).hexdigest()
    return md5string

# Form download url
def get_url(file):
    url = base_url
    url += file.replace(base_path, '')
    return url

# Form changelog url
def get_changelog_url(file):
    url = base_url
    url += os.path.dirname(file).replace(base_path, '') + '/changelogs/' + os.path.basename(file).replace('.zip', '.changelog')
    return url

# Scan path for zip files and extract information
def scan_path(path):
    found_files = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file.endswith(".zip"):
                found_files.append(os.path.join(root, file))
    return found_files

# Extract data from build.prop inside zip files
def extract_data(files):
    build_prop_data = []
    for file in files:
        with zipfile.ZipFile(file) as z:
            with z.open("system/build.prop") as f:
                cp = ConfigParser.ConfigParser()
                cp.readfp(FakeSecHead(f))
                device = cp.get('properties', 'ro.cm.device')
                filename = os.path.basename(file)
                incremental = cp.get('properties', 'ro.build.version.incremental')
                timestamp = cp.get('properties', 'ro.build.date.utc')
                md5sum = get_md5(file)
                try:
                    channel = cp.get('properties', 'ro.odp.releasetype').lower()
                except ConfigParser.NoOptionError:
                    if DEBUG:
                        print("ro.odp.releasetype property not found... skipping.")
                    continue
                api_level = cp.get('properties', 'ro.build.version.sdk')
                url = get_url(file)
                changes = get_changelog_url(file)
                build_prop_data.append({"device" : device, "filename" : filename, "incremental" : incremental,
                    "timestamp" : timestamp, "md5sum" : md5sum, "channel" : channel, "api_level" : api_level,
                    "url" : url, "changes" : changes})
    return build_prop_data

# Sync data to database
def sync_database(data):
    # Read connection info from config file
    dbconf = ConfigParser.ConfigParser()
    dbconf.read('config.ini')
    host = config.get('database', 'host')
    port = config.getint('database', 'port')
    user = config.get('database', 'user')
    passwd = config.get('database', 'passwd')
    db = config.get('database', 'db')

    try:
        con = mdb.connect(host, user, passwd, db, port);
        with con:
            cur = con.cursor()

            # Get existing urls from database for this mirror
            cur.execute("SELECT url FROM updates WHERE mirror_id = %s", (mirror_id,))
            rows = cur.fetchall()
            old_urls = []

            for row in rows:
                old_urls.append(row[0])

            # Insert/update file information to database
            for ota in data:
                if DEBUG:
                    print("Inserting/updating " + ota["filename"])
                cur.execute("""INSERT INTO updates (filename, device, incremental, timestamp, md5sum, channel, api_level, url, changes, mirror_id)
                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE
                        filename=VALUES(filename), device=VALUES(device), incremental=VALUES(incremental), timestamp=VALUES(timestamp), md5sum=VALUES(md5sum),
                        channel=VALUES(channel), api_level=VALUES(api_level), changes=VALUES(changes), mirror_id=VALUES(mirror_id)""",
                        (ota["filename"], ota["device"], ota["incremental"], ota["timestamp"], ota["md5sum"], ota["channel"], ota["api_level"], ota["url"],
                            ota["changes"], mirror_id))
                # File still exists so remove from to-be-removed list
                if ota["url"] in old_urls:
                    old_urls.remove(ota["url"])

            # Clean up old files from database
            for old_url in old_urls:
                if DEBUG:
                    print("Removing " + old_url)
                cur.execute("DELETE FROM updates WHERE mirror_id = %s AND url = %s", (mirror_id,old_url))

    except mdb.Error, e:
        print("Error %d: %s" % (e.args[0],e.args[1]))
        sys.exit(1)

###############################################################################
## Main                                                                       #
###############################################################################

# Initialize variables from config file
config = ConfigParser.ConfigParser()
config.read('config.ini')
mirror_id = config.getint('general', 'mirror_id')
base_url = config.get('general', 'base_url')
base_path = config.get('general', 'base_path')
scan_dirs = config.get('general', 'scan_dirs').split(':')

files = []
for dir in scan_dirs:
    files.extend(scan_path(base_path + dir))

ota_data = extract_data(files)

sync_database(ota_data)
