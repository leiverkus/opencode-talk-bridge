from __future__ import annotations

from nextcloud_talk_core import Settings

from opencode_talk_bridge.talk import IncomingMessage, TalkGateway, _parse_message

SETTINGS = Settings(nc_url="https://cloud.example.com", nc_user="bot", nc_app_password="pw")


# --- _parse_message (pure) -------------------------------------------------


def test_parse_message_basic_fields():
    msg = _parse_message(
        {
            "id": 42,
            "actorId": "jdoe",
            "actorType": "users",
            "actorDisplayName": "Jane Doe",
            "message": "hello",
            "timestamp": 1700000000,
        }
    )
    assert msg == IncomingMessage(
        id=42,
        actor_id="jdoe",
        actor_type="users",
        actor_display_name="Jane Doe",
        text="hello",
        timestamp=1700000000,
        is_system=False,
        files=(),
    )


def test_parse_message_system_detection():
    assert _parse_message({"id": 1, "message": "x joined", "systemMessage": "user_added"}).is_system
    assert _parse_message({"id": 1, "message": "x", "messageType": "system"}).is_system
    assert not _parse_message({"id": 1, "message": "hi"}).is_system


def test_parse_message_extracts_file_attachments():
    msg = _parse_message(
        {
            "id": 1,
            "message": "{file}",
            "messageParameters": {
                "file": {"type": "file", "name": "a.png", "path": "/Talk/a.png", "mimetype": "image/png"},
                "actor": {"type": "user", "id": "jdoe"},  # non-file param ignored
            },
        }
    )
    assert len(msg.files) == 1
    f = msg.files[0]
    assert (f.name, f.path, f.mimetype, f.is_audio) == ("a.png", "/Talk/a.png", "image/png", False)


def test_parse_message_audio_flag():
    msg = _parse_message(
        {
            "id": 1,
            "message": "{file}",
            "messageParameters": {"file": {"type": "file", "path": "/v.ogg", "mimetype": "audio/ogg"}},
        }
    )
    assert msg.files[0].is_audio is True


# --- TalkGateway delegation ------------------------------------------------


class _FakeOCS:
    def __init__(self):
        self.calls = []
        self.result = []

    def get(self, path, params=None, timeout=None):
        self.calls.append((path, params, timeout))
        return self.result


class _FakeMsg:
    id = 99


class _FakeTalk:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.shared = []

    def send_message(self, token, text, reply_to=None):
        self.sent.append((token, text, reply_to))
        return _FakeMsg()

    def edit_message(self, token, message_id, text):
        self.edited.append((token, message_id, text))

    def share_file(self, token, path, caption=None):
        self.shared.append((token, path, caption))


class _FakeWebDav:
    def __init__(self):
        self.uploaded = []

    def upload(self, remote_path, content, content_type="text/markdown"):
        self.uploaded.append((remote_path, content, content_type))
        return "/" + remote_path.strip("/")

    def download(self, path):
        return b"DATA:" + path.encode()


def _gateway():
    gw = TalkGateway(SETTINGS)
    gw._ocs, gw._talk, gw._webdav = _FakeOCS(), _FakeTalk(), _FakeWebDav()
    return gw


def test_poll_builds_longpoll_params_and_parses():
    gw = _gateway()
    gw._ocs.result = [{"id": 7, "actorId": "jdoe", "actorType": "users", "message": "hi", "timestamp": 1}]
    out = gw.poll("tok", last_known_message_id=3, timeout=30)
    path, params, timeout = gw._ocs.calls[-1]
    assert path == "/api/v1/chat/tok"
    assert params["lookIntoFuture"] == 1 and params["lastKnownMessageId"] == 3 and params["timeout"] == 30
    assert timeout == 60  # outlasts the server-side long-poll
    assert out[0].id == 7 and out[0].actor_id == "jdoe"


def test_poll_empty_returns_list():
    gw = _gateway()
    gw._ocs.result = None
    assert gw.poll("tok", 0) == []


def test_latest_message_id():
    gw = _gateway()
    gw._ocs.result = [{"id": 4}, {"id": 9}, {"id": 2}]
    assert gw.latest_message_id("tok") == 9
    assert gw._ocs.calls[-1][1] == {"lookIntoFuture": 0, "limit": 1}
    gw._ocs.result = []
    assert gw.latest_message_id("tok") == 0


def test_send_returns_message_id():
    gw = _gateway()
    assert gw.send("tok", "hello") == 99
    assert gw._talk.sent[-1] == ("tok", "hello", None)


def test_edit_delegates():
    gw = _gateway()
    gw.edit("tok", 5, "edited")
    assert gw._talk.edited[-1] == ("tok", 5, "edited")


def test_upload_and_share():
    gw = _gateway()
    gw.upload_and_share("tok", "/Bridge/x.md", b"code", caption="cap")
    assert gw._webdav.uploaded[-1][0] == "/Bridge/x.md"
    assert gw._talk.shared[-1] == ("tok", "/Bridge/x.md", "cap")


def test_download_delegates():
    gw = _gateway()
    assert gw.download("/Talk/a.png") == b"DATA:/Talk/a.png"
