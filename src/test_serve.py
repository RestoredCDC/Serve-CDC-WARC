from serve import rewrite_html_urls, simplify_path, ServeLevelDB, set_globals


def test_relative_paths():
    """
    Check that we handle relative paths correctly
    """
    assert (
        rewrite_html_urls("hivrisk.cdc.gov/", b"<a href='../foo.html'>")
        == b"<a href='../foo.html'>"
    )
    assert (
        rewrite_html_urls("hivrisk.cdc.gov/", b'<a href="../foo.html">')
        == b'<a href="../foo.html">'
    )


def test_absolute_paths():
    """
    Check that we handle absolute paths correctly
    """
    assert (
        rewrite_html_urls("hivrisk.cdc.gov/", b"<a href='/foo.html'>")
        == b"<a href='/hivrisk.cdc.gov/foo.html'>"
    )
    assert (
        rewrite_html_urls("hivrisk.cdc.gov/", b'<a href="/foo.html">')
        == b'<a href="/hivrisk.cdc.gov/foo.html">'
    )
    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/",
            b'<link rel="shortcut icon" href="/favicon.ico">'
        )
        == b'<link rel="shortcut icon" href="/hivrisk.cdc.gov/favicon.ico">'
    )


def test_full_urls():
    """
    Check that we handle full URLs correctly
    """
    set_globals(
        ['hivrisk.cdc.gov', 'nccd.cdc.gov'],
        'www.restoredcdc.org',
        ['www.cdc.gov']
    )

    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/", b"<a href='https://hivrisk.cdc.gov/foo.html'>"
        )
        == b"<a href='/hivrisk.cdc.gov/foo.html'>"
    )
    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/", b'<a href="https://hivrisk.cdc.gov/foo.html">'
        )
        == b'<a href="/hivrisk.cdc.gov/foo.html">'
    )


def test_other_subdomains():
    """
    Check that we aren't just redirecting everything to hivrisk
    """
    set_globals(
        ['hivrisk.cdc.gov', 'nccd.cdc.gov'],
        'www.restoredcdc.org',
        ['www.cdc.gov']
    )

    assert (
        rewrite_html_urls(
            "nccd.cdc.gov/", b"<a href='https://nccd.cdc.gov/foo.html'>"
        )
        == b"<a href='/nccd.cdc.gov/foo.html'>"
    )


def test_src_rewrites():
    """
    Check that we rewrite src as well as href
    """
    set_globals(
        ['hivrisk.cdc.gov', 'nccd.cdc.gov'],
        'www.restoredcdc.org',
        ['www.cdc.gov']
    )

    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/", b"<img src='https://hivrisk.cdc.gov/img.jpg'>"
        )
        == b"<img src='/hivrisk.cdc.gov/img.jpg'>"
    )
    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/", b'<img src="https://hivrisk.cdc.gov/img.jpg">'
        )
        == b'<img src="/hivrisk.cdc.gov/img.jpg">'
    )


def test_primary_rewrite():
    """
    Check that we redirect to the primary restoredcdc site appropriately
    """
    set_globals(
        ['hivrisk.cdc.gov', 'nccd.cdc.gov'],
        'www.restoredcdc.org',
        ['www.cdc.gov']
    )

    assert (
        rewrite_html_urls(
            "hivrisk.cdc.gov/", b"<a href='https://www.cdc.gov/'>"
        )
        == b"<a href='https://www.restoredcdc.org/www.cdc.gov/'>"
    )


class MyServeLevelDB(ServeLevelDB):
    """
    Class for testing, with a hashmap instead of a LevelDB instance

    This works because we can use get() on each.
    """
    def __init__(self, dbfolder):
        self.content_db = {
            b"https://hivrisk.cdc.gov/": b"<p>Welcome to hivrisk.cdc.gov</p>",
            b"https://nccd.cdc.gov/": b"<p>Welcome to nccd.cdc.gov</p>",
            b"https://nccd.cdc.gov/favicon.ico": b"1234"
        }
        self.mimetype_db = {
            b"https://hivrisk.cdc.gov/": b"text/html",
            b"https://nccd.cdc.gov/": b"text/html",
            b"https://nccd.cdc.gov/favicon.ico": b"image/x-icon"
        }


def test_find_content():
    """
    Check that we find the content with or without a trailing slash
    """
    db = MyServeLevelDB("dummy")

    # Check without a trailing slash
    assert (
        db.find_content("https://hivrisk.cdc.gov")
        == (b"<p>Welcome to hivrisk.cdc.gov</p>", "text/html")
    )

    # Check with a trailing slash
    assert (
        db.find_content("https://hivrisk.cdc.gov/")
        == (b"<p>Welcome to hivrisk.cdc.gov</p>", "text/html")
    )


def test_find_content_mimetypes():
    """
    Check that we return other mime types
    """
    db = MyServeLevelDB("dummy")

    # Check something other than the main page
    assert (
        db.find_content("https://nccd.cdc.gov/favicon.ico")
        == (b"1234", "image/x-icon")
    )


def test_find_content_not_found():
    """
    Check how we respond for a request for something we don't have
    """
    db = MyServeLevelDB("dummy")

    # Check something that we don't expect to exist
    assert (
        db.find_content("https://nccd.cdc.gov/page-definitely-not-there.html")
        == (None, None)
    )


def test_simplify_path():
    """
    Check that simplify_path does what is needed for various
    http/https prefixes
    """
    assert (
        simplify_path("https://hivrisk.cdc.gov/testing.html")
        == "hivrisk.cdc.gov/testing.html"
    )
    assert (
        simplify_path("http://hivrisk.cdc.gov/testing.html")
        == "hivrisk.cdc.gov/testing.html"
    )
    assert (
        simplify_path("https:/hivrisk.cdc.gov/testing.html")
        == "hivrisk.cdc.gov/testing.html"
    )
    assert (
        simplify_path("http:/hivrisk.cdc.gov/testing.html")
        == "hivrisk.cdc.gov/testing.html"
    )
    assert (
        simplify_path("hivrisk.cdc.gov/testing.html")
        == "hivrisk.cdc.gov/testing.html"
    )
