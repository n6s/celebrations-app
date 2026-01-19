# main.py
import json
from pathlib import Path

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.label import Label
from kivy.uix.screenmanager import ScreenManager
from kivy.utils import platform

from android_helpers import request_storage_permission
from config import CONFIG_PATH
from screens.add import AddEntryScreen
from screens.lookup import SmartLookupScreen

if platform == "android":
    from android_helpers import register_activity_result_handler

def ensure_config_exists():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        example_data = [
            {"name": "Example Person", "birthdate": "2000-01-01", "hint": "Sample", "gender": "f"},
            {"name": "Test User", "birthdate": "1999-12-31", "gender": "m"}
        ]
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(example_data, f, indent=2)

class CelebrationsApp(App):
    def build(self):
        request_storage_permission()
        if platform == "android":
            register_activity_result_handler()
        sm = ScreenManager()
        sm.add_widget(SmartLookupScreen(name='lookup'))
        sm.add_widget(AddEntryScreen(name='add'))
        sm.current = 'lookup'
        return sm

    def on_start(self):
        if platform == 'android':
            Window.bind(on_keyboard=self.android_back_handler)

    def android_back_handler(self, window, key, *args):
        # Keycode 27 is the Android "Back" button
        if key == 27:
            if self.root.current != 'lookup':
                self.root.current = 'lookup'
                return True  # Intercept the back press
        return False  # Allow default behavior (exit app)

if __name__ == '__main__':
    ensure_config_exists()
    CelebrationsApp().run()
