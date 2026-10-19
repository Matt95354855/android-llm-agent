import pytest
from pydantic import TypeAdapter, ValidationError

from android_bridge.actions import Tap, TypeText
from android_bridge.demo import DemoDevice
from android_bridge.device import escape_input_text
from android_bridge.exclusions import shell_command_violation
from android_bridge.network import parse_ip
from android_bridge.uitree import parse_uiautomator_xml, render_for_model

XML = """UI hierchary dumped to: /dev/tty<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" bounds="[0,0][720,1280]" clickable="false">
    <node index="0" text="Paramètres" class="android.widget.TextView" bounds="[20,40][300,100]" />
    <node index="1" text="" content-desc="Rechercher" class="android.widget.ImageButton"
          clickable="true" bounds="[600,40][700,100]" />
    <node index="2" text="secret" password="true" class="android.widget.EditText"
          clickable="true" focused="true" bounds="[20,200][700,280]" />
    <node index="3" text="Wi-Fi" checkable="true" checked="true" class="android.widget.Switch"
          clickable="true" bounds="[20,300][700,380]" />
    <node index="4" text="vide" class="android.view.View" bounds="[0,0][0,0]" />
  </node>
</hierarchy>"""


def test_parse_keeps_meaningful_visible_nodes():
    nodes = parse_uiautomator_xml(XML)
    assert [n.text or n.desc for n in nodes] == ["Paramètres", "Rechercher", "•••", "Wi-Fi"]
    assert nodes[2].editable and nodes[2].password and nodes[2].focused
    assert nodes[3].checked is True
    assert nodes[1].bounds.center == (650, 70)
    text = render_for_model(nodes)
    assert "[3] Switch «Wi-Fi» (cliquable, coché)" in text
    assert "secret" not in text


def test_escape_input_text():
    assert escape_input_text("a b&c") == "a%sb\\&c"


@pytest.mark.parametrize(
    "cmd",
    [
        "pm grant com.x android.permission.CAMERA",
        "appops set com.x RECORD_AUDIO allow",
        "settings put secure location_mode 3",
        "cmd location set-location-enabled true",
    ],
)
def test_shell_blocks_reactivation_of_excluded_capabilities(cmd):
    assert shell_command_violation(cmd)


def test_shell_allows_ordinary_commands():
    assert shell_command_violation("pm list packages -3") is None


def test_action_union_rejects_unknown_tool_and_extra_fields():
    ta = TypeAdapter(Tap | TypeText)
    with pytest.raises(ValidationError):
        ta.validate_python({"tool": "tap", "x": 1, "y": 2, "rm": "-rf"})


async def test_demo_device_reacts_to_taps_and_text():
    d = DemoDevice("tel-1")
    obs = await d.observe()
    assert obs.screenshot_png.startswith(b"\x89PNG")
    add = next(n for n in obs.ui_nodes if n.text == "Ajouter")
    await d.execute(Tap(x=add.bounds.center[0], y=add.bounds.center[1]))
    await d.execute(TypeText(text="Été à Noël ✓"))
    obs2 = await d.observe()
    assert any(n.text == "Valeur : 1" for n in obs2.ui_nodes)
    assert any(n.text == "Été à Noël ✓" for n in obs2.ui_nodes)
    assert obs2.screenshot_sha256 != obs.screenshot_sha256


def test_parse_ip_from_http_body():
    assert parse_ip("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\n203.0.113.7\n") == "203.0.113.7"
    assert parse_ip("<html>erreur</html>") is None
