#!/usr/bin/env python3

import argparse
import json
import logging
import re
from pathlib import Path
from urllib import parse
from urllib.parse import urlparse


from flask import Flask, Response, redirect, render_template, request, url_for, jsonify
from waitress import serve
import plyvel

# Logging directory setup
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

parser = argparse.ArgumentParser()
parser.add_argument('--hostname', default="127.0.0.1", type=str)
parser.add_argument('--port', default=7070, type=int)
parser.add_argument('--dbfolder', default="../../Restore-CDC-WARC/data/dev/db/cdc_database", type=str)
args = parser.parse_args()

# this is the path of the LevelDB database we converted from .zim using zim_converter.py
db = plyvel.DB(str(args.dbfolder))

# the LevelDB database has 2 keyspaces, one for the content, and one for its type
# please check zim_converter.py script comments for more info
content_db = db.prefixed_db(b"c-")
mimetype_db = db.prefixed_db(b"m-")

app = Flask(__name__)

# serving to localhost interfaces at port 9090
hostName = args.hostname
serverPort = args.port

def rewrite_html_urls(full_path, content):
    """
    Rewrite any link to a *.cdc.gov URL in attributes or raw text
    to point to local /<domain>/ paths (e.g. /www.cdc.gov/foo).
    """

    # Fix known staging domains
    content = content.replace(b"hivriskstage.cdc.gov", b"hivrisk.cdc.gov")

    # Match any *.cdc.gov domain
    domain_pattern = rb'([a-zA-Z0-9.-]+\.cdc\.gov)'

    # --- Step 1: Rewrite in href/src/srcset attributes ---
    content = re.sub(
        rb'(?P<attr>(href|src|srcset))=(["\'])https://' + domain_pattern + rb'/',
        rb'\g<attr>=\3/\1/',
        content
    )

    # --- Step 2: Rewrite raw URLs in text or JS ---
    # Avoid replacing URLs that are already rewritten (e.g. starting with `/www.cdc.gov`)
    # Match: https://[sub].cdc.gov/whatever
    content = re.sub(
        rb'(?<!["\'=/])https://' + domain_pattern + rb'/',
        rb'/\1/',
        content
    )

    # --- Step 3: Rewrite relative URLs (e.g. href="/foo") to include domain path ---
    # Only if we can infer current domain from full_path
     # Ensure full_path is bytes for regex
    if isinstance(full_path, str):
        full_path = full_path.encode()

    # Extract domain from the beginning of the path (e.g., "hivrisk.cdc.gov")
    domain_match = re.match(rb'^/?([a-zA-Z0-9.-]+\.cdc\.gov)\b', full_path)
    current_domain = domain_match.group(1) if domain_match else None

    if domain_match:
        domain = domain_match.group(1)
        content = re.sub(
            rb'(?P<attr>(href|src|srcset))=(["\'])/',
            rb'\g<attr>=\3/' + domain + b'/',
            content
        )
    # --- Step 4: Match JS-style object properties like "key": "https://*.cdc.gov/..."
    content = re.sub(
        rb'(:\s*["\'])https://([a-zA-Z0-9.-]+\.cdc\.gov)/',
        rb'\1/\2/',
        content
    )
    
    # --- Step 5: Rewrite localhost:8080 references to the mirrored domain path ---
    if current_domain:
        content = re.sub(
            rb'https?://localhost:8080/',
            b'/' + current_domain + b'/',
            content
        )


    return content

    

def find_content(full_path):
    """
    Find the relevant content, possibly adding or removing an extra '/'

    :param full_path: The original URL, as bytes
    :return: Two values, the content (as bytes), ans the mimetype (as str)
    """
    raw_key = b"https://" + bytes(full_path, "utf-8")

    logging.debug(f"Looking up key: {full_path}")
    content = content_db.get(raw_key)
    mimetype_bytes = mimetype_db.get(raw_key)

    if content is None or mimetype_bytes is None:
        # Try with, or without a / at the end
        key_match = re.match(r"([^?]+)/\?(.*)$", full_path)
        if key_match:
            raw_key = bytes(key_match.group(1) + "?" + key_match.group(2), "utf-8")
        else:
            key_match = re.match(r"([^?]+)\?(.*)$", full_path)
            if key_match:
                raw_key = bytes(key_match.group(1) + "/?" + key_match.group(2), "utf-8")
            else:
                raw_key = raw_key + b"/"
        logging.debug(f"Looking up secondary key: {raw_key}")
        content = content_db.get(raw_key)
        mimetype_bytes = mimetype_db.get(raw_key)
        if content is None or mimetype_bytes is None:
            logging.warning(f"Missing content or mimetype for path: {full_path}")
            return None, None

        logging.debug(f"Found {raw_key} after modification")

    mimetype = mimetype_bytes.decode("utf-8")

    return content, mimetype

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
            
        # Normalize the incoming path to remove https:// prefix
        if full_path.startswith("https://"):
            full_path = full_path[len("https://"):]
        elif full_path.startswith("http://"):
            full_path = full_path[len("http://"):]

        logging.debug(f"Full path: {full_path}")
        # Fix missing slash if needed
        if full_path.startswith("https:/") and not full_path.startswith("https://"):
            full_path = full_path.replace("https:/", "https://", 1)
            logging.debug(f"Full path fixed: {full_path}")

        content, mimetype = find_content(full_path)
        raw_key = bytes(full_path, "UTF-8")

        if content is None or mimetype is None:
            return Response("Not Found", status=404)

        if mimetype == "=redirect=":
            redirect_target = content.decode("utf-8")
            logging.info(f"Redirecting from {full_path} to {redirect_target}")
            return redirect(f'/{redirect_target}')

        logging.debug(f"Mime type {mimetype} for {full_path}")

        if full_path.startswith("https://") and mimetype == "text/html" or mimetype.startswith("text/html;"):
            content = rewrite_html_urls(full_path, content)

        return Response(content, mimetype=mimetype)

    except Exception as e:
        logging.exception(f"Error retrieving {subpath}")
        return Response("Internal Server Error", status=500)


if __name__ == "__main__":
    print(f"Starting cdcmirror server process at port {serverPort}")
    serve(app, host=hostName, port=serverPort)
