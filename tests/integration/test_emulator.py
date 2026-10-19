"""Tests sur un vrai Android joignable par ADB (job CI « emulator », ou Pod Runpod).

PE_TEST_SERIAL=emulator-5554 uv run pytest -m emulator -o addopts=""
"""

import os

import pytest

from android_bridge import exclusions, network
from android_bridge.actions import Key, OpenApp, Shell, Tap, TypeText
from android_bridge.adb import Adb
from android_bridge.device import AdbDevice

pytestmark = pytest.mark.emulator
SERIAL = os.environ.get("PE_TEST_SERIAL", "emulator-5554")


@pytest.fixture
def device():
    return AdbDevice("tel-test", SERIAL)


async def test_device_is_ready(device):
    assert await device.is_ready()


async def test_arm_translation_is_advertised(device):
    """Les APK du propriétaire sont ARM : l'image x86_64 doit annoncer une ABI ARM traduite (F05)."""
    abis = (await device.adb.shell("getprop ro.product.cpu.abilist")).strip()
    print("abilist:", abis)
    assert "arm64-v8a" in abis or "armeabi-v7a" in abis, f"pas de traduction ARM annoncée : {abis}"


async def test_observe_returns_screen_and_tree(device):
    obs = await device.observe()
    assert obs.screenshot_png.startswith(b"\x89PNG")
    assert obs.width > 0 and obs.height > 0
    assert obs.ui_tree_status in ("ok", "empty", "unavailable")


async def test_open_settings_and_interact(device):
    out = await device.execute(OpenApp(package="com.android.settings"))
    assert out.status == "done", out.message
    obs = await device.observe()
    assert obs.foreground_package == "com.android.settings"
    clickable = [n for n in obs.ui_nodes if n.clickable]
    assert clickable, "aucun élément cliquable dans les Paramètres"
    x, y = clickable[0].bounds.center
    assert (await device.execute(Tap(x=x, y=y))).status == "done"
    assert (await device.execute(Key(key="home"))).status == "done"


async def test_ascii_typing_goes_through_input_text(device):
    await device.execute(OpenApp(package="com.android.settings"))
    out = await device.execute(TypeText(text="bonjour test"))
    assert out.status == "done", out.message


async def test_exclusions_hold(device):
    adb = Adb(SERIAL)
    await exclusions.enforce(adb)
    report = await exclusions.check(adb)
    print(report.model_dump())
    assert report.camera_devices == 0, "l'émulateur expose encore une caméra"
    assert report.location_enabled is not True
    assert not report.packages_with_grants
    blocked = await device.execute(Shell(command="pm grant com.android.chrome android.permission.CAMERA"))
    assert blocked.status == "rejected"


async def test_egress_ip_is_measured_from_android(device):
    ip, method = await network.egress_ip(device.adb)
    print("egress:", ip, method)
    assert ip, method
