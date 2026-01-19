# ui_utils.py
import os
import shutil
from datetime import date as dt_date
from datetime import datetime, timedelta

from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.utils import platform

from celebrations_core import get_today
from config import CONFIG_PATH
from utils import generate_ical_text

def export_config(_=None):
    export_config_file()

def import_config(_=None):
    from android_helpers import import_config_file
    import_config_file()

def import_config_file():
    if platform == "android":
        from android_helpers import import_from_download
        import_from_download("birthdays.json", CONFIG_PATH)
    else:
        print("Import not supported on non-Android platforms.")

def export_config_file():
    if platform != 'android':
        Popup(title="Not Supported", content=Label(text="Export not supported on desktop."), size_hint=(0.8, 0.3)).open()
        return

    try:
        src = str(CONFIG_PATH)
        downloads_dir = "/sdcard/Download"
        dst = os.path.join(downloads_dir, "birthdays.json")

        # If the file already exists, try to back it up
        if os.path.exists(dst):
            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            backup = os.path.join(downloads_dir, f"birthdays-{timestamp}.json")
            try:
                os.rename(dst, backup)
                backup_msg = f" (backed up old file as {os.path.basename(backup)})"
            except Exception:
                dst = backup  # fallback to timestamped export if rename fails
                backup_msg = " (couldn’t overwrite, so saved as new backup)"
        else:
            backup_msg = ""

        shutil.copy2(src, dst)
        msg = f"Copied to Downloads as {os.path.basename(dst)}{backup_msg}"
        content = Label(
            text=msg,
            halign='center',
            valign='middle',
            text_size=(800, None)  # This will wrap at about 800px width
        )
        content.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1]))
        Popup(title="Export Successful", content=content, size_hint=(0.9, 0.3)).open()

    except Exception as e:
        content = Label(
            text=str(e),
            halign='center',
            valign='middle',
            text_size=(800, None)
        )
        content.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1]))
        Popup(title="Export Failed", content=content, size_hint=(0.9, 0.3)).open()

def export_ical(events, out_path=None, days_ahead=None):
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup

    if not out_path:
        out_path = "/sdcard/Download/celebrations.ics" if platform == 'android' else "celebrations.ics"

    try:
        ical_text, count = generate_ical_text(events, days_ahead=days_ahead)

        if days_ahead in (None, 0):
            one_liner = "♻️ One-time events only"
            reminder_note = ""
        else:
            one_liner = f"♻️ One-time events only — next {days_ahead} days."
            reminder_note = "\n📅 Reminder event added to re-export later."

        note = (
            f"✅ Exported to {out_path}"
            f"\n{one_liner}"
            f"{reminder_note}"
            f"\n📄 Total events written: {count}"
        )

        if count > 500:
            warning = f"⚠️ Exported {count} events. Google Calendar may fail to import files over 500 events."
            print(warning)  # optional: useful in logs
            note = warning + "\n\n" + note

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(ical_text)

        title = "Export Successful"
    except Exception as e:
        note = f"⚠️ Export failed: {e}"
        title = "Export Failed"

    Popup(title=title, content=Label(text=note, text_size=(800, None), halign='center'), size_hint=(0.95, 0.4)).open()
