# Lambda ke layak NAHI: background thread, local file state, websocket-style long connection
import threading, time, sqlite3
from flask import Flask, jsonify

app = Flask(__name__)
db = sqlite3.connect("local_state.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS hits (n INTEGER)")


def worker():
    while True:               # always-on loop, 24x7
        db.execute("INSERT INTO hits VALUES (1)")
        db.commit()
        time.sleep(5)


threading.Thread(target=worker, daemon=True).start()


@app.get("/count")
def count():
    return jsonify(hits=db.execute("SELECT COUNT(*) FROM hits").fetchone()[0])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
