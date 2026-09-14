"""Web server entry point.

Run this rather than `python app.py`:

    python run.py

app.py imports tasks, and tasks does `from app import ...`. Launching app.py
directly makes it the __main__ module, so that import loads app.py a SECOND time
under the name "app" — a duplicate Flask app and a duplicate SQLAlchemy() that
is not bound to the app serving requests. Going through this file means app.py is
only ever imported as "app", so exactly one of each exists.

(app.py still self-registers in sys.modules to keep `python app.py` working, but
that is a safety net, not the intended path.)
"""

from app import app, bootstrap

if __name__ == '__main__':
    bootstrap()
    app.run(host='0.0.0.0', port=6060, debug=True)
