#!/usr/bin/env python3

import argparse
import logging
import re
from pathlib import Path

from flask import Flask, Response, redirect, request
from waitress import serve
import plyvel

app = Flask(__name__)


class ServeLevelDB:

    def __init__(self, dbfolder):
        """
        Initialize the ServeLevelDB object from a given dbfolder

        :param dbfolder: The relative or absolute path to the LevelDB
        with restored CDC content
        """
        self.dbfolder = dbfolder

        # this is the path of the LevelDB database we converted from
        # .zim using zim_converter.py
        self.db = plyvel.DB(str(self.dbfolder))

        # the LevelDB database has 2 keyspaces, one for the content,
        # and one for its type please check zim_converter.py script
        # comments for more info
        self.content_db = self.db.prefixed_db(b"c-")
        self.mimetype_db = self.db.prefixed_db(b"m-")

    def find_content(self, full_path):
        """
        Find the relevant content, possibly adding or removing an extra '/'

        :param full_path: The original URL, as bytes
        :return: Two values, the content (as bytes), ans the mimetype (as str)
        """
        raw_key = bytes(full_path, "utf-8")

        logging.debug(f"Looking up key: {full_path}")
        content = self.content_db.get(raw_key)
        mimetype_bytes = self.mimetype_db.get(raw_key)

        if content is None or mimetype_bytes is None:
            # Try with, or without a / at the end
            key_match = re.match(r"([^?]+)/\?(.*)$", full_path)
            if key_match:
                raw_key = bytes(
                    key_match.group(1) + "?" + key_match.group(2), "utf-8"
                )
            else:
                key_match = re.match(r"([^?]+)\?(.*)$", full_path)
                if key_match:
                    raw_key = bytes(
                        key_match.group(1) + "/?" + key_match.group(2), "utf-8"
                    )
                else:
                    raw_key = raw_key + b"/"
            logging.debug(f"Looking up secondary key: {raw_key}")
            content = self.content_db.get(raw_key)
            mimetype_bytes = self.mimetype_db.get(raw_key)
            if content is None or mimetype_bytes is None:
                logging.warning(
                    f"Missing content or mimetype for path: {full_path}"
                )
                return None, None

            logging.debug(f"Found {raw_key} after modification")

        mimetype = mimetype_bytes.decode("utf-8")

        return content, mimetype


def rewrite_html_urls(full_path, content):
    """
    Rewrite any of these to point to ourselves, as needed

    <a      href="...">
    <link   href="...">
    <script src="...">
    <img    src="...">

    :param full_path: The full path, to find the relevant (sub)domain
    :param content: The HTML content as bytes
    :return: Rewritten (if needed) HTML content as bytes

    The proper way will be to parse the HTML, and then cross our
    fingers there is nothing in the HTML comments to parse, but for
    now the initial version this does a broad set of text replaces.

    There are also places with references to the original websites in
    srcset attributes and such, so there are no doubt other hidden
    treasures.
    """
    path_match = re.match(r"([^/]+)/", full_path)
    if not path_match:
        # Can't do anything useful here
        return content
    website = path_match.group(1)

    # Looks like the hivrisk.cdc.gov site had some stray references to
    # their staging site, not that it makes much of a difference :)
    content = content.replace(b"hivriskstage.cdc.gov", b"hivrisk.cdc.gov")

    content = content.replace(bytes(f" https://{website}/", "utf-8"),
                              bytes(f" /{website}/", "utf-8"))
    content = content.replace(
        b"href=\"/", bytes(f"href=\"/{website}/", "utf-8")
    )
    content = content.replace(
        b"href=\'/", bytes(f"href=\'/{website}/", "utf-8")
    )
    content = content.replace(bytes(f"href=\"https://{website}/", "utf-8"),
                              bytes(f"href=\"/{website}/", "utf-8"))
    content = content.replace(bytes(f"href=\'https://{website}/", "utf-8"),
                              bytes(f"href=\'/{website}/", "utf-8"))
    content = content.replace(bytes(f"src=\"https://{website}/", "utf-8"),
                              bytes(f"src=\"/{website}/", "utf-8"))
    content = content.replace(bytes(f"src=\'https://{website}/", "utf-8"),
                              bytes(f"src=\'/{website}/", "utf-8"))

    return content


def simplify_path(path):
    """
    Remove any http: and https: and slashes so all that's left is
    subdomain.cdc.gov/...

    :param path: The original full-path
    """
    # Fix missing slash if needed
    if path.startswith("https:/") and not path.startswith("https://"):
        path = path.replace("https:/", "", 1)
        return path

    if path.startswith("http:/") and not path.startswith("http://"):
        path = path.replace("http:/", "", 1)
        return path

    if path.startswith("https://"):
        path = path.replace("https://", "", 1)
        return path

    if path.startswith("http://"):
        path = path.replace("http://", "", 1)
        return path

    return path


@app.route("/")
def home():
    """
    Default route
    """
    return redirect("/www.cdc.gov/")


@app.route("/<path:subpath>")
def lookup(subpath):
    """
    Catch-all route
    """

    try:
        if request.query_string:
            full_path = request.full_path[1:]
        else:
            full_path = request.path[1:]
        logging.debug(f"Full path: {full_path}")

        full_path = simplify_path(full_path)

        content, mimetype = serve_db.find_content(f"https://{full_path}")

        if content is None or mimetype is None:
            return Response("Not Found", status=404)

        if mimetype == "=redirect=":
            redirect_target = content.decode("utf-8")
            logging.info(f"Redirecting from {full_path} to {redirect_target}")
            return redirect(f'/{redirect_target}')

        logging.debug(f"Mime type {mimetype} for {full_path}")

        if full_path.startswith("https://") and (
                mimetype == "text/html" or mimetype.startswith("text/html;")
        ):
            content = rewrite_html_urls(full_path, content)

        # XXX: We probably also need to rewrite URLs in javascript and
        #      stylesheets that we serve up

        return Response(content, mimetype=mimetype)

    except Exception as e:
        logging.exception(f"Error retrieving {subpath}: {e}")
        return Response("Internal Server Error", status=500)


def setup_logging():
    """
    Set up our logging, creating the directory first if necessary
    """
    LOG_DIR = Path("../logs")
    if not LOG_DIR.exists():
        logging.info(f"Creating log directory: {LOG_DIR}")
        LOG_DIR.mkdir(mode=0o755, parents=True)

    # Configure logging: logs to both console and a file
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(levelname)s - %(funcName)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "serve_restoreCDCWarc.log")
        ]
    )


def parse_arguments():
    """
    Parse command line arguments and return the result

    :return: the parsed arguments
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--hostname', default="127.0.0.1", type=str)
    parser.add_argument('--port', default=7070, type=int)
    parser.add_argument(
        '--dbfolder', default="../data/dev/db/cdc_database", type=str
    )
    return parser.parse_args()


def main():
    """
    Main loop
    """
    global serve_db

    setup_logging()
    args = parse_arguments()

    serve_db = ServeLevelDB(args.dbfolder)

    print(f"Starting cdcmirror server process at port {args.port}")
    serve(app, host=args.hostname, port=args.port)


if __name__ == "__main__":
    main()
